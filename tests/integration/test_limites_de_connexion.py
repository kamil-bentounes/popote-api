"""Spec § 3.6, § 7.1 ; B5, B6, B12, B19, B21 : les limites de connexion comptées en base (migration 0138).

Base locale par défaut. Le temps est injecté par la variante à horloge de `private` (en administrateur) ;
les fonctions publiques se jouent en `popote_api`, qui seul les exécute (avec `service_role`, B3). Chaque test
prend des clés neuves et retire ses lignes à la fin : la base est partagée.
"""

import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from secrets import token_bytes

import psycopg
import pytest
from _connexions import DSN_ADMIN, DSN_API, connecte

from popote_api.config import Settings
from popote_api.infra.db import Base
from popote_api.security.empreintes import Empreintes
from popote_api.security.limites_base import (
    CleBloquee,
    liberer_le_compte,
    prendre_les_creneaux,
    prendre_un_creneau_de_reinitialisation,
)

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
MIN = timedelta(minutes=1)
PRENDRE = "select attente_s, nouveau_blocage from private.prend_les_creneaux(%s, %s, 5, 20, 900, 3600, %s)"
REINIT = "select private.prend_un_creneau_reinit(%s, 3, 3600, %s)"


@pytest.fixture
def admin() -> Iterator[psycopg.Connection[Ligne]]:
    with psycopg.connect(DSN_ADMIN, autocommit=True) as cx:
        yield cx


@pytest.fixture
def cles(admin: psycopg.Connection[Ligne]) -> Iterator[list[bytes]]:
    """Les clés que le test a tirées ; leurs lignes sont retirées à la fin, même s'il échoue."""
    tirees: list[bytes] = []
    yield tirees
    admin.execute("delete from public.login_throttle where key = any(%s)", (tirees,))


def neuve(cles: list[bytes]) -> bytes:
    k = token_bytes(32)
    cles.append(k)
    return k


def prend(
    admin: psycopg.Connection[Ligne], compte: bytes, ip: bytes, quand: datetime = T0
) -> tuple[int, str | None]:
    ligne = admin.execute(PRENDRE, (compte, ip, quand)).fetchone()
    assert ligne is not None
    return ligne[0], ligne[1]  # type: ignore[return-value]


def ligne_de(admin: psycopg.Connection[Ligne], scope: str, cle: bytes) -> dict[str, object]:
    c = admin.execute(
        "select attempts, strikes, blocked_until, last_block_at from public.login_throttle"
        " where scope = %s and key = %s",
        (scope, cle),
    )
    noms = [d.name for d in c.description or []]
    ligne = c.fetchone()
    assert ligne is not None
    return dict(zip(noms, ligne, strict=True))


def bloque(admin: psycopg.Connection[Ligne], compte: bytes, ip: bytes, quand: datetime) -> int:
    """Épuise les 5 essais puis rend l'attente du 6e."""
    for _ in range(5):
        assert prend(admin, compte, ip, quand)[0] == 0
    return prend(admin, compte, ip, quand)[0]


# ── Le compte : 5 essais, puis l'attente ────────────────────────────────────


def test_cinq_essais_passent_le_sixieme_attend_quinze_minutes(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, ip = neuve(cles), neuve(cles)
    for _ in range(5):
        assert prend(admin, compte, ip) == (0, None)
    assert prend(admin, compte, ip) == (900, "account")


def test_pendant_le_blocage_l_attente_decroit_sans_compter(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, ip = neuve(cles), neuve(cles)
    bloque(admin, compte, ip, T0)
    avant = ligne_de(admin, "account", compte)
    assert prend(admin, compte, ip, T0 + 5 * MIN) == (600, None)  # le « bon mot de passe » reste refusé
    assert ligne_de(admin, "account", compte) == avant  # un tiers ne prolonge pas le blocage


def test_apres_quinze_minutes_le_creneau_revient(admin: psycopg.Connection[Ligne], cles: list[bytes]) -> None:
    compte, ip = neuve(cles), neuve(cles)
    bloque(admin, compte, ip, T0)
    assert prend(admin, compte, ip, T0 + 15 * MIN - timedelta(seconds=1))[0] == 1
    assert prend(admin, compte, ip, T0 + 15 * MIN) == (0, None)


@pytest.mark.parametrize(("blocage", "attendu"), [(1, 900), (2, 1800), (3, 3600), (4, 3600), (7, 3600)])
def test_l_attente_double_a_chaque_blocage_et_plafonne_a_soixante_minutes(
    blocage: int, attendu: int, admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, ip = neuve(cles), neuve(cles)
    quand = T0
    for rang in range(1, blocage + 1):
        attente = bloque(admin, compte, ip, quand)
        if rang == blocage:
            assert attente == attendu
        quand += timedelta(seconds=attente)
        # Le test avance sur des heures : l'IP (20 par 15 min) ne doit pas s'épuiser, on la rend neuve.
        ip = neuve(cles)


@pytest.mark.parametrize(
    ("apres_la_fin", "attendu", "crans"),
    [(timedelta(hours=24) - timedelta(seconds=1), 3600, 3), (timedelta(hours=24), 900, 1)],
    ids=["une_seconde_avant", "pile"],
)
def test_les_blocages_retombent_vingt_quatre_heures_apres_leur_fin(
    apres_la_fin: timedelta, attendu: int, crans: int, admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, ip = neuve(cles), neuve(cles)
    assert bloque(admin, compte, ip, T0) == 900
    assert bloque(admin, compte, neuve(cles), T0 + 15 * MIN) == 1800
    deuxieme_fin = T0 + 15 * MIN + 30 * MIN  # 0149 : la retombée se mesure depuis la FIN du blocage
    assert ligne_de(admin, "account", compte)["strikes"] == 2
    assert bloque(admin, compte, neuve(cles), deuxieme_fin + apres_la_fin) == attendu
    assert ligne_de(admin, "account", compte)["strikes"] == crans


def test_un_succes_remet_le_compte_a_zero_mais_pas_l_ip(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, ip = neuve(cles), neuve(cles)
    for _ in range(3):
        prend(admin, compte, ip)
    admin.execute("select public.libere_compte(%s)", (compte,))
    assert ligne_de(admin, "account", compte)["attempts"] == 0
    assert ligne_de(admin, "ip", ip)["attempts"] == 3


def test_liberer_un_compte_inconnu_ne_cree_rien(admin: psycopg.Connection[Ligne], cles: list[bytes]) -> None:
    compte = neuve(cles)
    admin.execute("select public.libere_compte(%s)", (compte,))
    assert admin.execute(
        "select count(*) from public.login_throttle where key = %s", (compte,)
    ).fetchone() == (0,)


def test_une_cle_de_compte_inconnue_se_comporte_comme_une_connue(
    admin: psycopg.Connection[Ligne], cles: list[bytes], fabrique: object
) -> None:
    # La fonction ne regarde jamais auth.users : deux clés tirées au hasard, dont une « connue » d'avoir déjà
    # servi, répondent pareil au même rang d'essai.
    connue, inconnue = neuve(cles), neuve(cles)
    prend(admin, connue, neuve(cles))
    suite_connue = [prend(admin, connue, neuve(cles))[0] for _ in range(5)]
    suite_inconnue = [prend(admin, inconnue, neuve(cles))[0] for _ in range(5)]
    assert suite_connue[:4] == suite_inconnue[:4] == [0, 0, 0, 0]
    assert suite_connue[4] == 900  # 6e essai de la connue
    assert suite_inconnue[4] == 0  # 5e essai de l'inconnue : même règle, un essai de moins pris


# ── L'IP : 20 essais, et l'IP d'abord ───────────────────────────────────────


def test_vingt_essais_d_une_ip_sur_des_comptes_differents_puis_le_vingt_et_unieme_refuse(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    ip = neuve(cles)
    for _ in range(20):
        assert prend(admin, neuve(cles), ip)[0] == 0
    assert prend(admin, neuve(cles), ip) == (900, "ip")


def test_une_ip_bloquee_n_epuise_pas_les_creneaux_d_un_compte(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    ip, compte = neuve(cles), neuve(cles)
    for _ in range(20):
        prend(admin, neuve(cles), ip)
    for _ in range(10):
        assert prend(admin, compte, ip)[0] > 0  # l'IP est bloquée
    assert admin.execute(
        "select count(*) from public.login_throttle where key = %s", (compte,)
    ).fetchone() == (0,)
    # Le compte garde ses 5 essais depuis une autre IP.
    for _ in range(5):
        assert prend(admin, compte, neuve(cles))[0] == 0


def test_cent_essais_refuses_pendant_un_blocage_ne_signalent_qu_un_seul_blocage_par_cle(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte = neuve(cles)
    # Le compte : 105 essais depuis autant d'IP (aucune ne se bloque) → un seul drapeau « account ».
    drapeaux = [prend(admin, compte, neuve(cles), T0)[1] for _ in range(105)]
    assert [d for d in drapeaux if d is not None] == ["account"]
    # L'IP : 105 essais sur autant de comptes → un seul drapeau « ip ».
    ip = neuve(cles)
    drapeaux = [prend(admin, neuve(cles), ip, T0)[1] for _ in range(105)]
    assert [d for d in drapeaux if d is not None] == ["ip"]


# ── Les clés et les paramètres ──────────────────────────────────────────────


@pytest.mark.parametrize("longueur", [0, 16, 31, 33, 64])
def test_une_cle_de_longueur_differente_de_32_est_refusee(
    longueur: int, admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute(PRENDRE, (token_bytes(longueur), neuve(cles), T0))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute(PRENDRE, (neuve(cles), token_bytes(longueur), T0))


def test_une_cle_nulle_est_refusee(admin: psycopg.Connection[Ligne], cles: list[bytes]) -> None:
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute(PRENDRE, (None, neuve(cles), T0))


@pytest.mark.parametrize(
    "parametres",
    [
        (None, 20, 900, 3600),
        (5, None, 900, 3600),
        (5, 20, None, 3600),
        (5, 20, 900, None),
        (0, 20, 900, 3600),
        (2_147_483_647, 20, 900, 3600),
        (5, 20, 0, 3600),
        (5, 20, 2_147_483_647, 2_147_483_647),
        (5, 20, 900, 899),
        (5, 20, 900, 86401),
    ],
)
def test_une_limite_nulle_ou_hors_bornes_est_refusee_par_la_fonction_publique(
    parametres: tuple[int | None, ...], admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, ip = neuve(cles), neuve(cles)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute(
            "select * from public.prend_les_creneaux(%s, %s, %s, %s, %s, %s)", (compte, ip, *parametres)
        )


@pytest.mark.parametrize(
    "parametres", [(None, 3600), (3, None), (0, 3600), (100_000, 3600), (3, 0), (3, 86401)]
)
def test_une_limite_de_reinitialisation_hors_bornes_est_refusee(
    parametres: tuple[int | None, ...], admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute("select public.prend_un_creneau_reinit(%s, %s, %s)", (neuve(cles), *parametres))


def test_le_plafond_de_la_configuration_ne_peut_pas_etre_sous_la_fenetre() -> None:
    with pytest.raises(ValueError, match="connexion_attente_max_s"):
        Settings(env="local", connexion_fenetre_s=900, connexion_attente_max_s=899)  # type: ignore[arg-type,call-arg]


# ── La réinitialisation : 3 par heure et par (e-mail, IP) ───────────────────


def test_reset_trois_passent_le_quatrieme_attend_sans_toucher_la_connexion(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    cle_reset, compte, ip = neuve(cles), neuve(cles), neuve(cles)
    attentes = [admin.execute(REINIT, (cle_reset, T0 + i * MIN)).fetchone() for i in range(4)]
    assert attentes == [(0,), (0,), (0,), (3600 - 3 * 60,)]
    assert ligne_de(admin, "reset", cle_reset)["attempts"] == 3  # le 4e n'a pas compté
    assert ligne_de(admin, "reset", cle_reset)["strikes"] == 0  # sans escalade
    assert prend(admin, compte, ip)[0] == 0
    assert admin.execute(
        "select count(*) from public.login_throttle where scope <> 'reset' and key = %s", (cle_reset,)
    ).fetchone() == (0,)
    assert admin.execute(REINIT, (cle_reset, T0 + 60 * MIN)).fetchone() == (0,)  # l'heure écoulée


def test_la_cle_de_reinitialisation_est_celle_du_couple_email_ip() -> None:
    e = Empreintes(__import__("pydantic").SecretStr("p" * 32))
    assert e.cle_reinitialisation("a@x.fr", "1.2.3.4") != e.cle_reinitialisation("a@x.fr", "1.2.3.5")
    assert e.cle_reinitialisation("a@x.fr", "1.2.3.4") != e.cle_reinitialisation("b@x.fr", "1.2.3.4")
    assert e.cle_reinitialisation(" A@X.fr ", "1.2.3.4") == e.cle_reinitialisation("a@x.fr", "1.2.3.4")
    assert e.cle_reinitialisation("a@x.fr", "1.2.3.4") != e.cle_compte("a@x.fr")
    assert Empreintes(None).cle_reinitialisation("a@x.fr", None) is None


# ── Concurrence ─────────────────────────────────────────────────────────────


FILS = 20  # la base locale n'accepte pas 200 connexions à la fois : 20 fils, chacun sur sa connexion


def en_parallele(travaux: list[tuple[bytes, bytes]], fois: int = 1) -> list[tuple[bytes, bytes, int]]:
    """Joue chaque (compte, ip) `fois` fois par `FILS` fils qui partent ensemble, chacun sur sa connexion."""
    a_faire = travaux * fois
    resultats: list[tuple[bytes, bytes, int]] = []
    verrou = threading.Lock()
    nombre = min(FILS, len(a_faire))
    depart = threading.Barrier(nombre)
    erreurs: list[BaseException] = []

    def un_fil(rang: int) -> None:
        try:
            with connecte(DSN_API) as cx:
                depart.wait(timeout=30)
                for compte, ip in a_faire[rang::nombre]:
                    with cx.transaction():
                        ligne = cx.execute(
                            "select attente_s from public.prend_les_creneaux(%s, %s)", (compte, ip)
                        ).fetchone()
                    assert ligne is not None
                    with verrou:
                        resultats.append((compte, ip, int(str(ligne[0]))))
        except BaseException as e:  # remonté par le test
            erreurs.append(e)

    fils = [threading.Thread(target=un_fil, args=(rang,)) for rang in range(nombre)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=120)
    assert not erreurs, erreurs[:1]
    return resultats


def test_cinquante_appels_simultanes_sur_le_meme_compte_en_laissent_passer_cinq(cles: list[bytes]) -> None:
    compte = neuve(cles)
    ips = [neuve(cles) for _ in range(50)]
    resultats = en_parallele([(compte, ip) for ip in ips])
    assert sum(1 for *_, attente in resultats if attente == 0) == 5


def test_trente_comptes_depuis_une_ip_en_laissent_passer_vingt(cles: list[bytes]) -> None:
    ip = neuve(cles)
    resultats = en_parallele([(neuve(cles), ip) for _ in range(30)])
    assert sum(1 for *_, attente in resultats if attente == 0) == 20


def test_deux_cents_paires_croisees_ne_s_interbloquent_pas(cles: list[bytes]) -> None:
    a, b = neuve(cles), neuve(cles)
    # compte A / IP B et compte B / IP A, par moitié : l'ordre IP puis compte exclut tout cercle d'attente.
    resultats = en_parallele([(a, b), (b, a)] * 50, fois=2)
    assert len(resultats) == 200  # aucun `40P01`, aucune exception


# ── Purge ───────────────────────────────────────────────────────────────────


def test_la_purge_efface_les_lignes_sans_activite_depuis_24_h_par_lots_et_est_idempotente(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    vieux = [neuve(cles) for _ in range(3)]
    jeune = neuve(cles)
    for k in vieux:
        admin.execute(
            "insert into public.login_throttle (scope, key, window_start) values ('ip', %s, %s)",
            (k, T0 - timedelta(hours=24, seconds=1)),
        )
    admin.execute(
        "insert into public.login_throttle (scope, key, window_start) values ('ip', %s, %s)",
        (jeune, T0 - timedelta(hours=24) + timedelta(seconds=1)),
    )
    # Un blocage récent retient sa ligne même si la fenêtre est vieille.
    bloquee = neuve(cles)
    admin.execute(
        "insert into public.login_throttle (scope, key, window_start, blocked_until)"
        " values ('account', %s, %s, %s)",
        (bloquee, T0 - timedelta(hours=30), T0 + MIN),
    )
    en_base = admin.execute(
        "select count(*) from public.login_throttle where key = any(%s) and key <> all(%s)", (vieux, [jeune])
    ).fetchone()
    assert en_base == (3,)
    efface = admin.execute("select private.purge_login_throttle(%s, 2)", (T0,)).fetchone()
    assert efface is not None
    assert isinstance(efface[0], int) and efface[0] >= 3
    restant = admin.execute(
        "select key from public.login_throttle where key = any(%s)", ([*vieux, jeune, bloquee],)
    ).fetchall()
    assert {r[0] for r in restant} == {jeune, bloquee}
    assert admin.execute("select private.purge_login_throttle(%s, 2)", (T0,)).fetchone() == (0,)


def test_la_purge_refuse_un_lot_non_positif(admin: psycopg.Connection[Ligne]) -> None:
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute("select private.purge_login_throttle(%s, 0)", (T0,))


# ── Le code Python ──────────────────────────────────────────────────────────


@pytest.fixture
def reglages() -> Settings:
    return Settings(env="local")  # type: ignore[arg-type]


async def test_prendre_les_creneaux_rend_l_attente_et_le_blocage(
    base: Base, reglages: Settings, cles: list[bytes]
) -> None:
    compte, ip = neuve(cles), neuve(cles)
    async with base.connexion() as curseur:
        for _ in range(5):
            assert (await prendre_les_creneaux(curseur, compte, ip, reglages)).passe
        sixieme = await prendre_les_creneaux(curseur, compte, ip, reglages)
        septieme = await prendre_les_creneaux(curseur, compte, ip, reglages)
    assert (sixieme.attente_s, sixieme.nouveau_blocage, sixieme.passe) == (900, CleBloquee.compte, False)
    assert septieme.nouveau_blocage is None
    assert 0 < septieme.attente_s <= 900


async def test_liberer_le_compte_et_la_reinitialisation_par_le_contexte_service(
    base: Base, reglages: Settings, cles: list[bytes], admin: psycopg.Connection[Ligne]
) -> None:
    compte, ip, cle_reset = neuve(cles), neuve(cles), neuve(cles)
    async with base.service() as curseur:
        await prendre_les_creneaux(curseur, compte, ip, reglages)
        await liberer_le_compte(curseur, compte)
        attentes = [
            await prendre_un_creneau_de_reinitialisation(curseur, cle_reset, reglages) for _ in range(4)
        ]
    assert ligne_de(admin, "account", compte)["attempts"] == 0
    assert attentes[:3] == [0, 0, 0]
    assert attentes[3] > 0
