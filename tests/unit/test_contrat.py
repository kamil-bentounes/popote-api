from pathlib import Path
from typing import Any

import httpx
from _commun import reglages
from fastapi import FastAPI
from pydantic import BaseModel, Field

from popote_api.contrat import contrat_publie, serialise
from popote_api.errors import MEDIA, ProblemDetails, reponses_erreur
from popote_api.main import create_app

OPENAPI_JSON = Path(__file__).resolve().parents[2] / "openapi.json"


class Entree(BaseModel):
    nom: str = Field(min_length=3)


def _application_avec_une_route() -> FastAPI:
    app = create_app(reglages("local"))

    @app.post("/api/_test/ressource", responses=reponses_erreur(404, 422))
    async def cree(entree: Entree, page: int = 1) -> dict[str, str]:
        return {"nom": entree.nom}

    @app.get("/api/_test/oubli")  # ne déclare pas son 422 : FastAPI y mettrait son propre schéma
    async def oubli(page: int = 1) -> dict[str, int]:
        return {"page": page}

    return app


def test_openapi_json_est_celui_que_le_code_produit() -> None:
    """Un contrat oublié échoue ici comme dans la CI : `uv run python scripts/exporte_contrat.py`."""
    assert OPENAPI_JSON.read_text(encoding="utf-8") == contrat_publie()


def test_le_contrat_serialise_trie_ses_cles_et_finit_par_une_fin_de_ligne() -> None:
    texte = serialise({"b": 1, "a": {"d": "é", "c": 2}})
    assert texte == '{\n  "a": {\n    "c": 2,\n    "d": "é"\n  },\n  "b": 1\n}\n'


def test_le_contrat_de_l_essai_est_celui_de_local() -> None:
    """Le contrat ne dépend pas de l'environnement qui le produit."""
    assert serialise(create_app(reglages("essai")).openapi()) == OPENAPI_JSON.read_text(encoding="utf-8")


def _reponses_du_contrat(contrat: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (f"{methode.upper()} {chemin}", statut, reponse)
        for chemin, operations in contrat["paths"].items()
        for methode, operation in operations.items()
        for statut, reponse in operation["responses"].items()
    ]


def test_toute_erreur_documentee_est_un_probleme_json() -> None:
    contrat = _application_avec_une_route().openapi()
    erreurs = [(o, s, r) for o, s, r in _reponses_du_contrat(contrat) if int(s) >= 400]
    assert len(erreurs) > 3  # la garde ne passe pas à vide
    for operation, statut, reponse in erreurs:
        assert list(reponse["content"]) == [MEDIA], f"{operation} {statut}"
        assert reponse["content"][MEDIA]["schema"] == {"$ref": "#/components/schemas/ProblemDetails"}


def test_le_422_de_fastapi_est_remplace_par_problem_details_partout() -> None:
    contrat = _application_avec_une_route().openapi()
    assert not {"HTTPValidationError", "ValidationError"} & set(contrat["components"]["schemas"])
    oubli = contrat["paths"]["/api/_test/oubli"]["get"]["responses"]["422"]
    assert oubli["content"] == {MEDIA: {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}}


def test_chaque_operation_a_un_identifiant_et_un_resume() -> None:
    contrat = create_app(reglages("local")).openapi()
    for operations in contrat["paths"].values():
        for operation in operations.values():
            assert operation["operationId"]
            assert operation["summary"]


def test_healthz_et_readyz_declarent_leurs_erreurs() -> None:
    chemins = create_app(reglages("local")).openapi()["paths"]
    assert set(chemins["/api/healthz"]["get"]["responses"]) == {"200", "500"}
    assert set(chemins["/api/readyz"]["get"]["responses"]) == {"200", "500", "503"}


async def test_les_erreurs_reelles_respectent_le_schema_problem_details() -> None:
    """`ProblemDetails` décrit ce que `reponse()` produit : on valide de vraies réponses d'erreur."""
    app = _application_avec_une_route()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        reponses = [
            await c.get("/api/nexiste-pas"),
            await c.post("/api/_test/ressource?page=x", json={"nom": "a"}),
            await c.post("/api/_test/ressource", content=b"{", headers={"content-type": "application/json"}),
        ]
    assert [r.status_code for r in reponses] == [404, 422, 422]
    for r in reponses:
        assert r.headers["content-type"].startswith(MEDIA)
        ProblemDetails.model_validate(r.json())
    champs = ProblemDetails.model_validate(reponses[1].json()).errors or []
    assert {(e.pointer, e.parameter.name if e.parameter else None) for e in champs} == {
        ("/nom", None),
        (None, "page"),
    }
    assert any(e.parameter and e.parameter.emplacement == "query" for e in champs)
    assert {"name": "page", "in": "query"} in [e.get("parameter") for e in reponses[1].json()["errors"]]
