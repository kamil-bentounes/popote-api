"""Spec § 3.10 : les modèles d'entrée refusent les champs inconnus ; les modèles de sortie sont à part."""

import importlib
import inspect
import pkgutil
from typing import Any

import pytest
from _commun import reglages
from _routes import routes_de_l_api
from fastapi import FastAPI
from pydantic import BaseModel, TypeAdapter, ValidationError

import popote_api.schemas
from popote_api.main import create_app
from popote_api.schemas.base import Entree, Sortie


def modeles_de_schemas() -> list[type[BaseModel]]:
    """Tout modèle défini dans un module de `popote_api.schemas` (pas ceux qu'il importe)."""
    trouves: list[type[BaseModel]] = []
    for info in pkgutil.iter_modules(popote_api.schemas.__path__, "popote_api.schemas."):
        module = importlib.import_module(info.name)
        trouves += [
            classe
            for _, classe in inspect.getmembers(module, inspect.isclass)
            if issubclass(classe, BaseModel) and classe.__module__ == module.__name__
        ]
    return trouves


def objets_ouverts(schema: Any) -> list[str]:
    """Les objets du schéma JSON qui acceptent un champ inconnu."""
    ouverts: list[str] = []
    if isinstance(schema, dict):
        if (
            schema.get("type") == "object"
            and "properties" in schema
            and schema.get("additionalProperties") is not False
        ):
            ouverts.append(str(schema.get("title", "?")))
        for valeur in schema.values():
            ouverts += objets_ouverts(valeur)
    elif isinstance(schema, list):
        for valeur in schema:
            ouverts += objets_ouverts(valeur)
    return ouverts


def corps_ouverts(app: FastAPI) -> list[str]:
    """Les routes dont le corps ne descend pas d'`Entree` ou accepte un champ inconnu, à toute profondeur."""
    fautes: list[str] = []
    for route in routes_de_l_api(app):
        champ = route.body_field
        if champ is None:
            continue
        modele = champ.field_info.annotation
        nom = f"{sorted(route.methods or [])[0]} {route.path}"
        if not (inspect.isclass(modele) and issubclass(modele, Entree)):
            fautes.append(f"{nom} : le corps ne descend pas d'Entree")
            continue
        schema = TypeAdapter(modele).json_schema()
        fautes += [f"{nom} : {titre} accepte un champ inconnu" for titre in objets_ouverts(schema)]
    return fautes


def test_tout_modele_de_schemas_descend_d_entree_ou_de_sortie() -> None:
    sans_base = [m.__qualname__ for m in modeles_de_schemas() if not issubclass(m, Entree | Sortie)]
    assert sans_base == []


def test_une_entree_refuse_un_champ_inconnu() -> None:
    class Exemple(Entree):
        nom: str

    with pytest.raises(ValidationError) as erreur:
        Exemple.model_validate({"nom": "x", "household_id": "autre-foyer"})
    assert erreur.value.errors()[0]["type"] == "extra_forbidden"


def test_aucune_route_de_l_application_n_accepte_un_champ_inconnu() -> None:
    assert corps_ouverts(create_app(reglages("local"))) == []


def test_le_garde_voit_un_corps_qui_ne_descend_pas_d_entree() -> None:
    class Ouvert(BaseModel):
        nom: str

    app = FastAPI()

    @app.post("/ouvert")
    async def ouvert(corps: Ouvert) -> None:
        return None

    assert corps_ouverts(app) == ["POST /ouvert : le corps ne descend pas d'Entree"]


def test_le_garde_voit_un_modele_imbrique_qui_accepte_un_champ_inconnu() -> None:
    class Imbrique(BaseModel):
        nom: str

    class Externe(Entree):
        dedans: Imbrique

    app = FastAPI()

    @app.post("/imbrique")
    async def imbrique(corps: Externe) -> None:
        return None

    assert corps_ouverts(app) == ["POST /imbrique : Imbrique accepte un champ inconnu"]


def test_le_garde_laisse_passer_un_corps_ferme() -> None:
    class Interne(Entree):
        nom: str

    class Externe(Entree):
        dedans: Interne
        liste: list[Interne]

    app = FastAPI()

    @app.post("/ferme")
    async def ferme(corps: Externe) -> None:
        return None

    assert corps_ouverts(app) == []
