"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

from fastapi import FastAPI

from popote_api import errors, relais
from popote_api.api import health, preuves
from popote_api.config import Env, Settings
from popote_api.identifiant import Identifiant
from popote_api.infra.db import SondeBase


def create_app(settings: Settings | None = None) -> FastAPI:
    # POPOTE_ENV et les autres réglages viennent de l'environnement du processus.
    settings = settings or Settings()  # type: ignore[call-arg]
    app = FastAPI(
        title="Popote", version="0.1.0", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json"
    )
    app.state.settings = settings
    dsn = settings.database_url.get_secret_value() if settings.database_url else None
    app.state.sonde = SondeBase(dsn)

    # Le dernier middleware ajouté est le plus extérieur : `Identifiant` enveloppe `Garde`, si bien que
    # le refus de la garde porte lui aussi son identifiant.
    app.add_middleware(relais.Garde, settings=settings)
    app.add_middleware(Identifiant)

    app.include_router(health.router)
    if settings.env is Env.essai:
        app.include_router(preuves.router)
    errors.installe(app)
    return app
