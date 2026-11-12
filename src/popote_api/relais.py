"""Seul le relais Cloudflare peut appeler l'API hors du poste local (spec § 2).

La garde refuse par défaut : tout scope `http` ou `websocket`, quel que soit le chemin ou la méthode.
"""

import hmac
import logging
from ipaddress import IPv6Address, ip_address

from fastapi import Request
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from popote_api.config import Settings
from popote_api.errors import reponse

journal = logging.getLogger(__name__)

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


def _ip_normalisee(brut: str) -> str:
    """L'adresse en forme canonique ; refuse un identifiant de zone, ramène `::ffff:a.b.c.d` à l'IPv4."""
    adresse = ip_address(brut)
    if isinstance(adresse, IPv6Address):
        if adresse.scope_id:
            raise ValueError("identifiant de zone IPv6")
        if adresse.ipv4_mapped:
            return str(adresse.ipv4_mapped)
    return str(adresse)


def ip_de(request: Request) -> str | None:
    """L'adresse de la personne, telle que le relais l'a vue.

    Hors local, rend `None` plutôt que l'adresse de la connexion (celle du relais) quand
    `X-Popote-IP` manque ou n'est pas une adresse : une limite par IP ne doit jamais compter
    tout le monde sur l'adresse du relais.
    """
    settings: Settings = request.app.state.settings
    if not settings.relais_exige:
        return request.client.host if request.client else None
    if not relais_valide(request.headers, settings):
        return None
    try:
        return _ip_normalisee(request.headers.get(EN_TETE_IP, "").strip())
    except ValueError:
        journal.warning("X-Popote-IP absente ou invalide malgré un relais authentique.")
        return None


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
