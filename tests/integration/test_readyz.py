import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import psycopg
import pytest
from _connexions import DSN_ADMIN, DSN_API

from popote_api.config import Settings
from popote_api.infra import db
from popote_api.main import create_app

pytestmark = pytest.mark.integration


@asynccontextmanager
async def client_de_l_application() -> AsyncIterator[httpx.AsyncClient]:
    """L'application avec son cycle de vie (les pools s'ouvrent au démarrage) et son rôle `popote_api`."""
    app = create_app(Settings.model_validate({"env": "local", "database_url": DSN_API}))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def test_readyz_lit_la_base_par_le_pool_du_role_popote_api() -> None:
    async with client_de_l_application() as client:
        reponse = await client.get("/api/readyz")
    assert reponse.status_code == 200
    assert reponse.json() == {"status": "ok"}


async def test_readyz_rend_503_en_moins_de_quatre_secondes_si_la_table_de_reference_est_verrouillee() -> None:
    # Une table verrouillée par une autre session bloque la lecture : la sonde s'arrête au délai.
    debut = time.monotonic()
    with psycopg.connect(DSN_ADMIN) as verrou:
        verrou.execute("lock table public.instance_setting in access exclusive mode")
        async with client_de_l_application() as client:
            reponse = await client.get("/api/readyz")
    assert reponse.status_code == 503
    assert time.monotonic() - debut < 4


async def test_une_table_sans_ligne_lisible_rend_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "REQUETE_DE_SONDE", "select 1 from public.instance_setting where false")
    async with client_de_l_application() as client:
        reponse = await client.get("/api/readyz")
    assert reponse.status_code == 503
