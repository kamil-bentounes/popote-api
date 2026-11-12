import json

import httpx
import pytest
from _commun import RELAIS, SECRET, appeler, appeler_websocket, reglages
from pydantic import SecretStr
from starlette.datastructures import Headers

from popote_api import relais
from popote_api.config import Env, Settings
from popote_api.main import create_app
from popote_api.relais import REFUS_WEBSOCKET, relais_valide


def client(env: str) -> httpx.AsyncClient:
    app = create_app(reglages(env))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_hors_local_sans_en_tete_rend_404() -> None:
    assert (await client("essai").get("/api/healthz")).status_code == 404


async def test_hors_local_mauvais_en_tete_rend_404() -> None:
    r = await client("essai").get("/api/healthz", headers={"X-Popote-Relais": "faux"})
    assert r.status_code == 404


async def test_hors_local_bon_en_tete_passe() -> None:
    r = await client("essai").get("/api/healthz", headers={"X-Popote-Relais": SECRET})
    assert r.status_code == 200


async def test_en_local_le_relais_nest_pas_exige() -> None:
    assert (await client("local").get("/api/healthz")).status_code == 200


async def test_le_refus_est_un_probleme_qui_porte_son_identifiant() -> None:
    r = await client("essai").get("/api/healthz")
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.headers["x-request-id"] == r.json()["instance"]
    assert r.json()["code"] == "introuvable"


CHEMINS = ["/api/healthz", "/api", "//api/healthz", "/API/healthz", "/api/%2e%2e/healthz", "/", "/autre"]


@pytest.mark.parametrize("methode", ["GET", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("chemin", CHEMINS)
async def test_en_essai_sans_relais_toute_forme_de_chemin_rend_404(chemin: str, methode: str) -> None:
    retour = await appeler(create_app(reglages("essai")), methode, chemin)
    assert retour.status == 404
    assert retour.en_tetes["content-type"].startswith("application/problem+json")
    assert retour.en_tetes["x-request-id"]


async def test_le_refus_de_la_garde_porte_un_identifiant_egal_a_son_instance() -> None:
    retour = await appeler(create_app(reglages("essai")), "GET", "//api/healthz")
    assert retour.en_tetes["x-request-id"] == json.loads(retour.corps)["instance"]


async def test_un_faux_secret_de_meme_longueur_est_refuse() -> None:
    faux = {"X-Popote-Relais": "x" * len(SECRET)}
    retour = await appeler(create_app(reglages("essai")), "GET", "/api/healthz", faux)
    assert retour.status == 404


async def test_un_chemin_hors_api_avec_le_bon_relais_passe_la_garde() -> None:
    retour = await appeler(create_app(reglages("essai")), "GET", "/autre", RELAIS)
    assert retour.status == 404
    assert json.loads(retour.corps)["code"] == "introuvable"
    assert retour.en_tetes["x-request-id"]


def test_un_en_tete_recu_vide_est_refuse_meme_si_le_secret_est_vide() -> None:
    reglages_sans_controle = Settings.model_construct(env=Env.prod, relay_secret=SecretStr(""))
    assert relais_valide(Headers({"x-popote-relais": ""}), reglages_sans_controle) is False


async def test_un_websocket_sans_relais_est_ferme_avant_l_acceptation() -> None:
    messages = await appeler_websocket(create_app(reglages("essai")), "/api/ws")
    assert messages == [{"type": "websocket.close", "code": REFUS_WEBSOCKET}]


async def test_un_websocket_avec_le_relais_traverse_la_garde() -> None:
    messages = await appeler_websocket(create_app(reglages("essai")), "/api/ws", RELAIS)
    assert messages[0]["type"] == "websocket.close"
    assert messages[0]["code"] != REFUS_WEBSOCKET


async def test_une_exemption_declaree_passe_sans_relais(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relais, "EXEMPTIONS", ("/interne/",))
    retour = await appeler(create_app(reglages("essai")), "GET", "/interne/x")
    assert retour.status == 404
    assert "x-popote-relais" not in retour.en_tetes


def test_la_liste_d_exemptions_est_vide_a_l_etape_0_2() -> None:
    assert relais.EXEMPTIONS == ()
