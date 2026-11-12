"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

from fastapi import FastAPI

from popote_api import contrat, errors, journal, relais
from popote_api.api import health, preuves
from popote_api.config import Env, Settings
from popote_api.identifiant import Identifiant
from popote_api.infra.db import SondeBase
from popote_api.trace import Trace


def create_app(settings: Settings | None = None) -> FastAPI:
    # POPOTE_ENV et les autres réglages viennent de l'environnement du processus.
    settings = settings or Settings()  # type: ignore[call-arg]
    if settings.json_logs:
        journal.configure()
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

    # Le dernier middleware ajouté est le plus extérieur. De l'extérieur vers l'intérieur : `Identifiant`,
    # `Trace`, `Acces`, `Garde`. Le refus de la garde porte donc son identifiant et sa trace, et sa ligne
    # d'accès aussi. Le gestionnaire des 500 s'exécute encore au-dessus de tous : il lit les identifiants dans
    # l'état de la requête, pas dans les `ContextVar` (voir `errors._inattendue`).
    app.add_middleware(relais.Garde, settings=settings)
    app.add_middleware(journal.Acces)
    app.add_middleware(Trace)
    app.add_middleware(Identifiant)

    app.include_router(health.router)
    if settings.env is Env.essai:
        app.include_router(preuves.router)
    errors.installe(app)
    contrat.installe(app)
    return app
