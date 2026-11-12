import logging

import httpx
import pytest
from _commun import ECRITURE_ESSAI, ECRITURE_LOCALE, RELAIS, appeler_websocket, reglages
from fastapi import FastAPI, WebSocket
from starlette.requests import HTTPConnection

from popote_api.config import Settings
from popote_api.errors import Probleme
from popote_api.main import create_app
from popote_api.security.origine import garde_origine

ECRITURES = ["POST", "PUT", "PATCH", "DELETE"]
COMPTE = "monbureau"
APERCU = f"https://a1b2c3d4-popote-web-essai.{COMPTE}.workers.dev"


def app_de_test(env: str, **autres: str) -> FastAPI:
    app = create_app(reglages(env, **autres))

    @app.api_route("/api/_test/ecrit", methods=[*ECRITURES, "GET", "HEAD"])
    async def ecrit() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/internal/_test/signe")
    async def interne() -> dict[str, bool]:
        return {"ok": True}

    @app.websocket("/api/_test/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"ok": True})
        await websocket.close()

    @app.post("/internalement/_test")
    async def presque_interne() -> dict[str, bool]:
        return {"ok": True}

    return app


async def envoie(
    env: str, methode: str, en_tetes: dict[str, str], chemin: str = "/api/_test/ecrit", **reglage: str
) -> httpx.Response:
    app = app_de_test(env, **reglage)
    en_tetes = en_tetes | (RELAIS if env != "local" else {})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        return await c.request(methode, chemin, headers=en_tetes)


def sans(en_tetes: dict[str, str], nom: str) -> dict[str, str]:
    return {k: v for k, v in en_tetes.items() if k != nom}


@pytest.mark.parametrize("methode", ECRITURES)
async def test_une_ecriture_avec_les_trois_preuves_passe(methode: str) -> None:
    r = await envoie("local", methode, ECRITURE_LOCALE | {"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


@pytest.mark.parametrize("methode", ECRITURES)
async def test_sans_sec_fetch_site_une_ecriture_passe(methode: str) -> None:
    assert (await envoie("local", methode, ECRITURE_LOCALE)).status_code == 200


@pytest.mark.parametrize("methode", ECRITURES)
async def test_sans_origin_une_ecriture_est_refusee(methode: str) -> None:
    r = await envoie("local", methode, sans(ECRITURE_LOCALE, "Origin"))
    assert r.status_code == 403
    assert r.json()["code"] == "origine_refusee"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.headers["x-request-id"] == r.json()["instance"]


@pytest.mark.parametrize(
    "origine",
    [
        "https://evil.example",
        "null",
        "",
        "http://localhost:5174",
        "http://localhost",
        "https://localhost:5173",
        "http://localhost:5173/",
        "http://localhost:5173.evil.example",
        "HTTP://LOCALHOST:5173",
    ],
)
async def test_une_origine_etrangere_est_refusee(origine: str) -> None:
    r = await envoie("local", "POST", ECRITURE_LOCALE | {"Origin": origine})
    assert r.status_code == 403


async def test_deux_en_tetes_origin_sont_refuses() -> None:
    app = app_de_test("local")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/_test/ecrit",
            headers=[
                ("Origin", "http://localhost:5173"),
                ("Origin", "https://evil.example"),
                ("X-Popote-Client", "web"),
            ],
        )
    assert r.status_code == 403


@pytest.mark.parametrize("valeur", ["cross-site", "same-site", "none", "", "Same-Origin"])
async def test_un_sec_fetch_site_autre_que_same_origin_est_refuse(valeur: str) -> None:
    r = await envoie("local", "POST", ECRITURE_LOCALE | {"Sec-Fetch-Site": valeur})
    assert r.status_code == 403


async def test_sans_x_popote_client_une_ecriture_est_refusee() -> None:
    assert (await envoie("local", "POST", sans(ECRITURE_LOCALE, "X-Popote-Client"))).status_code == 403


@pytest.mark.parametrize("valeur", ["mobile", "", "WEB", "web "])
async def test_un_x_popote_client_autre_que_web_est_refuse(valeur: str) -> None:
    r = await envoie("local", "POST", ECRITURE_LOCALE | {"X-Popote-Client": valeur})
    assert r.status_code == 403


@pytest.mark.parametrize("methode", ["GET", "HEAD"])
async def test_une_lecture_n_est_pas_gardee(methode: str) -> None:
    r = await envoie("local", methode, {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200


async def test_une_route_interne_est_exemptee_de_la_garde() -> None:
    r = await envoie("local", "POST", {}, "/internal/_test/signe")
    assert r.status_code == 200


async def test_un_chemin_qui_ressemble_a_internal_n_est_pas_exempte() -> None:
    assert (await envoie("local", "POST", {}, "/internalement/_test")).status_code == 403


@pytest.mark.parametrize(
    ("env", "origine", "attendu"),
    [
        ("prod", "https://notre-popote.fr", 200),
        ("prod", "https://essai.notre-popote.fr", 403),
        ("prod", "http://localhost:5173", 403),
        ("prod", "https://notre-popote.fr.evil.example", 403),
        ("prod", "https://notre-popote.fr:8443", 403),
        ("prod", "http://notre-popote.fr", 403),
        ("prod", "https://www.notre-popote.fr", 403),
        ("essai", "https://essai.notre-popote.fr", 200),
        ("essai", "https://notre-popote.fr", 403),
        ("essai", "http://localhost:5173", 403),
        ("local", "http://localhost:5173", 200),
        ("local", "http://127.0.0.1:5173", 200),
        ("local", "https://notre-popote.fr", 403),
    ],
)
async def test_chaque_environnement_n_admet_que_ses_origines(env: str, origine: str, attendu: int) -> None:
    r = await envoie(env, "POST", {"Origin": origine, "X-Popote-Client": "web"})
    assert r.status_code == attendu


async def test_la_garde_s_applique_aussi_derriere_le_relais() -> None:
    sans_origine = await envoie("essai", "POST", {"X-Popote-Client": "web"})
    avec = await envoie("essai", "POST", ECRITURE_ESSAI | {"Sec-Fetch-Site": "same-origin"})
    assert (sans_origine.status_code, avec.status_code) == (403, 200)


# --- Les aperçus de fusion du front (essai seulement) ---------------------------------------------


@pytest.mark.parametrize(
    "origine",
    [
        APERCU,
        f"https://pr-12-popote-web-essai.{COMPTE}.workers.dev",
        f"https://12-popote-web-essai.{COMPTE}.workers.dev",
        f"https://a-b-c-popote-web-essai.{COMPTE}.workers.dev",
    ],
)
async def test_un_apercu_du_front_est_admis_sur_l_essai(origine: str) -> None:
    r = await envoie("essai", "POST", {"Origin": origine, "X-Popote-Client": "web"}, apercu_compte=COMPTE)
    assert r.status_code == 200


@pytest.mark.parametrize(
    "origine",
    [
        "https://a1b2c3d4-popote-web-essai.autrecompte.workers.dev",  # le même Worker, un autre compte
        f"https://a1b2c3d4-popote-api.{COMPTE}.workers.dev",  # un autre Worker du compte
        f"https://a1b2c3d4-popote-web-essai-bis.{COMPTE}.workers.dev",
        f"https://popote-web-essai.{COMPTE}.workers.dev",  # sans préfixe : l'adresse du Worker lui-même
        f"https://-popote-web-essai.{COMPTE}.workers.dev",
        f"http://a1b2c3d4-popote-web-essai.{COMPTE}.workers.dev",
        f"https://a1b2c3d4-popote-web-essai.{COMPTE}.workers.dev:8443",
        f"https://a1b2c3d4-popote-web-essai.{COMPTE}.workers.dev/",
        f"https://a1b2c3d4-popote-web-essai.{COMPTE}.workers.dev.evil.example",
        f"https://evil.example/a-popote-web-essai.{COMPTE}.workers.dev",
        f"https://x.a1b2c3d4-popote-web-essai.{COMPTE}.workers.dev",
        f"https://a1b2c3d4-popote-web-essai.{COMPTE}.pages.dev",
        f"https://A1B2C3D4-popote-web-essai.{COMPTE}.workers.dev",
        f"https://{'a' * 60}-popote-web-essai.{COMPTE}.workers.dev",  # étiquette de plus de 63 caractères
    ],
)
async def test_une_origine_voisine_d_un_apercu_est_refusee(origine: str) -> None:
    r = await envoie("essai", "POST", {"Origin": origine, "X-Popote-Client": "web"}, apercu_compte=COMPTE)
    assert r.status_code == 403


async def test_l_etiquette_de_63_caracteres_passe_et_celle_de_64_est_refusee() -> None:
    longueur = 63 - len("-popote-web-essai")
    for prefixe, attendu in (("a" * longueur, 200), ("a" * (longueur + 1), 403)):
        origine = f"https://{prefixe}-popote-web-essai.{COMPTE}.workers.dev"
        r = await envoie("essai", "POST", {"Origin": origine, "X-Popote-Client": "web"}, apercu_compte=COMPTE)
        assert r.status_code == attendu


async def test_sans_compte_configure_aucun_apercu_n_est_admis() -> None:
    r = await envoie("essai", "POST", {"Origin": APERCU, "X-Popote-Client": "web"})
    assert r.status_code == 403


@pytest.mark.parametrize("env", ["prod", "local"])
def test_un_apercu_est_impossible_hors_de_l_essai(env: str) -> None:
    with pytest.raises(ValueError, match="apercu_compte"):
        reglages(env, apercu_compte=COMPTE)


@pytest.mark.parametrize("compte", ["", "Mon", "a.b", "-a", "a-", "a" * 64, "a/b", "é"])
def test_un_compte_qui_n_est_pas_un_sous_domaine_echoue_au_demarrage(compte: str) -> None:
    with pytest.raises(ValueError, match="apercu_compte"):
        reglages("essai", apercu_compte=compte)


# --- Journal --------------------------------------------------------------------------------------


async def test_le_refus_est_journalise_sans_recopier_la_valeur_recue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="popote_api.security.origine"):
        await envoie("local", "POST", ECRITURE_LOCALE | {"Origin": "https://evil.example"})
    assert "origine" in caplog.text
    assert "evil.example" not in caplog.text


def test_le_compte_des_apercus_est_lu_dans_l_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    for nom, valeur in {
        "POPOTE_ENV": "essai",
        "POPOTE_RELAY_SECRET": "s" * 32,
        "POPOTE_DATABASE_URL": "postgresql://x:y@127.0.0.1:1/rien",
        "POPOTE_APERCU_COMPTE": COMPTE,
    }.items():
        monkeypatch.setenv(nom, valeur)
    assert Settings().origine_admise(APERCU)


# --- Les méthodes inattendues et les websockets ---------------------------------------------------


@pytest.mark.parametrize("methode", ["PROPPATCH", "TRACE", "PURGE", "LINK", "post"])
async def test_une_methode_inattendue_est_gardee_comme_une_ecriture(methode: str) -> None:
    scope = {"type": "http", "method": methode, "path": "/api/x", "headers": [], "app": app_de_test("local")}
    with pytest.raises(Probleme) as erreur:
        await garde_origine(HTTPConnection(scope))
    assert erreur.value.code == "origine_refusee"


@pytest.mark.parametrize("methode", ["GET", "HEAD", "OPTIONS"])
async def test_les_methodes_sures_ne_sont_pas_gardees(methode: str) -> None:
    scope = {"type": "http", "method": methode, "path": "/api/x", "headers": [], "app": app_de_test("local")}
    await garde_origine(HTTPConnection(scope))


async def test_un_websocket_avec_l_origine_de_l_environnement_est_accepte() -> None:
    messages = await appeler_websocket(
        app_de_test("local"), "/api/_test/ws", {"Origin": "http://localhost:5173"}
    )
    assert messages[0]["type"] == "websocket.accept"


@pytest.mark.parametrize(
    "en_tetes",
    [
        {},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "cross-site"},
    ],
    ids=["sans-origin", "etrangere", "null", "cross-site"],
)
async def test_un_websocket_d_une_origine_etrangere_est_refuse_a_la_poignee_de_main(
    en_tetes: dict[str, str],
) -> None:
    messages = await appeler_websocket(app_de_test("local"), "/api/_test/ws", en_tetes)
    assert [(m["type"], m.get("code")) for m in messages] == [("websocket.close", 1008)]


async def test_un_websocket_n_a_pas_besoin_de_x_popote_client() -> None:
    """Un navigateur ne peut pas poser d'en-tête personnalisé sur un websocket : seule l'origine compte."""
    en_tetes = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"}
    messages = await appeler_websocket(app_de_test("local"), "/api/_test/ws", en_tetes)
    assert messages[0]["type"] == "websocket.accept"
