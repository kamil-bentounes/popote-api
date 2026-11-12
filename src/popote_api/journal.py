"""Le journal : une ligne = un objet JSON sur la sortie standard, et le journal d'accès.

Aucune donnée personnelle (spec § 3.11, plan 0.3) : les champs `extra` sont une liste fermée, l'accès ne
porte que le gabarit de la route (jamais le chemin brut, la chaîne de requête, l'adresse IP ni l'agent
utilisateur), et aucune exception n'est écrite par son message, qui peut recopier des valeurs.
"""

import json
import logging
import sys
import time
import traceback
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

import psycopg
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from popote_api.identifiant import request_id_courant
from popote_api.trace import span_id_courant, trace_id_courant

journal_acces = logging.getLogger("popote_api.acces")

# Les seuls champs `extra` qui sortent : tout autre est écarté, pour qu'une valeur ne passe pas par mégarde.
CHAMPS_AUTORISES = ("method", "route", "status", "duration_ms")
SANS_ROUTE = "(aucune)"
_MARQUE = "_popote_journal"


# Les identifiants de corrélation que chaque ligne porte, et la `ContextVar` d'où ils viennent.
CONTEXTE: dict[str, ContextVar[str | None]] = {
    "request_id": request_id_courant,
    "trace_id": trace_id_courant,
    "span_id": span_id_courant,
}


def _entree(exc: BaseException) -> dict[str, Any]:
    """Une exception de la chaîne : son type et sa pile, jamais son message.

    `str(exc)` peut recopier une valeur (le `DETAIL` d'une erreur de la base, la valeur qu'une validation
    refuse, l'URL d'un appel), quel que soit le type : aucune exception n'est donc écrite par son message.
    La pile ne dit que fichier, ligne et fonction, pas le texte de la ligne.
    """
    entree: dict[str, Any] = {
        "type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "stack": [f"{f.filename}:{f.lineno} {f.name}" for f in traceback.extract_tb(exc.__traceback__)],
    }
    if isinstance(exc, psycopg.Error):
        # De quoi retrouver la cause d'une erreur de la base, sans le message du serveur.
        diagnostic = exc.diag
        for nom, valeur in (
            ("sqlstate", exc.sqlstate),
            ("constraint_name", diagnostic.constraint_name),
            ("table_name", diagnostic.table_name),
        ):
            if valeur:
                entree[nom] = valeur
    return entree


def _chaine(exc: BaseException) -> list[dict[str, Any]]:
    """L'exception puis ses causes, de la plus extérieure à la racine."""
    entrees: list[dict[str, Any]] = []
    vues: set[int] = set()
    courante: BaseException | None = exc
    while courante is not None and id(courante) not in vues:
        vues.add(id(courante))
        entrees.append(_entree(courante))
        courante = courante.__cause__ or (None if courante.__suppress_context__ else courante.__context__)
    return entrees


class Formateur(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        heure = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        corps: dict[str, Any] = {
            "ts": heure.replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Ce que l'appelant a posé en `extra` l'emporte : un gestionnaire d'erreur qui s'exécute hors des
        # middlewares n'a plus les `ContextVar`.
        for nom, variable in CONTEXTE.items():
            corps[nom] = getattr(record, nom, None) or variable.get()
        corps |= {nom: getattr(record, nom) for nom in CHAMPS_AUTORISES if hasattr(record, nom)}
        if record.exc_info and record.exc_info[1] is not None:
            corps["exception"] = _chaine(record.exc_info[1])
        return json.dumps({k: v for k, v in corps.items() if v is not None}, ensure_ascii=False)


def configure(flux: TextIO | None = None) -> None:
    """Remplace la configuration d'uvicorn et la racine par le journal JSON. Idempotente.

    Uvicorn configure ses journaux avant d'appeler la fabrique, avec son format texte : on lui retire ses
    gestionnaires, et ses lignes passent par la racine. Son journal d'accès, qui écrit le chemin brut et
    l'adresse IP, est éteint (`--no-access-log` aussi, au lancement). Seuls nos propres gestionnaires
    sont retirés de la racine : ceux d'un autre outil restent.
    """
    gestionnaire = logging.StreamHandler(flux or sys.stdout)
    gestionnaire.setFormatter(Formateur())
    setattr(gestionnaire, _MARQUE, True)
    racine = logging.getLogger()
    for ancien in [h for h in racine.handlers if getattr(h, _MARQUE, False)]:
        racine.removeHandler(ancien)
    racine.addHandler(gestionnaire)
    racine.setLevel(logging.INFO)
    for nom in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(nom)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)
    logging.getLogger("uvicorn.access").disabled = True


class Acces:
    """Middleware ASGI pur : une ligne par réponse, avec le gabarit de la route et jamais le chemin."""

    def __init__(self, app: ASGIApp, horloge: Callable[[], float] = time.perf_counter) -> None:
        self.app = app
        self.horloge = horloge

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        debut = self.horloge()
        statut: int | None = None

        async def envoie_et_retient_le_statut(message: Message) -> None:
            nonlocal statut
            if message["type"] == "http.response.start":
                statut = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, envoie_et_retient_le_statut)
        except Exception:
            # La réponse 500 est rendue plus haut, par le gestionnaire d'erreur : on l'annonce ici.
            if statut is None:
                statut = 500
            raise
        finally:
            if statut is not None:
                gabarit = getattr(scope.get("route"), "path_format", None)
                journal_acces.info(
                    "Requête traitée",
                    extra={
                        "method": scope["method"],
                        "route": gabarit or SANS_ROUTE,
                        "status": statut,
                        "duration_ms": round((self.horloge() - debut) * 1000, 1),
                    },
                )
