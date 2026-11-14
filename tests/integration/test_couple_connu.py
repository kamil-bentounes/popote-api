# ruff: noqa: F811  # les fixtures `admin` et `cles` viennent de test_blocage_par_couple
"""0.4bis S7c (migration 0152) : un couple (compte, IP) qui a réussi une connexion il y a moins de 30 j est
« connu » : le blocage du compte entier ne l'arrête pas, sa propre limite de 5 reste.
"""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from test_blocage_par_couple import admin, cles, prend, refus_depuis  # noqa: F401
from test_limites_de_connexion import MIN, T0, Ligne, ligne_de, neuve

pytestmark = pytest.mark.integration

JOUR = timedelta(days=1)


def pose_connu(admin: psycopg.Connection[Ligne], couple: bytes, dernier_succes: datetime) -> None:
    admin.execute(
        "insert into public.login_throttle (scope, key, window_start, last_success_at)"
        " values ('couple', %s, %s, %s)",
        (couple, T0, dernier_succes),
    )


def bloque_le_compte(admin: psycopg.Connection[Ligne], cles: list[bytes], compte: bytes) -> None:
    refus_depuis(admin, cles, compte, 20)
    assert prend(admin, neuve(cles), compte, neuve(cles)) == (3600, "account")


def test_un_couple_connu_passe_pendant_le_blocage_du_compte_entier_un_inconnu_reste_bloque(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, couple, ip = neuve(cles), neuve(cles), neuve(cles)
    pose_connu(admin, couple, T0 - 5 * JOUR)
    bloque_le_compte(admin, cles, compte)
    assert prend(admin, couple, compte, ip, T0 + 10 * MIN) == (0, None)
    assert prend(admin, neuve(cles), compte, neuve(cles), T0 + 10 * MIN)[0] == 3000


def test_un_couple_connu_garde_sa_propre_limite_de_cinq_meme_pendant_le_blocage_du_compte(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, couple, ip = neuve(cles), neuve(cles), neuve(cles)
    pose_connu(admin, couple, T0 - JOUR)
    bloque_le_compte(admin, cles, compte)
    assert [prend(admin, couple, compte, ip, T0 + MIN)[0] for _ in range(5)] == [0] * 5
    assert prend(admin, couple, compte, ip, T0 + MIN) == (900, "couple")


@pytest.mark.parametrize(
    ("age", "attente"),
    [(timedelta(days=30) - timedelta(seconds=1), 0), (timedelta(days=30), 3000)],
    ids=["connu_a_30_j_moins_1_s", "inconnu_a_30_j"],
)
def test_un_couple_n_est_connu_que_trente_jours(
    age: timedelta, attente: int, admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    compte, couple = neuve(cles), neuve(cles)
    pose_connu(admin, couple, T0 + 10 * MIN - age)
    bloque_le_compte(admin, cles, compte)
    assert prend(admin, couple, compte, neuve(cles), T0 + 10 * MIN)[0] == attente


def test_un_succes_date_le_couple_et_ne_rend_rien_au_compte_quand_le_couple_etait_deja_connu(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    couple, compte, ip = neuve(cles), neuve(cles), neuve(cles)
    maintenant = datetime.now(UTC)
    prend(admin, couple, compte, ip, maintenant)
    prend(admin, couple, compte, ip, maintenant)
    admin.execute("select public.libere_le_couple(%s, %s)", (couple, compte))
    (date,) = admin.execute(
        "select last_success_at from public.login_throttle where scope = 'couple' and key = %s", (couple,)
    ).fetchone()  # type: ignore[misc]
    assert abs(date - maintenant) < timedelta(minutes=5)
    assert ligne_de(admin, "compte_entier", compte)["attempts"] == 1  # premier succès : son essai est rendu
    prend(admin, couple, compte, ip, maintenant)  # connu : cet essai ne compte pas sur le compte entier
    admin.execute("select public.libere_le_couple(%s, %s)", (couple, compte))
    assert ligne_de(admin, "compte_entier", compte)["attempts"] == 1  # et le succès suivant ne rend rien


def test_la_purge_garde_un_couple_connu_trente_jours(
    admin: psycopg.Connection[Ligne], cles: list[bytes]
) -> None:
    recent, ancien = neuve(cles), neuve(cles)
    for cle, age in ((recent, 29), (ancien, 31)):
        admin.execute(
            "insert into public.login_throttle (scope, key, window_start, last_success_at)"
            " values ('couple', %s, %s, %s)",
            (cle, T0 - 40 * JOUR, T0 - age * JOUR),
        )
    admin.execute("select private.purge_login_throttle(%s, 100)", (T0,))
    restant = admin.execute(
        "select key from public.login_throttle where key = any(%s)", ([recent, ancien],)
    ).fetchall()
    assert [bytes(r[0]) for r in restant] == [recent]
