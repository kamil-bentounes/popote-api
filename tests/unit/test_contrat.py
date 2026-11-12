from pathlib import Path
from typing import Any

import httpx
from _commun import ECRITURE_LOCALE, reglages
from fastapi import FastAPI
from pydantic import BaseModel, Field

from popote_api.contrat import contrat_publie, serialise
from popote_api.errors import MEDIA, ProblemDetails, reponses_erreur
from popote_api.main import create_app
from popote_api.security.debit import NON_LIMITEES

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
    # Ni limitées (pas de 429) ni sous `/api/v1/` (pas de 404) : seulement le délai et le 500.
    assert set(chemins["/api/healthz"]["get"]["responses"]) == {"200", "500", "503"}
    assert set(chemins["/api/readyz"]["get"]["responses"]) == {"200", "500", "503"}


async def test_les_erreurs_reelles_respectent_le_schema_problem_details() -> None:
    """`ProblemDetails` décrit ce que `reponse()` produit : on valide de vraies réponses d'erreur."""
    app = _application_avec_une_route()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        reponses = [
            await c.get("/api/nexiste-pas"),
            await c.post("/api/_test/ressource?page=x", json={"nom": "a"}, headers=ECRITURE_LOCALE),
            await c.post(
                "/api/_test/ressource",
                content=b"{",
                headers=ECRITURE_LOCALE | {"content-type": "application/json"},
            ),
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


def _operations(contrat: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (methode, chemin, operation)
        for chemin, operations in contrat["paths"].items()
        for methode, operation in operations.items()
    ]


def _en_tetes(operation: dict[str, Any], statut: str) -> set[str]:
    return set(operation["responses"][statut].get("headers", {}))


def test_toute_reponse_declare_x_request_id() -> None:
    contrat = _application_avec_une_route().openapi()
    reponses = _reponses_du_contrat(contrat)
    assert len(reponses) > 5
    assert [(o, s) for o, s, r in reponses if "X-Request-Id" not in r.get("headers", {})] == []


def test_toute_operation_limitee_declare_son_429_et_ses_en_tetes() -> None:
    contrat = _application_avec_une_route().openapi()
    limitees = [(m, c, o) for m, c, o in _operations(contrat) if c not in NON_LIMITEES]
    assert len(limitees) >= 2
    for methode, chemin, operation in limitees:
        assert _en_tetes(operation, "429") >= {"Retry-After", "RateLimit", "RateLimit-Policy"}, (
            methode,
            chemin,
        )
    assert all("429" not in contrat["paths"][c]["get"]["responses"] for c in NON_LIMITEES)


def test_toute_operation_declare_le_503_du_delai_avec_retry_after() -> None:
    for methode, chemin, operation in _operations(_application_avec_une_route().openapi()):
        assert "Retry-After" in _en_tetes(operation, "503"), (methode, chemin)


def test_une_ecriture_declare_origine_refusee_corps_trop_gros_et_type_refuse() -> None:
    contrat = _application_avec_une_route().openapi()
    ecriture = contrat["paths"]["/api/_test/ressource"]["post"]["responses"]
    lecture = contrat["paths"]["/api/_test/oubli"]["get"]["responses"]
    assert {"403", "413", "415"} <= set(ecriture)
    assert not {"403", "413", "415"} & set(lecture)


def test_les_adresses_de_v1_declarent_leur_404() -> None:
    chemins = create_app(reglages("local")).openapi()["paths"]
    assert "404" in chemins["/api/v1/me"]["get"]["responses"]
    assert "404" not in chemins["/api/healthz"]["get"]["responses"]


def test_le_304_de_me_declare_etag_et_cache_control_et_les_en_tetes_conditionnels_sont_des_parametres() -> (
    None
):
    me = create_app(reglages("local")).openapi()["paths"]["/api/v1/me"]["get"]
    assert _en_tetes(me, "304") >= {"ETag", "Cache-Control"}
    parametres = {p["name"]: p["in"] for p in me["parameters"]}
    assert parametres["If-None-Match"] == "header"
    assert parametres["If-Match"] == "header"


def test_les_erreurs_communes_ne_remplacent_pas_la_declaration_d_une_route() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/propre", responses={429: {"description": "Le refus de cette route"}})
    async def propre() -> dict[str, int]:
        return {}

    reponse = app.openapi()["paths"]["/api/_test/propre"]["get"]["responses"]["429"]
    assert reponse["description"] == "Le refus de cette route"
    assert {"Retry-After", "RateLimit", "RateLimit-Policy"} <= set(reponse["headers"])
