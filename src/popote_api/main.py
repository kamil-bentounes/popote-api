"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from popote_api import errors, relais
from popote_api.api import health, preuves
from popote_api.config import Env, Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    # POPOTE_ENV et les autres réglages viennent de l'environnement du processus.
    settings = settings or Settings()  # type: ignore[call-arg]
    app = FastAPI(
        title="Popote", version="0.1.0", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json"
    )
    app.state.settings = settings

    # Starlette exécute en premier le dernier middleware déclaré : `identifiant` doit envelopper `garde`.
    app.middleware("http")(relais.garde)

    @app.middleware("http")
    async def identifiant(request: Request, suite: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = uuid4().hex
        reponse = await suite(request)
        reponse.headers["X-Request-Id"] = request.state.request_id
        return reponse

    app.include_router(health.router)
    if settings.env is Env.essai:
        app.include_router(preuves.router)
    errors.installe(app)
    return app
