"""Le contrat OpenAPI : produit par le code, exporté dans `openapi.json`, jamais écrit à la main."""

import json
from typing import Any

from fastapi import FastAPI
from pydantic.json_schema import models_json_schema

from popote_api.config import Settings
from popote_api.errors import MEDIA, ProblemDetails

MODELE_DE_REFERENCE = "#/components/schemas/{model}"
SCHEMA_DES_ERREURS = MODELE_DE_REFERENCE.format(model="ProblemDetails")
SCHEMA_DE_FASTAPI = MODELE_DE_REFERENCE.format(model="HTTPValidationError")
JSON = "application/json"


def _schema_problem_details() -> dict[str, Any]:
    """`ProblemDetails` et ses dépendances, prêts à entrer dans `components.schemas`."""
    _, definitions = models_json_schema([(ProblemDetails, "validation")], ref_template=MODELE_DE_REFERENCE)
    schemas: dict[str, Any] = definitions["$defs"]
    return schemas


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
            _problemes_en_problem_json(generer())
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
