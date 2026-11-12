"""La matrice d'autorisation (spec § 7.1 API1, § 8.2) : chaque route de `/api/v1`, avec trois acteurs.

Les acteurs : une personne de MON foyer, une personne d'UN AUTRE foyer, et PERSONNE (sans session). La liste
des routes vient de l'énumération de l'application, pas d'une liste écrite à la main : une route nouvelle
sans cas ici fait échouer son test, et c'est la matrice qu'on complète, pas le test qu'on contourne.

Un cas dit, pour sa route, quel chemin vise la ressource de mon foyer et ce que chaque acteur doit en tirer :
- chez moi : la ressource ;
- chez un autre foyer : `404` pour une ressource désignée par son identifiant (on ne révèle pas qu'elle
  existe), ou pour une route « de soi » (`/me`) la propre ressource de l'autre et rien de la mienne ;
- sans session : `401`, partout.
"""

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest
from _client import application_de_test, client_de, cookie
from _commun import reglages
from _fabrique import Fabrique, Personne
from _routes import routes_de_l_api
from fastapi import APIRouter, FastAPI

from popote_api.api import v1
from popote_api.infra.db import Base
from popote_api.main import create_app
from popote_api.security.session import DEFI_D_AUTHENTIFICATION


@dataclass(frozen=True)
class Monde:
    """Deux foyers, une personne dans chacun."""

    moi: Personne
    autre: Personne


@dataclass(frozen=True)
class Cas:
    chemin: Callable[[Monde], str]
    chez_moi: Callable[[Monde, httpx.Response], None]
    chez_un_autre_foyer: Callable[[Monde, httpx.Response], None]


def _me_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 200
    assert reponse.json()["id"] == str(monde.moi.id)
    assert reponse.json()["household"]["id"] == str(monde.moi.foyer_id)


def _me_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # `/me` est « de soi » : l'autre foyer lit sa propre fiche, jamais la mienne.
    assert reponse.status_code == 200
    assert reponse.json()["id"] == str(monde.autre.id)
    assert reponse.json()["household"]["id"] == str(monde.autre.foyer_id)
    assert str(monde.moi.id) not in reponse.text
    assert str(monde.moi.foyer_id) not in reponse.text


MATRICE: dict[tuple[str, str], Cas] = {
    ("GET", "/api/v1/me"): Cas(lambda _: "/api/v1/me", _me_chez_moi, _me_chez_un_autre_foyer),
}


def routes_de_v1(app: FastAPI) -> list[tuple[str, str]]:
    """Chaque couple (méthode, chemin) de `/api/v1`, énuméré sur l'application elle-même."""
    return sorted(
        (methode, route.path)
        for route in routes_de_l_api(app)
        if route.path.startswith("/api/v1/")
        for methode in sorted(route.methods or [])
        if methode not in {"HEAD", "OPTIONS"}
    )


ROUTES = routes_de_v1(create_app(reglages("local")))


def test_l_enumeration_trouve_des_routes() -> None:
    assert ("GET", "/api/v1/me") in ROUTES


def test_la_matrice_ne_garde_que_des_routes_qui_existent() -> None:
    assert set(MATRICE) <= set(ROUTES)


def test_une_route_sans_cas_est_vue_par_l_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    orpheline = APIRouter()

    @orpheline.get("/essai/orpheline")
    async def sans_cas() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(v1, "SOUS_ROUTEURS", (orpheline,))
    vues = routes_de_v1(create_app(reglages("local")))
    assert ("GET", "/api/v1/essai/orpheline") in vues
    assert ("GET", "/api/v1/essai/orpheline") not in MATRICE


@pytest.fixture
def monde(fabrique: Fabrique) -> Monde:
    return Monde(moi=fabrique.personne(fabrique.foyer()), autre=fabrique.personne(fabrique.foyer()))


def _cas(methode: str, chemin: str) -> Cas:
    cas = MATRICE.get((methode, chemin))
    assert cas is not None, f"{methode} {chemin} n'a pas de cas dans la matrice d'autorisation"
    return cas


@pytest.fixture
def client(base: Base, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    return client_de(application_de_test(base, monkeypatch))


pytestmark = pytest.mark.integration


@pytest.mark.parametrize(("methode", "chemin"), ROUTES, ids=[f"{m} {c}" for m, c in ROUTES])
class TestMatriceParRoute:
    async def test_mon_foyer(
        self, client: httpx.AsyncClient, fabrique: Fabrique, monde: Monde, methode: str, chemin: str
    ) -> None:
        cas = _cas(methode, chemin)
        reponse = await client.request(
            methode, cas.chemin(monde), headers=cookie(fabrique.session(monde.moi.id))
        )
        cas.chez_moi(monde, reponse)

    async def test_un_autre_foyer(
        self, client: httpx.AsyncClient, fabrique: Fabrique, monde: Monde, methode: str, chemin: str
    ) -> None:
        cas = _cas(methode, chemin)
        reponse = await client.request(
            methode, cas.chemin(monde), headers=cookie(fabrique.session(monde.autre.id))
        )
        cas.chez_un_autre_foyer(monde, reponse)

    async def test_sans_session(
        self, client: httpx.AsyncClient, monde: Monde, methode: str, chemin: str
    ) -> None:
        reponse = await client.request(methode, _cas(methode, chemin).chemin(monde))
        assert reponse.status_code == 401
        assert reponse.headers["www-authenticate"] == DEFI_D_AUTHENTIFICATION
        assert reponse.json()["code"] == "pas_de_session"
        assert str(monde.moi.id) not in reponse.text
