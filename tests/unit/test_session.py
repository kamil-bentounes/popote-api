"""La dépendance `personne_connectee`, sans base : tout ce qui se décide avant de lire la session."""

import base64
import logging

import httpx
import pytest
from _commun import reglages
from fastapi import APIRouter

from popote_api.api import v1
from popote_api.main import create_app
from popote_api.security.session import DEFI_D_AUTHENTIFICATION, PersonneDeLaSession

COOKIE = "__Host-popote_session"
JETON = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
URL = "/api/v1/essai/qui"


def application(monkeypatch: pytest.MonkeyPatch, **autres: object) -> httpx.AsyncClient:
    sous_routeur = APIRouter()

    @sous_routeur.get("/essai/qui")
    async def qui(personne: PersonneDeLaSession) -> dict[str, str]:
        return {"id": str(personne.id)}

    monkeypatch.setattr(v1, "SOUS_ROUTEURS", (sous_routeur,))
    app = create_app(reglages("local", **autres))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_sans_cookie_la_reponse_est_un_401_pas_de_session(monkeypatch: pytest.MonkeyPatch) -> None:
    reponse = await application(monkeypatch).get(URL)
    assert reponse.status_code == 401
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "pas_de_session"


async def test_le_401_porte_un_defi_www_authenticate(monkeypatch: pytest.MonkeyPatch) -> None:
    reponse = await application(monkeypatch).get(URL)
    assert reponse.headers["www-authenticate"] == DEFI_D_AUTHENTIFICATION == 'Cookie realm="popote"'


async def test_le_401_n_est_jamais_mis_en_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    reponse = await application(monkeypatch).get(URL)
    assert reponse.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "jeton",
    ["", "abc", JETON[:-1], JETON + "A", JETON[:-1] + "+", JETON[:-1] + "B"],
    ids=["vide", "court", "un_de_moins", "un_de_plus", "alphabet", "non_canonique"],
)
async def test_un_cookie_mal_forme_rend_le_meme_401(monkeypatch: pytest.MonkeyPatch, jeton: str) -> None:
    client = application(monkeypatch)
    sans_cookie = await client.get(URL)
    reponse = await client.get(URL, headers={"Cookie": f"{COOKIE}={jeton}"})
    assert reponse.status_code == 401
    assert reponse.headers["www-authenticate"] == DEFI_D_AUTHENTIFICATION
    corps, corps_sans_cookie = reponse.json(), sans_cookie.json()
    for corps_lu in (corps, corps_sans_cookie):
        corps_lu.pop("instance")
    assert corps == corps_sans_cookie


async def test_un_cookie_d_un_autre_nom_est_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    reponse = await application(monkeypatch).get(URL, headers={"Cookie": f"popote_session={JETON}"})
    assert reponse.status_code == 401


async def test_en_local_le_nom_du_cookie_est_celui_de_la_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bien formé, au bon nom : la requête va jusqu'à la base, absente ici, donc 503 et pas 401.
    client = application(monkeypatch, session_cookie_name="popote_session")
    reponse = await client.get(URL, headers={"Cookie": f"popote_session={JETON}"})
    assert reponse.status_code == 503
    ancien = await client.get(URL, headers={"Cookie": f"{COOKIE}={JETON}"})
    assert ancien.status_code == 401


async def test_sans_base_un_jeton_bien_forme_ne_passe_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    reponse = await application(monkeypatch).get(URL, headers={"Cookie": f"{COOKIE}={JETON}"})
    assert reponse.status_code == 503
    assert reponse.json()["code"] == "base_indisponible"


async def test_le_journal_dit_la_raison_d_un_cookie_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        await application(monkeypatch).get(URL)
    assert "Session refusée : absente" in caplog.text


async def test_le_journal_ne_recopie_pas_le_cookie_refuse(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "jeton-que-personne-ne-doit-lire"
    with caplog.at_level(logging.INFO):
        await application(monkeypatch).get(URL, headers={"Cookie": f"{COOKIE}={secret}"})
    assert "mal_formee" in caplog.text
    assert secret not in caplog.text
