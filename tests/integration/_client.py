"""L'application complète contre la base locale, et le cookie d'une session de test."""

import httpx
import pytest
from _fabrique import SessionDeTest
from fastapi import APIRouter, FastAPI

from popote_api.api import v1
from popote_api.config import Settings
from popote_api.infra.db import Base
from popote_api.main import create_app

NOM_DU_COOKIE = "__Host-popote_session"


def application_de_test(base: Base, monkeypatch: pytest.MonkeyPatch, *routeurs: APIRouter) -> FastAPI:
    """L'application, ses routes de `/api/v1` remplacées par `routeurs` si on en donne, sur la base du test.

    `base` vient de la fixture du conftest : ses pools sont déjà ouverts, l'application ne gère pas leur vie.
    """
    if routeurs:
        monkeypatch.setattr(v1, "SOUS_ROUTEURS", routeurs)
    app = create_app(Settings.model_validate({"env": "local", "json_logs": False}))
    app.state.base = base
    return app


def client_de(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def cookie(session: SessionDeTest) -> dict[str, str]:
    return {"Cookie": f"{NOM_DU_COOKIE}={session.jeton}"}
