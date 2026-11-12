import asyncio
import json
import logging
from collections.abc import Awaitable
from typing import Any

import httpx
import pytest
from _commun import RELAIS, appeler, reglages
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from popote_api import limites
from popote_api.limites import TAILLE_MAX_OCTETS, Delai, SansCache, TailleMax, TypeJson
from popote_api.main import create_app

JSON = {"Content-Type": "application/json"}
# Ce que le front envoie dans une écriture (garde d'origine) ; sans effet tant qu'elle n'est pas fusionnée.
WEB = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}
BORNE_SECONDES = 5  # un test lent qui régresse échoue au lieu de bloquer toute la suite


async def borne[T](attente: Awaitable[T]) -> T:
    return await asyncio.wait_for(attente, BORNE_SECONDES)


async def lit_tout(scope: Scope, receive: Receive, send: Send) -> None:
    """Une application témoin : elle lit tout le corps et rend sa taille, ce que l'application a vu."""
    corps = b""
    while True:
        message = await receive()
        corps += message.get("body", b"")
        if not message.get("more_body", False):
            break
    reponse = json.dumps({"octets": len(corps)}).encode()
    await send(
        {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]}
    )
    await send({"type": "http.response.body", "body": reponse})


def client(app: ASGIApp) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def flux(*morceaux: bytes):
    for morceau in morceaux:
        yield morceau


# --- Les valeurs écrites dans les normes ----------------------------------------------------------


def test_les_limites_sont_celles_des_normes() -> None:
    assert TAILLE_MAX_OCTETS == 1_048_576  # 1 Mio
    assert limites.DELAI_SECONDES == 25  # le relais coupe à 30 s


# --- Taille ---------------------------------------------------------------------------------------


async def test_un_corps_d_un_mio_passe_et_l_application_le_voit_en_entier() -> None:
    r = await client(TailleMax(lit_tout)).post("/", content=b"x" * TAILLE_MAX_OCTETS)
    assert (r.status_code, r.json()) == (200, {"octets": TAILLE_MAX_OCTETS})


async def test_un_corps_d_un_mio_et_un_octet_rend_413_avec_content_length() -> None:
    r = await client(TailleMax(lit_tout)).post("/", content=b"x" * (TAILLE_MAX_OCTETS + 1))
    assert r.status_code == 413
    assert r.json()["code"] == "corps_trop_gros"
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_un_flux_sans_content_length_passe_a_un_mio_exactement() -> None:
    moitie = b"x" * (TAILLE_MAX_OCTETS // 2)
    r = await client(TailleMax(lit_tout)).post("/", content=flux(moitie, moitie))
    assert (r.status_code, r.json()) == (200, {"octets": TAILLE_MAX_OCTETS})


async def test_un_flux_sans_content_length_rend_413_a_un_mio_et_un_octet() -> None:
    moitie = b"x" * (TAILLE_MAX_OCTETS // 2)
    envoye = client(TailleMax(lit_tout))
    r = await envoye.post("/", content=flux(moitie, moitie, b"x"))
    assert r.status_code == 413


async def test_un_content_length_menteur_ne_trompe_pas_le_compte_des_octets() -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", b"10")],
        "state": {},
    }
    messages: list[Message] = []
    morceaux = iter([b"x" * TAILLE_MAX_OCTETS, b"x"])

    async def receive() -> Message:
        morceau = next(morceaux)
        return {
            "type": "http.request",
            "body": morceau,
            "more_body": morceau[-1:] == b"x" and len(morceau) > 1,
        }

    async def send(message: Message) -> None:
        messages.append(message)

    await TailleMax(lit_tout)(scope, receive, send)
    assert messages[0]["status"] == 413


@pytest.mark.parametrize(
    "declaree",
    [b"abc", b"-1", b"1.5", b"", b"\xb2", "١٢".encode(), b"\xc2\xb2", b"1 2", b"0x10", b"+5"],
    ids=repr,
)
async def test_un_content_length_invalide_rend_400_et_jamais_500(declaree: bytes) -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", declaree)],
    }
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        raise AssertionError("le corps ne doit pas être lu")

    await TailleMax(lit_tout)(scope, receive, send)
    assert messages[0]["status"] == 400


async def test_un_content_length_au_dela_de_la_limite_rend_413_sans_lire_le_corps() -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", str(TAILLE_MAX_OCTETS + 1).encode())],
    }
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        raise AssertionError("le corps ne doit pas être lu")

    await TailleMax(lit_tout)(scope, receive, send)
    assert messages[0]["status"] == 413


async def test_un_content_length_gigantesque_rend_413_sans_calcul_demesure() -> None:
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [(b"content-length", b"9" * 5000)]}
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        raise AssertionError("le corps ne doit pas être lu")

    await TailleMax(lit_tout)(scope, receive, send)
    assert messages[0]["status"] == 413


async def test_la_413_ferme_la_connexion() -> None:
    r = await client(TailleMax(lit_tout)).post("/", content=b"x" * (TAILLE_MAX_OCTETS + 1))
    assert r.headers["connection"] == "close"


async def test_une_requete_sans_corps_passe_la_taille() -> None:
    r = await client(TailleMax(lit_tout)).get("/")
    assert r.json() == {"octets": 0}


# --- Type -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("methode", ["POST", "PUT", "PATCH"])
async def test_un_corps_en_texte_brut_rend_415(methode: str) -> None:
    r = await client(TypeJson(lit_tout)).request(
        methode, "/", content=b"abc", headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 415
    assert r.json()["code"] == "type_non_supporte"


@pytest.mark.parametrize(
    "type_media",
    [
        "application/json",
        "application/json; charset=utf-8",
        'Application/JSON ; charset="UTF-8"',
    ],
)
async def test_json_passe_avec_ou_sans_charset_utf8(type_media: str) -> None:
    r = await client(TypeJson(lit_tout)).post("/", content=b"{}", headers={"Content-Type": type_media})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "type_media",
    [
        "application/json; charset=latin-1",
        "application/json; boundary=x",
        "application/jsonx",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "application/merge-patch+json",  # admis pour PATCH seulement
    ],
)
async def test_un_type_voisin_de_json_est_refuse_en_post(type_media: str) -> None:
    r = await client(TypeJson(lit_tout)).post("/", content=b"{}", headers={"Content-Type": type_media})
    assert r.status_code == 415


async def test_patch_accepte_merge_patch() -> None:
    r = await client(TypeJson(lit_tout)).patch(
        "/", content=b"{}", headers={"Content-Type": "application/merge-patch+json"}
    )
    assert r.status_code == 200


async def test_un_corps_sans_content_type_rend_415() -> None:
    r = await client(TypeJson(lit_tout)).post("/", content=b"{}")
    assert r.status_code == 415


async def test_deux_content_type_rendent_415() -> None:
    r = await client(TypeJson(lit_tout)).post(
        "/", content=b"{}", headers=[("Content-Type", "application/json"), ("Content-Type", "text/plain")]
    )
    assert r.status_code == 415


async def test_un_flux_sans_content_length_est_controle_lui_aussi() -> None:
    r = await client(TypeJson(lit_tout)).post("/", content=flux(b"a"), headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


@pytest.mark.parametrize("methode", ["GET", "HEAD", "DELETE", "OPTIONS"])
async def test_les_autres_methodes_ne_sont_pas_controlees(methode: str) -> None:
    r = await client(TypeJson(lit_tout)).request(methode, "/", headers={"Content-Type": "text/plain"})
    assert r.status_code == 200


@pytest.mark.parametrize("methode", ["POST", "PUT", "PATCH"])
async def test_une_ecriture_sans_corps_ni_type_passe(methode: str) -> None:
    r = await client(TypeJson(lit_tout)).request(methode, "/")
    assert r.status_code == 200


async def test_le_prefixe_hors_json_echappe_au_controle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limites, "PREFIXES_HORS_JSON", ("/api/v1/photos",))
    app = TypeJson(lit_tout)
    photo = await client(app).post("/api/v1/photos", content=b"x", headers={"Content-Type": "image/jpeg"})
    ailleurs = await client(app).post(
        "/api/v1/recettes", content=b"x", headers={"Content-Type": "image/jpeg"}
    )
    assert (photo.status_code, ailleurs.status_code) == (200, 415)


# --- Délai ----------------------------------------------------------------------------------------


async def bloque_toujours(scope: Scope, receive: Receive, send: Send) -> None:
    await asyncio.Event().wait()


async def test_un_gestionnaire_lent_rend_503_delai_depasse_avec_retry_after() -> None:
    r = await borne(client(Delai(bloque_toujours, secondes=0.05)).get("/"))
    assert r.status_code == 503
    assert r.json()["code"] == "delai_depasse"
    assert r.headers["retry-after"] == str(limites.ATTENTE_APRES_DELAI)


async def test_un_gestionnaire_rapide_n_est_pas_touche_par_le_delai() -> None:
    r = await client(Delai(lit_tout, secondes=5)).get("/")
    assert r.status_code == 200


async def test_un_corps_qui_n_arrive_jamais_est_borne_par_le_delai() -> None:
    async def goutte_a_goutte() -> Any:
        yield b"x"
        await asyncio.Event().wait()

    app = Delai(TailleMax(lit_tout), secondes=0.05)
    r = await borne(client(app).post("/", content=goutte_a_goutte()))
    assert r.status_code == 503


async def test_un_timeout_du_gestionnaire_lui_meme_n_est_pas_pris_pour_le_delai() -> None:
    async def leve(scope: Scope, receive: Receive, send: Send) -> None:
        raise TimeoutError("celui du gestionnaire")

    with pytest.raises(TimeoutError, match="gestionnaire"):
        await Delai(leve, secondes=5)({"type": "http"}, None, None)  # type: ignore[arg-type]


async def test_un_delai_apres_le_debut_de_la_reponse_est_journalise_sans_nouvelle_reponse(
    caplog: pytest.LogCaptureFixture,
) -> None:
    messages: list[Message] = []

    async def debut_puis_bloque(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.Event().wait()

    async def send(message: Message) -> None:
        messages.append(message)

    with caplog.at_level(logging.WARNING, logger="popote_api.limites"):
        await borne(Delai(debut_puis_bloque, secondes=0.05)({"type": "http"}, None, send))  # type: ignore[arg-type]
    assert [m["type"] for m in messages] == ["http.response.start"]
    assert "après le début de la réponse" in caplog.text


# --- no-store par défaut --------------------------------------------------------------------------


async def test_une_reponse_sans_cache_control_recoit_no_store() -> None:
    r = await client(SansCache(lit_tout)).get("/")
    assert r.headers["cache-control"] == "no-store"


async def test_un_cache_control_deja_pose_est_conserve() -> None:
    async def avec_cache(scope: Scope, receive: Receive, send: Send) -> None:
        en_tetes = [(b"cache-control", b"private, max-age=60")]
        await send({"type": "http.response.start", "status": 200, "headers": en_tetes})
        await send({"type": "http.response.body", "body": b""})

    r = await client(SansCache(avec_cache)).get("/")
    assert r.headers.get_list("cache-control") == ["private, max-age=60"]


# --- Dans l'application complète ------------------------------------------------------------------


async def test_chaque_refus_de_limite_garde_son_identifiant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limites, "DELAI_SECONDES", 0.05)
    app = create_app(reglages("essai"))

    @app.get("/api/_test/lent")
    async def lent() -> None:
        await asyncio.Event().wait()

    @app.post("/api/_test/ecrit")
    async def ecrit() -> None:
        return None

    cas = {
        413: ("POST", "/api/_test/ecrit", JSON, b"x" * (TAILLE_MAX_OCTETS + 1)),
        415: ("POST", "/api/_test/ecrit", {"Content-Type": "text/plain"}, b"abc"),
        503: ("GET", "/api/_test/lent", {}, b""),
    }
    async with client(app) as c:
        for attendu, (methode, chemin, en_tetes, corps) in cas.items():
            r = await borne(c.request(methode, chemin, headers=RELAIS | WEB | en_tetes, content=corps))
            assert r.status_code == attendu
            assert r.headers["x-request-id"] == r.json()["instance"]
            assert r.headers["cache-control"] == "no-store"


async def test_le_refus_de_la_garde_precede_les_limites() -> None:
    """Sans le secret du relais : 404, et le corps (trop gros, mal typé) n'est même pas lu."""
    app = create_app(reglages("essai"))
    r = await client(app).post("/api/_test/ecrit", content=b"x" * (TAILLE_MAX_OCTETS + 1))
    assert r.status_code == 404
    assert r.headers["x-request-id"] == r.json()["instance"]


async def test_toute_reponse_de_l_application_porte_no_store_y_compris_une_erreur_de_route() -> None:
    app = create_app(reglages("local"))
    ok = await appeler(app, "GET", "/api/healthz")
    inconnue = await appeler(app, "GET", "/api/n-existe-pas")
    assert (ok.en_tetes["cache-control"], inconnue.en_tetes["cache-control"]) == ("no-store", "no-store")


async def test_un_corps_json_valide_traverse_toute_la_pile() -> None:
    app = create_app(reglages("local"))

    @app.post("/api/_test/echo")
    async def echo(donnees: dict[str, int]) -> dict[str, int]:
        return donnees

    r = await client(app).post("/api/_test/echo", json={"a": 1}, headers=WEB)
    assert (r.status_code, r.json()) == (200, {"a": 1})
