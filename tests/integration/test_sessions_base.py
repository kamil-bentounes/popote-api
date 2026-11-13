"""Spec § 4 ; B2, B3, B18, B19, B22 : créer, faire tourner, fermer, purger une session (migration 0139).

Base locale par défaut. Le temps est injecté par les variantes à horloge de `private` (en administrateur) ;
les fonctions publiques se jouent en `popote_api`. Le droit `execute` : `test_surface.py` (par rôle courant).
"""

import re
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from secrets import token_bytes
from uuid import UUID

import psycopg
import pytest
from _connexions import DSN_API, connecte
from _fabrique import Fabrique
from psycopg import errors

from popote_api.infra.db import Base
from popote_api.security.appareil import NAVIGATEURS, SYSTEMES, Appareil
from popote_api.security.sessions_base import (
    cree_session,
    fait_tourner_session,
    ferme_session,
    marque_reauth,
    session_courante,
)

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
MIN = timedelta(minutes=1)
JOUR = timedelta(days=1)
CREE = "select private.cree_session(%s, %s, 'chrome', 'linux', %s, %s)"
LIT = "select person_id, session_id, reauth_at from private.session_valide(%s, %s)"
NOTE = "select private.note_l_activite_de_la_session(%s, %s)"


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


@pytest.fixture
def personne(fabrique: Fabrique) -> UUID:
    return fabrique.personne(fabrique.foyer()).id


def cree(
    admin: psycopg.Connection[Ligne], personne: UUID, quand: datetime = T0, ancienne: bytes | None = None
) -> tuple[UUID, bytes]:
    empreinte = token_bytes(32)
    ligne = admin.execute(CREE, (personne, empreinte, ancienne, quand)).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], UUID)
    return ligne[0], empreinte


def lit(admin: psycopg.Connection[Ligne], empreinte: bytes, quand: datetime = T0) -> Ligne | None:
    return admin.execute(LIT, (empreinte, quand)).fetchone()


def actives(admin: psycopg.Connection[Ligne], personne: UUID, quand: datetime = T0) -> int:
    ligne = admin.execute(
        "select count(*) from public.login_session where person_id = %s and revoked_at is null"
        " and expires_at > %s and absolute_expires_at > %s",
        (personne, quand, quand),
    ).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], int)
    return ligne[0]


def colonne(admin: psycopg.Connection[Ligne], session: UUID, nom: str) -> object:
    ligne = admin.execute(f"select {nom} from public.login_session where id = %s", (session,)).fetchone()  # noqa: S608
    assert ligne is not None
    return ligne[0]


# ── Création ────────────────────────────────────────────────────────────────


def test_creation_pose_les_echeances_et_l_appareil(admin: psycopg.Connection[Ligne], personne: UUID) -> None:
    session, _ = cree(admin, personne)
    ligne = admin.execute(
        "select browser, os, created_at, last_seen_at, expires_at, absolute_expires_at, reauth_at, revoked_at"
        " from public.login_session where id = %s",
        (session,),
    ).fetchone()
    assert ligne == ("chrome", "linux", T0, T0, T0 + 30 * JOUR, T0 + 90 * JOUR, T0, None)


def test_une_empreinte_deja_prise_est_refusee(admin: psycopg.Connection[Ligne], personne: UUID) -> None:
    _, empreinte = cree(admin, personne)
    with pytest.raises(errors.UniqueViolation):
        admin.execute(CREE, (personne, empreinte, None, T0))


@pytest.mark.parametrize("longueur", [0, 16, 31, 33])
def test_une_empreinte_de_mauvaise_longueur_est_refusee(
    longueur: int, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    with pytest.raises(errors.CheckViolation):
        admin.execute(CREE, (personne, token_bytes(longueur), None, T0))


@pytest.mark.parametrize("cas", ["bannie", "supprimee"])
def test_une_personne_bannie_ou_supprimee_n_ouvre_pas_de_session(
    cas: str, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    colonne_ = "banned_until" if cas == "bannie" else "deleted_at"
    admin.execute(f"update auth.users set {colonne_} = %s where id = %s", (T0 + 10 * MIN, personne))  # noqa: S608
    with pytest.raises(errors.InvalidAuthorizationSpecification):
        admin.execute(CREE, (personne, token_bytes(32), None, T0 + MIN if cas == "bannie" else T0))
    assert actives(admin, personne) == 0


def test_un_ban_echu_n_empeche_pas_la_session(admin: psycopg.Connection[Ligne], personne: UUID) -> None:
    admin.execute("update auth.users set banned_until = %s where id = %s", (T0, personne))
    cree(admin, personne, T0)  # banned_until = maintenant : le ban est fini


def test_une_personne_inconnue_est_refusee(admin: psycopg.Connection[Ligne]) -> None:
    with pytest.raises(errors.ForeignKeyViolation):
        admin.execute(CREE, (UUID(int=7), token_bytes(32), None, T0))


@pytest.mark.parametrize(
    ("navigateur", "systeme"), [("netscape", "autre"), ("chrome", "beos"), ("Chrome", "linux"), ("", "autre")]
)
def test_l_appareil_est_borne_par_des_familles(
    navigateur: str, systeme: str, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    with pytest.raises(errors.CheckViolation):
        admin.execute(
            "select private.cree_session(%s, %s, %s, %s, null, %s)",
            (personne, token_bytes(32), navigateur, systeme, T0),
        )


def test_les_familles_de_python_sont_celles_de_la_base(admin: psycopg.Connection[Ligne]) -> None:
    def valeurs(colonne_: str) -> set[str]:
        defn = admin.execute(
            "select pg_get_constraintdef(c.oid) from pg_constraint c"
            " where c.conrelid = 'public.login_session'::regclass"
            " and c.contype = 'c' and pg_get_constraintdef(c.oid) like %s",
            (f"CHECK (({colonne_} =%",),
        ).fetchone()
        assert defn is not None
        return set(re.findall(r"'([a-z]+)'::text", str(defn[0])))

    assert valeurs("browser") == set(NAVIGATEURS)
    assert valeurs("os") == set(SYSTEMES)


def test_le_jeton_n_est_jamais_une_colonne(admin: psycopg.Connection[Ligne]) -> None:
    colonnes = {
        ligne[0]
        for ligne in admin.execute(
            "select column_name from information_schema.columns where table_name = 'login_session'"
        ).fetchall()
    }
    assert "token" not in colonnes
    assert "token_hash" in colonnes
    assert not {c for c in colonnes if "ip" in c.split("_") or "agent" in c or "location" in c or "geo" in c}


def test_la_onzieme_session_ferme_la_plus_ancienne_par_derniere_activite(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    sessions = [cree(admin, personne, T0 + i * MIN) for i in range(10)]
    # La première est la plus ancienne de création mais la plus récemment vue : ce n'est pas elle qui part.
    admin.execute(
        "update public.login_session set last_seen_at = %s where id = %s", (T0 + 60 * MIN, sessions[0][0])
    )
    cree(admin, personne, T0 + 20 * MIN)
    assert actives(admin, personne, T0 + 20 * MIN) == 10
    assert colonne(admin, sessions[1][0], "revoked_at") == T0 + 20 * MIN  # la moins récemment vue
    assert colonne(admin, sessions[0][0], "revoked_at") is None


def test_les_sessions_revoquees_ou_echues_ne_comptent_pas_dans_les_dix(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    anciennes = [cree(admin, personne, T0 - 40 * JOUR)[0] for _ in range(4)]  # échues à T0 (30 jours)
    fermees = [cree(admin, personne, T0)[0] for _ in range(4)]
    admin.execute("update public.login_session set revoked_at = %s where id = any(%s)", (T0, fermees))
    vivantes = [cree(admin, personne, T0 + MIN * i)[0] for i in range(9)]
    cree(admin, personne, T0 + 30 * MIN)
    assert actives(admin, personne, T0 + 30 * MIN) == 10
    assert all(colonne(admin, s, "revoked_at") is None for s in vivantes)
    assert all(colonne(admin, s, "revoked_at") is None for s in anciennes)  # échues, pas révoquées par nous


def test_la_limite_de_dix_ne_touche_pas_les_sessions_d_une_autre_personne(
    admin: psycopg.Connection[Ligne], personne: UUID, fabrique: Fabrique
) -> None:
    autre = fabrique.personne(fabrique.foyer()).id
    d_une_autre = [cree(admin, autre, T0 + i * MIN)[0] for i in range(10)]
    for i in range(11):
        cree(admin, personne, T0 + i * MIN)
    assert actives(admin, autre, T0 + 30 * MIN) == 10
    assert all(colonne(admin, s, "revoked_at") is None for s in d_une_autre)


def test_douze_connexions_simultanees_laissent_dix_sessions_actives(
    personne: UUID, fabrique: Fabrique
) -> None:
    erreurs: list[BaseException] = []
    depart = threading.Barrier(12)

    def connecte_une_fois() -> None:
        try:
            with connecte(DSN_API) as cx:
                depart.wait(timeout=30)
                with cx.transaction():
                    cx.execute(
                        "select public.cree_session(%s, %s, 'firefox', 'linux')", (personne, token_bytes(32))
                    )
        except BaseException as e:  # remonté par le test
            erreurs.append(e)

    fils = [threading.Thread(target=connecte_une_fois) for _ in range(12)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=60)
    assert not erreurs, erreurs[:1]
    assert actives(fabrique.admin, personne, datetime.now(tz=T0.tzinfo)) == 10


# ── Lecture : `session_courante` ────────────────────────────────────────────


def test_session_courante_valide_rend_personne_session_et_reauth(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    session, empreinte = cree(admin, personne)
    assert lit(admin, empreinte, T0 + MIN) == (personne, session, T0)


def test_session_courante_inconnue_rend_rien(admin: psycopg.Connection[Ligne]) -> None:
    assert lit(admin, token_bytes(32)) is None


def test_session_courante_revoquee_rend_rien(admin: psycopg.Connection[Ligne], personne: UUID) -> None:
    session, empreinte = cree(admin, personne)
    admin.execute("update public.login_session set revoked_at = %s where id = %s", (T0, session))
    assert lit(admin, empreinte, T0 + MIN) is None


@pytest.mark.parametrize(
    ("age", "valide"),
    [(30 * JOUR - timedelta(seconds=1), True), (30 * JOUR, False), (30 * JOUR + timedelta(seconds=1), False)],
)
def test_session_courante_echue_apres_trente_jours_sans_activite(
    age: timedelta, valide: bool, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    _, empreinte = cree(admin, personne)
    assert (lit(admin, empreinte, T0 + age) is not None) is valide


def test_session_courante_s_arrete_au_bout_des_quatre_vingt_dix_jours_malgre_l_activite(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    _, empreinte = cree(admin, personne)
    for jours in range(10, 90, 10):  # une visite tous les 10 jours repousse l'échéance glissante
        admin.execute(NOTE, (empreinte, T0 + jours * JOUR))
        assert lit(admin, empreinte, T0 + jours * JOUR) is not None
    assert lit(admin, empreinte, T0 + 90 * JOUR - timedelta(seconds=1)) is not None
    assert lit(admin, empreinte, T0 + 90 * JOUR) is None


def test_session_courante_refuse_une_personne_bannie_puis_la_rend_apres_le_ban(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    _, empreinte = cree(admin, personne)
    admin.execute("update auth.users set banned_until = %s where id = %s", (T0 + 10 * MIN, personne))
    assert lit(admin, empreinte, T0 + MIN) is None
    assert lit(admin, empreinte, T0 + 10 * MIN) is not None


def test_une_personne_bannie_ne_voit_pas_son_activite_reecrite_ni_sa_session_rendue(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    # Vue il y a plus de 5 minutes : la branche qui ÉCRIT l'activité doit elle aussi refuser le ban.
    session, empreinte = cree(admin, personne)
    admin.execute("update auth.users set banned_until = %s where id = %s", (T0 + 10 * MIN, personne))
    assert lit(admin, empreinte, T0 + 6 * MIN) is None
    assert colonne(admin, session, "last_seen_at") == T0


def test_session_courante_refuse_une_personne_supprimee(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    _, empreinte = cree(admin, personne)
    admin.execute("update auth.users set deleted_at = %s where id = %s", (T0, personne))
    assert lit(admin, empreinte, T0 + MIN) is None


def test_la_lecture_n_ecrit_jamais_l_activite_et_l_ecriture_attend_cinq_minutes(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    session, empreinte = cree(admin, personne)
    lit(admin, empreinte, T0 + 10 * MIN)
    assert colonne(admin, session, "last_seen_at") == T0  # une lecture, même tardive, n'écrit rien (0148)
    admin.execute(NOTE, (empreinte, T0 + 4 * MIN))
    assert colonne(admin, session, "last_seen_at") == T0
    admin.execute(NOTE, (empreinte, T0 + 5 * MIN))
    assert colonne(admin, session, "last_seen_at") == T0 + 5 * MIN
    assert colonne(admin, session, "expires_at") == T0 + 5 * MIN + 30 * JOUR


def test_session_personne_et_session_courante_appliquent_la_meme_regle(
    admin: psycopg.Connection[Ligne], personne: UUID, fabrique: Fabrique
) -> None:
    _, vivante = cree(admin, personne, datetime.now(tz=T0.tzinfo))
    revoquee = fabrique.session(personne, revoquee=True).empreinte
    for empreinte in (vivante, revoquee, token_bytes(32)):
        courante = admin.execute("select person_id from public.session_courante(%s)", (empreinte,)).fetchone()
        ancienne = admin.execute("select public.session_personne(%s)", (empreinte,)).fetchone()
        assert (courante[0] if courante else None) == (ancienne[0] if ancienne else None)


# ── Rotation, fermeture, réauthentification ─────────────────────────────────

TOURNE = "select private.fait_tourner_session(%s, %s, %s)"


def test_la_rotation_garde_la_session_et_tue_l_ancienne_empreinte(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    session, ancienne = cree(admin, personne)
    nouvelle = token_bytes(32)
    assert admin.execute(TOURNE, (ancienne, nouvelle, T0 + MIN)).fetchone() == (session,)
    assert lit(admin, ancienne, T0 + MIN) is None
    assert lit(admin, nouvelle, T0 + MIN) == (personne, session, T0)


def test_la_rotation_avec_une_mauvaise_ancienne_empreinte_ne_fait_rien(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    session, ancienne = cree(admin, personne)
    assert admin.execute(TOURNE, (token_bytes(32), token_bytes(32), T0)).fetchone() == (None,)
    assert lit(admin, ancienne) is not None
    assert colonne(admin, session, "token_hash") == ancienne


@pytest.mark.parametrize("cas", ["revoquee", "echue", "bannie"])
def test_la_rotation_d_une_session_morte_ne_fait_rien(
    cas: str, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    session, ancienne = cree(admin, personne)
    quand = T0 + MIN
    if cas == "revoquee":
        admin.execute("update public.login_session set revoked_at = %s where id = %s", (T0, session))
    elif cas == "echue":
        quand = T0 + 31 * JOUR
    else:
        admin.execute("update auth.users set banned_until = %s where id = %s", (T0 + JOUR, personne))
    assert admin.execute(TOURNE, (ancienne, token_bytes(32), quand)).fetchone() == (None,)
    assert colonne(admin, session, "token_hash") == ancienne


def test_la_rotation_vers_une_empreinte_prise_est_refusee(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    _, a = cree(admin, personne)
    _, b = cree(admin, personne)
    with pytest.raises(errors.UniqueViolation):
        admin.execute(TOURNE, (a, b, T0))


def test_marque_reauth_met_a_jour_la_bonne_session_seulement(
    admin: psycopg.Connection[Ligne], personne: UUID, fabrique: Fabrique
) -> None:
    session, _ = cree(admin, personne, T0 - JOUR)
    autre = fabrique.personne(fabrique.foyer()).id
    assert admin.execute("select public.marque_reauth(%s, %s)", (session, autre)).fetchone() == (False,)
    assert colonne(admin, session, "reauth_at") == T0 - JOUR
    assert admin.execute("select public.marque_reauth(%s, %s)", (session, personne)).fetchone() == (True,)
    assert colonne(admin, session, "reauth_at") != T0 - JOUR


def test_marque_reauth_sur_une_session_fermee_ne_fait_rien(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    session, empreinte = cree(admin, personne, T0 - JOUR)
    admin.execute("select public.ferme_session(%s)", (empreinte,))
    assert admin.execute("select public.marque_reauth(%s, %s)", (session, personne)).fetchone() == (False,)
    assert colonne(admin, session, "reauth_at") == T0 - JOUR


def test_marque_reauth_sur_une_session_echue_ne_fait_rien(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    # La fonction publique lit l'horloge de la base : la session est ouverte en 2020, échue depuis longtemps.
    ancien = datetime.fromisoformat("2020-01-01T00:00:00+00:00")
    session, _ = cree(admin, personne, ancien)
    assert admin.execute("select public.marque_reauth(%s, %s)", (session, personne)).fetchone() == (False,)
    assert colonne(admin, session, "reauth_at") == ancien


def test_ferme_session_est_idempotente(admin: psycopg.Connection[Ligne], personne: UUID) -> None:
    session, empreinte = cree(admin, personne, datetime.now(tz=T0.tzinfo))
    assert admin.execute("select public.ferme_session(%s)", (empreinte,)).fetchone() == (session,)
    assert admin.execute("select public.ferme_session(%s)", (empreinte,)).fetchone() == (None,)
    assert admin.execute("select public.ferme_session(%s)", (token_bytes(32),)).fetchone() == (None,)
    assert admin.execute("select count(*) from public.session_courante(%s)", (empreinte,)).fetchone() == (0,)


# ── B22 : la connexion révoque la session présentée ─────────────────────────


def test_une_connexion_revoque_la_session_presentee_et_journalise_sa_fermeture(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    ancienne_id, ancienne = cree(admin, personne)
    nouvelle_id, nouvelle = cree(admin, personne, T0 + MIN, ancienne=ancienne)
    assert lit(admin, ancienne, T0 + 2 * MIN) is None  # l'ancien cookie répond « pas de session »
    assert lit(admin, nouvelle, T0 + 2 * MIN) is not None
    assert colonne(admin, ancienne_id, "revoked_at") == T0 + MIN
    evenements = admin.execute(
        "select kind, person_id from public.security_event where session_id = %s", (ancienne_id,)
    ).fetchall()
    assert evenements == [("session_fermee", personne)]
    assert nouvelle_id != ancienne_id
    admin.execute("delete from public.security_event where session_id = %s", (ancienne_id,))


@pytest.mark.parametrize("cas", ["inconnue", "revoquee", "echue"])
def test_un_cookie_invalide_present_est_ignore_sans_erreur_ni_evenement(
    cas: str, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    presentee = token_bytes(32)
    if cas != "inconnue":
        vieille, presentee = cree(admin, personne, T0 - 40 * JOUR if cas == "echue" else T0)
        if cas == "revoquee":
            admin.execute("update public.login_session set revoked_at = %s where id = %s", (T0, vieille))
    nouvelle_id, _ = cree(admin, personne, T0 + MIN, ancienne=presentee)
    assert actives(admin, personne, T0 + MIN) >= 1
    assert colonne(admin, nouvelle_id, "revoked_at") is None
    assert admin.execute(
        "select count(*) from public.security_event"
        " where session_id is not distinct from %s and kind = 'session_fermee'",
        (nouvelle_id,),
    ).fetchone() == (0,)


# ── Purge (B18) ─────────────────────────────────────────────────────────────

PURGE = "select private.purge_login_session(%s, %s)"


def existe(admin: psycopg.Connection[Ligne], session: UUID) -> bool:
    return (
        admin.execute("select 1 from public.login_session where id = %s", (session,)).fetchone() is not None
    )


def test_la_purge_garde_trente_jours_moins_une_seconde_et_efface_trente_jours_plus_une(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    maintenant = T0 + 200 * JOUR
    # Échues : expires_at = création + 30 jours.
    juste_avant, juste_apres = (
        cree(admin, personne, maintenant - 60 * JOUR + timedelta(seconds=1))[0],
        cree(admin, personne, maintenant - 60 * JOUR - timedelta(seconds=1))[0],
    )
    # Révoquées, encore valides par l'échéance.
    revoquee_avant, revoquee_apres = (
        cree(admin, personne, maintenant - JOUR)[0],
        cree(admin, personne, maintenant - JOUR)[0],
    )
    admin.execute(
        "update public.login_session set revoked_at = %s where id = %s",
        (maintenant - 30 * JOUR + timedelta(seconds=1), revoquee_avant),
    )
    admin.execute(
        "update public.login_session set revoked_at = %s where id = %s",
        (maintenant - 30 * JOUR - timedelta(seconds=1), revoquee_apres),
    )
    vivante = cree(admin, personne, maintenant - JOUR)[0]
    admin.execute(PURGE, (maintenant, 2))
    assert [
        existe(admin, s) for s in (juste_avant, juste_apres, revoquee_avant, revoquee_apres, vivante)
    ] == [
        True,
        False,
        True,
        False,
        True,
    ]
    assert admin.execute(PURGE, (maintenant, 2)).fetchone() is not None  # idempotente : rien de plus ne part
    assert [existe(admin, s) for s in (juste_avant, revoquee_avant, vivante)] == [True, True, True]


def test_la_purge_refuse_un_lot_non_positif(admin: psycopg.Connection[Ligne]) -> None:
    with pytest.raises(errors.InvalidParameterValue):
        admin.execute(PURGE, (T0, 0))


# ── Le code Python, par les contextes connexion et service ───────────────────


@pytest.fixture
def jetons() -> Iterator[None]:
    yield


async def test_le_code_python_cree_lit_tourne_reauthentifie_et_ferme(
    base: Base, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    ancienne, nouvelle = token_bytes(32), token_bytes(32)
    async with base.connexion() as curseur:
        session = await cree_session(curseur, personne, ancienne, Appareil("firefox", "linux"))
        lue = await session_courante(curseur, ancienne)
        assert lue is not None
        assert (lue.personne, lue.session) == (personne, session)
        assert await fait_tourner_session(curseur, ancienne, nouvelle) == session
        assert await session_courante(curseur, ancienne) is None
        assert await marque_reauth(curseur, session, personne) is True
        assert await ferme_session(curseur, nouvelle) == session
        assert await ferme_session(curseur, nouvelle) is None
        assert await session_courante(curseur, nouvelle) is None
    assert admin.execute(
        "select browser, os from public.login_session where id = %s", (session,)
    ).fetchone() == (
        "firefox",
        "linux",
    )


async def test_le_contexte_service_peut_creer_une_session(base: Base, personne: UUID) -> None:
    async with base.service() as curseur:
        assert await cree_session(curseur, personne, token_bytes(32), Appareil()) is not None


async def test_le_contexte_personne_ne_peut_pas_creer_de_session(base: Base, personne: UUID) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        async with base.personne(personne) as curseur:
            await cree_session(curseur, personne, token_bytes(32), Appareil())
