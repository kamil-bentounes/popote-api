"""Spec § 4 (journal de sécurité), B3, B7, B17 : la table `security_event` et ses fonctions (migration 0136).

Base locale par défaut ; `POPOTE_TEST_DSN_API`, `POPOTE_TEST_DSN_INTERNAL` et `POPOTE_TEST_DSN_ADMIN` les
rejouent sur un autre serveur. Le droit `execute` se joue par `set local role` (le rôle COURANT, B3), jamais
par le seul rôle de connexion. Chaque test marque ses lignes d'un `request_id` propre et les retire à la fin.
"""

import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_ADMIN, DSN_API, DSN_INTERNAL, connecte
from _fabrique import Fabrique
from psycopg import errors
from pydantic import SecretStr

from popote_api.infra.db import Base
from popote_api.security.empreintes import Empreintes
from popote_api.security.journal_securite import Evenement, journalise

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
JOURNALISE = "select public.journalise(%s, %s, %s, %s, %s, %s, %s)"
PURGE = "select private.purge_journal_securite(%s, %s)"
CLE = bytes(range(32))
MAINTENANT = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
SEUL_L_ECHEC = {"connexion_ratee", "connexion_bloquee"}


@pytest.fixture
def marque() -> Iterator[str]:
    """Un `request_id` propre au test, et le nettoyage de ses lignes même si le test échoue."""
    valeur = uuid4().hex
    yield valeur
    with psycopg.connect(DSN_ADMIN, autocommit=True) as admin:
        admin.execute("delete from public.security_event where request_id = %s", (valeur,))


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


def evenements(admin: psycopg.Connection[Ligne], marque: str) -> list[dict[str, object]]:
    curseur = admin.execute(
        "select kind, person_id, session_id, invitation_id, account_key, ip_hash, request_id, occurred_at"
        " from public.security_event where request_id = %s order by id",
        (marque,),
    )
    noms = [colonne.name for colonne in curseur.description or []]
    return [dict(zip(noms, ligne, strict=True)) for ligne in curseur.fetchall()]


def insere(admin: psycopg.Connection[Ligne], marque: str, kind: str, age: timedelta) -> None:
    """Un événement vieux de `age` à l'instant `MAINTENANT` (la purge prend son horloge en paramètre)."""
    admin.execute(
        "insert into public.security_event (kind, occurred_at, request_id) values (%s, %s, %s)",
        (kind, MAINTENANT - age, marque),
    )


def purge(admin: psycopg.Connection[Ligne], lot: int = 5000) -> int:
    ligne = admin.execute(PURGE, (MAINTENANT, lot)).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], int)
    return ligne[0]


def a_purger(admin: psycopg.Connection[Ligne]) -> int:
    """Combien de lignes la purge devrait emporter, toutes marques confondues (base partagée)."""
    ligne = admin.execute(
        "select count(*) from public.security_event where occurred_at < %s - case"
        " when kind in ('connexion_ratee', 'connexion_bloquee') then interval '90 days'"
        " else interval '365 days' end",
        (MAINTENANT,),
    ).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], int)
    return ligne[0]


# ── Écriture ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("evenement", list(Evenement), ids=str)
def test_chaque_type_d_evenement_s_ecrit(
    evenement: Evenement, admin: psycopg.Connection[Ligne], marque: str
) -> None:
    with connecte(DSN_API) as cx:
        assert cx.execute("select session_user, current_user").fetchone() == ("popote_api", "popote_api")
        cx.execute(JOURNALISE, (str(evenement), None, None, None, CLE, CLE[::-1], marque))
        cx.commit()
    [ligne] = evenements(admin, marque)
    assert ligne["kind"] == str(evenement)
    assert ligne["account_key"] == CLE
    assert ligne["ip_hash"] == CLE[::-1]
    assert ligne["person_id"] is None


def test_un_evenement_garde_la_personne_la_session_et_l_invitation(
    admin: psycopg.Connection[Ligne], fabrique: Fabrique, marque: str
) -> None:
    personne = fabrique.personne(fabrique.foyer()).id
    session, invitation = uuid4(), uuid4()
    with connecte(DSN_API) as cx:
        cx.execute(JOURNALISE, ("invitation_acceptee", personne, session, invitation, None, None, marque))
        cx.commit()
    [ligne] = evenements(admin, marque)
    assert (ligne["person_id"], ligne["session_id"], ligne["invitation_id"]) == (
        personne,
        session,
        invitation,
    )


def test_un_type_inconnu_est_refuse_par_la_base(marque: str) -> None:
    with connecte(DSN_API) as cx, pytest.raises(errors.CheckViolation):
        cx.execute(JOURNALISE, ("connexion_reussie_ou_pas", None, None, None, None, None, marque))


@pytest.mark.parametrize("cle", [b"", b"\x00" * 31, b"\x00" * 33])
@pytest.mark.parametrize("colonne", [3, 4])
def test_une_cle_de_mauvaise_longueur_est_refusee(colonne: int, cle: bytes, marque: str) -> None:
    arguments: list[object] = ["connexion_ratee", None, None, None, None, None, marque]
    arguments[colonne + 1] = cle
    with connecte(DSN_API) as cx, pytest.raises(errors.CheckViolation):
        cx.execute(JOURNALISE, arguments)


@pytest.mark.parametrize(
    "texte", ["a@b.fr", "1.2.3.4", "x" * 32, "A" * 32, "a" * 31, "a" * 33, "", "avec espace"]
)
def test_le_request_id_n_accepte_ni_adresse_ni_ip_ni_texte_libre(texte: str) -> None:
    with connecte(DSN_API) as cx, pytest.raises(errors.CheckViolation):
        cx.execute(JOURNALISE, ("deconnexion", None, None, None, None, None, texte))


def test_la_liste_python_est_celle_de_la_contrainte(admin: psycopg.Connection[Ligne]) -> None:
    ligne = admin.execute(
        "select pg_get_constraintdef(oid) from pg_constraint"
        " where conrelid = 'public.security_event'::regclass and contype = 'c'"
        " and pg_get_constraintdef(oid) like '%%kind%%'"
    ).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], str)
    assert set(re.findall(r"'([a-z_]+)'::text", ligne[0])) == {str(e) for e in Evenement}


def test_la_table_ne_garde_rien_d_autre_que_des_cles_et_des_identifiants(
    admin: psycopg.Connection[Ligne],
) -> None:
    colonnes = admin.execute(
        "select column_name, data_type from information_schema.columns"
        " where table_schema = 'public' and table_name = 'security_event' order by ordinal_position"
    ).fetchall()
    assert dict(colonnes) == {
        "id": "bigint",
        "occurred_at": "timestamp with time zone",
        "kind": "text",
        "person_id": "uuid",
        "session_id": "uuid",
        "invitation_id": "uuid",
        "account_key": "bytea",
        "ip_hash": "bytea",
        "request_id": "text",
    }


def test_apres_un_scenario_complet_aucune_ligne_ne_contient_de_motif_d_adresse_ni_d_ip(
    admin: psycopg.Connection[Ligne], marque: str
) -> None:
    empreintes = Empreintes(SecretStr("p" * 32))
    cle_compte = empreintes.cle_compte("quelquun@exemple.test")
    cle_ip = empreintes.cle_ip("203.0.113.9")
    with connecte(DSN_API) as cx:
        for evenement in Evenement:
            cx.execute(JOURNALISE, (str(evenement), None, None, None, cle_compte, cle_ip, marque))
        cx.commit()
    assert len(evenements(admin, marque)) == len(Evenement)
    ligne = admin.execute(
        "select count(*) from public.security_event e where request_id = %s"
        " and e::text ~ '[A-Za-z0-9._-]+@[A-Za-z0-9.-]+|[0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}'",
        (marque,),
    ).fetchone()
    assert ligne == (0,)


# ── Suppression d'un compte ─────────────────────────────────────────────────


def test_la_suppression_du_compte_garde_l_evenement_sans_la_personne(
    admin: psycopg.Connection[Ligne], fabrique: Fabrique, marque: str
) -> None:
    personne = fabrique.personne(fabrique.foyer()).id
    with connecte(DSN_API) as cx:
        cx.execute(JOURNALISE, ("deconnexion", personne, None, None, CLE, CLE, marque))
        cx.commit()
    admin.execute("delete from auth.users where id = %s", (personne,))
    [ligne] = evenements(admin, marque)
    assert ligne["person_id"] is None
    assert ligne["kind"] == "deconnexion"


# ── Droits (par `set local role`, le rôle courant) ──────────────────────────


def appelle_comme(admin: psycopg.Connection[Ligne], role: str, marque: str) -> None:
    with admin.transaction():
        admin.execute(f"set local role {role}")
        admin.execute(JOURNALISE, ("deconnexion", None, None, None, None, None, marque))


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_journalise_est_refusee_aux_roles_de_l_api_publique(
    role: str, admin: psycopg.Connection[Ligne], marque: str
) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        appelle_comme(admin, role, marque)
    assert evenements(admin, marque) == []


@pytest.mark.parametrize("role", ["service_role"])
def test_journalise_est_permise_au_role_courant_du_service(
    role: str, admin: psycopg.Connection[Ligne], marque: str
) -> None:
    appelle_comme(admin, role, marque)
    assert len(evenements(admin, marque)) == 1


def test_popote_api_apres_emprunt_d_authenticated_ne_peut_plus_journaliser(
    marque: str,
) -> None:
    with connecte(DSN_API) as cx, pytest.raises(errors.InsufficientPrivilege):
        with cx.transaction():
            cx.execute("set local role authenticated")
            cx.execute(JOURNALISE, ("deconnexion", None, None, None, None, None, marque))


def test_popote_internal_sans_emprunt_ne_peut_pas_journaliser(marque: str) -> None:
    with connecte(DSN_INTERNAL) as cx, pytest.raises(errors.InsufficientPrivilege):
        cx.execute(JOURNALISE, ("deconnexion", None, None, None, None, None, marque))


def test_le_contexte_service_journalise_sous_service_role(
    admin: psycopg.Connection[Ligne], marque: str
) -> None:
    with connecte(DSN_INTERNAL) as cx:
        with cx.transaction():
            cx.execute("set local role service_role")
            cx.execute(JOURNALISE, ("compte_repris", None, None, None, None, None, marque))
    assert [e["kind"] for e in evenements(admin, marque)] == ["compte_repris"]


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role", "popote_api", "popote_internal"])
def test_la_table_est_fermee_a_tous_les_roles(role: str, admin: psycopg.Connection[Ligne]) -> None:
    with pytest.raises(errors.InsufficientPrivilege), admin.transaction():
        admin.execute(f"set local role {role}")
        admin.execute("select * from public.security_event")


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role", "popote_api"])
def test_l_aide_interne_et_la_purge_ne_sont_executables_par_aucun_role_applicatif(
    role: str, admin: psycopg.Connection[Ligne]
) -> None:
    for appel in (
        "select private.ecrit_evenement('deconnexion')",
        "select private.purge_journal_securite()",
    ):
        with pytest.raises(errors.InsufficientPrivilege), admin.transaction():
            admin.execute(f"set local role {role}")
            admin.execute(appel)


# ── Purge ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "jours"),
    [("connexion_reussie", 365), ("session_fermee", 365), ("connexion_ratee", 90), ("connexion_bloquee", 90)],
)
def test_purge_garde_une_seconde_avant_l_echeance_et_efface_une_seconde_apres(
    kind: str, jours: int, admin: psycopg.Connection[Ligne], marque: str
) -> None:
    echeance = timedelta(days=jours)
    insere(admin, marque, kind, echeance - timedelta(seconds=1))
    insere(admin, marque, kind, echeance + timedelta(seconds=1))
    attendu = a_purger(admin)
    assert purge(admin) == attendu
    [reste] = evenements(admin, marque)
    assert MAINTENANT - reste["occurred_at"] == echeance - timedelta(seconds=1)  # type: ignore[operator]


def test_les_echecs_de_connexion_partent_a_90_jours_le_reste_a_un_an(
    admin: psycopg.Connection[Ligne], marque: str
) -> None:
    age = timedelta(days=91)
    insere(admin, marque, "connexion_ratee", age)
    insere(admin, marque, "connexion_bloquee", age)
    insere(admin, marque, "connexion_reussie", age)
    insere(admin, marque, "mot_de_passe_change", age)
    purge(admin)
    assert sorted(e["kind"] for e in evenements(admin, marque)) == [
        "connexion_reussie",
        "mot_de_passe_change",
    ]  # type: ignore[type-var]


def test_un_deuxieme_passage_n_efface_rien(admin: psycopg.Connection[Ligne], marque: str) -> None:
    insere(admin, marque, "connexion_reussie", timedelta(days=400))
    purge(admin)
    assert purge(admin) == 0


def test_la_purge_par_lots_de_deux_efface_tout_et_rend_le_total(
    admin: psycopg.Connection[Ligne], marque: str
) -> None:
    for _ in range(5):
        insere(admin, marque, "connexion_reussie", timedelta(days=400))
    insere(admin, marque, "connexion_reussie", timedelta(days=10))
    attendu = a_purger(admin)
    assert purge(admin, lot=2) == attendu
    assert len(evenements(admin, marque)) == 1


@pytest.mark.parametrize("lot", [0, -1])
def test_la_purge_refuse_un_lot_non_positif(lot: int, admin: psycopg.Connection[Ligne]) -> None:
    with pytest.raises(errors.InvalidParameterValue), admin.transaction():
        admin.execute(PURGE, (MAINTENANT, lot))


def test_la_ligne_de_journal_de_la_purge_ne_porte_qu_un_compte(
    admin: psycopg.Connection[Ligne], marque: str
) -> None:
    insere(admin, marque, "connexion_ratee", timedelta(days=200))
    messages: list[str] = []
    admin.add_notice_handler(lambda notice: messages.append(notice.message_primary or ""))
    purge(admin)
    assert len(messages) == 1
    assert re.fullmatch(r"purge du journal de securite : \d+ ligne\(s\) effacee\(s\)", messages[0])
    assert marque not in messages[0]


def test_la_purge_est_planifiee_par_pg_cron_en_sql_pur(admin: psycopg.Connection[Ligne]) -> None:
    ligne = admin.execute("select command from cron.job where jobname = 'journal-securite-purge'").fetchone()
    assert ligne == ("select private.purge_journal_securite()",)


# ── Le code Python ──────────────────────────────────────────────────────────


async def test_journalise_ecrit_par_le_contexte_connexion(
    base: Base, admin: psycopg.Connection[Ligne], marque: str
) -> None:
    async with base.connexion() as curseur:
        await journalise(curseur, Evenement.connexion_ratee, cle_compte=CLE, cle_ip=CLE, request_id=marque)
    [ligne] = evenements(admin, marque)
    assert (ligne["kind"], ligne["account_key"], ligne["ip_hash"]) == ("connexion_ratee", CLE, CLE)


async def test_journalise_ecrit_par_le_contexte_service(
    base: Base, admin: psycopg.Connection[Ligne], fabrique: Fabrique, marque: str
) -> None:
    personne = fabrique.personne(fabrique.foyer()).id
    async with base.service() as curseur:
        await journalise(curseur, Evenement.invitation_acceptee, personne=personne, request_id=marque)
    [ligne] = evenements(admin, marque)
    assert (ligne["kind"], ligne["person_id"]) == ("invitation_acceptee", personne)


async def test_journalise_est_refusee_dans_le_contexte_personne(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer()).id
    with pytest.raises(errors.InsufficientPrivilege):
        async with base.personne(personne) as curseur:
            await journalise(curseur, Evenement.deconnexion, personne=personne)


async def test_une_exception_apres_l_ecriture_annule_l_evenement(
    base: Base, admin: psycopg.Connection[Ligne], marque: str
) -> None:
    with pytest.raises(ZeroDivisionError):
        async with base.connexion() as curseur:
            await journalise(curseur, Evenement.deconnexion, request_id=marque)
            1 / 0  # noqa: B018
    assert evenements(admin, marque) == []


def test_uuid_de_personne_inconnue_est_refuse_par_la_cle_etrangere(marque: str) -> None:
    with connecte(DSN_API) as cx, pytest.raises(errors.ForeignKeyViolation):
        cx.execute(JOURNALISE, ("deconnexion", UUID(int=7), None, None, None, None, marque))
