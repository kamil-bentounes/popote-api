"""La fabrique de l'application."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from popote_api import errors
from popote_api.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Popote", version="0.1.0", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json"
    )
    app.state.settings = settings

    @app.middleware("http")
    async def identifiant(request: Request, suite: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = uuid4().hex
        reponse = await suite(request)
        reponse.headers["X-Request-Id"] = request.state.request_id
        return reponse

    errors.installe(app)
    return app


app = create_app()
