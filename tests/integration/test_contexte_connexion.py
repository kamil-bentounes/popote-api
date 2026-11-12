"""Spec § 5.1 (3e ligne), B4 : `Base.connexion()`, le rôle de connexion nu, sans rôle emprunté ni identité."""

import re

import pytest
from _fabrique import Fabrique
from psycopg import errors

from popote_api.infra import db
from popote_api.infra.db import Base, BaseIndisponibleError, Pool

pytestmark = pytest.mark.integration


async def test_connexion_agit_comme_popote_api_sans_role_emprunte_ni_identite(base: Base) -> None:
    async with base.connexion() as curseur:
        await curseur.execute(
            "select current_user as role, session_user as connexion,"
            " current_setting('request.jwt.claims', true) as claims"
        )
        ligne = await curseur.fetchone()
    assert ligne is not None
    assert ligne["role"] == "popote_api"
    assert ligne["connexion"] == "popote_api"
    assert ligne["claims"] in (None, "")


async def test_connexion_ne_lit_aucune_table(base: Base, fabrique: Fabrique) -> None:
    fabrique.foyer()
    with pytest.raises(errors.InsufficientPrivilege):
        async with base.connexion() as curseur:
            await curseur.execute("select id from public.household limit 1")


async def test_connexion_pose_les_delais_de_l_api(base: Base) -> None:
    attendu = dict(re.findall(r"set local (\w+) = '([^']+)'", db.DELAIS_API))
    async with base.connexion() as curseur:
        await curseur.execute(
            "select current_setting('statement_timeout') as statement_timeout,"
            " current_setting('lock_timeout') as lock_timeout,"
            " current_setting('idle_in_transaction_session_timeout') as idle_in_transaction_session_timeout"
        )
        assert await curseur.fetchone() == attendu


async def test_une_exception_annule_la_transaction_et_rend_une_connexion_propre(
    base: Base, pools: tuple[Pool, Pool]
) -> None:
    with pytest.raises(ZeroDivisionError):
        async with base.connexion() as curseur:
            await curseur.execute("create temp table essai_connexion (a int)")
            await curseur.execute("insert into essai_connexion values (1)")
            1 / 0  # noqa: B018
    async with pools[0].connection() as connexion:
        ligne = await (await connexion.execute("select to_regclass('pg_temp.essai_connexion')")).fetchone()
        assert ligne == (None,)  # la table temporaire, créée dans la transaction annulée, n'existe plus
        assert connexion.pgconn.transaction_status == 0


async def test_la_sortie_normale_valide_la_transaction(base: Base, pools: tuple[Pool, Pool]) -> None:
    async with base.connexion() as curseur:
        await curseur.execute("create temp table essai_connexion_valide (a int)")
    async with pools[0].connection() as connexion:
        # `on commit drop` n'est pas posé : la table survit au `commit` sur cette connexion du pool.
        ligne = await (
            await connexion.execute("select to_regclass('pg_temp.essai_connexion_valide')")
        ).fetchone()
        assert ligne is not None
        assert ligne[0] is not None
        await connexion.execute("drop table pg_temp.essai_connexion_valide")


async def test_la_connexion_suivante_du_pool_ne_garde_ni_role_ni_identite(
    base: Base, pools: tuple[Pool, Pool]
) -> None:
    async with base.connexion() as curseur:
        await curseur.execute("select set_config('request.jwt.claims', 'x', true)")
    async with pools[0].connection() as connexion:
        ligne = await (
            await connexion.execute("select current_user, current_setting('request.jwt.claims', true)")
        ).fetchone()
        assert ligne == ("popote_api", "")
        assert connexion.pgconn.transaction_status == 0


async def test_sans_pool_api_la_connexion_n_a_pas_de_base() -> None:
    with pytest.raises(BaseIndisponibleError):
        async with Base(None, None).connexion():
            pass
