"""Les erreurs que la base produit vraiment, rendues par l'application (spec § 8.2).

Chaque route d'essai est ajoutée à une application complète (garde, identifiant, gestionnaires, pools réels) ;
rien n'est écrit en base : chaque transaction échoue, donc s'annule.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from _connexions import DSN_ADMIN, DSN_API, DSN_INTERNAL
from _fabrique import Fabrique
from fastapi import FastAPI

from popote_api.config import Settings
from popote_api.erreurs_base import refus_vaut_introuvable
from popote_api.infra.db import Base, cree_pool
from popote_api.main import create_app

pytestmark = pytest.mark.integration

# Recopiée dans le DETAIL des erreurs de la base : elle ne doit apparaître ni dans la réponse, ni au journal.
NOM_SECRET = "foyer-montant-4217-Zoe"


def ajoute_les_routes(app: FastAPI, personne: UUID, base: Base) -> None:

    @app.get("/essai/doublon")
    async def doublon() -> None:
        async with base.service() as curseur:
            requete = "insert into public.household (id, name) values (%s, %s)"
            foyer = uuid4()
            await curseur.execute(requete, (foyer, NOM_SECRET))
            await curseur.execute(requete, (foyer, NOM_SECRET))

    @app.get("/essai/cle-etrangere")
    async def cle_etrangere() -> None:
        async with base.service() as curseur:
            await curseur.execute(
                "insert into public.user_profile (id, household_id, display_name) values (%s, %s, %s)",
                (uuid4(), uuid4(), NOM_SECRET),
            )

    @app.get("/essai/non-nul")
    async def non_nul() -> None:
        async with base.service() as curseur:
            await curseur.execute(
                "insert into public.user_profile (id, household_id, display_name) values (%s, null, %s)",
                (uuid4(), NOM_SECRET),
            )

    @app.get("/essai/contrainte")
    async def contrainte() -> None:
        async with base.service() as curseur:
            await curseur.execute(
                "insert into public.household (name, food_budget_eur) values (%s, -1)", (NOM_SECRET,)
            )

    @app.get("/essai/mauvais-uuid")
    async def mauvais_uuid() -> None:
        async with base.personne(personne) as curseur:
            await curseur.execute("select %s::uuid", (NOM_SECRET,))

    @app.get("/essai/droit-refuse")
    async def droit_refuse() -> None:
        async with base.personne(personne) as curseur:
            await curseur.execute("select id from auth.users limit 1")

    @app.get("/essai/droit-refuse-cible")
    async def droit_refuse_cible() -> None:
        async with base.personne(personne) as curseur:
            with refus_vaut_introuvable():
                await curseur.execute("insert into public.instance_setting (key, value) values ('x', '{}')")

    @app.get("/essai/serialisation/{sqlstate}")
    async def serialisation(sqlstate: str) -> None:
        async with base.personne(personne) as curseur:
            await curseur.execute(f"do $$ begin raise exception 'x' using errcode = '{sqlstate}'; end $$")

    @app.get("/essai/verrou")
    async def verrou() -> None:
        async with base.service() as curseur:
            await curseur.execute("set local lock_timeout = '200ms'")
            await curseur.execute("lock table public.instance_setting in access exclusive mode")

    @app.get("/essai/delai")
    async def delai() -> None:
        async with base.personne(personne) as curseur:
            await curseur.execute("set local statement_timeout = '300ms'")
            await curseur.execute("select pg_sleep(5)")


@asynccontextmanager
async def client(fabrique: Fabrique, base: Base | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """L'application complète ; les routes d'essai passent par sa `Base`, ou par celle qu'on lui donne."""
    app = create_app(
        Settings.model_validate(
            {
                "env": "local",
                "database_url": DSN_API,
                "database_url_internal": DSN_INTERNAL,
                "internal_secret": "i"
                * 32,  # sans lui, le démarrage avertit et fausse les comptes d'avertissements
            }
        )
    )
    ajoute_les_routes(app, fabrique.personne(fabrique.foyer()).id, base or app.state.base)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.parametrize(
    ("chemin", "status", "code"),
    [
        ("/essai/doublon", 409, "conflit"),
        ("/essai/cle-etrangere", 422, "donnees_invalides"),
        ("/essai/contrainte", 422, "donnees_invalides"),
        ("/essai/mauvais-uuid", 422, "donnees_invalides"),
        ("/essai/non-nul", 500, "erreur_interne"),  # 23502 : sans traduction, son DETAIL recopie la ligne
        ("/essai/droit-refuse", 500, "erreur_interne"),
        ("/essai/droit-refuse-cible", 404, "introuvable"),
        ("/essai/serialisation/40001", 503, "reessayer"),
        ("/essai/serialisation/40P01", 503, "reessayer"),
        ("/essai/delai", 503, "delai_depasse"),
    ],
)
async def test_une_vraie_erreur_de_la_base_est_rendue_sans_son_message(
    fabrique: Fabrique, capsys: pytest.CaptureFixture[str], chemin: str, status: int, code: str
) -> None:
    # Le journal vérifié est celui que l'application écrit (JSON, sortie standard), pas le rendu de pytest.
    async with client(fabrique) as c:
        reponse = await c.get(chemin)
    assert (reponse.status_code, reponse.json()["code"]) == (status, code)
    assert NOM_SECRET not in reponse.text
    assert NOM_SECRET not in capsys.readouterr().out


async def test_un_conflit_journalise_la_contrainte_et_la_table(
    fabrique: Fabrique, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="popote_api.erreurs_base"):
        async with client(fabrique) as c:
            await c.get("/essai/doublon")
    assert "sqlstate=23505" in caplog.text
    assert "contrainte=household_pkey" in caplog.text
    assert "table=household" in caplog.text


@pytest.mark.parametrize(
    ("chemin", "objet", "rendu"),
    [("/essai/droit-refuse", "users", 500), ("/essai/droit-refuse-cible", "instance_setting", 404)],
)
async def test_un_droit_refuse_est_journalise_en_avertissement_avec_son_objet(
    fabrique: Fabrique, caplog: pytest.LogCaptureFixture, chemin: str, objet: str, rendu: int
) -> None:
    with caplog.at_level(logging.WARNING, logger="popote_api.erreurs_base"):
        async with client(fabrique) as c:
            await c.get(chemin)
    avertissements = [
        r for r in caplog.records if r.levelno == logging.WARNING and r.name == "popote_api.erreurs_base"
    ]
    assert len(avertissements) == 1
    assert f"objet={objet}" in avertissements[0].getMessage()
    assert f"rendu={rendu}" in avertissements[0].getMessage()


async def test_les_erreurs_transitoires_portent_retry_after(fabrique: Fabrique) -> None:
    async with client(fabrique) as c:
        reponse = await c.get("/essai/serialisation/40001")
    assert reponse.headers["retry-after"] == "1"


async def test_un_verrou_trop_long_est_55p03_rendu_en_503_reessayer(fabrique: Fabrique) -> None:
    # Le client (et la personne que la fabrique crée) existent AVANT le verrou : créer un foyer écrit
    # dans `instance_setting`, que le verrou bloquerait.
    async with client(fabrique) as c:
        with psycopg.connect(DSN_ADMIN) as bloqueur:
            bloqueur.execute("lock table public.instance_setting in access exclusive mode")
            reponse = await c.get("/essai/verrou")
    assert (reponse.status_code, reponse.json()["code"]) == (503, "reessayer")
    assert reponse.headers["retry-after"] == "1"


async def test_le_delai_de_la_base_coupe_vite_et_rend_503_delai_depasse(fabrique: Fabrique) -> None:
    debut = time.monotonic()
    async with client(fabrique) as c:
        reponse = await c.get("/essai/delai")
    assert reponse.json()["code"] == "delai_depasse"
    assert time.monotonic() - debut < 3


async def test_un_pool_epuise_rend_503_base_indisponible_sans_attendre_longtemps(fabrique: Fabrique) -> None:
    pool = cree_pool(DSN_API, 1, attente_s=0.3)
    await pool.open(wait=False)
    base = Base(pool, None)
    libere = asyncio.Event()

    async def occupe() -> None:
        async with base.personne(uuid4()):
            await libere.wait()

    try:
        async with client(fabrique, base) as c:
            tache = asyncio.create_task(occupe())
            await asyncio.sleep(0)  # laisse la tâche emprunter l'unique connexion
            debut = time.monotonic()
            reponse = await c.get("/essai/mauvais-uuid")
            libere.set()
            await tache
    finally:
        await pool.close()
    assert (reponse.status_code, reponse.json()["code"]) == (503, "base_indisponible")
    assert time.monotonic() - debut < 2
