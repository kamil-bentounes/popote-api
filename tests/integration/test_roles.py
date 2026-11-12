"""Spec § 5.1 : deux rôles de connexion, chacun n'emprunte que le sien, rien ne survit à la transaction.

Par défaut le test vise la base locale. Pour le rejouer contre un autre serveur (le pooler Supavisor de
l'essai), poser `POPOTE_TEST_DSN_API` et `POPOTE_TEST_DSN_INTERNAL` : les mots de passe locaux ne sont
alors pas touchés.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest

ADMIN_LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
MOT_DE_PASSE_LOCAL = "essai-local"

# Lues à l'import : la fixture autouse de tests/conftest.py retire ensuite tout POPOTE_* de l'environnement.
DSN_API_DISTANT = os.environ.get("POPOTE_TEST_DSN_API")
DSN_INTERNAL_DISTANT = os.environ.get("POPOTE_TEST_DSN_INTERNAL")


def dsn_local(role: str) -> str:
    return f"postgresql://{role}:{MOT_DE_PASSE_LOCAL}@127.0.0.1:54322/postgres"


DSN_API = DSN_API_DISTANT or dsn_local("popote_api")
DSN_INTERNAL = DSN_INTERNAL_DISTANT or dsn_local("popote_internal")


def connecte(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    # Pas d'instruction préparée : le pooler (mode transaction) change de serveur d'une transaction à l'autre.
    return psycopg.connect(dsn, prepare_threshold=None, connect_timeout=15)


@pytest.fixture(scope="module", autouse=True)
def mots_de_passe_locaux() -> None:
    """Pose les mots de passe locaux, seulement quand aucune adresse distante n'est fournie."""
    if DSN_API_DISTANT or DSN_INTERNAL_DISTANT:
        if not (DSN_API_DISTANT and DSN_INTERNAL_DISTANT):
            pytest.fail("POPOTE_TEST_DSN_API et POPOTE_TEST_DSN_INTERNAL vont ensemble")
        return
    with psycopg.connect(ADMIN_LOCAL, autocommit=True) as cx:
        cx.execute("alter role popote_api password 'essai-local'")
        cx.execute("alter role popote_internal password 'essai-local'")


@pytest.fixture
def cx_api() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with connecte(DSN_API) as cx:
        yield cx


@pytest.fixture
def cx_internal() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with connecte(DSN_INTERNAL) as cx:
        yield cx


@pytest.mark.integration
def test_popote_api_emprunte_authenticated_le_temps_de_la_transaction(
    cx_api: psycopg.Connection[tuple[object, ...]],
) -> None:
    with cx_api.transaction():
        cx_api.execute("set local role authenticated")
        pendant = cx_api.execute("select current_user").fetchone()
    apres = cx_api.execute("select current_user").fetchone()
    assert pendant == ("authenticated",)
    assert apres == ("popote_api",)


@pytest.mark.integration
def test_popote_api_ne_peut_pas_emprunter_service_role(
    cx_api: psycopg.Connection[tuple[object, ...]],
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        cx_api.execute("set role service_role")


@pytest.mark.integration
def test_popote_internal_emprunte_service_role_le_temps_de_la_transaction(
    cx_internal: psycopg.Connection[tuple[object, ...]],
) -> None:
    with cx_internal.transaction():
        cx_internal.execute("set local role service_role")
        pendant = cx_internal.execute("select current_user").fetchone()
    apres = cx_internal.execute("select current_user").fetchone()
    assert pendant == ("service_role",)
    assert apres == ("popote_internal",)


@pytest.mark.integration
def test_popote_internal_ne_peut_pas_emprunter_authenticated(
    cx_internal: psycopg.Connection[tuple[object, ...]],
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        cx_internal.execute("set role authenticated")


@pytest.mark.integration
def test_aucun_droit_sur_les_tables_sans_emprunt(cx_api: psycopg.Connection[tuple[object, ...]]) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        cx_api.execute("select 1 from public.household limit 1")


@pytest.mark.integration
@pytest.mark.xfail(strict=True, reason="EXECUTE hérité de PUBLIC, à fermer à l'étape 0.7")
def test_aucun_droit_d_execute_sur_les_fonctions_security_definer_sans_emprunt(
    cx_api: psycopg.Connection[tuple[object, ...]],
) -> None:
    ouvertes = cx_api.execute(
        """
        select p.oid::regprocedure::text
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public'
          and p.prosecdef
          and has_function_privilege(current_user, p.oid, 'execute')
        order by 1
        """
    ).fetchall()
    assert ouvertes == []
