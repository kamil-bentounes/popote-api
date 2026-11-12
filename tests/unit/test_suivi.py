import logging

import httpx
import pytest
from _commun import reglages

from popote_api import suivi
from popote_api.main import create_app


def test_signale_ne_fait_rien_et_ne_rend_rien() -> None:
    assert suivi.signale(RuntimeError("x"), "abc") is None


async def une_500() -> httpx.Response:
    app = create_app(reglages("local"))

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("interne")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/_test/boom")


async def test_le_gestionnaire_des_500_signale_l_exception_avec_l_identifiant_de_requete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appels: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(suivi, "signale", lambda exc, request_id: appels.append((exc, request_id)))
    reponse = await une_500()
    assert reponse.status_code == 500
    assert len(appels) == 1
    assert isinstance(appels[0][0], RuntimeError)
    assert appels[0][1] == reponse.json()["instance"]


async def test_une_prise_de_suivi_qui_echoue_ne_fait_pas_echouer_la_reponse(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def casse(exc: BaseException, request_id: str) -> None:
        raise ConnectionError("récepteur injoignable")

    monkeypatch.setattr(suivi, "signale", casse)
    with caplog.at_level(logging.ERROR):
        reponse = await une_500()
    assert reponse.status_code == 500
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "erreur_interne"
    messages = [r.getMessage() for r in caplog.records]
    assert "Erreur inattendue" in messages
    assert any("suivi" in m.lower() for m in messages)
