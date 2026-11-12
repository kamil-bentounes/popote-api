"""Le contrat OpenAPI : produit par le code, exporté dans `openapi.json`, jamais écrit à la main."""

import json
from typing import Any

from fastapi import FastAPI
from pydantic.json_schema import models_json_schema

from popote_api.config import Settings
from popote_api.errors import MEDIA, PREFIXE_V1, STATUTS, ProblemDetails
from popote_api.limites import METHODES_AVEC_CORPS
from popote_api.security import METHODES_SURES
from popote_api.security.debit import NON_LIMITEES

MODELE_DE_REFERENCE = "#/components/schemas/{model}"
SCHEMA_DES_ERREURS = MODELE_DE_REFERENCE.format(model="ProblemDetails")
SCHEMA_DE_FASTAPI = MODELE_DE_REFERENCE.format(model="HTTPValidationError")
JSON = "application/json"


def _en_tete(description: str) -> dict[str, Any]:
    return {"description": description, "schema": {"type": "string"}}


EN_TETE_RETRY_AFTER = _en_tete("Secondes à attendre avant de réessayer (entier, RFC 9110 § 10.2.3).")
# Posé sur chaque réponse par le middleware `Identifiant`, succès comme erreurs.
EN_TETE_X_REQUEST_ID = _en_tete(
    "Identifiant de la requête, repris dans le journal et dans `instance` d'une erreur."
)
EN_TETES_DU_LIMITEUR = {
    "Retry-After": EN_TETE_RETRY_AFTER,
    "RateLimit": _en_tete("Ce qui reste de la fenêtre (IETF draft-ietf-httpapi-ratelimit-headers)."),
    "RateLimit-Policy": _en_tete("Le quota et la fenêtre de la politique (même brouillon IETF)."),
}


def _schema_problem_details() -> dict[str, Any]:
    """`ProblemDetails` et ses dépendances, prêts à entrer dans `components.schemas`."""
    _, definitions = models_json_schema([(ProblemDetails, "validation")], ref_template=MODELE_DE_REFERENCE)
    schemas: dict[str, Any] = definitions["$defs"]
    return schemas


def _probleme(statut: int, en_tetes: dict[str, Any] | None = None) -> dict[str, Any]:
    reponse: dict[str, Any] = {
        "description": STATUTS[statut][0],
        "content": {MEDIA: {"schema": {"$ref": SCHEMA_DES_ERREURS}}},
    }
    if en_tetes:
        reponse["headers"] = en_tetes
    return reponse


def _erreurs_communes(chemin: str, methode: str) -> dict[str, dict[str, Any]]:
    """Les refus que les middlewares et la garde d'origine rendent à toute route, quoi qu'elle déclare."""
    communes = {
        "503": _probleme(503, {"Retry-After": EN_TETE_RETRY_AFTER})
    }  # le délai, ou un limiteur saturé
    if chemin.startswith(PREFIXE_V1):
        communes["404"] = _probleme(404)
    if chemin not in NON_LIMITEES:
        communes["429"] = _probleme(429, EN_TETES_DU_LIMITEUR)
    if methode.upper() not in METHODES_SURES:
        communes["403"] = _probleme(403)  # la garde d'origine, sur toute écriture
    if methode.upper() in METHODES_AVEC_CORPS:
        communes["413"] = _probleme(413)
        communes["415"] = _probleme(415)
    return communes


def _declare_les_erreurs_communes(contrat: dict[str, Any]) -> None:
    """Déclare une fois, pour toute l'application, ce qui n'appartient à aucune route en particulier.

    Une route qui déclare déjà un de ces statuts le garde (sa description est la sienne) ; les en-têtes
    communs s'ajoutent à ceux qu'elle déclare, sans les remplacer. Les en-têtes d'un `304` se déclarent sur
    la route (`conditionnel.REPONSE_304`) : toutes ne sont pas conditionnelles.
    """
    for chemin, operations in contrat.get("paths", {}).items():
        for methode, operation in operations.items():
            reponses = operation["responses"]
            for statut, commune in _erreurs_communes(chemin, methode).items():
                reponses.setdefault(statut, commune)
                if "headers" in commune:
                    reponses[statut]["headers"] = {
                        **commune["headers"],
                        **reponses[statut].get("headers", {}),
                    }
            for reponse in reponses.values():
                reponse.setdefault("headers", {}).setdefault("X-Request-Id", EN_TETE_X_REQUEST_ID)


def _problemes_en_problem_json(contrat: dict[str, Any]) -> None:
    """Toute erreur du contrat est un `ProblemDetails` servi en `application/problem+json`.

    FastAPI rattache un modèle de réponse au type de contenu de la route (`application/json`) et décrit
    le `422` d'une route qui ne le déclare pas par son propre `HTTPValidationError` : aucun des deux
    n'est ce que `errors.py` rend, et la conformité du type de contenu serait fausse pour les clients.
    """
    schemas = contrat.setdefault("components", {}).setdefault("schemas", {})
    for chemin in contrat.get("paths", {}).values():
        for operation in chemin.values():
            for reponse in operation.get("responses", {}).values():
                contenu = reponse.get("content", {})
                schema = contenu.get(JSON, {}).get("schema", {})
                if schema.get("$ref") in (SCHEMA_DES_ERREURS, SCHEMA_DE_FASTAPI):
                    contenu[MEDIA] = {"schema": {"$ref": SCHEMA_DES_ERREURS}}
                    del contenu[JSON]
    if any(SCHEMA_DES_ERREURS in json.dumps(c) for c in contrat["paths"].values()):
        schemas.update(_schema_problem_details())
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)


def installe(app: FastAPI) -> None:
    """Remplace la génération du contrat de `app` par la nôtre (mise en cache comme celle de FastAPI)."""
    generer = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            contrat = generer()
            _declare_les_erreurs_communes(contrat)
            _problemes_en_problem_json(contrat)
        assert app.openapi_schema is not None  # noqa: S101 - posé par `generer()`
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def serialise(contrat: dict[str, Any]) -> str:
    """Un texte stable : clés triées, indentation fixe, fin de ligne finale."""
    return json.dumps(contrat, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def contrat_publie() -> str:
    """Le contrat de l'application construite en `local`, sans base : c'est le contenu d'`openapi.json`."""
    from popote_api.main import create_app  # import tardif : `main` importe ce module

    return serialise(create_app(Settings.model_validate({"env": "local"})).openapi())
