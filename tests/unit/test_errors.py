import json

import httpx
import pytest
from _commun import reglages
from starlette.requests import Request

from popote_api.errors import reponse
from popote_api.main import create_app


@pytest.fixture
def client() -> httpx.AsyncClient:
    app = create_app(reglages("local"))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_une_route_inconnue_rend_un_probleme(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/nexiste-pas")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    corps = r.json()
    assert corps["type"] == "https://notre-popote.fr/problemes/introuvable"
    assert corps["status"] == 404
    assert corps["code"] == "introuvable"
    assert corps["title"] == "Introuvable"
    assert corps["instance"]
    assert "Traceback" not in r.text


async def test_chaque_reponse_porte_son_identifiant(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/nexiste-pas")
    assert r.headers["x-request-id"] == r.json()["instance"]


async def test_une_methode_non_permise_rend_405_en_probleme() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/lecture")
    async def lecture() -> dict[str, bool]:
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/_test/lecture")
    assert r.status_code == 405
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "methode_non_permise"


async def test_une_donnee_invalide_rend_422_avec_ses_erreurs() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/nombre/{n}")
    async def nombre(n: int) -> dict[str, int]:
        return {"n": n}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/nombre/abc")
    assert r.status_code == 422
    corps = r.json()
    assert corps["code"] == "donnees_invalides"
    assert corps["errors"][0]["pointer"] == "/n"


async def test_une_exception_inattendue_rend_500_sans_trace() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret interne: postgresql://u:p@h/db")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    corps = r.json()
    assert corps["code"] == "erreur_interne"
    assert corps["instance"]
    assert r.headers["x-request-id"] == corps["instance"]
    assert "Traceback" not in r.text
    assert "secret interne" not in r.text


def test_reponse_sans_identifiant_de_requete_prend_une_valeur_de_repli() -> None:
    requete = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    r = reponse(requete, 404, "introuvable", "Cette adresse n'existe pas.")
    corps = json.loads(bytes(r.body))
    assert corps["instance"]
    assert r.headers["x-request-id"] == corps["instance"]
