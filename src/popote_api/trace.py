"""Le contexte de trace W3C (`traceparent`), posé par un middleware ASGI pur.

Référence : W3C Trace Context, niveau 1 (Recommandation du 23/11/2021), § 3.2. Le format est celui
d'OpenTelemetry, mais sans son SDK à cette étape : aucun récepteur n'est choisi et le SDK pèse sur le
démarrage à froid. `tracestate` n'est pas interprété.
"""

import re
import secrets
from contextvars import ContextVar

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

trace_id_courant: ContextVar[str | None] = ContextVar("trace_id", default=None)
span_id_courant: ContextVar[str | None] = ContextVar("span_id", default=None)

# Aucun en-tête légitime n'approche cette taille : la spécification n'interdit que les en-têtes
# « prohibitivement » gros, et on ne lit pas plus que cela.
LONGUEUR_MAX = 512
# version, trace-id, parent-id, drapeaux, puis ce qu'une version future ajoute. Les chiffres
# hexadécimaux sont en minuscules seulement (ABNF `HEXDIGLC`) : une majuscule est une forme invalide.
_FORME = re.compile(r"([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}(-.*)?")
_TRACE_ID_NUL = "0" * 32
_PARENT_ID_NUL = "0" * 16


def trace_id_repris(valeur: str) -> str | None:
    """Le `trace-id` d'un `traceparent` valide, ou `None` : l'en-tête est alors ignoré."""
    if len(valeur) > LONGUEUR_MAX:
        return None
    forme = _FORME.fullmatch(valeur)
    if forme is None:
        return None
    version, trace_id, parent_id, suite = forme.groups()
    if version == "ff" or trace_id == _TRACE_ID_NUL or parent_id == _PARENT_ID_NUL:
        return None
    if version == "00" and suite is not None:
        return None  # la version 00 a exactement 55 caractères ; seules les suivantes s'allongent
    return trace_id


def identifiant_non_nul(octets: int) -> str:
    """Des octets aléatoires, en hexadécimal minuscule, jamais tous à zéro."""
    return f"{1 + secrets.randbelow(16 ** (2 * octets) - 1):0{2 * octets}x}"


def _trace_id_de(scope: Scope) -> str:
    lignes = Headers(scope=scope).getlist("traceparent")
    # Deux lignes `traceparent` se contredisent : la spécification ne dit rien, on repart d'une trace neuve.
    repris = trace_id_repris(lignes[0]) if len(lignes) == 1 else None
    return repris or identifiant_non_nul(16)


class Trace:
    """Pose `trace_id` et `span_id` dans l'état de la requête et dans des `ContextVar` (pour le journal).

    Le `span-id` est celui de cette requête, jamais celui de l'appelant.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        trace_id, span_id = _trace_id_de(scope), identifiant_non_nul(8)
        etat = scope.setdefault("state", {})
        etat["trace_id"], etat["span_id"] = trace_id, span_id
        jetons = (trace_id_courant.set(trace_id), span_id_courant.set(span_id))
        try:
            await self.app(scope, receive, send)
        finally:
            trace_id_courant.reset(jetons[0])
            span_id_courant.reset(jetons[1])
