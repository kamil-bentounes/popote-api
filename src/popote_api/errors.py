"""Toutes les erreurs de l'API au format Problem Details (RFC 9457).

Règle de levée : une route ou une dépendance FastAPI lève `Probleme` (ou `HTTPException`) ; un
middleware, lui, rend `reponse(...)` directement. Une exception levée dans un middleware échappe
aux handlers ci-dessous et finit en 500. L'authentification et la limite de débit sont donc des
dépendances FastAPI, pas des middlewares.
"""

import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

journal = logging.getLogger(__name__)

TYPE_DE_BASE = "https://notre-popote.fr/problemes/"
MEDIA = "application/problem+json"
TITRE_PAR_DEFAUT = "Erreur"
CODE_PAR_DEFAUT = "erreur"
# statut: (titre, code stable). Un statut absent prend le titre et le code par défaut.
STATUTS: dict[int, tuple[str, str]] = {
    400: ("Requête mal formée", "requete_mal_formee"),
    401: ("Pas de session", "pas_de_session"),
    403: ("Interdit", "interdit"),
    404: ("Introuvable", "introuvable"),
    405: ("Méthode non permise", "methode_non_permise"),
    406: ("Format non acceptable", "non_acceptable"),
    409: ("Conflit", "conflit"),
    410: ("Disparu", "disparu"),
    412: ("Précondition échouée", "precondition_echouee"),
    413: ("Corps trop gros", "corps_trop_gros"),
    415: ("Type de contenu non supporté", "type_non_supporte"),
    422: ("Données invalides", "donnees_invalides"),
    428: ("Précondition requise", "precondition_requise"),
    429: ("Trop de requêtes", "trop_de_requetes"),
    500: ("Erreur interne", "erreur_interne"),
    502: ("Mauvaise passerelle", "mauvaise_passerelle"),
    503: ("Service indisponible", "service_indisponible"),
    504: ("Délai de passerelle dépassé", "delai_de_passerelle_depasse"),
}
# En-têtes que `reponse()` pose elle-même : l'appelant ne peut pas les remplacer.
EN_TETES_RESERVES = {"cache-control", "content-type", "content-length", "x-request-id"}

LONGUEUR_MAX_POINTEUR = 256
MESSAGE_PAR_DEFAUT = "Valeur invalide."
MESSAGE_JSON_INVALIDE = "Le corps n'est pas un JSON valide."
# type d'erreur pydantic -> message ; les champs entre accolades viennent de `ctx`.
MESSAGES_422 = {
    "missing": "Ce champ est obligatoire.",
    "string_too_short": "Trop court : {min_length} caractères au minimum.",
    "string_too_long": "Trop long : {max_length} caractères au maximum.",
    "int_parsing": "Un nombre entier est attendu.",
    "float_parsing": "Un nombre est attendu.",
    "bool_parsing": "Un booléen (vrai ou faux) est attendu.",
    "dict_type": "Un objet JSON est attendu.",
    "model_attributes_type": "Un objet JSON est attendu.",
    "literal_error": "Valeur attendue parmi : {expected}.",
    "enum": "Valeur attendue parmi : {expected}.",
    "greater_than": "Doit être strictement supérieur à {gt}.",
    "greater_than_equal": "Doit être supérieur ou égal à {ge}.",
    "less_than": "Doit être strictement inférieur à {lt}.",
    "less_than_equal": "Doit être inférieur ou égal à {le}.",
    "uuid_parsing": "Un identifiant UUID valide est attendu.",
    "date_parsing": "Une date valide est attendue (AAAA-MM-JJ).",
    "date_from_datetime_parsing": "Une date valide est attendue (AAAA-MM-JJ).",
    "datetime_parsing": "Une date et une heure valides sont attendues (ISO 8601).",
    "datetime_from_date_parsing": "Une date et une heure valides sont attendues (ISO 8601).",
    "extra_forbidden": "Ce champ n'est pas permis.",
    "value_error": "La valeur n'est pas acceptée.",
}


class ParametreEnCause(BaseModel):
    """Le paramètre de requête, d'en-tête ou de chemin que la validation a refusé."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    # `in` est un mot réservé de Python : le champ s'appelle `emplacement`, le JSON dit `in`.
    emplacement: str = Field(alias="in", description="query, header, path ou cookie")


class ErreurDeChamp(BaseModel):
    """Une erreur de validation (`422`) : `pointer` pour le corps, `parameter` pour le reste."""

    pointer: str | None = Field(None, description="JSON Pointer (RFC 6901) vers le champ du corps.")
    parameter: ParametreEnCause | None = None
    message: str


class ProblemDetails(BaseModel):
    """Le corps de toute erreur de l'API (RFC 9457). Sa forme est celle que `reponse()` produit."""

    type: str = Field(description=f"URI stable du problème : `{TYPE_DE_BASE}<code>`.")
    title: str
    status: int
    detail: str
    instance: str = Field(description="Identifiant de la requête, repris dans le journal.")
    code: str = Field(description="Code machine stable, par exemple `base_indisponible`.")
    errors: list[ErreurDeChamp] | None = Field(None, description="Seulement pour `422`.")


def reponses_erreur(*statuts: int) -> dict[int | str, dict[str, Any]]:
    """Les réponses d'erreur d'une route, à passer à `responses=` du décorateur.

    Le contrat les publie en `application/problem+json` (voir `contrat.py`) avec le schéma
    `ProblemDetails`. Un statut inconnu de `STATUTS` est une faute de programmation.
    """
    return {statut: {"model": ProblemDetails, "description": STATUTS[statut][0]} for statut in statuts}


# Marque posée sur l'exception qu'on a déjà journalisée avec son `request_id`.
DEJA_JOURNALISEE = "_popote_deja_journalisee"


class DoubleJournalisation(logging.Filter):
    """Écarte, sur `uvicorn.error`, la seconde trace d'une 500 que `_inattendue` a déjà journalisée.

    Starlette relève l'exception après notre réponse, et uvicorn l'écrit alors une deuxième fois.
    Seul cet enregistrement-là est écarté ; tout le reste de `uvicorn.error` passe.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.getMessage().startswith("Exception in ASGI application"):
            return True
        exc = record.exc_info[1] if record.exc_info else None
        return not getattr(exc, DEJA_JOURNALISEE, False)


FILTRE_UVICORN = DoubleJournalisation()


class Probleme(Exception):
    """Une erreur métier qui doit sortir telle quelle, avec son code stable."""

    def __init__(self, status: int, code: str, detail: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.headers = status, code, detail, headers


def _identifiant(request: Request) -> str:
    """L'identifiant de la requête ; une erreur peut précéder le middleware qui le pose."""
    identifiant: str | None = getattr(request.state, "request_id", None)
    if not identifiant:
        identifiant = uuid4().hex
        request.state.request_id = identifiant
    return identifiant


def reponse(
    request: Request,
    status: int,
    code: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    identifiant = _identifiant(request)
    corps: dict[str, Any] = {
        "type": TYPE_DE_BASE + code,
        "title": STATUTS.get(status, (TITRE_PAR_DEFAUT, CODE_PAR_DEFAUT))[0],
        "status": status,
        "detail": detail,
        "instance": identifiant,
        "code": code,
    }
    if errors:
        corps["errors"] = errors
    en_tetes = {k: v for k, v in (headers or {}).items() if k.lower() not in EN_TETES_RESERVES}
    en_tetes |= {"Cache-Control": "no-store", "X-Request-Id": identifiant}
    return JSONResponse(corps, status_code=status, media_type=MEDIA, headers=en_tetes)


def _pointeur(chemin: tuple[Any, ...]) -> str:
    """Pointeur JSON (RFC 6901) vers un champ du corps ; la racine s'écrit `""`.

    Une clé saisie par le client revient entière dans le pointeur : au-delà de
    `LONGUEUR_MAX_POINTEUR`, on remonte au parent le plus proche qui tient, et le pointeur reste valide.
    """
    segments = ["/" + str(p).replace("~", "~0").replace("/", "~1") for p in chemin]
    while segments and sum(len(s) for s in segments) > LONGUEUR_MAX_POINTEUR:
        segments.pop()
    return "".join(segments)


def _message(erreur: Mapping[str, Any]) -> str:
    modele = MESSAGES_422.get(erreur["type"])
    if modele is None:
        return MESSAGE_PAR_DEFAUT
    contexte = dict(erreur.get("ctx") or {})
    if "expected" in contexte:
        contexte["expected"] = str(contexte["expected"]).replace("' or '", "' ou '")
    return modele.format(**contexte)


def _erreur_de_validation(erreur: Mapping[str, Any]) -> dict[str, Any]:
    emplacement, *chemin = erreur["loc"]
    if emplacement == "body":
        if erreur["type"] == "json_invalid":
            return {"pointer": "", "message": MESSAGE_JSON_INVALIDE}
        return {"pointer": _pointeur(tuple(chemin)), "message": _message(erreur)}
    nom = str(chemin[0]) if chemin else ""
    return {"parameter": {"name": nom, "in": str(emplacement)}, "message": _message(erreur)}


def installe(app: FastAPI) -> None:
    logging.getLogger("uvicorn.error").addFilter(FILTRE_UVICORN)  # sans doublon : même instance

    @app.exception_handler(Probleme)
    async def _probleme(request: Request, exc: Probleme) -> JSONResponse:
        return reponse(request, exc.status, exc.code, exc.detail, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        titre, code = STATUTS.get(exc.status_code, (TITRE_PAR_DEFAUT, CODE_PAR_DEFAUT))
        detail = "Cette adresse n'existe pas." if exc.status_code == 404 else titre
        return reponse(request, exc.status_code, code, detail, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        erreurs = [_erreur_de_validation(e) for e in exc.errors()]
        return reponse(request, 422, "donnees_invalides", "Certaines données ne sont pas valides.", erreurs)

    @app.exception_handler(Exception)
    async def _inattendue(request: Request, exc: Exception) -> JSONResponse:
        journal.exception("Erreur inattendue (request_id=%s)", _identifiant(request), exc_info=exc)
        setattr(exc, DEJA_JOURNALISEE, True)
        return reponse(request, 500, "erreur_interne", "Une erreur inattendue est survenue.")
