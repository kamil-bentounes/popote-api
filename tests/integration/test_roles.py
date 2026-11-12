"""Spec § 5.1 : deux rôles de connexion, chacun n'emprunte que le sien, rien ne survit à la transaction.

Base locale par défaut ; `POPOTE_TEST_DSN_API` et `POPOTE_TEST_DSN_INTERNAL` rejouent les tests sur un
autre serveur (voir `_connexions.py`).
"""

from collections.abc import Iterator

import psycopg
import pytest
from _connexions import DSN_API, DSN_INTERNAL, connecte


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
