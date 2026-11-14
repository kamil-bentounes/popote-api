"""0.4bis S7c (migration 0151) : le blocage vise le couple (compte, IP) ; le compte entier, à 20 refus.

Le temps est injecté par la variante à horloge de `private` ; chaque test tire des clés neuves.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta

import psycopg
import pytest
from _connexions import DSN_ADMIN
from test_limites_de_connexion import MIN, T0, Ligne, ligne_de, neuve

pytestmark = pytest.mark.integration

PRENDRE = (
    "select attente_s, nouveau_blocage from"
    " private.prend_les_creneaux_de_connexion(%s, %s, %s, 5, 20, 20, 900, 86400, 86400, 3600, %s)"
)


@pytest.fixture
def admin() -> Iterator[psycopg.Connection[Ligne]]:
    with psycopg.connect(DSN_ADMIN, autocommit=True) as cx:
        yield cx


@pytest.fixture
def cles(admin: psycopg.Connection[Ligne]) -> Iterator[list[bytes]]:
    tirees: list[bytes] = []
    yield tirees
    admin.execute("delete from public.login_throttle where key = any(%s)", (tirees,))


def prend(
    admin: psycopg.Connection[Ligne], couple: bytes, compte: bytes, ip: bytes, quand: datetime = T0
) -> tuple[int, str | None]:
    ligne = admin.execute(PRENDRE, (couple, compte, ip, quand)).fetchone()
    assert ligne is not None
    return int(str(ligne[0])), None if ligne[1] is None else str(ligne[1])


def refus_depuis(
    admin: psycopg.Connection[Ligne], cles: list[bytes], compte: bytes, nombre: int, quand: datetime = T0
) -> list[tuple[int, str | None]]:
    return [prend(admin, neuve(cles), compte, neuve(cles), quand) for _ in range(nombre)]


def test_cinq_essais_du_couple_passent_le_sixieme_attend_et_pose_un_blocage_de_couple(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    couple, compte, ip = neuve(cles), neuve(cles), neuve(cles)
    assert [prend(admin, couple, compte, ip) for _ in range(5)] == [(0, None)] * 5
    assert prend(admin, couple, compte, ip) == (900, "couple")


def test_l_ip_d_un_attaquant_ne_bloque_pas_la_victime_sur_une_autre_ip(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, attaquant, ip_attaquant = neuve(cles), neuve(cles), neuve(cles)
    for _ in range(5):
        prend(admin, attaquant, compte, ip_attaquant)
    assert prend(admin, attaquant, compte, ip_attaquant)[0] > 0  # le couple de l'attaquant est bloqué
    assert prend(admin, neuve(cles), compte, neuve(cles)) == (0, None)  # la victime entre, de chez elle


def test_un_couple_bloque_ne_compte_ni_sur_le_compte_entier_ni_ne_prolonge_son_blocage(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    couple, compte, ip = neuve(cles), neuve(cles), neuve(cles)
    for _ in range(6):
        prend(admin, couple, compte, ip)
    avant = (ligne_de(admin, "couple", couple), ligne_de(admin, "compte_entier", compte))
    assert avant[1]["attempts"] == 5
    for _ in range(10):  # l'attaquant insiste depuis la même IP (sous la limite de l'IP) : rien ne bouge
        assert prend(admin, couple, compte, ip, T0 + 5 * MIN) == (600, None)
    assert (ligne_de(admin, "couple", couple), ligne_de(admin, "compte_entier", compte)) == avant


def test_une_ip_bloquee_n_use_ni_le_couple_ni_le_compte(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    ip, compte, couple = neuve(cles), neuve(cles), neuve(cles)
    for _ in range(20):
        prend(admin, neuve(cles), neuve(cles), ip)
    assert prend(admin, couple, compte, ip) == (900, "ip")
    assert admin.execute(
        "select count(*) from public.login_throttle where key = any(%s)", ([couple, compte],)
    ).fetchone() == (0,)


def test_vingt_refus_de_vingt_adresses_bloquent_le_compte_entier_au_vingt_et_unieme(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte = neuve(cles)
    assert refus_depuis(admin, cles, compte, 20) == [(0, None)] * 20
    assert prend(admin, neuve(cles), compte, neuve(cles)) == (3600, "account")


def test_le_blocage_du_compte_entier_dure_soixante_minutes_pour_toutes_les_ip(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte = neuve(cles)
    refus_depuis(admin, cles, compte, 20)
    prend(admin, neuve(cles), compte, neuve(cles))  # le 21e pose le blocage
    victime, ip_victime = neuve(cles), neuve(cles)
    assert prend(admin, victime, compte, ip_victime, T0 + 59 * MIN + timedelta(seconds=59)) == (1, None)
    assert prend(admin, victime, compte, ip_victime, T0 + 60 * MIN) == (0, None)


def test_une_ip_seule_ne_pese_que_cinq_refus_sur_le_compte_entier(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    couple, compte, ip = neuve(cles), neuve(cles), neuve(cles)
    quand = T0
    for attente in (900, 1800, 3600, 7200):  # les blocages successifs du même couple : 15, 30, 60, 120 min
        assert [prend(admin, couple, compte, ip, quand)[0] for _ in range(5)] == [0] * 5
        assert prend(admin, couple, compte, ip, quand)[0] == attente
        quand += timedelta(seconds=attente)
    assert prend(admin, couple, compte, ip, quand) == (
        0,
        None,
    )  # le 21e essai de l'IP : pas de blocage
    assert ligne_de(admin, "compte_entier", compte)["attempts"] == 5


def test_un_compte_entier_bloque_ne_consomme_pas_le_creneau_du_couple(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte = neuve(cles)
    refus_depuis(admin, cles, compte, 20)
    prend(admin, neuve(cles), compte, neuve(cles))
    victime, ip_victime = neuve(cles), neuve(cles)
    for _ in range(10):  # la victime insiste pendant le blocage : son couple ne s'use pas
        assert prend(admin, victime, compte, ip_victime, T0 + 10 * MIN)[0] == 3000
    assert admin.execute(
        "select count(*) from public.login_throttle where key = %s", (victime,)
    ).fetchone() == (0,)


def test_le_creneau_fixe_deja_bloque_rend_l_attente_sans_compter(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    """Le préfiltre sans verrou lit « libre » pendant qu'un essai concurrent pose le blocage : relu ici."""
    compte = neuve(cles)
    fixe = (
        "select attente_s, nouveau_blocage"
        " from private.prend_un_creneau_fixe('compte_entier', %s, 20, 86400, 3600, %s)"
    )
    for _ in range(20):
        admin.execute(fixe, (compte, T0))
    assert admin.execute(fixe, (compte, T0)).fetchone() == (3600, True)
    avant = ligne_de(admin, "compte_entier", compte)
    assert admin.execute(fixe, (compte, T0 + 10 * MIN)).fetchone() == (3000, False)
    assert ligne_de(admin, "compte_entier", compte) == avant


def test_la_fenetre_du_compte_entier_est_de_vingt_quatre_heures(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte = neuve(cles)
    refus_depuis(admin, cles, compte, 20)
    assert (
        prend(admin, neuve(cles), compte, neuve(cles), T0 + timedelta(hours=24) - timedelta(seconds=1))[1]
        == "account"
    )
    compte = neuve(cles)
    refus_depuis(admin, cles, compte, 20)
    assert prend(admin, neuve(cles), compte, neuve(cles), T0 + timedelta(hours=24)) == (0, None)


def test_un_succes_remet_le_couple_a_zero_rend_un_essai_au_compte_et_ne_touche_pas_l_ip(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    couple, compte, ip = neuve(cles), neuve(cles), neuve(cles)
    for _ in range(4):
        prend(admin, couple, compte, ip)
    admin.execute("select public.libere_le_couple(%s, %s)", (couple, compte))
    assert ligne_de(admin, "couple", couple)["attempts"] == 0
    assert ligne_de(admin, "compte_entier", compte)["attempts"] == 3  # le succès n'est pas un refus
    assert ligne_de(admin, "ip", ip)["attempts"] == 4


def test_un_succes_efface_les_crans_du_couple_et_ne_rend_rien_si_son_essai_n_a_pas_compte(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    couple, compte, ip = neuve(cles), neuve(cles), neuve(cles)
    for _ in range(6):
        prend(admin, couple, compte, ip)  # cinq comptés, puis le blocage du couple
    prend(admin, couple, compte, ip, T0 + 15 * MIN)  # un essai passé, mais pas compté sur le compte entier
    admin.execute("select public.libere_le_couple(%s, %s)", (couple, compte))
    assert ligne_de(admin, "compte_entier", compte)["attempts"] == 5
    assert ligne_de(admin, "couple", couple) == {
        "attempts": 0, "strikes": 0, "blocked_until": None, "last_block_at": None,
    }  # fmt: skip


@pytest.mark.parametrize(("rang", "valeur"), [(0, 0), (6, 86401), (1, None)])  # limite, blocage, valeur nulle
def test_une_limite_hors_bornes_est_refusee(
    rang: int, valeur: int | None, admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    parametres: list[int | None] = [5, 20, 20, 900, 86400, 86400, 3600]
    parametres[rang] = valeur
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute(
            "select * from public.prend_les_creneaux_de_connexion(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (neuve(cles), neuve(cles), neuve(cles), *parametres),
        )
