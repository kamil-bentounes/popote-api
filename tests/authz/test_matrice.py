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

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from _client import application_de_test, client_de, cookie
from _commun import reglages
from _fabrique import Fabrique, Personne
from _routes import routes_de_l_api
from fastapi import APIRouter, FastAPI

from popote_api.api import v1
from popote_api.infra.db import Base
from popote_api.infra.fuites import ResultatFuite
from popote_api.main import ROUTES_PUBLIQUES, create_app
from popote_api.security.session import DEFI_D_AUTHENTIFICATION

ECRITURE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}


def _entetes(methode: str, cas: "Cas | None" = None) -> dict[str, str]:
    """La garde d'origine ne regarde que les écritures ; un `POST` à effet porte sa clé d'idempotence."""
    if methode == "GET":
        return {}
    return ECRITURE | ({"Idempotency-Key": '"matrice"'} if cas and cas.avec_cle_d_idempotence else {})


MOT_DE_PASSE_DE_MOI = "le-mot-de-passe-de-moi-1234"


@dataclass(frozen=True)
class Monde:
    """Deux foyers, une personne dans chacun."""

    moi: Personne
    autre: Personne
    a_viser: UUID  # une session de `moi`, autre que celle qui sert de cookie
    invitation: UUID  # un lien en attente du foyer de `moi`


@dataclass(frozen=True)
class Cas:
    chemin: Callable[[Monde], str]
    chez_moi: Callable[[Monde, httpx.Response], None]
    chez_un_autre_foyer: Callable[[Monde, httpx.Response], None]
    corps: Callable[[Monde], dict[str, str]] | None = None  # le corps JSON d'une écriture, le même pour tous
    avec_cle_d_idempotence: bool = False  # un `POST` à effet exige `Idempotency-Key`


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


def _sessions_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 200
    assert str(monde.a_viser) in [i["id"] for i in reponse.json()["items"]]


def _sessions_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # Liste « de soi » : l'autre foyer ne voit que ses sessions, jamais celles de `moi`.
    assert reponse.status_code == 200
    assert str(monde.a_viser) not in reponse.text
    assert len(reponse.json()["items"]) == 1


def _fermer_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 204


def _fermer_un_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # Une session désignée par son identifiant : introuvable, sans dire qu'elle existe.
    assert reponse.status_code == 404
    assert str(monde.a_viser) not in reponse.text


def _fermer_les_autres_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # Route « de soi » : l'autre foyer ferme ses propres autres sessions ; celles de `moi` ne bougent pas
    # (gardé en base par `test_appareils.py`).
    assert reponse.status_code == 204


def _mot_de_passe_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 204
    assert "set-cookie" in reponse.headers


def _mot_de_passe_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # Route « de soi » : l'autre foyer change SON mot de passe ; celui de `moi` ne bouge pas.
    assert reponse.status_code == 204
    assert str(monde.moi.id) not in reponse.text


def _reauth_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 204


def _reauth_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # Route « de soi » : la session de l'autre vérifie SON mot de passe, jamais celui de `moi`.
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "mot_de_passe_incorrect"
    assert str(monde.moi.id) not in reponse.text


def _invitation_creee_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 201
    assert len(reponse.json()["token"]) == 43
    assert reponse.headers["location"] == f"/api/v1/me/invitations/{reponse.json()['id']}"


def _invitation_creee_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # Route « de soi » : le lien se crée pour le foyer de l'autre (gardé en base par
    # `test_invitations_hote.py`), et rien de `moi` n'apparaît dans la réponse.
    assert reponse.status_code == 201
    assert str(monde.moi.id) not in reponse.text
    assert str(monde.moi.foyer_id) not in reponse.text


def _invitations_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 200
    assert [i["id"] for i in reponse.json()["items"]] == [str(monde.invitation)]


def _invitations_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # « Du foyer » : l'autre foyer ne voit rien du mien.
    assert reponse.status_code == 200
    assert reponse.json()["items"] == []
    assert str(monde.invitation) not in reponse.text


def _revoque_chez_moi(monde: Monde, reponse: httpx.Response) -> None:
    assert reponse.status_code == 204


def _revoque_chez_un_autre_foyer(monde: Monde, reponse: httpx.Response) -> None:
    # Le lien de `moi` n'existe pas pour l'autre foyer (le lien reste valide : gardé en base par
    # `test_invitations_hote.py`).
    assert reponse.status_code == 404
    assert reponse.json()["code"] == "invitation_introuvable"
    assert reponse.json()["status"] == 404


MATRICE: dict[tuple[str, str], Cas] = {
    ("GET", "/api/v1/me"): Cas(lambda _: "/api/v1/me", _me_chez_moi, _me_chez_un_autre_foyer),
    ("GET", "/api/v1/me/sessions"): Cas(
        lambda _: "/api/v1/me/sessions", _sessions_chez_moi, _sessions_chez_un_autre_foyer
    ),
    ("DELETE", "/api/v1/me/sessions/{id}"): Cas(
        lambda monde: f"/api/v1/me/sessions/{monde.a_viser}",
        _fermer_chez_moi,
        _fermer_un_chez_un_autre_foyer,
    ),
    ("DELETE", "/api/v1/me/sessions"): Cas(
        lambda _: "/api/v1/me/sessions?scope=others", _fermer_chez_moi, _fermer_les_autres_chez_un_autre_foyer
    ),
    ("POST", "/api/v1/me/reauthentication"): Cas(
        lambda _: "/api/v1/me/reauthentication",
        _reauth_chez_moi,
        _reauth_chez_un_autre_foyer,
        lambda _: {"password": MOT_DE_PASSE_DE_MOI},
    ),
    ("PUT", "/api/v1/me/password"): Cas(
        lambda _: "/api/v1/me/password",
        _mot_de_passe_chez_moi,
        _mot_de_passe_chez_un_autre_foyer,
        lambda _: {"new_password": "un-tout-nouveau-mot-de-passe"},
    ),
    ("POST", "/api/v1/me/invitations"): Cas(
        lambda _: "/api/v1/me/invitations",
        _invitation_creee_chez_moi,
        _invitation_creee_chez_un_autre_foyer,
        avec_cle_d_idempotence=True,
    ),
    ("GET", "/api/v1/me/invitations"): Cas(
        lambda _: "/api/v1/me/invitations", _invitations_chez_moi, _invitations_chez_un_autre_foyer
    ),
    ("DELETE", "/api/v1/me/invitations/{id}"): Cas(
        lambda monde: f"/api/v1/me/invitations/{monde.invitation}",
        _revoque_chez_moi,
        _revoque_chez_un_autre_foyer,
    ),
}


def routes_de_v1(app: FastAPI) -> list[tuple[str, str]]:
    """Chaque couple (méthode, chemin) de `/api/v1`, énuméré sur l'application elle-même."""
    return sorted(
        (methode, route.path)
        for route in routes_de_l_api(app)
        if route.path.startswith("/api/v1/") and route.path not in ROUTES_PUBLIQUES
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


class FuitesSaines:
    async def verifie(self, mot_de_passe: str) -> ResultatFuite:
        return ResultatFuite.sain()


class AuthSansEffet:
    async def change_mot_de_passe(self, identifiant: UUID, mot_de_passe: str) -> None:
        return None


@pytest.fixture
def monde(fabrique: Fabrique) -> Monde:
    moi = fabrique.personne(fabrique.foyer())
    # Un mot de passe connu à `moi` seulement : la réauthentification de la matrice le vérifie en base.
    fabrique.admin.execute(
        "update auth.users set encrypted_password = extensions.crypt(%s, extensions.gen_salt('bf', 4)) "
        "where id = %s",
        (MOT_DE_PASSE_DE_MOI, moi.id),
    )
    lien = fabrique.admin.execute(
        "select id from private.cree_invitation(%s, %s, now())",
        (moi.id, hashlib.sha256(uuid4().bytes).digest()),
    ).fetchone()
    assert lien is not None
    return Monde(
        moi=moi,
        autre=fabrique.personne(fabrique.foyer()),
        a_viser=fabrique.session(moi.id).id,
        invitation=lien[0],
    )


def _cas(methode: str, chemin: str) -> Cas:
    cas = MATRICE.get((methode, chemin))
    assert cas is not None, f"{methode} {chemin} n'a pas de cas dans la matrice d'autorisation"
    return cas


@pytest.fixture
def client(base: Base, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    # Le poivre : sans lui, la réauthentification refuse de compter. L'IP ne bloque pas la matrice.
    app = application_de_test(base, monkeypatch, identity_pepper="p" * 32, connexion_essais_par_ip=10000)
    # Ni réseau ni Auth : la matrice garde l'autorisation (le changement : `test_changement_mot_de_passe.py`).
    app.state.fuites = FuitesSaines()
    app.state.auth_admin = AuthSansEffet()
    return client_de(app)


pytestmark = pytest.mark.integration


@pytest.mark.parametrize(("methode", "chemin"), ROUTES, ids=[f"{m} {c}" for m, c in ROUTES])
class TestMatriceParRoute:
    async def test_mon_foyer(
        self, client: httpx.AsyncClient, fabrique: Fabrique, monde: Monde, methode: str, chemin: str
    ) -> None:
        cas = _cas(methode, chemin)
        reponse = await client.request(
            methode,
            cas.chemin(monde),
            headers=cookie(fabrique.session(monde.moi.id)) | _entetes(methode, cas),
            json=cas.corps(monde) if cas.corps else None,
        )
        cas.chez_moi(monde, reponse)

    async def test_un_autre_foyer(
        self, client: httpx.AsyncClient, fabrique: Fabrique, monde: Monde, methode: str, chemin: str
    ) -> None:
        cas = _cas(methode, chemin)
        reponse = await client.request(
            methode,
            cas.chemin(monde),
            headers=cookie(fabrique.session(monde.autre.id)) | _entetes(methode, cas),
            json=cas.corps(monde) if cas.corps else None,
        )
        cas.chez_un_autre_foyer(monde, reponse)

    async def test_sans_session(
        self, client: httpx.AsyncClient, monde: Monde, methode: str, chemin: str
    ) -> None:
        cas = _cas(methode, chemin)
        reponse = await client.request(
            methode,
            cas.chemin(monde),
            headers=_entetes(methode, cas),
            json=cas.corps(monde) if cas.corps else None,
        )
        assert reponse.status_code == 401
        assert reponse.headers["www-authenticate"] == DEFI_D_AUTHENTIFICATION
        assert reponse.json()["code"] == "pas_de_session"
        assert str(monde.moi.id) not in reponse.text


async def test_la_connexion_publique_ne_change_rien_pour_qui_a_deja_une_session(
    client: httpx.AsyncClient, fabrique: Fabrique, monde: Monde
) -> None:
    """Route publique : la session présentée ne donne ni accès ni information, et un échec ne la ferme pas."""
    ouverte = {"Cookie": f"__Host-popote_session={fabrique.session(monde.moi.id).jeton}"}
    refus = await client.post(
        "/api/v1/sessions",
        json={"email": "inconnue@test.local", "password": "mauvais-mot-de-passe-long"},
        headers=ouverte | ECRITURE,
    )
    assert refus.status_code == 401
    assert refus.json()["code"] == "identifiants_incorrects"
    assert "set-cookie" not in refus.headers
    assert str(monde.moi.id) not in refus.text
    assert (await client.get("/api/v1/me", headers=ouverte)).status_code == 200  # l'échec ne l'a pas fermée
