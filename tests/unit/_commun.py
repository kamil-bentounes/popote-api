"""Aides communes aux tests unitaires."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI

from popote_api.config import Settings

SECRET = "s" * 32
DSN = "postgresql://x:y@127.0.0.1:1/rien"
RELAIS = {"X-Popote-Relais": SECRET}
# Ce qu'envoie le front dans une écriture : l'origine de l'environnement et l'en-tête propre à l'appli.
ECRITURE_LOCALE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}
ECRITURE_ESSAI = {"Origin": "https://essai.notre-popote.fr", "X-Popote-Client": "web"}


def reglages(env: str, **autres: Any) -> Settings:
    """Des réglages valides pour l'environnement demandé (secret et base fournis hors local)."""
    valeurs: dict[str, Any] = {"env": env}
    if env != "local":
        valeurs |= {"relay_secret": SECRET, "database_url": DSN}
    return Settings.model_validate(valeurs | autres)


@dataclass
class Retour:
    status: int
    en_tetes: dict[str, str]
    corps: bytes


async def appeler(app: FastAPI, methode: str, chemin: str, en_tetes: dict[str, str] | None = None) -> Retour:
    """Appelle l'application en ASGI brut, pour maîtriser le chemin exact (httpx le normalise)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": methode,
        "scheme": "http",
        "path": unquote(chemin),
        "raw_path": chemin.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (en_tetes or {}).items()],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)  # type: ignore[arg-type]
    debut = next(m for m in messages if m["type"] == "http.response.start")
    corps = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return Retour(
        debut["status"],
        {k.decode().lower(): v.decode() for k, v in debut["headers"]},
        corps,
    )


async def appeler_websocket(
    app: FastAPI, chemin: str, en_tetes: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Ouvre un websocket en ASGI brut et rend les messages que l'application a envoyés."""
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": chemin,
        "raw_path": chemin.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (en_tetes or {}).items()],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
        "subprotocols": [],
    }
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)  # type: ignore[arg-type]
    return messages
