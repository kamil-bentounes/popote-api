import time

import httpx
import pytest

from popote_api.config import Settings
from popote_api.infra import db
from popote_api.main import create_app

LOCALE = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


@pytest.mark.integration
async def test_readyz_avec_la_base_locale() -> None:
    app = create_app(Settings.model_validate({"env": "local", "database_url": LOCALE}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.integration
async def test_un_select_bloque_rend_false_en_moins_de_quatre_secondes() -> None:
    debut = time.monotonic()
    assert await db.repond(LOCALE, "select pg_sleep(10)") is False
    assert time.monotonic() - debut < 4


@pytest.mark.integration
async def test_readyz_rend_503_en_moins_de_quatre_secondes_si_la_base_est_bloquee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vraie = db.repond

    async def bloquee(dsn: str) -> bool:
        return await vraie(dsn, "select pg_sleep(10)")

    monkeypatch.setattr(db, "repond", bloquee)
    app = create_app(Settings.model_validate({"env": "local", "database_url": LOCALE}))
    debut = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/readyz")
    assert r.status_code == 503
    assert time.monotonic() - debut < 4
