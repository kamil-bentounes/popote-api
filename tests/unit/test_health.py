import httpx
from _commun import reglages

from popote_api.main import create_app


def client(**autres: object) -> httpx.AsyncClient:
    app = create_app(reglages("local", **autres))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_healthz_rend_la_version_de_l_image() -> None:
    r = await client(version="0123456789abcdef0123456789abcdef01234567").get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0123456789abcdef0123456789abcdef01234567"}


async def test_healthz_sans_version_connue_rend_inconnue() -> None:
    r = await client().get("/api/healthz")
    assert r.json() == {"status": "ok", "version": "inconnue"}


async def test_readyz_sans_base_rend_503() -> None:
    r = await client(database_url="postgresql://x:y@127.0.0.1:1/rien").get("/api/readyz")
    assert r.status_code == 503
    assert r.json()["code"] == "base_indisponible"


async def test_readyz_sans_url_de_base_rend_503() -> None:
    r = await client().get("/api/readyz")
    assert r.status_code == 503
    assert r.json()["code"] == "base_indisponible"
