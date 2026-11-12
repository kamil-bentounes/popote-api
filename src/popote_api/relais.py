"""Seul le relais Cloudflare peut appeler l'API hors du poste local (spec § 2).

La garde refuse par défaut : tout scope `http` ou `websocket`, quel que soit le chemin ou la méthode.
"""

import hmac

from fastapi import Request
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from popote_api.config import Settings
from popote_api.errors import reponse

EN_TETE = "x-popote-relais"
EN_TETE_IP = "x-popote-ip"
REFUS_WEBSOCKET = 1008  # code RFC 6455 « violation de politique »
# Préfixes de chemin servis sans relais. Vide à l'étape 0.2 : `/internal/` y entrera à l'étape 0.3,
# protégé par son propre HMAC.
EXEMPTIONS: tuple[str, ...] = ()


def relais_valide(headers: Headers, settings: Settings) -> bool:
    if settings.relay_secret is None:
        return False
    recu = headers.get(EN_TETE, "")
    attendu = settings.relay_secret.get_secret_value()
    if not recu or not attendu:
        return False
    return hmac.compare_digest(recu.encode(), attendu.encode())


def ip_de(request: Request) -> str:
    """L'adresse de la personne : celle que le relais a vue, seulement si le relais est authentique."""
    settings: Settings = request.app.state.settings
    if relais_valide(request.headers, settings) and request.headers.get(EN_TETE_IP):
        return request.headers[EN_TETE_IP]
    return request.client.host if request.client else ""


class Garde:
    """Middleware ASGI pur : il rend `reponse(...)` au lieu de lever une exception."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and self._refuse(scope):
            await self._repond_non(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _refuse(self, scope: Scope) -> bool:
        if not self.settings.relais_exige:
            return False
        if scope["path"].startswith(EXEMPTIONS):
            return False
        return not relais_valide(Headers(scope=scope), self.settings)

    async def _repond_non(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await receive()  # l'événement de connexion, avant de fermer sans accepter
            await send({"type": "websocket.close", "code": REFUS_WEBSOCKET})
            return
        refus = reponse(Request(scope), 404, "introuvable", "Cette adresse n'existe pas.")
        await refus(scope, receive, send)
