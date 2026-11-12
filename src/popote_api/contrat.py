"""Le contrat OpenAPI : produit par le code, exporté dans `openapi.json`, jamais écrit à la main."""

import json
from typing import Any

from fastapi import FastAPI

from popote_api.config import Settings
from popote_api.errors import MEDIA

SCHEMA_DES_ERREURS = "#/components/schemas/ProblemDetails"
JSON = "application/json"


def _problemes_en_problem_json(contrat: dict[str, Any]) -> None:
    """FastAPI rattache un modèle de réponse au type de contenu de la route (`application/json`).

    Une réponse qui décrit `ProblemDetails` est en réalité servie en `application/problem+json` :
    on déplace son contenu, sinon la conformité du type de contenu serait fausse pour tous les clients.
    """
    for chemin in contrat.get("paths", {}).values():
        for operation in chemin.values():
            for reponse in operation.get("responses", {}).values():
                contenu = reponse.get("content", {})
                if contenu.get(JSON, {}).get("schema", {}).get("$ref") == SCHEMA_DES_ERREURS:
                    contenu[MEDIA] = contenu.pop(JSON)


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
