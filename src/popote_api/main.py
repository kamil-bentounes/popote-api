"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import SecretStr

from popote_api import contrat, errors, relais
from popote_api.api import health, preuves
from popote_api.config import Env, Settings
from popote_api.identifiant import Identifiant
from popote_api.infra.db import Base, SondeBase

journal = logging.getLogger(__name__)


def _secret(valeur: SecretStr | None) -> str | None:
    return valeur.get_secret_value() if valeur else None


def create_app(settings: Settings | None = None) -> FastAPI:
    # POPOTE_ENV et les autres réglages viennent de l'environnement du processus.
    settings = settings or Settings()  # type: ignore[call-arg]
    # Le contrat n'est publié ni en prod, ni sous une forme interactive. Pas de redirection de
    # barre finale : `/api/x/` n'est pas `/api/x`, et une redirection révélerait la route.
    base = Base.depuis_dsn(_secret(settings.database_url), _secret(settings.database_url_internal))
    if not base.service_configure:
        journal.warning("POPOTE_DATABASE_URL_INTERNAL absente : le contexte service est indisponible (503).")

    @asynccontextmanager
    async def cycle_de_vie(_app: FastAPI) -> AsyncIterator[None]:
        try:
            await base.ouvre()  # sans attendre de connexion : le démarrage ne dépend pas de la base
            yield
        finally:
            await base.ferme()

    app = FastAPI(
        lifespan=cycle_de_vie,
        title="Popote",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None if settings.env is Env.prod else "/api/openapi.json",
        redirect_slashes=False,
    )
    app.state.settings = settings
    app.state.base = base
    app.state.sonde = SondeBase(base.repond if settings.database_url else None)

    # Le dernier middleware ajouté est le plus extérieur : `Identifiant` enveloppe `Garde`, si bien que
    # le refus de la garde porte lui aussi son identifiant.
    app.add_middleware(relais.Garde, settings=settings)
    app.add_middleware(Identifiant)

    app.include_router(health.router)
    if settings.env is Env.essai:
        app.include_router(preuves.router)
    errors.installe(app)
    contrat.installe(app)
    return app
