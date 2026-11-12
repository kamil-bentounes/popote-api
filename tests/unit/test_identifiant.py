import json

import httpx
from _commun import RELAIS, appeler, reglages

from popote_api.main import create_app


async def test_une_reponse_normale_porte_un_identifiant() -> None:
    retour = await appeler(create_app(reglages("local")), "GET", "/api/readyz")
    assert retour.en_tetes["x-request-id"] == json.loads(retour.corps)["instance"]


async def test_chaque_requete_recoit_son_propre_identifiant() -> None:
    app = create_app(reglages("local"))
    premier = await appeler(app, "GET", "/api/healthz")
    second = await appeler(app, "GET", "/api/healthz")
    assert premier.en_tetes["x-request-id"] != second.en_tetes["x-request-id"]


async def test_un_identifiant_envoye_par_le_client_n_est_pas_repris() -> None:
    app = create_app(reglages("local"))
    retour = await appeler(app, "GET", "/api/healthz", {"X-Request-Id": "choisi-par-le-client"})
    assert retour.en_tetes["x-request-id"] != "choisi-par-le-client"


async def test_une_500_porte_un_identifiant_egal_a_son_instance() -> None:
    app = create_app(reglages("essai"))

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("interne")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/boom", headers=RELAIS)
    assert r.status_code == 500
    assert r.headers["x-request-id"] == r.json()["instance"]
