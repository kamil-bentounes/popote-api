"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

from fastapi import FastAPI

from popote_api import errors, limites, relais
from popote_api.api import health, preuves
from popote_api.config import Env, Settings
from popote_api.identifiant import Identifiant
from popote_api.infra.db import SondeBase


def create_app(settings: Settings | None = None) -> FastAPI:
    # POPOTE_ENV et les autres réglages viennent de l'environnement du processus.
    settings = settings or Settings()  # type: ignore[call-arg]
    # Le contrat n'est publié ni en prod, ni sous une forme interactive. Pas de redirection de
    # barre finale : `/api/x/` n'est pas `/api/x`, et une redirection révélerait la route.
    app = FastAPI(
        title="Popote",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None if settings.env is Env.prod else "/api/openapi.json",
        redirect_slashes=False,
    )
    app.state.settings = settings
    dsn = settings.database_url.get_secret_value() if settings.database_url else None
    app.state.sonde = SondeBase(dsn)

    # Le dernier middleware ajouté est le plus extérieur. De l'extérieur vers l'intérieur : `Identifiant`
    # (tout refus porte son identifiant), `Garde` (un appelant sans le secret du relais est renvoyé avant
    # que son corps soit lu), puis les limites de `limites.py`, le délai enveloppant les autres.
    app.add_middleware(limites.TailleMax)
    app.add_middleware(limites.TypeJson)
    app.add_middleware(limites.Delai, secondes=limites.DELAI_SECONDES)
    app.add_middleware(limites.SansCache)
    app.add_middleware(relais.Garde, settings=settings)
    app.add_middleware(Identifiant)

    app.include_router(health.router)
    if settings.env is Env.essai:
        app.include_router(preuves.router)
    errors.installe(app)
    return app
