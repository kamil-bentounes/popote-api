"""Spec § 3.10, « par défaut, fermé » : toute route exige une session, sauf une liste écrite ici."""

import pytest
from _commun import reglages
from _routes import autres_routes, routes_de_l_api
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant

from popote_api.api import v1
from popote_api.main import create_app
from popote_api.security.session import personne_connectee

# Les routes publiques, chacune avec sa raison. Une route qui s'ajoute ici se justifie en relecture ; celles
# de 0.4 (connexion, invitation, réinitialisation) s'y ajouteront avec leur jeton à usage unique.
LISTE_BLANCHE = {
    "/api/healthz": "le processus répond, sans donnée",
    "/api/readyz": "la base répond, sans donnée ; sert au réveil quotidien du projet",
}
# Servi par FastAPI et non par une `APIRoute` : n'existe pas en prod (`openapi_url=None`).
CONTRAT = "/api/openapi.json"
ENVIRONNEMENTS = ["local", "essai", "prod"]


def dependances(dependant: Dependant) -> set[object]:
    """Tout ce que la route appelle avant son code, de proche en proche."""
    appels: set[object] = set()
    for dependance in dependant.dependencies:
        appels.add(dependance.call)
        appels |= dependances(dependance)
    return appels


def sans_session(app: FastAPI) -> list[str]:
    """Les routes qui ne passent pas par `personne_connectee`, hors liste blanche."""
    return [
        f"{sorted(route.methods or [])[0]} {route.path}"
        for route in routes_de_l_api(app)
        if route.path not in LISTE_BLANCHE and personne_connectee not in dependances(route.dependant)
    ]


@pytest.mark.parametrize("env", ENVIRONNEMENTS)
def test_toute_route_hors_liste_blanche_exige_une_session(env: str) -> None:
    assert sans_session(create_app(reglages(env))) == []


def test_la_liste_blanche_ne_garde_que_des_routes_qui_existent() -> None:
    # Une entrée qui ne correspond plus à rien reste ouverte pour la prochaine route de ce nom.
    chemins = {r.path for env in ENVIRONNEMENTS for r in routes_de_l_api(create_app(reglages(env)))}
    assert set(LISTE_BLANCHE) <= chemins


@pytest.mark.parametrize("env", ENVIRONNEMENTS)
def test_les_routes_servies_hors_apiroute_sont_connues(env: str) -> None:
    # Une `Route` ou un `Mount` échappe aux dépendances : le contrat, et rien d'autre.
    autres = {route.path for route in autres_routes(create_app(reglages(env)))}
    assert autres <= {CONTRAT}


def test_les_routes_de_v1_portent_la_session_par_le_routeur(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pas de dépendance écrite sur la route : c'est le routeur `/api/v1` qui la pose.
    sous_routeur = APIRouter()

    @sous_routeur.get("/essai/oubli")
    async def oubli() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(v1, "SOUS_ROUTEURS", (sous_routeur,))
    app = create_app(reglages("local"))
    routes = {route.path: route for route in routes_de_l_api(app)}
    assert personne_connectee in dependances(routes["/api/v1/essai/oubli"].dependant)
    assert sans_session(app) == []


def test_le_garde_voit_une_route_montee_sans_session() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/essai/ouverte")
    async def ouverte() -> dict[str, bool]:
        return {"ok": True}

    assert sans_session(app) == ["GET /api/essai/ouverte"]


def test_le_garde_voit_une_route_de_v1_montee_en_dehors_du_routeur() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/v1/essai/hors-routeur")
    async def hors_routeur() -> dict[str, bool]:
        return {"ok": True}

    assert sans_session(app) == ["GET /api/v1/essai/hors-routeur"]


def test_le_garde_accepte_la_dependance_posee_sur_la_route() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/essai/protegee", dependencies=[Depends(personne_connectee)])
    async def protegee() -> dict[str, bool]:
        return {"ok": True}

    assert sans_session(app) == []


def test_l_enumeration_voit_les_routes_des_routeurs_inclus(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sans cela le garde passerait à vide si FastAPI changeait la façon dont il garde un routeur inclus.
    sous_routeur = APIRouter()

    @sous_routeur.get("/essai/vue")
    async def vue() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(v1, "SOUS_ROUTEURS", (sous_routeur,))
    chemins = {route.path for route in routes_de_l_api(create_app(reglages("local")))}
    assert {"/api/healthz", "/api/readyz", "/api/v1/essai/vue"} <= chemins
