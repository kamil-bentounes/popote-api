"""Aides communes aux tests unitaires."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI

from popote_api.config import Settings

SECRET = "s" * 32
DSN = "postgresql://x:y@127.0.0.1:1/rien"
RELAIS = {"X-Popote-Relais": SECRET}


def reglages(env: str, **autres: Any) -> Settings:
    """Des réglages valides pour l'environnement demandé (secret et base fournis hors local)."""
    # Le journal JSON est coupé par défaut : les tests ne touchent pas à la configuration du journal.
    valeurs: dict[str, Any] = {"env": env, "json_logs": False}
    if env != "local":
        valeurs |= {"relay_secret": SECRET, "database_url": DSN}
    return Settings.model_validate(valeurs | autres)


@dataclass
class Retour:
    status: int
    en_tetes: dict[str, str]
    corps: bytes


EnTetes = dict[str, str] | list[tuple[str, str]]


def _en_tetes_asgi(en_tetes: EnTetes | None) -> list[tuple[bytes, bytes]]:
    """Une liste de paires permet de répéter un en-tête, ce qu'un dict ne sait pas dire."""
    paires = en_tetes.items() if isinstance(en_tetes, dict) else (en_tetes or [])
    return [(k.lower().encode(), v.encode()) for k, v in paires]


async def appeler(
    app: FastAPI, methode: str, chemin: str, en_tetes: EnTetes | None = None, requete: str = ""
) -> Retour:
    """Appelle l'application en ASGI brut, pour maîtriser le chemin exact (httpx le normalise)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": methode,
        "scheme": "http",
        "path": unquote(chemin),
        "raw_path": chemin.encode(),
        "query_string": requete.encode(),
        "root_path": "",
        "headers": _en_tetes_asgi(en_tetes),
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
