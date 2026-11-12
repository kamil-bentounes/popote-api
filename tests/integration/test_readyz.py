import logging
import time

import httpx
import psycopg
import pytest

from popote_api.config import Settings
from popote_api.infra import db
from popote_api.main import create_app

LOCALE = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
SERVICE_LOCAL = "postgresql://popote_api:essai-local@127.0.0.1:54322/postgres"


@pytest.mark.integration
async def test_readyz_avec_la_base_locale() -> None:
    app = create_app(Settings.model_validate({"env": "local", "database_url": LOCALE}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.integration
async def test_un_select_bloque_rend_false_en_moins_de_quatre_secondes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    debut = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="popote_api.infra.db"):
        assert await db.repond(LOCALE, "select pg_sleep(10)") is False
    assert time.monotonic() - debut < 4
    assert "TimeoutError" in caplog.text


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


@pytest.mark.integration
async def test_la_sonde_passe_avec_le_role_du_service_qui_n_a_aucun_droit_sur_les_tables() -> None:
    with psycopg.connect(LOCALE, autocommit=True) as admin:
        admin.execute("alter role popote_api password 'essai-local'")
    assert await db.repond(SERVICE_LOCAL) is True


@pytest.mark.integration
async def test_la_sonde_lit_vraiment_la_table_de_reference() -> None:
    # Une table verrouillée par une autre session bloque la lecture : la sonde s'arrête au délai.
    debut = time.monotonic()
    with psycopg.connect(LOCALE) as verrou:
        verrou.execute("lock table public.instance_setting in access exclusive mode")
        assert await db.repond(LOCALE) is False
    assert time.monotonic() - debut < 4


@pytest.mark.integration
async def test_une_table_sans_ligne_lisible_rend_false() -> None:
    assert await db.repond(LOCALE, "select 1 from public.instance_setting where false") is False
