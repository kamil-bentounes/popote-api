import httpx
import pytest

from popote_api.config import Settings
from popote_api.main import create_app

LOCALE = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


@pytest.mark.integration
async def test_readyz_avec_la_base_locale() -> None:
    app = create_app(Settings(env="local", database_url=LOCALE))  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
