"""Spec § 5.1 : `is_service_role()` ne se fie plus à une revendication posée par la session.

Quatre rôles de connexion : `popote_api`, `popote_internal` et, en local seulement, `authenticator` (celui
de PostgREST, mot de passe par défaut de la pile Supabase) et `postgres`. Chaque test vérifie `session_user`.
Rôle emprunté et revendication se posent comme PostgREST et l'API (`set local role`, `set_config(..., true)`),
sans jamais rien valider. Rejeu sur le pooler de l'essai : `POPOTE_TEST_DSN_API` et `POPOTE_TEST_DSN_INTERNAL`
(les tests qui demandent un semis, `authenticator` ou `postgres` sont alors passés).
"""

import os
import uuid
from collections.abc import Iterator
from typing import NamedTuple

import psycopg
import pytest
from psycopg import sql

ADMIN_LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
MOT_DE_PASSE_LOCAL = "essai-local"
# `authenticator` garde le mot de passe de la pile locale : on s'y connecte tel quel, sans le changer.
DSN_AUTHENTICATOR_LOCAL = "postgresql://authenticator:postgres@127.0.0.1:54322/postgres"

# Lues à l'import : la fixture autouse de tests/conftest.py retire ensuite tout POPOTE_* de l'environnement.
DSN_API_DISTANT = os.environ.get("POPOTE_TEST_DSN_API")
DSN_INTERNAL_DISTANT = os.environ.get("POPOTE_TEST_DSN_INTERNAL")
EN_LOCAL = not (DSN_API_DISTANT or DSN_INTERNAL_DISTANT)
seulement_en_local = pytest.mark.skipif(
    not EN_LOCAL, reason="demande la base locale (semis, authenticator, postgres)"
)

Connexion = psycopg.Connection[tuple[object, ...]]

SERVICE = '{"role": "service_role"}'
ANONYME = '{"role": "anon"}'
UN_MOIS = "2026-11-01"

# Les fonctions qui refusent quand l'appelant n'est pas le service (inventaire de la PR, 0126).
RESERVEES = [
    "rappels_a_envoyer(timestamp with time zone)",
    "reserve_rappel(uuid, text, text[])",
    "libere_rappel(uuid, text, text[])",
    "prepare_les_rappels(timestamp with time zone)",
    "note_la_passe(text, integer, integer, integer)",
    "rappel_actifs(text)",
    "rappel_point(uuid, date, text)",
    "rappel_prenom(text, text)",
    "appelle_les_rappels()",  # lancée par `pg_cron` en `postgres` ; sans porte propre
]
# Ce que le front en ligne appelle en tant que personne (les déclencheurs lisent `is_service_role()`).
OUVERTES = [
    ("is_service_role()", (True, True, True, True)),
    ("ouvre_le_mois(date, uuid)", (True, False, False, True)),
    ("ouvre_la_charge(uuid, uuid, date)", (True, False, False, True)),
    ("parts_du_foyer(date, uuid, text)", (True, False, False, True)),
]


def dsn_local(role: str) -> str:
    return f"postgresql://{role}:{MOT_DE_PASSE_LOCAL}@127.0.0.1:54322/postgres"


DSN_API = DSN_API_DISTANT or dsn_local("popote_api")
DSN_INTERNAL = DSN_INTERNAL_DISTANT or dsn_local("popote_internal")


def connecte(dsn: str, attendu: str) -> Connexion:
    """Ouvre la connexion et affirme qui elle est : un test sur le mauvais rôle ne prouverait rien."""
    # Pas d'instruction préparée, comme test_roles.py : le pooler change de serveur par transaction.
    cx = psycopg.connect(dsn, prepare_threshold=None, connect_timeout=15)
    reel = cx.execute("select session_user").fetchone()
    cx.rollback()
    assert reel == (attendu,)
    return cx


@pytest.fixture(scope="module", autouse=True)
def mots_de_passe_locaux() -> None:
    """Pose les mots de passe locaux, seulement quand aucune adresse distante n'est fournie."""
    if not EN_LOCAL:
        if not (DSN_API_DISTANT and DSN_INTERNAL_DISTANT):
            pytest.fail("POPOTE_TEST_DSN_API et POPOTE_TEST_DSN_INTERNAL vont ensemble")
        return
    with psycopg.connect(ADMIN_LOCAL, autocommit=True) as cx:
        cx.execute(f"alter role popote_api password '{MOT_DE_PASSE_LOCAL}'")
        cx.execute(f"alter role popote_internal password '{MOT_DE_PASSE_LOCAL}'")


@pytest.fixture
def cx_api() -> Iterator[Connexion]:
    with connecte(DSN_API, "popote_api") as cx:
        yield cx


@pytest.fixture
def cx_internal() -> Iterator[Connexion]:
    with connecte(DSN_INTERNAL, "popote_internal") as cx:
        yield cx


@pytest.fixture
def cx_authenticator() -> Iterator[Connexion]:
    with connecte(DSN_AUTHENTICATOR_LOCAL, "authenticator") as cx:
        yield cx


@pytest.fixture
def cx_postgres() -> Iterator[Connexion]:
    with connecte(ADMIN_LOCAL, "postgres") as cx:
        yield cx


def pose(cx: Connexion, role: str | None, revendication: str | None) -> None:
    if role is not None:
        cx.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
    if revendication is not None:
        cx.execute("select set_config('request.jwt.claims', %s, true)", (revendication,))


def requete(
    cx: Connexion,
    role: str | None,
    revendication: str | None,
    texte: str,
    parametres: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    """Rend les lignes de la requête sous ce rôle et cette revendication ; la transaction est défaite."""
    with cx.transaction(force_rollback=True):
        pose(cx, role, revendication)
        return cx.execute(sql.SQL(texte), parametres).fetchall()  # type: ignore[arg-type]  # texte constant du test


def est_service(cx: Connexion, role: str | None, revendication: str | None) -> object:
    return requete(cx, role, revendication, "select public.is_service_role()")[0][0]


@seulement_en_local
@pytest.mark.integration
@pytest.mark.parametrize("role", ["service_role", None])
def test_authenticator_avec_la_revendication_service_est_le_service(
    cx_authenticator: Connexion, role: str | None
) -> None:
    assert est_service(cx_authenticator, role, SERVICE) is True


@seulement_en_local
@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "revendication"),
    [
        ("authenticated", '{"sub": "00000000-0000-0000-0000-000000000001", "role": "authenticated"}'),
        ("anon", ANONYME),
        ("authenticated", None),
        ("service_role", None),
        ("service_role", ANONYME),
        (None, None),
    ],
)
def test_authenticator_sans_la_revendication_service_n_est_pas_le_service(
    cx_authenticator: Connexion, role: str | None, revendication: str | None
) -> None:
    assert est_service(cx_authenticator, role, revendication) is False


@pytest.mark.integration
@pytest.mark.parametrize("role", ["authenticated", None])
def test_popote_api_qui_pose_la_revendication_service_n_est_pas_le_service(
    cx_api: Connexion, role: str | None
) -> None:
    assert est_service(cx_api, role, SERVICE) is False


@pytest.mark.integration
def test_popote_api_avec_une_revendication_illisible_est_refuse_sans_erreur(cx_api: Connexion) -> None:
    assert est_service(cx_api, "authenticated", "pas du json") is False


@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "revendication"),
    [("service_role", None), ("service_role", SERVICE), ("service_role", ANONYME), (None, None)],
)
def test_popote_internal_est_le_service_quelle_que_soit_la_revendication(
    cx_internal: Connexion, role: str | None, revendication: str | None
) -> None:
    assert est_service(cx_internal, role, revendication) is True


@seulement_en_local
@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "revendication"),
    [(None, None), (None, SERVICE), ("service_role", None), ("service_role", SERVICE)],
)
def test_postgres_n_est_pas_le_service(
    cx_postgres: Connexion, role: str | None, revendication: str | None
) -> None:
    assert est_service(cx_postgres, role, revendication) is False


class DeuxFoyers(NamedTuple):
    """Deux foyers semés : `a` (une personne) se connecte, `b` (deux personnes, un magasin) est l'étranger."""

    personne_a: uuid.UUID
    foyer_a: uuid.UUID
    personnes_b: frozenset[uuid.UUID]
    foyer_b: uuid.UUID
    magasin_b: uuid.UUID


@pytest.fixture(scope="module")
def foyers() -> Iterator[DeuxFoyers]:
    """Données jetables, validées pour être vues des autres connexions, retirées à la fin (en cascade)."""
    if not EN_LOCAL:
        pytest.skip("demande la base locale (semis de données)")
    foyer_a, foyer_b, magasin = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    membres = [(uuid.uuid4(), foyer_a), (uuid.uuid4(), foyer_b), (uuid.uuid4(), foyer_b)]
    with psycopg.connect(ADMIN_LOCAL, autocommit=True) as cx:
        try:
            for personne, foyer in membres:
                cx.execute(
                    "insert into auth.users (id, aud, role, email) "
                    "values (%s, 'authenticated', 'authenticated', %s)",
                    (personne, f"zz-porte-{personne}@test.local"),
                )
                cx.execute(
                    "insert into public.household (id, name) values (%s, %s) on conflict do nothing",
                    (foyer, f"zz-{foyer}"),
                )
                cx.execute(
                    "insert into public.user_profile (id, household_id, display_name) values (%s, %s, 'zz')",
                    (personne, foyer),
                )
            cx.execute(
                "insert into public.store (id, household_id, name) values (%s, %s, 'zz')", (magasin, foyer_b)
            )
            yield DeuxFoyers(membres[0][0], foyer_a, frozenset(p for p, _ in membres[1:]), foyer_b, magasin)
        finally:
            cx.execute("delete from auth.users where id = any(%s)", ([p for p, _ in membres],))
            cx.execute("delete from public.household where id = any(%s)", ([foyer_a, foyer_b],))


@pytest.mark.integration
@pytest.mark.parametrize(
    ("connexion", "role", "revendication", "ouvert"),
    [
        # Le pool « personne » ne s'ouvre pas un foyer étranger en s'annonçant service, ni sans s'annoncer.
        ("cx_api", "authenticated", "service_role", False),
        ("cx_api", "authenticated", "authenticated", False),
        # Le pool du service garde sa porte, comme les Edge Functions actuelles (PostgREST).
        ("cx_internal", "service_role", "service_role", True),
        pytest.param("cx_authenticator", "service_role", "service_role", True, marks=seulement_en_local),
    ],
)
def test_foyer_etranger_ferme_aux_personnes_et_ouvert_au_service(
    request: pytest.FixtureRequest,
    foyers: DeuxFoyers,
    connexion: str,
    role: str,
    revendication: str,
    ouvert: bool,
) -> None:
    cx: Connexion = request.getfixturevalue(connexion)
    claims = f'{{"sub": "{foyers.personne_a}", "role": "{revendication}"}}'
    lecture = ("select user_profile_id from public.parts_du_foyer(%s::date, %s)", (UN_MOIS, foyers.foyer_b))
    ecriture = (  # écriture gardée par `tg_meme_foyer` : un magasin d'un autre foyer
        "insert into public.shopping_habit (household_id, label, store_id) "
        "values (%s, 'zz-porte', %s) returning id",
        (foyers.foyer_a, foyers.magasin_b),
    )
    lues = {ligne[0] for ligne in requete(cx, role, claims, *lecture)}
    assert (lues == foyers.personnes_b) if ouvert else lues.isdisjoint(foyers.personnes_b)
    if ouvert:
        requete(cx, role, claims, *ecriture)
    else:
        with pytest.raises(psycopg.errors.ForeignKeyViolation, match="store_id"):
            requete(cx, role, claims, *ecriture)


@seulement_en_local
@pytest.mark.integration
def test_rappels_a_envoyer_refuse_a_postgres_qui_emprunte_service_role(cx_postgres: Connexion) -> None:
    # `service_role` a bien le droit d'exécuter : c'est la porte, dans la fonction, qui refuse.
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="Réservé au rôle de service"):
        requete(cx_postgres, "service_role", SERVICE, "select count(*) from public.rappels_a_envoyer(now())")


@seulement_en_local
@pytest.mark.integration
@pytest.mark.parametrize(
    ("fonction", "attendu"),
    # (authenticated, anon, PUBLIC, service_role)
    [(f, (False, False, False, True)) for f in RESERVEES] + OUVERTES,
)
def test_droits_d_execute(cx_postgres: Connexion, fonction: str, attendu: tuple[bool, ...]) -> None:
    droits = cx_postgres.execute(
        """
        select has_function_privilege('authenticated', p.oid, 'execute'),
               has_function_privilege('anon', p.oid, 'execute'),
               exists (select 1 from aclexplode(p.proacl) a where a.grantee = 0),
               has_function_privilege('service_role', p.oid, 'execute')
        from pg_proc p where p.oid = ('public.' || %s)::regprocedure
        """,
        (fonction,),
    ).fetchone()
    assert droits == attendu


@seulement_en_local
@pytest.mark.integration
def test_definition_de_la_porte_est_epinglee(cx_postgres: Connexion) -> None:
    ligne = cx_postgres.execute(
        """
        select p.proconfig, p.provolatile, p.prosecdef, p.prorettype::regtype::text, p.pronargs,
               obj_description(p.oid, 'pg_proc')
        from pg_proc p where p.oid = 'public.is_service_role()'::regprocedure
        """
    ).fetchone()
    assert ligne is not None
    configuration, volatilite, definer, retour, nb_arguments, commentaire = ligne
    assert configuration == ['search_path=""']
    assert (volatilite, definer, retour, nb_arguments) == ("s", False, "boolean", 0)
    assert isinstance(commentaire, str)
    assert "J+2" in commentaire
