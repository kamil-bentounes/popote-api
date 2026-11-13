"""L'idempotence des `POST` de bout en bout : session, verrou, rejeu, refus, annulation (spec § 3.5).

La route d'essai est montée par le test seul, dans `/api/v1` (donc derrière la session) ; son effet est un
réglage de rappel basculé dans la transaction de la personne. Aucun objet n'est créé hors du produit : le
réglage, la ligne d'idempotence et la session partent avec la personne (la fabrique).
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from _client import application_de_test, cookie
from _fabrique import Fabrique
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from popote_api.errors import Probleme
from popote_api.infra.db import Base
from popote_api.schemas.base import Entree, Sortie
from popote_api.security.idempotence import RouteIdempotente, cherche_la_ligne
from popote_api.security.session import PersonneDeLaSession

pytestmark = pytest.mark.integration

URL = "/api/v1/essai/reglages"
CORPS = {"type": "choisir_les_repas"}
CLE = '"7f3c9a52-0b1e-4c1d-9b0a-5d2f7e8a1c34"'
# Ce qu'envoie le front dans une écriture : la garde d'origine les exige (spec § 4).
ECRITURE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}

BASCULE = (
    "insert into public.rappel_reglage (user_id, type, actif) values (auth.uid(), %s, true)"
    " on conflict (user_id, type) do update set actif = not public.rappel_reglage.actif"
)


class Reglage(Entree):
    type: str


class Cree(Sortie):
    type: str


class Essai:
    """Ce que la route d'essai fait, et ce que le test lui commande de faire."""

    def __init__(self) -> None:
        self.effets: list[str] = []
        self.avant_l_effet: Callable[[], Awaitable[None]] | None = None
        self.apres_l_effet: Callable[[], None] | None = None
        self.dependances: list[str] = []


def routeur_d_essai(essai: Essai) -> APIRouter:
    routeur = APIRouter(prefix="/essai", route_class=RouteIdempotente)

    @routeur.post("/reglages", status_code=201)
    async def cree(corps: Reglage, personne: PersonneDeLaSession, response: Response) -> Cree:
        essai.effets.append(corps.type)
        if essai.avant_l_effet is not None:
            await essai.avant_l_effet()
        await personne.curseur.execute(BASCULE, (corps.type,))
        if essai.apres_l_effet is not None:
            essai.apres_l_effet()
        response.headers["Location"] = f"/api/v1/essai/reglages/{corps.type}"
        response.headers["ETag"] = '"v1"'
        response.headers["Set-Cookie"] = "ne-se-rejoue-pas=1"
        response.headers["X-Essai"] = "ne-se-rejoue-pas"
        return Cree(type=corps.type)

    @routeur.post("/rend-une-erreur")
    async def rend_une_erreur(personne: PersonneDeLaSession) -> Response:
        await personne.curseur.execute(BASCULE, ("choisir_les_repas",))
        return JSONResponse({"detail": "x"}, status_code=400)

    @routeur.post("/gros")
    async def gros(personne: PersonneDeLaSession) -> Response:
        await personne.curseur.execute(BASCULE, ("choisir_les_repas",))
        return JSONResponse({"x": "y" * 70_000}, status_code=201)

    @routeur.post("/sans-contenu", status_code=204)
    async def sans_contenu(personne: PersonneDeLaSession) -> None:
        await personne.curseur.execute(BASCULE, ("choisir_les_repas",))

    @routeur.post("/reglages-bis", status_code=201)
    async def cree_ailleurs(corps: Reglage, personne: PersonneDeLaSession) -> Cree:
        await personne.curseur.execute(BASCULE, (corps.type,))
        return Cree(type=corps.type)

    @routeur.post("/melange", status_code=201)
    @routeur.patch("/melange", status_code=201)
    async def melange(corps: Reglage, personne: PersonneDeLaSession) -> Cree:
        await personne.curseur.execute(BASCULE, (corps.type,))
        return Cree(type=corps.type)

    @routeur.post("/chemin/{nom}", status_code=201)
    async def chemin(nom: str, personne: PersonneDeLaSession) -> dict[str, str]:
        await personne.curseur.execute(BASCULE, ("choisir_les_repas",))
        return {"nom": nom}

    def note_la_dependance() -> None:
        essai.dependances.append("dep")

    @routeur.post("/avec-dependance", status_code=201, dependencies=[Depends(note_la_dependance)])
    async def avec_dependance(personne: PersonneDeLaSession) -> dict[str, bool]:
        await personne.curseur.execute(BASCULE, ("choisir_les_repas",))
        return {"ok": True}

    @routeur.get("/lecture")
    async def lecture(request: Request) -> dict[str, bool]:
        return {"ok": True}

    return routeur


@pytest.fixture
def essai() -> Essai:
    return Essai()


@pytest.fixture
def application(base: Base, monkeypatch: pytest.MonkeyPatch, essai: Essai) -> httpx.AsyncClient:
    app = application_de_test(base, monkeypatch, routeur_d_essai(essai))
    # Une exception inattendue de la route doit finir en 500 rendu, pas remonter dans le test.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def en_tetes(fabrique: Fabrique, personne_id: UUID, cle: str | None = CLE, **autres: str) -> dict[str, str]:
    entetes = cookie(fabrique.session(personne_id)) | ECRITURE | autres
    if cle is not None:
        entetes["Idempotency-Key"] = cle
    return entetes


def reglages(fabrique: Fabrique, personne_id: UUID) -> list[tuple[str, bool]]:
    lignes = fabrique.admin.execute(
        "select type, actif from public.rappel_reglage where user_id = %s order by type", (personne_id,)
    ).fetchall()
    return [(str(t), bool(a)) for t, a in lignes]


def gardees(fabrique: Fabrique, personne_id: UUID) -> list[tuple[Any, ...]]:
    return fabrique.admin.execute(
        "select key, method, path, status, headers, body from public.idempotency_key where person_id = %s",
        (personne_id,),
    ).fetchall()


# ── L'en-tête ───────────────────────────────────────────────────────────────


async def test_sans_en_tete_le_post_est_refuse_400_et_rien_n_est_fait(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponse = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id, cle=None))
    assert reponse.status_code == 400
    assert reponse.json()["code"] == "cle_idempotence_manquante"
    assert reponse.headers["content-type"] == "application/problem+json"
    assert (essai.effets, reglages(fabrique, personne.id), gardees(fabrique, personne.id)) == ([], [], [])


@pytest.mark.parametrize("cle", ["abc", '""', '"a"; b=1', '"a", "b"', '"' + "x" * 256 + '"'])
async def test_une_cle_mal_formee_est_refusee_400_et_rien_n_est_fait(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai, cle: str
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponse = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id, cle=cle))
    assert reponse.status_code == 400
    assert reponse.json()["code"] == "cle_idempotence_invalide"
    assert (essai.effets, reglages(fabrique, personne.id), gardees(fabrique, personne.id)) == ([], [], [])


async def test_deux_lignes_d_en_tete_sont_une_liste_et_sont_refusees(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    entetes = [
        *(cookie(fabrique.session(personne.id)) | ECRITURE).items(),
        ("Idempotency-Key", '"a"'),
        ("Idempotency-Key", '"b"'),
    ]
    reponse = await application.post(URL, json=CORPS, headers=entetes)
    assert reponse.status_code == 400
    assert reponse.json()["code"] == "cle_idempotence_invalide"
    assert essai.effets == []


async def test_sans_session_c_est_401_avant_toute_idempotence(
    application: httpx.AsyncClient, essai: Essai
) -> None:
    reponse = await application.post(URL, json=CORPS, headers=ECRITURE)
    assert reponse.status_code == 401
    assert reponse.json()["code"] == "pas_de_session"
    assert essai.effets == []


async def test_un_get_sur_le_routeur_idempotent_n_exige_pas_de_cle(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponse = await application.get(
        "/api/v1/essai/lecture", headers=en_tetes(fabrique, personne.id, cle=None)
    )
    assert (reponse.status_code, reponse.json()) == (200, {"ok": True})


# ── Premier envoi, rejeu, autre contenu ─────────────────────────────────────


async def test_le_premier_envoi_fait_l_effet_rend_201_et_garde_la_reponse(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponse = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    assert (reponse.status_code, reponse.json()) == (201, {"type": "choisir_les_repas"})
    assert essai.effets == ["choisir_les_repas"]
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", True)]
    [(cle, methode, chemin, statut, entetes, corps)] = gardees(fabrique, personne.id)
    assert (cle, methode, chemin, statut) == (CLE[1:-1], "POST", URL, 201)
    assert entetes == {
        "content-type": "application/json",
        "location": "/api/v1/essai/reglages/choisir_les_repas",
        "etag": '"v1"',
    }
    assert bytes(corps) == reponse.content


async def test_le_rejeu_rend_la_meme_reponse_sans_refaire_l_effet(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    premiere = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    seconde = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    assert seconde.status_code == premiere.status_code == 201
    assert seconde.content == premiere.content
    for nom in ("content-type", "location", "etag"):
        assert seconde.headers[nom] == premiere.headers[nom]
    # La liste est fermée : ni le cookie ni l'en-tête de l'essai ne sont rejoués.
    assert "set-cookie" not in seconde.headers
    assert "x-essai" not in seconde.headers
    assert essai.effets == ["choisir_les_repas"]  # la route n'a pas été rappelée
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", True)]  # un 2e effet l'aurait basculé
    assert len(gardees(fabrique, personne.id)) == 1


async def test_le_rejeu_sans_contenu_rend_204(application: httpx.AsyncClient, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    premiere = await application.post("/api/v1/essai/sans-contenu", headers=en_tetes(fabrique, personne.id))
    seconde = await application.post("/api/v1/essai/sans-contenu", headers=en_tetes(fabrique, personne.id))
    assert (premiere.status_code, seconde.status_code, seconde.content) == (204, 204, b"")
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", True)]


@pytest.mark.parametrize(
    ("autre_corps", "autre_url"),
    [
        ({"type": "noter_les_depenses"}, URL),
        (CORPS, URL + "?x=1"),
    ],
    ids=["autre-corps", "autre-requete"],
)
async def test_la_meme_cle_avec_un_autre_contenu_est_refusee_422_sans_effet(
    application: httpx.AsyncClient,
    fabrique: Fabrique,
    essai: Essai,
    autre_corps: dict[str, str],
    autre_url: str,
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    premiere = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    seconde = await application.post(autre_url, json=autre_corps, headers=en_tetes(fabrique, personne.id))
    assert premiere.status_code == 201
    assert seconde.status_code == 422
    assert seconde.json()["code"] == "cle_idempotence_reutilisee"
    assert essai.effets == ["choisir_les_repas"]
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", True)]
    [ligne] = gardees(fabrique, personne.id)
    assert ligne[3] == 201  # la ligne d'origine est intacte


async def test_une_autre_cle_est_un_autre_envoi(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id, cle='"un"'))
    await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id, cle='"deux"'))
    assert essai.effets == ["choisir_les_repas"] * 2
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", False)]  # basculé deux fois
    assert len(gardees(fabrique, personne.id)) == 2


async def test_la_meme_cle_chez_une_autre_personne_est_independante(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    foyer = fabrique.foyer()
    a, b = fabrique.personne(foyer), fabrique.personne(foyer)
    chez_a = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, a.id))
    chez_b = await application.post(
        URL, json={"type": "noter_les_depenses"}, headers=en_tetes(fabrique, b.id)
    )
    assert (chez_a.status_code, chez_b.status_code) == (201, 201)  # ni 422 ni rejeu de la réponse de A
    assert chez_b.json() == {"type": "noter_les_depenses"}
    assert essai.effets == ["choisir_les_repas", "noter_les_depenses"]
    assert [len(gardees(fabrique, p.id)) for p in (a, b)] == [1, 1]


# ── Deux envois à la fois ───────────────────────────────────────────────────


async def test_deux_envois_simultanes_de_la_meme_cle_l_un_201_l_autre_409(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    premier_en_vol, feu_vert = asyncio.Event(), asyncio.Event()

    async def retient_le_premier() -> None:
        premier_en_vol.set()
        await feu_vert.wait()

    essai.avant_l_effet = retient_le_premier
    tete = en_tetes(fabrique, personne.id)

    premier = asyncio.create_task(application.post(URL, json=CORPS, headers=tete))
    await asyncio.wait_for(premier_en_vol.wait(), timeout=5)
    second = await application.post(URL, json=CORPS, headers=tete)
    feu_vert.set()
    premier_reponse = await premier

    assert second.status_code == 409
    assert second.json()["code"] == "requete_en_cours"
    assert premier_reponse.status_code == 201
    assert essai.effets == ["choisir_les_repas"]  # le second n'a pas touché à l'effet
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", True)]
    # Une fois le premier validé, le renvoi du second rend la réponse du premier.
    rejeu = await application.post(URL, json=CORPS, headers=tete)
    assert (rejeu.status_code, rejeu.content) == (201, premier_reponse.content)


async def test_deux_cles_differentes_en_meme_temps_ne_se_genent_pas(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponses = await asyncio.gather(
        application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id, cle='"un"')),
        application.post(
            URL, json={"type": "noter_les_depenses"}, headers=en_tetes(fabrique, personne.id, cle='"deux"')
        ),
    )
    assert [r.status_code for r in reponses] == [201, 201]


# ── Une ligne échue ne compte plus ──────────────────────────────────────────


async def test_une_ligne_echue_ne_compte_plus_l_effet_est_refait(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    fabrique.admin.execute(
        "update public.idempotency_key set created_at = now() - interval '25 hours',"
        " expires_at = now() - interval '1 hour' where person_id = %s",
        (personne.id,),
    )
    # Même clé, AUTRE contenu : une ligne vivante donnerait 422 ; l'échue cède la place.
    nouvelle = await application.post(
        URL, json={"type": "noter_les_depenses"}, headers=en_tetes(fabrique, personne.id)
    )
    assert nouvelle.status_code == 201
    assert essai.effets == ["choisir_les_repas", "noter_les_depenses"]
    [ligne] = gardees(fabrique, personne.id)
    assert bytes(ligne[5]) == nouvelle.content  # la ligne a été remplacée, pas ajoutée
    assert fabrique.admin.execute(
        "select expires_at > now() from public.idempotency_key where person_id = %s", (personne.id,)
    ).fetchone() == (True,)


# ── Une erreur annule tout ──────────────────────────────────────────────────


async def test_une_erreur_pendant_l_effet_ne_laisse_aucune_ligne_et_le_renvoi_refait_l_effet(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())

    def echoue() -> None:
        raise Probleme(409, "conflit", "Refusé après l'effet.")

    essai.apres_l_effet = echoue
    refus = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    assert refus.status_code == 409
    assert refus.json()["code"] == "conflit"
    assert (reglages(fabrique, personne.id), gardees(fabrique, personne.id)) == ([], [])

    essai.apres_l_effet = None
    reprise = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    assert reprise.status_code == 201
    assert essai.effets == ["choisir_les_repas"] * 2  # refait : l'échec n'a rien gardé
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", True)]
    assert len(gardees(fabrique, personne.id)) == 1


async def test_une_exception_inattendue_pendant_l_effet_ne_laisse_aucune_ligne(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())

    def plante() -> None:
        raise ZeroDivisionError

    essai.apres_l_effet = plante
    reponse = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    assert reponse.status_code == 500
    assert (reglages(fabrique, personne.id), gardees(fabrique, personne.id)) == ([], [])


async def test_un_corps_invalide_ne_garde_rien_et_la_cle_reste_libre(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    invalide = await application.post(URL, json={"type": 3}, headers=en_tetes(fabrique, personne.id))
    assert invalide.status_code == 422
    assert gardees(fabrique, personne.id) == []
    valide = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    assert valide.status_code == 201


@pytest.mark.parametrize("chemin", ["rend-une-erreur", "gros"])
async def test_une_reponse_qu_on_ne_peut_pas_garder_annule_aussi_l_effet(
    application: httpx.AsyncClient, fabrique: Fabrique, chemin: str
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponse = await application.post(f"/api/v1/essai/{chemin}", headers=en_tetes(fabrique, personne.id))
    assert reponse.status_code == 500
    assert (reglages(fabrique, personne.id), gardees(fabrique, personne.id)) == ([], [])


# ── Le contrat ──────────────────────────────────────────────────────────────


async def test_le_contrat_declare_l_en_tete_obligatoire_et_les_erreurs_du_post_seulement(
    application: httpx.AsyncClient,
) -> None:
    contrat = (await application.get("/api/openapi.json")).json()
    post = contrat["paths"]["/api/v1/essai/reglages"]["post"]
    en_tete = next(p for p in post["parameters"] if p["name"] == "Idempotency-Key")
    assert (en_tete["in"], en_tete["required"]) == ("header", True)
    assert {"400", "409", "422"} <= set(post["responses"])
    lecture = contrat["paths"]["/api/v1/essai/lecture"]["get"]
    assert all(p["name"] != "Idempotency-Key" for p in lecture.get("parameters", []))
    assert "409" not in lecture["responses"]


# ── Ce que la revue adverse a trouvé ────────────────────────────────────────


async def test_la_meme_cle_sur_un_autre_chemin_est_refusee_422_sans_effet(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    premiere = await application.post(URL, json=CORPS, headers=en_tetes(fabrique, personne.id))
    ailleurs = await application.post(
        "/api/v1/essai/reglages-bis", json=CORPS, headers=en_tetes(fabrique, personne.id)
    )
    assert (premiere.status_code, ailleurs.status_code) == (201, 422)
    assert ailleurs.json()["code"] == "cle_idempotence_reutilisee"
    assert reglages(fabrique, personne.id) == [("choisir_les_repas", True)]


async def test_un_patch_garde_sa_reponse_et_la_methode_fait_partie_de_l_envoi(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    chemin = "/api/v1/essai/melange"
    patch = await application.patch(chemin, json=CORPS, headers=en_tetes(fabrique, personne.id, cle='"p"'))
    rejeu = await application.patch(chemin, json=CORPS, headers=en_tetes(fabrique, personne.id, cle='"p"'))
    assert (patch.status_code, rejeu.status_code, rejeu.content) == (201, 201, patch.content)
    assert reglages(fabrique, personne.id) == [
        ("choisir_les_repas", True)
    ]  # l'effet n'a été fait qu'une fois
    autre_methode = await application.post(
        chemin, json=CORPS, headers=en_tetes(fabrique, personne.id, cle='"p"')
    )
    assert autre_methode.status_code == 422
    assert autre_methode.json()["code"] == "cle_idempotence_reutilisee"
    assert [ligne[1] for ligne in gardees(fabrique, personne.id)] == ["PATCH"]


async def test_un_chemin_avec_un_octet_nul_encode_est_traite_sans_erreur(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponse = await application.post("/api/v1/essai/chemin/a%00b", headers=en_tetes(fabrique, personne.id))
    assert reponse.status_code == 201
    [ligne] = gardees(fabrique, personne.id)
    assert ligne[2] == "/api/v1/essai/chemin/a%00b"  # le chemin brut : rien de décodé n'entre dans la table


async def test_une_dependance_de_la_route_ne_se_reveille_pas_au_rejeu(
    application: httpx.AsyncClient, fabrique: Fabrique, essai: Essai
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    for _ in range(2):
        reponse = await application.post(
            "/api/v1/essai/avec-dependance", headers=en_tetes(fabrique, personne.id)
        )
        assert reponse.status_code == 201
    assert essai.dependances == ["dep"]


async def test_une_route_qui_melange_une_methode_sure_et_un_post_est_refusee_a_la_construction() -> None:
    routeur = APIRouter(route_class=RouteIdempotente)

    async def les_deux() -> None: ...

    with pytest.raises(ValueError, match="méthodes à clé"):
        routeur.add_api_route("/mixte", les_deux, methods=["GET", "POST"])


async def test_une_ligne_qui_expire_a_l_instant_meme_ne_compte_plus(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await curseur.execute(
            "insert into public.idempotency_key (person_id, key, method, path, fingerprint, status, body,"
            " created_at, expires_at)"
            " values (auth.uid(), 'k', 'POST', '/p', %s, 201, '', now() - interval '1 day', now())",
            ("a" * 64,),
        )
        assert await cherche_la_ligne(curseur, "k") is None


# ── Les champs secrets (B14) ─────────────────────────────────────────────────


def routeur_a_secret() -> APIRouter:
    routeur = APIRouter(prefix="/secret", route_class=RouteIdempotente.avec(champs_secrets=("token",)))

    @routeur.post("/avec", status_code=201)
    async def avec(personne: PersonneDeLaSession) -> dict[str, str]:
        await personne.curseur.execute(BASCULE, ("choisir_les_repas",))
        return {"id": "x", "token": "JETON-SECRET-0123"}

    @routeur.post("/sans-le-champ", status_code=201)
    async def sans_le_champ(personne: PersonneDeLaSession) -> dict[str, str]:
        await personne.curseur.execute(BASCULE, ("choisir_les_repas",))
        return {"id": "x"}

    return routeur


async def test_un_champ_secret_est_retire_avant_stockage_et_le_rejeu_ne_l_a_pas(
    base: Base, monkeypatch: pytest.MonkeyPatch, essai: Essai, fabrique: Fabrique
) -> None:
    app = application_de_test(base, monkeypatch, routeur_d_essai(essai), routeur_a_secret())
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )
    personne = fabrique.personne(fabrique.foyer())
    premiere = await client.post("/api/v1/secret/avec", headers=en_tetes(fabrique, personne.id))
    assert premiere.status_code == 201
    assert premiere.json() == {"id": "x", "token": "JETON-SECRET-0123"}
    ((_, _, _, _, _, corps),) = gardees(fabrique, personne.id)
    assert b"JETON-SECRET" not in bytes(corps)
    assert json.loads(bytes(corps)) == {"id": "x", "token": None}
    rejeu = await client.post("/api/v1/secret/avec", headers=en_tetes(fabrique, personne.id))
    assert (rejeu.status_code, rejeu.json()) == (201, {"id": "x", "token": None})


async def test_une_route_a_champs_secrets_sans_le_champ_annule_l_effet(
    base: Base, monkeypatch: pytest.MonkeyPatch, essai: Essai, fabrique: Fabrique
) -> None:
    app = application_de_test(base, monkeypatch, routeur_d_essai(essai), routeur_a_secret())
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )
    personne = fabrique.personne(fabrique.foyer())
    reponse = await client.post("/api/v1/secret/sans-le-champ", headers=en_tetes(fabrique, personne.id))
    assert reponse.status_code == 500
    assert gardees(fabrique, personne.id) == []
    assert reglages(fabrique, personne.id) == []


async def test_les_autres_routes_gardent_leur_corps_entier(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    reponse = await application.post("/api/v1/essai/chemin/token", headers=en_tetes(fabrique, personne.id))
    ((_, _, _, _, _, corps),) = gardees(fabrique, personne.id)
    assert json.loads(bytes(corps)) == reponse.json() == {"nom": "token"}
