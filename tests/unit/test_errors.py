import json
import logging
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
import pytest
from _commun import reglages
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from popote_api.errors import Probleme, reponse
from popote_api.main import create_app


@pytest.fixture
def client() -> httpx.AsyncClient:
    app = create_app(reglages("local"))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_une_route_inconnue_rend_un_probleme(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/nexiste-pas")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    corps = r.json()
    assert corps["type"] == "https://notre-popote.fr/problemes/introuvable"
    assert corps["status"] == 404
    assert corps["code"] == "introuvable"
    assert corps["title"] == "Introuvable"
    assert corps["instance"]
    assert "Traceback" not in r.text


async def test_chaque_reponse_porte_son_identifiant(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/nexiste-pas")
    assert r.headers["x-request-id"] == r.json()["instance"]


async def test_une_methode_non_permise_rend_405_en_probleme() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/lecture")
    async def lecture() -> dict[str, bool]:
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/_test/lecture")
    assert r.status_code == 405
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "methode_non_permise"


async def test_une_exception_inattendue_rend_500_sans_trace() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret interne: postgresql://u:p@h/db")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    corps = r.json()
    assert corps["code"] == "erreur_interne"
    assert corps["instance"]
    assert r.headers["x-request-id"] == corps["instance"]
    assert "Traceback" not in r.text
    assert "secret interne" not in r.text


def test_reponse_sans_identifiant_de_requete_prend_une_valeur_de_repli() -> None:
    requete = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    r = reponse(requete, 404, "introuvable", "Cette adresse n'existe pas.")
    corps = json.loads(bytes(r.body))
    assert corps["instance"]
    assert r.headers["x-request-id"] == corps["instance"]


def app_de_test() -> FastAPI:
    app = create_app(reglages("local"))

    class Couleur(StrEnum):
        rouge = "rouge"
        bleu = "bleu"

    class Corps(BaseModel):
        model_config = ConfigDict(extra="forbid")
        nom: str | None = Field(default=None, min_length=3, max_length=5)
        age: int | None = Field(default=None, gt=0, le=10)
        minimum: int | None = Field(default=None, ge=2)
        maximum: int | None = Field(default=None, lt=9)
        actif: bool | None = None
        ratio: float | None = None
        ref: UUID | None = None
        jour: date | None = None
        quand: datetime | None = None
        genre: Literal["a", "b"] | None = None
        couleur: Couleur | None = None
        texte: str | None = None
        pair: int | None = None

    @app.post("/api/_test/corps")
    async def corps(donnees: Corps) -> dict[str, bool]:
        return {"ok": True}

    class Imbrique(BaseModel):
        cles: dict[str, int]

    @app.post("/api/_test/imbrique")
    async def imbrique(donnees: Imbrique) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/_test/dictionnaire")
    async def dictionnaire(donnees: dict[str, int]) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/_test/parametres/{n}")
    async def parametres(n: int, q: int = 0, x_jeton: Annotated[int, Header()] = 0) -> dict[str, int]:
        return {"n": n}

    return app


async def poste(chemin: str, **requete: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post(chemin, **requete)


@pytest.mark.parametrize(
    ("corps", "champ", "message"),
    [
        ({"nom": "ab"}, "nom", "Trop court : 3 caractères au minimum."),
        ({"nom": "abcdef"}, "nom", "Trop long : 5 caractères au maximum."),
        ({"age": "x"}, "age", "Un nombre entier est attendu."),
        ({"age": 0}, "age", "Doit être strictement supérieur à 0."),
        ({"age": 11}, "age", "Doit être inférieur ou égal à 10."),
        ({"minimum": 1}, "minimum", "Doit être supérieur ou égal à 2."),
        ({"maximum": 9}, "maximum", "Doit être strictement inférieur à 9."),
        ({"actif": "peut-etre"}, "actif", "Un booléen (vrai ou faux) est attendu."),
        ({"ratio": "x"}, "ratio", "Un nombre est attendu."),
        ({"ref": "pas-un-uuid"}, "ref", "Un identifiant UUID valide est attendu."),
        ({"jour": "hier"}, "jour", "Une date valide est attendue (AAAA-MM-JJ)."),
        ({"quand": "bientôt"}, "quand", "Une date et une heure valides sont attendues (ISO 8601)."),
        ({"genre": "c"}, "genre", "Valeur attendue parmi : 'a' ou 'b'."),
        ({"couleur": "vert"}, "couleur", "Valeur attendue parmi : 'rouge' ou 'bleu'."),
        ({"inconnu": 1}, "inconnu", "Ce champ n'est pas permis."),
        ({"texte": 12}, "texte", "Valeur invalide."),
    ],
)
async def test_les_erreurs_de_corps_ont_un_message_en_francais_et_un_pointeur(
    corps: dict[str, Any], champ: str, message: str
) -> None:
    r = await poste("/api/_test/corps", json=corps)
    assert r.status_code == 422
    assert r.json()["errors"] == [{"pointer": f"/{champ}", "message": message}]


async def test_un_corps_de_mauvais_type_pointe_la_racine() -> None:
    r = await poste("/api/_test/corps", json=[1])
    assert r.json()["errors"] == [{"pointer": "", "message": "Un objet JSON est attendu."}]
    r = await poste("/api/_test/dictionnaire", json=[1])
    assert r.json()["errors"] == [{"pointer": "", "message": "Un objet JSON est attendu."}]


async def test_un_json_invalide_pointe_la_racine() -> None:
    r = await poste("/api/_test/corps", content=b"{pas du json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["errors"] == [{"pointer": "", "message": "Le corps n'est pas un JSON valide."}]


async def test_le_pointeur_echappe_les_barres_et_les_tildes() -> None:
    r = await poste("/api/_test/dictionnaire", json={"a/b": "x", "c~d": "y"})
    pointeurs = [e["pointer"] for e in r.json()["errors"]]
    assert pointeurs == ["/a~1b", "/c~0d"]


async def test_les_erreurs_hors_corps_portent_un_parametre_et_pas_de_pointeur() -> None:
    transport = httpx.ASGITransport(app=app_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/parametres/abc", params={"q": "z"}, headers={"X-Jeton": "t"})
    erreurs = r.json()["errors"]
    assert {"parameter": {"name": "n", "in": "path"}, "message": "Un nombre entier est attendu."} in erreurs
    assert {"parameter": {"name": "q", "in": "query"}, "message": "Un nombre entier est attendu."} in erreurs
    assert {
        "parameter": {"name": "x-jeton", "in": "header"},
        "message": "Un nombre entier est attendu.",
    } in erreurs
    assert all("pointer" not in e for e in erreurs)


@pytest.mark.parametrize(
    ("status", "titre", "code"),
    [
        (400, "Requête mal formée", "requete_mal_formee"),
        (401, "Pas de session", "pas_de_session"),
        (403, "Interdit", "interdit"),
        (404, "Introuvable", "introuvable"),
        (405, "Méthode non permise", "methode_non_permise"),
        (406, "Format non acceptable", "non_acceptable"),
        (409, "Conflit", "conflit"),
        (410, "Disparu", "disparu"),
        (412, "Précondition échouée", "precondition_echouee"),
        (413, "Corps trop gros", "corps_trop_gros"),
        (415, "Type de contenu non supporté", "type_non_supporte"),
        (422, "Données invalides", "donnees_invalides"),
        (428, "Précondition requise", "precondition_requise"),
        (429, "Trop de requêtes", "trop_de_requetes"),
        (500, "Erreur interne", "erreur_interne"),
        (502, "Mauvaise passerelle", "mauvaise_passerelle"),
        (503, "Service indisponible", "service_indisponible"),
        (504, "Délai de passerelle dépassé", "delai_de_passerelle_depasse"),
    ],
)
async def test_chaque_statut_courant_a_son_titre_et_son_code_en_francais(
    status: int, titre: str, code: str
) -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/statut")
    async def statut() -> None:
        raise HTTPException(status)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/statut")
    assert (r.status_code, r.json()["title"], r.json()["code"]) == (status, titre, code)
    assert r.json()["type"] == f"https://notre-popote.fr/problemes/{code}"


def test_un_statut_non_standard_prend_le_titre_et_le_code_par_defaut() -> None:
    requete = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    corps = json.loads(bytes(reponse(requete, 599, "autre", "Détail.").body))
    assert corps["title"] == "Erreur"
    assert corps["status"] == 599


async def test_un_statut_http_non_standard_rend_le_code_erreur() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/etrange")
    async def etrange() -> None:
        raise HTTPException(599, detail="bizarre")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/etrange")
    assert (r.status_code, r.json()["code"], r.json()["title"]) == (599, "erreur", "Erreur")


async def test_une_405_garde_l_en_tete_allow() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/lecture")
    async def lecture() -> dict[str, bool]:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/_test/lecture")
    assert "GET" in r.headers["allow"]


async def test_une_erreur_http_garde_ses_en_tetes() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/protege")
    async def protege() -> None:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/protege")
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_un_probleme_garde_ses_en_tetes_et_ne_peut_pas_changer_l_identifiant() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/limite")
    async def limite() -> None:
        raise Probleme(
            429, "trop_de_requetes", "Doucement.", headers={"Retry-After": "7", "X-Request-Id": "x"}
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/limite")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "7"
    assert r.headers["x-request-id"] == r.json()["instance"] != "x"


async def test_un_probleme_leve_dans_une_dependance_garde_son_statut() -> None:
    app = create_app(reglages("local"))

    def exige_une_session() -> None:
        raise Probleme(401, "pas_de_session", "Connecte-toi.")

    @app.get("/api/_test/session")
    async def session(_: Annotated[None, Depends(exige_une_session)]) -> dict[str, bool]:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/_test/session")
    assert r.status_code == 401
    assert r.json()["code"] == "pas_de_session"


async def test_la_500_est_journalisee_avec_l_identifiant(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret interne")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="popote_api.errors"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/_test/boom")
    enregistrements = [e for e in caplog.records if e.name == "popote_api.errors"]
    assert len(enregistrements) == 1
    assert enregistrements[0].request_id == r.json()["instance"]  # type: ignore[attr-defined]
    assert enregistrements[0].exc_info is not None
    assert "secret interne" not in r.text


async def test_un_pointeur_trop_long_remonte_au_parent_le_plus_proche() -> None:
    r = await poste("/api/_test/dictionnaire", json={"k" * 300: "x"})
    assert r.json()["errors"][0]["pointer"] == ""
    r = await poste("/api/_test/imbrique", json={"cles": {"k" * 300: "x"}})
    assert r.json()["errors"][0]["pointer"] == "/cles"


async def test_un_pointeur_de_256_caracteres_est_conserve() -> None:
    cle = "k" * 255  # "/" + 255 caractères = 256
    r = await poste("/api/_test/dictionnaire", json={cle: "x"})
    assert r.json()["errors"][0]["pointer"] == "/" + cle
