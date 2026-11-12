"""L'identifiant de chaque requête, posé par un middleware ASGI pur."""

from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Lu par le journal, qui ne reçoit pas la requête.
request_id_courant: ContextVar[str | None] = ContextVar("request_id", default=None)


class Identifiant:
    """Pose `request_id` dans l'état de la requête et `X-Request-Id` sur chaque réponse.

    L'identifiant est toujours généré ici : un identifiant envoyé par le client n'est pas repris.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        identifiant = uuid4().hex
        scope.setdefault("state", {})["request_id"] = identifiant

        async def envoie_avec_identifiant(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-Id"] = identifiant
            await send(message)

        jeton = request_id_courant.set(identifiant)
        try:
            await self.app(scope, receive, envoie_avec_identifiant)
        finally:
            request_id_courant.reset(jeton)
