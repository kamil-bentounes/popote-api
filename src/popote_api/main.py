"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

import time
from collections.abc import Callable

from fastapi import Depends, FastAPI

from popote_api import errors, relais
from popote_api.api import health, preuves
from popote_api.config import Env, Settings
from popote_api.identifiant import Identifiant
from popote_api.infra.db import SondeBase
from popote_api.security.debit import Debit, limite_par_ip


def create_app(settings: Settings | None = None, *, horloge: Callable[[], float] = time.monotonic) -> FastAPI:
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
        # Fermé par défaut : toute route est limitée par adresse, avant qu'aucun cookie soit lu.
        dependencies=[Depends(limite_par_ip)],
    )
    app.state.settings = settings
    app.state.debit = Debit(horloge)
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
