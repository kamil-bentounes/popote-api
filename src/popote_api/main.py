"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import SecretStr

from popote_api import contrat, erreurs_base, errors, journal, relais
from popote_api.api import health, internes, preuves
from popote_api.config import Env, Settings
from popote_api.identifiant import Identifiant
from popote_api.infra.db import Base, SondeBase
from popote_api.trace import Trace

avertissements = logging.getLogger(__name__)


def _secret(valeur: SecretStr | None) -> str | None:
    return valeur.get_secret_value() if valeur else None


def create_app(settings: Settings | None = None) -> FastAPI:
    # POPOTE_ENV et les autres réglages viennent de l'environnement du processus.
    settings = settings or Settings()  # type: ignore[call-arg]
    if settings.json_logs:
        journal.configure()
    base = Base.depuis_dsn(
        _secret(settings.database_url),
        _secret(settings.database_url_internal),
        emetteur=settings.emetteur_des_jetons,
    )

    @asynccontextmanager
    async def cycle_de_vie(_app: FastAPI) -> AsyncIterator[None]:
        if not base.service_configure:
            avertissements.warning(
                "POPOTE_DATABASE_URL_INTERNAL absente : le contexte service est indisponible (503)."
            )
        if not settings.secrets_internes:
            avertissements.warning(
                "POPOTE_INTERNAL_SECRET absente : toute route /internal/* répond 404 (fermée par défaut)."
            )
        try:
            await base.ouvre()  # sans attendre de connexion : le démarrage ne dépend pas de la base
            yield
        finally:
            await base.ferme()

    # Le contrat n'est publié ni en prod, ni sous une forme interactive. Pas de redirection de
    # barre finale : `/api/x/` n'est pas `/api/x`, et une redirection révélerait la route.
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
    app.state.horloge = time.time  # les tests la remplacent pour figer l'instant de la signature
    app.state.sonde = SondeBase(base.repond if settings.database_url else None)

    # Le dernier middleware ajouté est le plus extérieur. De l'extérieur vers l'intérieur : `Identifiant`,
    # `Trace`, `Acces`, `Garde`, `CorpsBorne`. Le refus de la garde porte donc son identifiant et sa trace,
    # et sa ligne d'accès aussi. Le gestionnaire des 500 s'exécute encore au-dessus de tous : il lit les
    # identifiants dans l'état de la requête, pas dans les `ContextVar` (voir `errors._inattendue`).
    app.add_middleware(internes.CorpsBorne)
    app.add_middleware(relais.Garde, settings=settings)
    app.add_middleware(journal.Acces)
    app.add_middleware(Trace)
    app.add_middleware(Identifiant)

    app.include_router(health.router)
    app.include_router(internes.router)
    if settings.env is Env.essai:
        app.include_router(preuves.router)
    errors.installe(app)
    erreurs_base.installe(app)
    contrat.installe(app)
    return app
