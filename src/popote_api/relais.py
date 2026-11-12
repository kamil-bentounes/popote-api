"""Seul le relais Cloudflare peut appeler /api hors du poste local (spec § 2)."""

import hmac
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from popote_api.config import Settings
from popote_api.errors import reponse

EN_TETE = "x-popote-relais"
EN_TETE_IP = "x-popote-ip"


def relais_valide(request: Request, settings: Settings) -> bool:
    if settings.relay_secret is None:
        return False
    recu = request.headers.get(EN_TETE, "")
    return hmac.compare_digest(recu.encode(), settings.relay_secret.get_secret_value().encode())


def ip_de(request: Request) -> str:
    """L'adresse de la personne : celle que le relais a vue, seulement si le relais est authentique."""
    settings: Settings = request.app.state.settings
    if relais_valide(request, settings) and request.headers.get(EN_TETE_IP):
        return request.headers[EN_TETE_IP]
    return request.client.host if request.client else ""


async def garde(request: Request, suite: Callable[[Request], Awaitable[Response]]) -> Response:
    settings: Settings = request.app.state.settings
    protege = settings.relais_exige and request.url.path.startswith("/api/")
    if protege and not relais_valide(request, settings):
        return reponse(request, 404, "introuvable", "Cette adresse n'existe pas.")
    return await suite(request)
