"""Spec § 5.1 et § 8.2 : les deux contextes de `Base`, leurs délais, leur propreté à la rendue au pool.

Base locale par défaut ; `POPOTE_TEST_DSN_API`, `POPOTE_TEST_DSN_INTERNAL` et `POPOTE_TEST_DSN_ADMIN` les
rejouent sur un autre serveur. Chaque test affirme `session_user` : c'est le rôle de CONNEXION, la preuve
qu'on parle bien au rôle attendu même derrière un pooler.
"""

import asyncio
import re
import time
from uuid import uuid4

import psycopg
import pytest
from _connexions import DSN_ADMIN, DSN_API, DSN_API_DISTANT
from _fabrique import Fabrique
from psycopg_pool import PoolTimeout

from popote_api import limites
from popote_api.infra import db
from popote_api.infra.db import Base, Pool, ServiceIndisponibleError, cree_pool

pytestmark = pytest.mark.integration

ETAT_AU_REPOS = "select current_user, session_user, current_setting('request.jwt.claims', true)"


async def au_repos(pool: Pool) -> dict[str, object]:
    """Ce que voit le prochain code qui emprunte une connexion du pool, hors de tout contexte."""
    async with pool.connection() as connexion:
        curseur = await connexion.execute(ETAT_AU_REPOS)
        ligne = await curseur.fetchone()
        assert ligne is not None
        return {
            "role": ligne[0],
            "connexion": ligne[1],
            "claims": ligne[2],
            "etat": connexion.pgconn.transaction_status,
        }


async def test_personne_agit_comme_authenticated_avec_son_identite(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await curseur.execute(
            "select current_user as role, session_user as connexion, auth.uid() as uid, auth.role() as r"
        )
        ligne = await curseur.fetchone()
    assert ligne == {
        "role": "authenticated",
        "connexion": "popote_api",
        "uid": personne.id,
        "r": "authenticated",
    }


async def test_service_agit_comme_service_role_depuis_popote_internal(base: Base) -> None:
    async with base.service() as curseur:
        await curseur.execute(
            "select current_user as role, session_user as connexion, auth.role() as r, auth.uid() as uid"
        )
        ligne = await curseur.fetchone()
    assert ligne == {"role": "service_role", "connexion": "popote_internal", "r": "service_role", "uid": None}


async def test_la_connexion_suivante_du_pool_ne_garde_ni_role_ni_identite(
    base: Base, pools: tuple[Pool, Pool], fabrique: Fabrique
) -> None:
    api, interne = pools
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id):
        pass
    async with base.service():
        pass
    assert await au_repos(api) == {"role": "popote_api", "connexion": "popote_api", "claims": "", "etat": 0}
    assert await au_repos(interne) == {
        "role": "popote_internal",
        "connexion": "popote_internal",
        "claims": "",
        "etat": 0,
    }


@pytest.mark.skipif(
    DSN_API_DISTANT is not None, reason="derrière un pooler, le serveur change d'une transaction à l'autre"
)
async def test_la_connexion_reprise_est_bien_la_meme(
    base: Base, pools: tuple[Pool, Pool], fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await curseur.execute("select pg_backend_pid() as pid")
        pendant = await curseur.fetchone()
    async with pools[0].connection() as connexion:
        apres = await (await connexion.execute("select pg_backend_pid()")).fetchone()
    assert pendant is not None
    assert apres == (pendant["pid"],)


async def test_une_exception_annule_l_ecriture_et_rend_une_connexion_propre(
    base: Base, pools: tuple[Pool, Pool], fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    with pytest.raises(ZeroDivisionError):
        async with base.personne(personne.id) as curseur:
            await curseur.execute(
                "update public.user_profile set display_name = 'changé' where id = %s", (personne.id,)
            )
            assert curseur.rowcount == 1
            1 / 0  # noqa: B018
    async with base.personne(personne.id) as curseur:
        await curseur.execute("select display_name from public.user_profile where id = %s", (personne.id,))
        ligne = await curseur.fetchone()
    assert ligne is not None
    assert ligne["display_name"] != "changé"
    assert (await au_repos(pools[0]))["etat"] == 0


async def test_la_sortie_normale_valide_l_ecriture(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await curseur.execute(
            "update public.user_profile set display_name = 'changé' where id = %s", (personne.id,)
        )
    async with base.personne(personne.id) as curseur:
        await curseur.execute("select display_name from public.user_profile where id = %s", (personne.id,))
        ligne = await curseur.fetchone()
    assert ligne == {"display_name": "changé"}


async def test_la_rls_ne_montre_que_le_foyer_de_la_personne(base: Base, fabrique: Fabrique) -> None:
    ma_personne = fabrique.personne(fabrique.foyer())
    autre = fabrique.personne(fabrique.foyer())
    async with base.personne(ma_personne.id) as curseur:
        await curseur.execute(
            "select id from public.household where id = any(%s)", ([ma_personne.foyer_id, autre.foyer_id],)
        )
        foyers = [ligne["id"] for ligne in await curseur.fetchall()]
        await curseur.execute(
            "select id from public.user_profile where id = any(%s)", ([ma_personne.id, autre.id],)
        )
        profils = [ligne["id"] for ligne in await curseur.fetchall()]
    assert foyers == [ma_personne.foyer_id]
    assert profils == [ma_personne.id]


async def test_sans_personne_connue_la_rls_ne_montre_aucun_foyer(base: Base, fabrique: Fabrique) -> None:
    foyer = fabrique.foyer()
    async with base.personne(uuid4()) as curseur:
        await curseur.execute("select id from public.household where id = %s", (foyer,))
        assert await curseur.fetchall() == []


async def test_service_voit_les_deux_foyers(base: Base, fabrique: Fabrique) -> None:
    foyers = [fabrique.foyer(), fabrique.foyer()]
    async with base.service() as curseur:
        await curseur.execute("select id from public.household where id = any(%s)", (foyers,))
        assert {ligne["id"] for ligne in await curseur.fetchall()} == set(foyers)


async def test_sans_adresse_interne_service_leve_une_erreur_typee(pools: tuple[Pool, Pool]) -> None:
    with pytest.raises(ServiceIndisponibleError):
        async with Base(pools[0], None).service():
            pass


async def test_un_pool_epuise_leve_pooltimeout_sans_attendre_longtemps() -> None:
    api = cree_pool(DSN_API, 1, attente_s=0.3)
    await api.open(wait=False)
    try:
        base = Base(api, None)
        async with base.personne(uuid4()):
            debut = time.monotonic()
            with pytest.raises(PoolTimeout):
                async with base.personne(uuid4()):
                    pass
        assert time.monotonic() - debut < 2
    finally:
        await api.close()


def delais_du_code(constante: str) -> dict[str, str]:
    return dict(re.findall(r"set local (\w+) = '([^']+)'", constante))


def delais_du_role(rolconfig: list[str]) -> dict[str, str]:
    return dict(parametre.split("=", 1) for parametre in rolconfig)


@pytest.mark.parametrize(
    ("role", "constante"), [("popote_api", db.DELAIS_API), ("popote_internal", db.DELAIS_INTERNE)]
)
async def test_les_delais_du_code_sont_ceux_du_role(base: Base, role: str, constante: str) -> None:
    async with base.service() as curseur:
        await curseur.execute("select rolconfig from pg_roles where rolname = %s", (role,))
        ligne = await curseur.fetchone()
    assert ligne is not None
    assert delais_du_role(ligne["rolconfig"]) == delais_du_code(constante)


@pytest.mark.parametrize("contexte", ["personne", "service"])
async def test_chaque_contexte_pose_ses_delais(base: Base, fabrique: Fabrique, contexte: str) -> None:
    ouvert = (
        base.personne(fabrique.personne(fabrique.foyer()).id) if contexte == "personne" else base.service()
    )
    attendu = delais_du_code(db.DELAIS_API if contexte == "personne" else db.DELAIS_INTERNE)
    if contexte == "service":
        attendu["statement_timeout"] = db.DELAI_DE_LA_BASE_DU_SERVICE
    async with ouvert as curseur:
        await curseur.execute(
            "select current_setting('statement_timeout') as statement_timeout,"
            " current_setting('lock_timeout') as lock_timeout,"
            " current_setting('idle_in_transaction_session_timeout') as idle_in_transaction_session_timeout"
        )
        assert await curseur.fetchone() == attendu


async def test_le_contexte_service_coupe_la_requete_avant_le_delai_de_l_api(base: Base) -> None:
    async with base.service() as curseur:
        await curseur.execute(
            "select current_setting('statement_timeout')::interval <= interval '20 seconds' as borne,"
            " current_setting('statement_timeout')::interval < make_interval(secs => %s) as avant_l_api",
            (limites.DELAI_SECONDES,),
        )
        assert await curseur.fetchone() == {"borne": True, "avant_l_api": True}


async def test_le_delai_de_la_base_coupe_une_requete_longue_en_sqlstate_57014(
    base: Base, pools: tuple[Pool, Pool]
) -> None:
    debut = time.monotonic()
    with pytest.raises(psycopg.errors.QueryCanceled) as erreur:
        async with base.personne(uuid4()) as curseur:
            await curseur.execute("set local statement_timeout = '300ms'")
            await curseur.execute("select pg_sleep(5)")
    assert erreur.value.sqlstate == "57014"
    assert time.monotonic() - debut < 3
    assert (await au_repos(pools[0]))["etat"] == 0


async def test_une_requete_annulee_cote_client_rend_une_connexion_propre(
    base: Base, pools: tuple[Pool, Pool]
) -> None:
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.4):
            async with base.personne(uuid4()) as curseur:
                await curseur.execute("select pg_sleep(5)")
    assert await au_repos(pools[0]) == {
        "role": "popote_api",
        "connexion": "popote_api",
        "claims": "",
        "etat": 0,
    }
    async with pools[0].connection() as connexion:
        curseur = await connexion.execute(
            "select count(*) from pg_stat_activity"
            " where state = 'active' and query like 'select pg_sleep(5)%%'"
        )
        assert await curseur.fetchone() == (0,)


async def test_les_set_local_posent_les_delais_meme_si_la_connexion_arrive_sans(fabrique: Fabrique) -> None:
    # Une connexion ouverte avec des délais nuls (options de démarrage, qui l'emportent sur le rôle) : seuls
    # les `set local` du contexte peuvent lui donner ceux du code.
    options = "-c statement_timeout=0 -c lock_timeout=0 -c idle_in_transaction_session_timeout=0"
    pool = cree_pool(DSN_API, 1)
    pool.kwargs["options"] = options
    await pool.open(wait=False)
    try:
        async with pool.connection() as connexion:
            ligne = await (await connexion.execute("show statement_timeout")).fetchone()
        assert ligne == ("0",)  # le piège est bien posé : sans contexte, aucun délai
        personne = fabrique.personne(fabrique.foyer())
        async with Base(pool, None).personne(personne.id) as curseur:
            await curseur.execute("select current_setting('statement_timeout') as statement_timeout")
            assert await curseur.fetchone() == {"statement_timeout": "8s"}
    finally:
        await pool.close()


async def test_aucune_instruction_n_est_preparee_cote_serveur(base: Base, fabrique: Fabrique) -> None:
    # Derrière un pooler en mode transaction, une instruction préparée se retrouve sur un autre serveur.
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        for _ in range(8):  # au-delà du seuil par défaut de psycopg (5)
            await curseur.execute("select id from public.user_profile where id = %s", (personne.id,))
        await curseur.execute("select count(*) as n from pg_prepared_statements")
        assert await curseur.fetchone() == {"n": 0}


@pytest.mark.skipif(
    DSN_API_DISTANT is not None, reason="le pid n'est pas celui du serveur derrière un pooler"
)
async def test_une_connexion_tuee_pendant_qu_elle_dormait_n_est_pas_rendue_au_code(
    base: Base, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await curseur.execute("select pg_backend_pid() as pid")
        ligne = await curseur.fetchone()
    assert ligne is not None
    with psycopg.connect(DSN_ADMIN, autocommit=True) as admin:
        admin.execute("select pg_terminate_backend(%s)", (ligne["pid"],))
        while admin.execute("select 1 from pg_stat_activity where pid = %s", (ligne["pid"],)).fetchone():
            pass  # attend que le serveur ait fini de fermer la connexion
    async with base.personne(personne.id) as curseur:  # `check=` écarte la connexion morte
        await curseur.execute("select 1 as un")
        assert await curseur.fetchone() == {"un": 1}
