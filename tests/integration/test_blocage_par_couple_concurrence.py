# ruff: noqa: F811  # les fixtures `admin` et `cles` viennent de test_blocage_par_couple
"""0.4bis S7c : des appels simultanés de `prend_les_creneaux_de_connexion`, chacun sur sa connexion.

Ni interblocage (`40P01`) entre l'IP, le couple et le compte entier pris dans cet ordre, ni créneau de trop.
"""

import threading

import pytest
from _connexions import DSN_API, connecte
from test_blocage_par_couple import admin, cles  # noqa: F401
from test_limites_de_connexion import neuve

pytestmark = pytest.mark.integration

FILS = 20  # la base locale n'accepte pas 200 connexions à la fois
APPEL = "select attente_s, nouveau_blocage from public.prend_les_creneaux_de_connexion(%s, %s, %s)"


def en_parallele(appels: list[tuple[bytes, bytes, bytes]]) -> list[tuple[int, str | None]]:
    """Joue chaque (couple, compte, ip) sur `FILS` fils partis ensemble ; une exception échoue le test."""
    resultats: list[tuple[int, str | None]] = []
    erreurs: list[BaseException] = []
    verrou = threading.Lock()
    nombre = min(FILS, len(appels))
    depart = threading.Barrier(nombre)

    def un_fil(rang: int) -> None:
        try:
            with connecte(DSN_API) as cx:
                depart.wait(timeout=30)
                for cles_de_l_appel in appels[rang::nombre]:
                    with cx.transaction():
                        ligne = cx.execute(APPEL, cles_de_l_appel).fetchone()
                    assert ligne is not None
                    with verrou:
                        resultats.append((int(str(ligne[0])), None if ligne[1] is None else str(ligne[1])))
        except BaseException as erreur:
            erreurs.append(erreur)

    fils = [threading.Thread(target=un_fil, args=(rang,)) for rang in range(nombre)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=120)
    assert not erreurs, erreurs[:1]
    return resultats


def test_soixante_essais_sur_le_meme_compte_depuis_soixante_couples_en_laissent_passer_vingt(
    cles: list[bytes],
) -> None:
    compte = neuve(cles)
    resultats = en_parallele([(neuve(cles), compte, neuve(cles)) for _ in range(60)])
    assert len(resultats) == 60
    assert sum(1 for attente, _ in resultats if attente == 0) == 20
    assert [blocage for _, blocage in resultats if blocage is not None] == ["account"]  # un seul blocage posé


def test_des_essais_croises_entre_comptes_ips_et_couples_ne_s_interbloquent_pas(cles: list[bytes]) -> None:
    a, b, x, y = (neuve(cles) for _ in range(4))
    couples = {(c, i): neuve(cles) for c in (a, b) for i in (x, y)}
    appels = [(couples[c, i], c, i) for c, i in [(a, x), (b, y), (a, y), (b, x)]] * 50
    resultats = en_parallele(appels)
    assert len(resultats) == 200  # aucune exception, dont `40P01`
    assert sum(1 for attente, _ in resultats if attente == 0) <= 4 * 5  # chaque couple : 5 par fenêtre
