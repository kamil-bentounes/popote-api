"""Toutes les erreurs de l'API au format Problem Details (RFC 9457)."""

from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

TYPE_DE_BASE = "https://notre-popote.fr/problemes/"
MEDIA = "application/problem+json"
TITRES = {
    400: "Requête mal formée",
    401: "Pas de session",
    403: "Interdit",
    404: "Introuvable",
    405: "Méthode non permise",
    409: "Conflit",
    422: "Données invalides",
    429: "Trop de requêtes",
    500: "Erreur interne",
    503: "Service indisponible",
}
CODES = {404: "introuvable", 405: "methode_non_permise", 422: "donnees_invalides", 500: "erreur_interne"}


class Probleme(Exception):
    """Une erreur métier qui doit sortir telle quelle, avec son code stable."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def reponse(
    request: Request,
    status: int,
    code: str,
    detail: str,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    # Une erreur peut survenir avant le middleware qui pose l'identifiant : on en fabrique un.
    identifiant: str = getattr(request.state, "request_id", None) or uuid4().hex
    corps: dict[str, Any] = {
        "type": TYPE_DE_BASE + code,
        "title": TITRES.get(status, HTTPStatus(status).phrase),
        "status": status,
        "detail": detail,
        "instance": identifiant,
        "code": code,
    }
    if errors:
        corps["errors"] = errors
    return JSONResponse(
        corps,
        status_code=status,
        media_type=MEDIA,
        headers={"Cache-Control": "no-store", "X-Request-Id": identifiant},
    )


def installe(app: FastAPI) -> None:
    @app.exception_handler(Probleme)
    async def _probleme(request: Request, exc: Probleme) -> JSONResponse:
        return reponse(request, exc.status, exc.code, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = CODES.get(exc.status_code, "erreur")
        detail = (
            "Cette adresse n'existe pas." if exc.status_code == 404 else TITRES.get(exc.status_code, "Erreur")
        )
        return reponse(request, exc.status_code, code, detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        erreurs = [
            {"pointer": "/" + "/".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return reponse(request, 422, "donnees_invalides", "Certaines données ne sont pas valides.", erreurs)

    @app.exception_handler(Exception)
    async def _inattendue(request: Request, exc: Exception) -> JSONResponse:
        return reponse(request, 500, "erreur_interne", "Une erreur inattendue est survenue.")
