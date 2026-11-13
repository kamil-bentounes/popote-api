"""Spec § 3.5 : tout `POST` ou `PATCH` d'un connecté garde sa réponse, sauf une liste écrite ici."""

import pytest
from _commun import reglages
from _routes import routes_de_l_api
from fastapi import APIRouter, FastAPI

from popote_api.api import v1
from popote_api.main import create_app
from popote_api.security.idempotence import METHODES_A_CLE, RouteIdempotente

# Les écritures de `/api/v1` qui n'ont pas besoin de clé, chacune avec sa raison. Une écriture PUBLIQUE n'a
# pas de personne, donc pas de clé d'idempotence, et rejouer sa réponse garderait un jeton en base.
LISTE_BLANCHE: dict[str, str] = {
    "/api/v1/sessions": "connexion : publique ; chaque succès ouvre une session neuve, un échec se compte",
    "/api/v1/invitations/inspections": "inspection d'un lien : publique ; lecture sans effet, sans clé",
    "/api/v1/invitations/acceptances": "acceptation d'un lien : publique ; le lien n'entre pas en base",
    "/api/v1/password-resets": "demande de réinitialisation : publique ; toujours 202, rien à rejouer",
    "/api/v1/me/reauthentication": "réauthentification : effet naturellement idempotent",
}
PREFIXE = "/api/v1/"


def ecritures_sans_cle(app: FastAPI) -> list[str]:
    return [
        f"{methode} {route.path}"
        for route in routes_de_l_api(app)
        if route.path.startswith(PREFIXE) and route.path not in LISTE_BLANCHE
        for methode in sorted(METHODES_A_CLE & set(route.methods or ()))
        if not isinstance(route.original_route, RouteIdempotente)
    ]


def application_avec(monkeypatch: pytest.MonkeyPatch, sous_routeur: APIRouter) -> FastAPI:
    monkeypatch.setattr(v1, "SOUS_ROUTEURS", (sous_routeur,))
    return create_app(reglages("local"))


@pytest.mark.parametrize("env", ["local", "essai", "prod"])
def test_toute_ecriture_de_v1_garde_sa_reponse_hors_liste_blanche(env: str) -> None:
    assert ecritures_sans_cle(create_app(reglages(env))) == []


def test_le_garde_voit_un_post_de_v1_sans_route_idempotente(monkeypatch: pytest.MonkeyPatch) -> None:
    sous_routeur = APIRouter()

    @sous_routeur.post("/essai/oubli")
    async def oubli() -> None: ...

    @sous_routeur.patch("/essai/oubli-patch")
    async def oubli_patch() -> None: ...

    app = application_avec(monkeypatch, sous_routeur)
    assert ecritures_sans_cle(app) == ["POST /api/v1/essai/oubli", "PATCH /api/v1/essai/oubli-patch"]


def test_le_garde_accepte_un_post_d_un_routeur_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    sous_routeur = APIRouter(route_class=RouteIdempotente)

    @sous_routeur.post("/essai/pose")
    async def pose() -> None: ...

    assert ecritures_sans_cle(application_avec(monkeypatch, sous_routeur)) == []


def test_le_garde_laisse_passer_les_lectures_et_les_suppressions(monkeypatch: pytest.MonkeyPatch) -> None:
    # `GET`, `PUT` et `DELETE` sont idempotents par nature (RFC 9110 § 9.2.2) : pas de clé.
    sous_routeur = APIRouter()

    @sous_routeur.get("/essai/lit")
    async def lit() -> None: ...

    @sous_routeur.put("/essai/remplace")
    async def remplace() -> None: ...

    @sous_routeur.delete("/essai/efface")
    async def efface() -> None: ...

    assert ecritures_sans_cle(application_avec(monkeypatch, sous_routeur)) == []


def test_la_liste_blanche_ne_garde_que_des_routes_qui_existent() -> None:
    chemins = {r.path for env in ("local", "prod") for r in routes_de_l_api(create_app(reglages(env)))}
    assert set(LISTE_BLANCHE) <= chemins
