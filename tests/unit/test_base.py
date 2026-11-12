"""`Base` sans serveur : ce qui dépend seulement de la configuration."""

import importlib
import logging
import time
from uuid import uuid4

import httpx
import pytest
from _commun import DSN, reglages
from psycopg_pool import PoolClosed

from popote_api.infra.db import FILTRE_DU_POOL, Base, BaseIndisponibleError, ServiceIndisponibleError
from popote_api.main import create_app


async def test_sans_pool_api_la_personne_n_a_pas_de_base() -> None:
    with pytest.raises(BaseIndisponibleError):
        async with Base(None, None).personne(uuid4()):
            pass


async def test_sans_pool_interne_le_service_n_a_pas_de_base() -> None:
    with pytest.raises(ServiceIndisponibleError):
        async with Base(None, None).service():
            pass


async def test_ouvrir_et_fermer_sans_pool_ne_fait_rien() -> None:
    base = Base(None, None)
    await base.ouvre()
    await base.ferme()


async def test_le_demarrage_n_attend_pas_de_connexion_et_l_arret_ferme_les_pools() -> None:
    # Adresse injoignable : si le démarrage attendait une connexion, il échouerait ou tarderait.
    app = create_app(reglages("essai", database_url_internal=DSN, internal_secret="i" * 32))
    debut = time.monotonic()
    async with app.router.lifespan_context(app):
        assert time.monotonic() - debut < 1
    with pytest.raises(PoolClosed):
        async with app.state.base.personne(uuid4()):
            pass


async def test_sans_adresse_interne_le_demarrage_avertit_et_la_base_de_service_manque(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(reglages("essai"))
    with caplog.at_level(logging.WARNING, logger="popote_api.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "POPOTE_DATABASE_URL_INTERNAL" in caplog.text
    assert app.state.base.service_configure is False


async def test_avec_l_adresse_interne_le_demarrage_n_avertit_pas(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(reglages("essai", database_url_internal=DSN, internal_secret="i" * 32))
    with caplog.at_level(logging.WARNING, logger="popote_api.main"):
        async with app.router.lifespan_context(app):
            pass
    assert caplog.text == ""
    assert app.state.base.service_configure is True


async def test_readyz_sans_base_configuree_rend_503() -> None:
    app = create_app(reglages("local"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        reponse = await client.get("/api/readyz")
    assert reponse.status_code == 503


@pytest.mark.parametrize(
    "module",
    [
        "psycopg.connection_async",
        "psycopg.generators",
        "psycopg.transaction",
        "psycopg.waiting",
        "psycopg_pool.pool_async",
        "psycopg_pool.sched_async",
    ],
)
def test_le_journal_de_chaque_module_de_psycopg_est_filtre(module: str) -> None:
    Base(None, None)
    assert FILTRE_DU_POOL in importlib.import_module(module).logger.filters


@pytest.mark.parametrize(
    ("modele", "arguments"),
    [
        ("discarding expired connection %s", ("<psycopg.AsyncConnection (host=db.interne port=5432)>",)),
        ("error connecting in %r: %s", ("pool-1", "connection to server at db.interne failed")),
        ("error ignored in rollback on %s", ("<psycopg.AsyncConnection [INTRANS] (host=db.interne)>",)),
    ],
)
def test_le_filtre_ne_garde_que_le_modele_du_message(modele: str, arguments: tuple[str, ...]) -> None:
    enregistrement = logging.LogRecord("psycopg.pool", logging.WARNING, "x", 1, modele, arguments, None)
    FILTRE_DU_POOL.filter(enregistrement)
    assert "db.interne" not in enregistrement.getMessage()
    assert enregistrement.getMessage().startswith(modele.partition("%")[0].rstrip(" :"))


async def test_sans_pool_api_la_connexion_n_a_pas_de_base() -> None:
    with pytest.raises(BaseIndisponibleError):
        async with Base(None, None).connexion():
            pass
