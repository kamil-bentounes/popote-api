import httpx
from _commun import ECRITURE_ESSAI, RELAIS, reglages

from popote_api.main import create_app


def client(env: str) -> httpx.AsyncClient:
    app = create_app(reglages(env))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test")


async def test_les_preuves_nexistent_pas_en_prod() -> None:
    assert (await client("prod").post("/api/_preuves/cookie", headers=RELAIS)).status_code == 404


async def test_les_preuves_nexistent_pas_en_local() -> None:
    assert (await client("local").post("/api/_preuves/cookie")).status_code == 404


async def test_le_cookie_de_preuve_a_les_bons_attributs() -> None:
    r = await client("essai").post("/api/_preuves/cookie", headers=RELAIS | ECRITURE_ESSAI)
    cookie = r.headers["set-cookie"]
    for attribut in ("__Host-popote_preuve=", "HttpOnly", "Secure", "Path=/", "SameSite=lax"):
        assert attribut in cookie
    assert "Domain" not in cookie


async def test_la_lecture_dit_le_cookie_et_lip() -> None:
    c = client("essai")
    r = await c.get(
        "/api/_preuves/cookie",
        headers={**RELAIS, "X-Popote-IP": "203.0.113.7", "Cookie": "__Host-popote_preuve=abc"},
    )
    assert r.json() == {"cookie_recu": True, "ip": "203.0.113.7"}
    assert r.headers["cache-control"] == "no-store"


async def test_la_lecture_sans_cookie_le_dit() -> None:
    r = await client("essai").get("/api/_preuves/cookie", headers=RELAIS)
    assert r.json()["cookie_recu"] is False


async def test_la_lecture_sans_ip_annoncee_rend_une_ip_nulle() -> None:
    r = await client("essai").get("/api/_preuves/cookie", headers=RELAIS)
    assert r.json()["ip"] is None
