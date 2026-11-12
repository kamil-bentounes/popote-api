"""Spec § 3.10, « fermé par défaut » : sans session validée, tout refus sous `/api/v1/` est un `401`.

Un `405` (avec son `Allow`) ou un `422` (corps lu avant les dépendances) répondrait à qui n'a pas de session
que la route existe. Une fois la session validée, ces refus reprennent leur statut.
"""

import httpx
import pytest
from _commun import ECRITURE_LOCALE, reglages
from fastapi import APIRouter

from popote_api.api import v1
from popote_api.main import create_app
from popote_api.schemas.base import Entree
from popote_api.security.session import DEFI_D_AUTHENTIFICATION


class Corps(Entree):
    nombre: int


def client(monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    sous_routeur = APIRouter()

    @sous_routeur.post("/essai/ecrit")
    async def ecrit(corps: Corps) -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(v1, "SOUS_ROUTEURS", (sous_routeur,))
    app = create_app(reglages("local"))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_head_n_est_pas_servi_et_rend_401_sans_session(monkeypatch: pytest.MonkeyPatch) -> None:
    reponse = await client(monkeypatch).head("/api/v1/me")
    assert reponse.status_code == 401
    assert "allow" not in reponse.headers


def assert_401_sans_indice(reponse: httpx.Response) -> None:
    assert reponse.status_code == 401
    assert reponse.json()["code"] == "pas_de_session"
    assert reponse.headers["www-authenticate"] == DEFI_D_AUTHENTIFICATION
    assert "allow" not in reponse.headers


@pytest.mark.parametrize("methode", ["PUT", "DELETE", "PATCH", "GET"])
async def test_une_methode_inconnue_sans_session_rend_401_et_non_405(
    monkeypatch: pytest.MonkeyPatch, methode: str
) -> None:
    reponse = await client(monkeypatch).request(methode, "/api/v1/essai/ecrit", headers=ECRITURE_LOCALE)
    assert_401_sans_indice(reponse)


@pytest.mark.parametrize("corps", [b"{", b'{"nombre": "x"}', b"{}"], ids=["invalide", "mauvais_type", "vide"])
async def test_un_corps_refuse_sans_session_rend_401_et_non_422(
    monkeypatch: pytest.MonkeyPatch, corps: bytes
) -> None:
    entetes = ECRITURE_LOCALE | {"Content-Type": "application/json"}
    reponse = await client(monkeypatch).post("/api/v1/essai/ecrit", content=corps, headers=entetes)
    assert_401_sans_indice(reponse)


async def test_une_adresse_inconnue_sans_session_rend_401_comme_une_adresse_connue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reponse = await client(monkeypatch).get("/api/v1/nexiste-pas")
    assert_401_sans_indice(reponse)


async def test_hors_de_v1_les_refus_gardent_leur_statut(monkeypatch: pytest.MonkeyPatch) -> None:
    c = client(monkeypatch)
    assert (await c.get("/api/nexiste-pas")).status_code == 404
    assert (await c.post("/api/healthz", headers=ECRITURE_LOCALE)).status_code == 405
