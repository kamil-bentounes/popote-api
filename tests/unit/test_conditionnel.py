"""Les requêtes conditionnelles, de bout en bout par un routeur de test, et la grammaire des étiquettes."""

import base64
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from popote_api import errors
from popote_api.conditionnel import (
    Condition,
    ConditionMalFormee,
    Etiquette,
    analyse_condition,
    analyse_etiquette,
    correspond_faible,
    correspond_fort,
    etag_de_contenu,
    etag_de_version,
    exige_if_match,
    repond_ou_304,
)

ETAG = '"v3"'
CORPS = {"nom": "tarte", "version": 3}


def fort(opaque: str) -> Etiquette:
    return Etiquette(faible=False, opaque=opaque)


def faible(opaque: str) -> Etiquette:
    return Etiquette(faible=True, opaque=opaque)


# --- Fabrication des ETag ---------------------------------------------------------------------------


@pytest.mark.parametrize(("version", "attendu"), [(0, '"v0"'), (3, '"v3"'), (12345, '"v12345"')])
def test_etag_de_version_est_fort_et_entre_guillemets(version: int, attendu: str) -> None:
    assert etag_de_version(version) == attendu
    assert not analyse_etiquette(attendu).faible


def test_etag_de_version_refuse_une_version_negative() -> None:
    with pytest.raises(ValueError, match="positif ou nul"):
        etag_de_version(-1)


def test_etag_de_contenu_est_un_sha256_tronque_en_base64url() -> None:
    etag = etag_de_contenu(b"bonjour")
    attendu = base64.urlsafe_b64encode(hashlib.sha256(b"bonjour").digest()[:16]).decode().rstrip("=")
    assert etag == f'"{attendu}"'
    assert not analyse_etiquette(etag).faible
    assert "=" not in etag
    assert len(attendu) == 22


def test_etag_de_contenu_change_avec_un_octet_et_pas_sans() -> None:
    assert etag_de_contenu(b"a") == etag_de_contenu(b"a")
    assert etag_de_contenu(b"a") != etag_de_contenu(b"b")
    assert etag_de_contenu(b"") != etag_de_contenu(b"\x00")


# --- Grammaire d'une étiquette -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        ('"xyzzy"', fort("xyzzy")),
        ('W/"xyzzy"', faible("xyzzy")),
        ('""', fort("")),
        ('W/""', faible("")),
        ('"a,b"', fort("a,b")),
        ('"é"', fort("é")),  # obs-text : octet 0xE9 décodé en latin-1
    ],
)
def test_analyse_etiquette_accepte_les_formes_de_la_rfc(valeur: str, attendu: Etiquette) -> None:
    assert analyse_etiquette(valeur) == attendu


@pytest.mark.parametrize(
    "valeur",
    [
        "",
        "xyzzy",
        '"xyzzy',
        'xyzzy"',
        '"a"b"',
        '"a b"',  # l'espace n'est pas un etagc
        'w/"a"',
        'W/ "a"',
        'W "a"',
        '"a" ',
        ' "a"',
        '"a"x',
        "*",
        '"\x7f"',
        '"\x01"',
    ],
)
def test_analyse_etiquette_refuse_une_forme_hors_grammaire(valeur: str) -> None:
    with pytest.raises(ConditionMalFormee):
        analyse_etiquette(valeur)


# --- Grammaire d'une liste ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        ("*", Condition(True, ())),
        (" * ", Condition(True, ())),
        ('"a"', Condition(False, (fort("a"),))),
        ('"a", "b","c"', Condition(False, (fort("a"), fort("b"), fort("c")))),
        ('W/"a", "b"', Condition(False, (faible("a"), fort("b")))),
        ('"a,b", "c"', Condition(False, (fort("a,b"), fort("c")))),  # une virgule dans une étiquette
        ('"a"\t,\t"b"', Condition(False, (fort("a"), fort("b")))),
        (',,"a",, ,"b",', Condition(False, (fort("a"), fort("b")))),  # éléments vides ignorés
        ("", Condition(False, ())),
        (" ,  , ", Condition(False, ())),
        ('"a""b"', None),  # deux étiquettes collées
        ('"a" "b"', None),  # séparées par un espace, pas une virgule
        ('"a";"b"', None),
        ('"a", b', None),  # sans guillemets
        ('"a", "b', None),  # guillemet non fermé
        ('*, "a"', None),  # `*` mêlé à une étiquette
        ('"a", *', None),
        ("*, *", None),
        ("**", None),
        ('*"a"', None),
        ("* x", None),
        ('W/"a" W/"b"', None),
    ],
)
def test_analyse_condition(valeur: str, attendu: Condition | None) -> None:
    if attendu is None:
        with pytest.raises(ConditionMalFormee):
            analyse_condition(valeur)
    else:
        assert analyse_condition(valeur) == attendu


def test_analyse_condition_d_une_grande_valeur_reste_lineaire() -> None:
    valeur = ",".join(['"a"'] * 5000) + "," + '"' + "b" * 20000  # guillemet non fermé à la fin
    with pytest.raises(ConditionMalFormee):
        analyse_condition(valeur)


# --- Comparaisons (RFC 9110 § 8.8.3.2, tableau 3) -------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "fort_attendu", "faible_attendu"),
    [
        (faible("1"), faible("1"), False, True),
        (faible("1"), faible("2"), False, False),
        (faible("1"), fort("1"), False, True),
        (fort("1"), faible("1"), False, True),
        (fort("1"), fort("1"), True, True),
        (fort("1"), fort("2"), False, False),
        (fort("a"), fort("A"), False, False),  # caractère par caractère, sensible à la casse
    ],
)
def test_comparaisons_forte_et_faible(
    a: Etiquette, b: Etiquette, fort_attendu: bool, faible_attendu: bool
) -> None:
    assert correspond_fort(a, b) is fort_attendu
    assert correspond_faible(a, b) is faible_attendu


# --- Le routeur de test -------------------------------------------------------------------------------


@dataclass
class Etat:
    """Ce que le routeur de test lit (l'`ETag` actuel) et écrit (les écritures acceptées)."""

    etag: str = ETAG
    ecritures: list[str] = field(default_factory=list)


@pytest.fixture
def etat() -> Etat:
    return Etat()


@pytest.fixture
async def client(etat: Etat) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    errors.installe(app)

    @app.api_route("/lecture", methods=["GET", "HEAD", "POST"])
    async def lecture(request: Request) -> Response:
        return repond_ou_304(request, etat.etag, CORPS)

    @app.get("/referentiel")
    async def referentiel(request: Request) -> Response:
        return repond_ou_304(
            request,
            etat.etag,
            CORPS,
            cache_control="private, max-age=60",
            en_tetes={"Vary": "Accept-Language", "Content-Location": "/referentiel/3"},
        )

    @app.api_route("/ecriture", methods=["PUT", "PATCH", "DELETE", "POST"])
    async def ecriture(request: Request) -> dict[str, bool]:
        exige_if_match(request, etat.etag)
        etat.ecritures.append(request.method)
        return {"ok": True}

    @app.get("/mauvaise-garde")
    async def mauvaise_garde(request: Request) -> dict[str, bool]:
        exige_if_match(request, etat.etag)
        return {"ok": True}

    @app.get("/etag-casse")
    async def etag_casse(request: Request) -> Response:
        return repond_ou_304(request, "pas-un-etag", CORPS)

    @app.get("/en-tete-interdit")
    async def en_tete_interdit(request: Request) -> Response:
        return repond_ou_304(request, ETAG, CORPS, en_tetes={"Content-Type": "text/plain"})

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def verifie_probleme(r: httpx.Response, statut: int, code: str) -> None:
    assert r.status_code == statut
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == code


# --- exige_if_match : absent, faux, vrai ----------------------------------------------------------------


@pytest.mark.parametrize("methode", ["PUT", "PATCH", "DELETE"])
async def test_exige_if_match_sans_en_tete_rend_428_et_n_ecrit_rien(
    client: httpx.AsyncClient, methode: str, etat: Etat
) -> None:
    r = await client.request(methode, "/ecriture")
    verifie_probleme(r, 428, "precondition_requise")
    assert etat.ecritures == []


@pytest.mark.parametrize("methode", ["PUT", "PATCH", "DELETE"])
async def test_exige_if_match_correspondant_laisse_passer(
    client: httpx.AsyncClient, methode: str, etat: Etat
) -> None:
    r = await client.request(methode, "/ecriture", headers={"If-Match": ETAG})
    assert r.status_code == 200
    assert etat.ecritures == [methode]


@pytest.mark.parametrize(
    "en_tete",
    ['"v2"', '"V3"', '""', '"v1", "v2"'],
)
async def test_exige_if_match_perime_rend_412_avec_l_etag_actuel(
    client: httpx.AsyncClient, en_tete: str, etat: Etat
) -> None:
    r = await client.put("/ecriture", headers={"If-Match": en_tete})
    verifie_probleme(r, 412, "precondition_echouee")
    assert r.headers["etag"] == ETAG
    assert r.headers["cache-control"] == "no-store"
    assert etat.ecritures == []


async def test_exige_if_match_refuse_une_etiquette_faible_meme_identique(client: httpx.AsyncClient) -> None:
    r = await client.put("/ecriture", headers={"If-Match": f"W/{ETAG}"})
    verifie_probleme(r, 412, "precondition_echouee")
    assert r.headers["etag"] == ETAG


async def test_exige_if_match_refuse_quand_l_etag_actuel_est_lui_meme_faible(
    client: httpx.AsyncClient, etat: Etat
) -> None:
    etat.etag = 'W/"v3"'
    r = await client.put("/ecriture", headers={"If-Match": '"v3"'})
    verifie_probleme(r, 412, "precondition_echouee")
    assert r.headers["etag"] == 'W/"v3"'


@pytest.mark.parametrize(
    "en_tete", ['"v1", "v3"', '"v3", "v1"', ' "v1" ,  "v3" ', '"v1",,"v3"', '"a,b","v3"']
)
async def test_exige_if_match_en_liste_passe_si_un_membre_correspond(
    client: httpx.AsyncClient, en_tete: str
) -> None:
    r = await client.put("/ecriture", headers={"If-Match": en_tete})
    assert r.status_code == 200


async def test_exige_if_match_etoile_correspond_a_toute_ressource_existante(
    client: httpx.AsyncClient,
) -> None:
    r = await client.put("/ecriture", headers={"If-Match": "*"})
    assert r.status_code == 200


async def test_exige_if_match_assemble_les_lignes_repetees(client: httpx.AsyncClient) -> None:
    r = await client.put("/ecriture", headers=[("If-Match", '"v1"'), ("If-Match", '"v3"')])  # type: ignore[arg-type]
    assert r.status_code == 200


async def test_exige_if_match_vide_est_une_liste_vide_donc_412(client: httpx.AsyncClient) -> None:
    r = await client.put("/ecriture", headers={"If-Match": ""})
    verifie_probleme(r, 412, "precondition_echouee")


@pytest.mark.parametrize("en_tete", ["v3", '"v3', 'w/"v3"', '*, "v3"', '"v3", *', "*, *", '"v3" "v1"'])
async def test_exige_if_match_mal_forme_rend_400_et_n_ecrit_rien(
    client: httpx.AsyncClient, en_tete: str, etat: Etat
) -> None:
    r = await client.put("/ecriture", headers={"If-Match": en_tete})
    verifie_probleme(r, 400, "requete_mal_formee")
    assert "If-Match" in r.json()["detail"]
    assert etat.ecritures == []


async def test_exige_if_match_ignore_les_dates_et_exige_quand_meme_if_match(
    client: httpx.AsyncClient,
) -> None:
    r = await client.put("/ecriture", headers={"If-Unmodified-Since": "Sat, 29 Oct 1994 19:43:31 GMT"})
    verifie_probleme(r, 428, "precondition_requise")


# --- Ordre d'évaluation (§ 13.2.2) ------------------------------------------------------------------------


async def test_if_none_match_correspondant_sur_une_ecriture_rend_412(
    client: httpx.AsyncClient, etat: Etat
) -> None:
    r = await client.put("/ecriture", headers={"If-Match": ETAG, "If-None-Match": ETAG})
    verifie_probleme(r, 412, "precondition_echouee")
    assert r.headers["etag"] == ETAG
    assert etat.ecritures == []


async def test_if_none_match_sans_correspondance_sur_une_ecriture_laisse_passer(
    client: httpx.AsyncClient,
) -> None:
    r = await client.put("/ecriture", headers={"If-Match": ETAG, "If-None-Match": '"v9"'})
    assert r.status_code == 200


async def test_if_match_faux_l_emporte_sur_if_none_match_qui_donnerait_un_304(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/lecture", headers={"If-Match": '"v1"', "If-None-Match": ETAG})
    verifie_probleme(r, 412, "precondition_echouee")


async def test_if_match_vrai_puis_if_none_match_correspondant_rend_304(client: httpx.AsyncClient) -> None:
    r = await client.get("/lecture", headers={"If-Match": ETAG, "If-None-Match": ETAG})
    assert r.status_code == 304


async def test_un_en_tete_mal_forme_rend_400_meme_si_l_autre_est_faux(client: httpx.AsyncClient) -> None:
    r = await client.get("/lecture", headers={"If-Match": '"v1"', "If-None-Match": "n'importe quoi"})
    verifie_probleme(r, 400, "requete_mal_formee")
    assert "If-None-Match" in r.json()["detail"]


async def test_les_dates_sont_ignorees_en_lecture(client: httpx.AsyncClient) -> None:
    r = await client.get("/lecture", headers={"If-Modified-Since": "Sat, 29 Oct 1994 19:43:31 GMT"})
    assert r.status_code == 200


# --- repond_ou_304 --------------------------------------------------------------------------------------


async def test_lecture_sans_condition_rend_200_avec_etag_et_no_store(client: httpx.AsyncClient) -> None:
    r = await client.get("/lecture")
    assert r.status_code == 200
    assert r.json() == CORPS
    assert r.headers["etag"] == ETAG
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "en_tete",
    [ETAG, f"W/{ETAG}", '"v1", "v3"', 'W/"v1", W/"v3"', "*", ' "v3" ', '"v1",,"v3"'],
)
async def test_lecture_avec_if_none_match_correspondant_rend_304_sans_corps(
    client: httpx.AsyncClient, en_tete: str
) -> None:
    r = await client.get("/lecture", headers={"If-None-Match": en_tete})
    assert r.status_code == 304
    assert r.content == b""
    assert r.headers["etag"] == ETAG
    assert r.headers["cache-control"] == "no-store"
    assert "content-length" not in r.headers
    assert "content-type" not in r.headers


@pytest.mark.parametrize("en_tete", ['"v2"', 'W/"v2"', '"V3"', '"v1", "v2"', "", " , "])
async def test_lecture_avec_if_none_match_sans_correspondance_rend_200(
    client: httpx.AsyncClient, en_tete: str
) -> None:
    r = await client.get("/lecture", headers={"If-None-Match": en_tete})
    assert r.status_code == 200
    assert r.json() == CORPS
    assert r.headers["etag"] == ETAG


async def test_lecture_etag_actuel_faible_correspond_en_comparaison_faible(
    client: httpx.AsyncClient, etat: Etat
) -> None:
    etat.etag = 'W/"v3"'
    r = await client.get("/lecture", headers={"If-None-Match": '"v3"'})
    assert r.status_code == 304
    assert r.headers["etag"] == 'W/"v3"'


@pytest.mark.parametrize("en_tete", ["v3", '"v3', '"v3" "v1"', '*, "v3"', 'w/"v3"'])
async def test_lecture_avec_if_none_match_mal_forme_rend_400(client: httpx.AsyncClient, en_tete: str) -> None:
    r = await client.get("/lecture", headers={"If-None-Match": en_tete})
    verifie_probleme(r, 400, "requete_mal_formee")
    assert "If-None-Match" in r.json()["detail"]


async def test_head_avec_if_none_match_correspondant_rend_304(client: httpx.AsyncClient) -> None:
    r = await client.head("/lecture", headers={"If-None-Match": ETAG})
    assert r.status_code == 304
    assert r.headers["etag"] == ETAG


async def test_if_none_match_correspondant_sur_une_methode_non_sure_rend_412_pas_304(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post("/lecture", headers={"If-None-Match": ETAG})
    verifie_probleme(r, 412, "precondition_echouee")
    assert r.headers["etag"] == ETAG


async def test_le_304_reprend_cache_control_et_les_champs_de_validation_du_200(
    client: httpx.AsyncClient,
) -> None:
    r200 = await client.get("/referentiel")
    r304 = await client.get("/referentiel", headers={"If-None-Match": ETAG})
    assert r304.status_code == 304
    for nom in ("etag", "cache-control", "vary", "content-location"):
        assert r304.headers[nom] == r200.headers[nom]
    assert r304.headers["cache-control"] == "private, max-age=60"
    assert r304.content == b""


async def test_une_ecriture_porteuse_de_if_none_match_etoile_est_refusee_en_412(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post("/ecriture", headers={"If-Match": "*", "If-None-Match": "*"})
    verifie_probleme(r, 412, "precondition_echouee")


# --- Mésusage : une erreur de code, jamais une réponse de l'API ------------------------------------------


async def test_exige_if_match_sur_une_lecture_est_une_erreur_de_programmation(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/mauvaise-garde", headers={"If-Match": ETAG})
    verifie_probleme(r, 500, "erreur_interne")


async def test_un_etag_actuel_mal_forme_est_une_erreur_de_programmation(client: httpx.AsyncClient) -> None:
    r = await client.get("/etag-casse")
    verifie_probleme(r, 500, "erreur_interne")


async def test_repond_ou_304_refuse_un_en_tete_que_le_304_ne_reprendrait_pas(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/en-tete-interdit")
    verifie_probleme(r, 500, "erreur_interne")
