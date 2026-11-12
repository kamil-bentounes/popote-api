"""La fabrique de l'application. Lancement : `uvicorn --factory popote_api.main:create_app`."""

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from pydantic import SecretStr

from popote_api import contrat, erreurs_base, errors, journal, limites, relais
from popote_api.api import health, internes, v1
from popote_api.config import Env, Settings
from popote_api.identifiant import Identifiant
from popote_api.infra.auth_admin import cree_auth_admin
from popote_api.infra.db import Base, SondeBase
from popote_api.security.debit import Debit, LimiteParAdresse
from popote_api.security.origine import garde_origine
from popote_api.trace import Trace

avertissements = logging.getLogger(__name__)


def _secret(valeur: SecretStr | None) -> str | None:
    return valeur.get_secret_value() if valeur else None


def create_app(settings: Settings | None = None, *, horloge: Callable[[], float] = time.monotonic) -> FastAPI:
    # POPOTE_ENV et les autres réglages viennent de l'environnement du processus.
    settings = settings or Settings()  # type: ignore[call-arg]
    if settings.json_logs:
        journal.configure()
    base = Base.depuis_dsn(
        _secret(settings.database_url),
        _secret(settings.database_url_internal),
        emetteur=settings.emetteur_des_jetons,
    )

    auth_admin = cree_auth_admin(settings)

    @asynccontextmanager
    async def cycle_de_vie(_app: FastAPI) -> AsyncIterator[None]:
        if not base.service_configure:
            avertissements.warning(
                "POPOTE_DATABASE_URL_INTERNAL absente : le contexte service est indisponible (503)."
            )
        if not auth_admin.configure:
            avertissements.warning(
                "POPOTE_SUPABASE_URL ou POPOTE_SUPABASE_SECRET_KEY absente : l'administration d'Auth est "
                "indisponible (503)."
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
        # Fermé par défaut : toute route d'écriture, présente ou future, passe par la garde d'origine.
        dependencies=[Depends(garde_origine)],
    )
    app.state.settings = settings
    app.state.base = base
    app.state.debit = Debit(horloge)
    app.state.horloge_debit = horloge  # la même que le débit : les tests l'avancent à la main
    app.state.derniers_avertissements_internes = {}
    app.state.horloge_unix = time.time  # l'instant de la signature interne ; les tests la remplacent
    app.state.sonde = SondeBase(base.repond if settings.database_url else None)
    app.state.auth_admin = auth_admin

    # Le dernier middleware ajouté est le plus extérieur. De l'extérieur vers l'intérieur : `Identifiant`,
    # `Trace`, `Acces`, `Garde`, `LimiteParAdresse` (un refus de débit ne lit pas le corps), puis les
    # limites de `limites.py` : `SansCache`, `Delai` (qui enveloppe aussi la lecture du corps), `TypeJson`,
    # `TailleMax`. Le refus de la garde porte donc son identifiant et
    # sa trace, et sa ligne d'accès aussi ; un appelant sans le secret du relais est renvoyé avant que son
    # corps soit lu. Le gestionnaire des 500 s'exécute encore au-dessus de tous : il lit les identifiants
    # dans l'état de la requête, pas dans les `ContextVar` (voir `errors._inattendue`).
    app.add_middleware(limites.TailleMax)
    app.add_middleware(limites.TypeJson)
    app.add_middleware(limites.Delai, secondes=limites.DELAI_SECONDES)
    app.add_middleware(limites.SansCache)
    app.add_middleware(LimiteParAdresse)
    app.add_middleware(relais.Garde, settings=settings)
    app.add_middleware(journal.Acces)
    app.add_middleware(Trace)
    app.add_middleware(Identifiant)

    app.include_router(health.router)
    app.include_router(internes.router)
    app.include_router(v1.cree_routeur())
    errors.installe(app)
    erreurs_base.installe(app)
    contrat.installe(app)
    return app
