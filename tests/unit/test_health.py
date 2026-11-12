import httpx

from popote_api.config import Settings
from popote_api.main import create_app


def client(**reglages: object) -> httpx.AsyncClient:
    app = create_app(Settings(env="local", **reglages))  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_healthz() -> None:
    r = await client().get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_sans_base_rend_503() -> None:
    r = await client(database_url="postgresql://x:y@127.0.0.1:1/rien").get("/api/readyz")
    assert r.status_code == 503
    assert r.json()["code"] == "base_indisponible"


async def test_readyz_sans_url_de_base_rend_503() -> None:
    r = await client().get("/api/readyz")
    assert r.status_code == 503
    assert r.json()["code"] == "base_indisponible"
