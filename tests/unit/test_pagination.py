"""La pagination par curseur : paramètres, curseur validé (et jamais forgeable), clause SQL, page."""

import base64
import json
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from popote_api import errors
from popote_api.errors import Probleme
from popote_api.pagination import (
    ENTIER_MAX,
    ENTIER_MIN,
    LIMITE_MAX,
    LIMITE_PAR_DEFAUT,
    LONGUEUR_MAX_CURSEUR,
    CurseurInvalide,
    Page,
    Parametres,
    Position,
    Tri,
    clause_apres,
    construit_page,
    decode_curseur,
    encode_curseur,
    lire_curseur,
    ordre,
    parametres_de_page,
)

IDENTIFIANT = UUID("11111111-2222-3333-4444-555555555555")
PARIS_ETE = timezone(timedelta(hours=2))
TRI_TEXTE = Tri(nom="recettes.titre", cle="titre", type_cle="texte")
TRI_ENTIER = Tri(nom="mois.rang", cle="rang", type_cle="entier", descendant=True)
TRI_INSTANT = Tri(
    nom="depenses.date", cle="d.cree_le", type_cle="instant", descendant=True, identifiant="d.id"
)


def fabrique(charge: object, *, brut: bytes | None = None) -> str:
    """Un curseur forgé à la main : le JSON de `charge` (ou les octets `brut`) en base64url."""
    octets = brut if brut is not None else json.dumps(charge, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(octets).decode().rstrip("=")


def charge_valide(**modifs: object) -> dict[str, object]:
    return {"v": 1, "t": TRI_TEXTE.nom, "k": "tarte", "i": str(IDENTIFIANT)} | modifs


# --- Paramètres : limit et cursor ---------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    errors.installe(app)

    @app.get("/liste")
    async def liste(page: Annotated[Parametres, Depends(parametres_de_page)]) -> dict[str, object]:
        return {"limit": page.limit, "cursor": page.cursor}

    @app.get("/liste-curseur")
    async def liste_curseur(page: Annotated[Parametres, Depends(parametres_de_page)]) -> dict[str, bool]:
        return {"debut": lire_curseur(TRI_TEXTE, page.cursor) is None}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_sans_parametre_la_page_est_de_vingt_lignes(client: httpx.AsyncClient) -> None:
    r = await client.get("/liste")
    assert r.json() == {"limit": LIMITE_PAR_DEFAUT, "cursor": None}
    assert LIMITE_PAR_DEFAUT == 20


@pytest.mark.parametrize("limit", [1, 2, 20, 99, LIMITE_MAX])
async def test_limit_de_un_a_cent_est_acceptee(client: httpx.AsyncClient, limit: int) -> None:
    r = await client.get("/liste", params={"limit": limit})
    assert r.json()["limit"] == limit


@pytest.mark.parametrize("limit", ["0", "-1", "101", "1000", "20.5", "abc", "", "1e2", " "])
async def test_limit_hors_de_un_a_cent_rend_422_jamais_une_troncature(
    client: httpx.AsyncClient, limit: str
) -> None:
    r = await client.get("/liste", params={"limit": limit})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["errors"][0]["parameter"] == {"name": "limit", "in": "query"}


async def test_le_message_du_422_dit_le_maximum(client: httpx.AsyncClient) -> None:
    r = await client.get("/liste", params={"limit": 101})
    assert r.json()["errors"][0]["message"] == "Doit être inférieur ou égal à 100."


async def test_un_curseur_est_transmis_tel_quel(client: httpx.AsyncClient) -> None:
    r = await client.get("/liste", params={"cursor": "abc"})
    assert r.json()["cursor"] == "abc"


async def test_sans_curseur_on_est_a_la_premiere_page(client: httpx.AsyncClient) -> None:
    assert (await client.get("/liste-curseur")).json() == {"debut": True}


@pytest.mark.parametrize("curseur", ["", "abc", "!!!", fabrique({"v": 1})])
async def test_un_curseur_altere_rend_400_et_non_422(client: httpx.AsyncClient, curseur: str) -> None:
    r = await client.get("/liste-curseur", params={"cursor": curseur})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "curseur_invalide"
    assert r.json()["detail"] == "Le curseur n'est pas valide : repartez de la première page."


# --- Aller-retour du curseur ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tri", "cle"),
    [
        (TRI_TEXTE, "tarte"),
        (TRI_TEXTE, ""),
        (TRI_TEXTE, "a,b"),
        (TRI_TEXTE, "Crème brûlée « façon maison » 🍰"),
        (TRI_TEXTE, "'; drop table recettes; --"),
        (TRI_TEXTE, '"\\/\n\t'),
        (TRI_TEXTE, "é" * 200),
        (TRI_ENTIER, 0),
        (TRI_ENTIER, -1),
        (TRI_ENTIER, ENTIER_MAX),
        (TRI_ENTIER, ENTIER_MIN),
        (TRI_INSTANT, datetime(2026, 11, 12, 10, 0, tzinfo=UTC)),
        (TRI_INSTANT, datetime(2026, 11, 12, 10, 0, 0, 123456, tzinfo=UTC)),
        (TRI_INSTANT, datetime(2026, 3, 29, 3, 30, tzinfo=PARIS_ETE)),
        (TRI_INSTANT, datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-5, minutes=-30)))),
    ],
)
def test_un_curseur_se_decode_en_la_position_qui_l_a_produit(tri: Tri, cle: object) -> None:
    curseur = encode_curseur(tri, Position(cle, IDENTIFIANT))  # type: ignore[arg-type]
    position = decode_curseur(tri, curseur)
    assert position.cle == cle
    assert position.identifiant == IDENTIFIANT
    assert encode_curseur(tri, position) == curseur


def test_un_instant_revient_au_meme_instant_en_utc() -> None:
    instant = datetime(2026, 3, 29, 3, 30, tzinfo=PARIS_ETE)
    position = decode_curseur(TRI_INSTANT, encode_curseur(TRI_INSTANT, Position(instant, IDENTIFIANT)))
    assert position.cle == instant
    assert isinstance(position.cle, datetime)
    assert position.cle.utcoffset() == timedelta(0)


def test_un_curseur_n_a_que_l_alphabet_des_url_et_pas_de_remplissage() -> None:
    curseur = encode_curseur(TRI_TEXTE, Position("ÿþ?>>>", IDENTIFIANT))
    assert curseur.replace("-", "").replace("_", "").isalnum()
    assert "=" not in curseur


# --- Tout ce que le curseur ne doit pas laisser passer ---------------------------------------


def curseurs_refuses() -> list[tuple[str, str]]:
    valide = encode_curseur(TRI_TEXTE, Position("tarte", IDENTIFIANT))
    canonique = json.dumps(charge_valide(), separators=(",", ":"), sort_keys=True)
    return [
        ("vide", ""),
        ("trop long", "A" * (LONGUEUR_MAX_CURSEUR + 1)),
        ("remplissage", valide + "="),
        ("alphabet standard", valide.replace("-", "+") + "+/"),
        ("espace", valide + " "),
        ("retour a la ligne", valide + "\n"),
        ("hors base64", "!!!!"),
        ("longueur impossible", valide[:-1] if len(valide) % 4 == 1 else valide + "A"),
        ("bits de queue", valide[:-1] + ("B" if valide[-1] != "B" else "C")),
        ("pas du JSON", fabrique(None, brut=b"pas du json")),
        ("octets non UTF-8", fabrique(None, brut=b"\xff\xfe\x00")),
        ("tableau", fabrique([1, 2, 3, 4])),
        ("nombre", fabrique(12)),
        ("null", fabrique(None)),
        ("objet vide", fabrique({})),
        ("clé manquante", fabrique({"v": 1, "t": TRI_TEXTE.nom, "k": "x"})),
        ("clé en trop", fabrique(charge_valide(x=1))),
        ("autre version", fabrique(charge_valide(v=2))),
        ("version en texte", fabrique(charge_valide(v="1"))),
        ("version booléenne", fabrique(charge_valide(v=True))),
        ("version décimale", fabrique(None, brut=canonique.replace('"v":1', '"v":1.0').encode())),
        ("autre liste", fabrique(charge_valide(t="recettes.cree_le"))),
        ("tri absent", fabrique({k: v for k, v in charge_valide().items() if k != "t"})),
        ("clé numérique pour un tri texte", fabrique(charge_valide(k=5))),
        ("clé nulle", fabrique(charge_valide(k=None))),
        ("clé tableau", fabrique(charge_valide(k=["a"]))),
        ("clé avec NUL", fabrique(charge_valide(k="a\x00b"))),
        ("clé avec substitut isolé", fabrique(None, brut=canonique.replace("tarte", "\\ud800").encode())),
        ("identifiant non UUID", fabrique(charge_valide(i="pas-un-uuid"))),
        ("identifiant en majuscules", fabrique(charge_valide(i=str(IDENTIFIANT).upper()))),
        ("identifiant sans tirets", fabrique(charge_valide(i=IDENTIFIANT.hex))),
        ("identifiant entre accolades", fabrique(charge_valide(i="{" + str(IDENTIFIANT) + "}"))),
        ("identifiant entier", fabrique(charge_valide(i=IDENTIFIANT.int))),
        ("identifiant nul", fabrique(charge_valide(i=None))),
        ("JSON non canonique : espaces", fabrique(None, brut=canonique.replace(",", ", ").encode())),
        ("JSON non canonique : ordre", fabrique(charge_valide())),
        (
            "JSON non canonique : échappement inutile",
            fabrique(None, brut=canonique.replace("tarte", "t\\u0061rte").encode()),
        ),
        (
            "JSON non canonique : clé dupliquée",
            fabrique(None, brut=canonique.replace('"v":1', '"v":0,"v":1').encode()),
        ),
        ("JSON en UTF-16", fabrique(None, brut=canonique.encode("utf-16"))),
        ("charge suivie d'octets", fabrique(None, brut=canonique.encode() + b" x")),
    ]


@pytest.mark.parametrize(("nom", "curseur"), curseurs_refuses(), ids=[nom for nom, _ in curseurs_refuses()])
def test_un_curseur_altere_est_refuse(nom: str, curseur: str) -> None:
    with pytest.raises(CurseurInvalide):
        decode_curseur(TRI_TEXTE, curseur)


@pytest.mark.parametrize(
    "cle",
    [True, 1.0, "5", None, ENTIER_MAX + 1, ENTIER_MIN - 1, 2**200, float("nan")],
)
def test_un_curseur_entier_refuse_ce_qui_n_est_pas_un_entier_de_postgres(cle: object) -> None:
    brut = json.dumps(
        {"v": 1, "t": TRI_ENTIER.nom, "k": cle, "i": str(IDENTIFIANT)}, separators=(",", ":"), sort_keys=True
    )
    with pytest.raises(CurseurInvalide):
        decode_curseur(TRI_ENTIER, fabrique(None, brut=brut.encode()))


@pytest.mark.parametrize(
    "cle",
    [
        5,
        None,
        "2026-11-12T10:00:00",  # sans décalage
        "2026-11-12",
        "2026-11-12 10:00:00+00:00",
        "2026-11-12T10:00:00Z",  # valide à lire mais pas canonique : on n'écrit que +00:00 à 6 décimales
        "2026-11-12T10:00:00+01:00",
        "2026-13-12T10:00:00.000000+00:00",
        "0001-01-01T00:00:00.000000+23:59",  # hors bornes une fois ramené en UTC
        "n'importe quoi",
    ],
)
def test_un_curseur_instant_n_accepte_que_l_ecriture_canonique(cle: object) -> None:
    with pytest.raises(CurseurInvalide):
        decode_curseur(TRI_INSTANT, fabrique({"v": 1, "t": TRI_INSTANT.nom, "k": cle, "i": str(IDENTIFIANT)}))


def test_un_curseur_d_une_autre_liste_est_refuse_meme_au_bon_type() -> None:
    autre = Tri(nom="aliments.nom", cle="nom", type_cle="texte")
    curseur = encode_curseur(autre, Position("tarte", IDENTIFIANT))
    with pytest.raises(CurseurInvalide):
        decode_curseur(TRI_TEXTE, curseur)


def test_un_curseur_forge_sur_un_autre_type_de_cle_est_refuse() -> None:
    curseur = encode_curseur(TRI_ENTIER, Position(7, IDENTIFIANT))
    imposteur = Tri(nom=TRI_ENTIER.nom, cle="rang", type_cle="texte")
    with pytest.raises(CurseurInvalide):
        decode_curseur(imposteur, curseur)


def test_un_curseur_alteree_au_hasard_ne_leve_jamais_autre_chose_que_curseur_invalide() -> None:
    rng = random.Random(20261112)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=+/ !\x00é"
    valides = [
        encode_curseur(TRI_TEXTE, Position("tarte aux pommes", IDENTIFIANT)),
        encode_curseur(TRI_ENTIER, Position(42, IDENTIFIANT)),
        encode_curseur(TRI_INSTANT, Position(datetime(2026, 11, 12, tzinfo=UTC), IDENTIFIANT)),
    ]
    tris = [TRI_TEXTE, TRI_ENTIER, TRI_INSTANT]
    for _ in range(3000):
        base = rng.choice(valides)
        position = rng.randrange(len(base))
        mutation = rng.choice(["remplace", "insere", "supprime", "hasard"])
        if mutation == "remplace":
            curseur = base[:position] + rng.choice(alphabet) + base[position + 1 :]
        elif mutation == "insere":
            curseur = base[:position] + rng.choice(alphabet) + base[position:]
        elif mutation == "supprime":
            curseur = base[:position] + base[position + 1 :]
        else:
            curseur = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 200)))
        for tri in tris:
            try:
                position_lue = decode_curseur(tri, curseur)
            except CurseurInvalide:
                continue
            # Ce qui passe est exactement ce que le code aurait écrit, pour ce tri.
            assert encode_curseur(tri, position_lue) == curseur


def test_des_cles_au_hasard_font_l_aller_retour() -> None:
    rng = random.Random(7)
    for _ in range(500):
        texte = "".join(
            chr(rng.choice([rng.randrange(1, 0xD800), rng.randrange(0xE000, 0x2FFFF)]))
            for _ in range(rng.randrange(40))
        )
        identifiant = UUID(int=rng.getrandbits(128))
        position = decode_curseur(TRI_TEXTE, encode_curseur(TRI_TEXTE, Position(texte, identifiant)))
        assert position == Position(texte, identifiant)
        entier = rng.randrange(ENTIER_MIN, ENTIER_MAX + 1)
        assert (
            decode_curseur(TRI_ENTIER, encode_curseur(TRI_ENTIER, Position(entier, identifiant))).cle
            == entier
        )


@pytest.mark.parametrize(
    ("tri", "cle"),
    [
        (TRI_ENTIER, True),
        (TRI_ENTIER, ENTIER_MAX + 1),
        (TRI_TEXTE, "a\x00"),
        (TRI_TEXTE, "\ud800"),
        (TRI_TEXTE, 5),
        (TRI_TEXTE, "a" * 201),
        (TRI_INSTANT, datetime(2026, 1, 1)),
    ],
)
def test_encoder_une_cle_que_postgres_refuserait_est_une_erreur_de_programmation(
    tri: Tri, cle: object
) -> None:
    with pytest.raises(CurseurInvalide):
        encode_curseur(tri, Position(cle, IDENTIFIANT))  # type: ignore[arg-type]


# --- lire_curseur ---------------------------------------------------------------------------------------


def test_lire_curseur_sans_curseur_rend_none() -> None:
    assert lire_curseur(TRI_TEXTE, None) is None


def test_lire_curseur_decode_un_curseur_valide() -> None:
    position = Position("tarte", IDENTIFIANT)
    assert lire_curseur(TRI_TEXTE, encode_curseur(TRI_TEXTE, position)) == position


def test_lire_curseur_altere_leve_un_probleme_400_qui_garde_sa_cause() -> None:
    with pytest.raises(Probleme) as erreur:
        lire_curseur(TRI_TEXTE, "n'importe quoi")
    assert (erreur.value.status, erreur.value.code) == (400, "curseur_invalide")
    assert isinstance(erreur.value.__cause__, CurseurInvalide)


# --- La clause « après ce curseur » ---------------------------------------------------------


def test_sans_position_la_clause_ne_filtre_rien() -> None:
    clause, parametres = clause_apres(TRI_TEXTE, None)
    assert clause.as_string() == "true"
    assert parametres == ()


@pytest.mark.parametrize(
    ("tri", "attendu"),
    [
        (TRI_TEXTE, '("titre", "id") > (%s, %s)'),
        (TRI_ENTIER, '("rang", "id") < (%s, %s)'),
        (TRI_INSTANT, '("d"."cree_le", "d"."id") < (%s, %s)'),
    ],
)
def test_la_clause_compare_la_paire_cle_identifiant_dans_le_sens_du_tri(tri: Tri, attendu: str) -> None:
    cle: object = {"texte": "x", "entier": 3, "instant": datetime(2026, 1, 1, tzinfo=UTC)}[tri.type_cle]
    clause, parametres = clause_apres(tri, Position(cle, IDENTIFIANT))  # type: ignore[arg-type]
    assert clause.as_string() == attendu
    assert parametres == (cle, IDENTIFIANT)


def test_la_valeur_du_curseur_ne_passe_jamais_dans_le_texte_du_sql() -> None:
    piege = "x'); drop table recettes; --"
    clause, parametres = clause_apres(TRI_TEXTE, Position(piege, IDENTIFIANT))
    assert piege not in clause.as_string()
    assert parametres[0] == piege


@pytest.mark.parametrize(
    ("tri", "attendu"),
    [
        (TRI_TEXTE, '"titre" asc, "id" asc'),
        (TRI_ENTIER, '"rang" desc, "id" desc'),
        (TRI_INSTANT, '"d"."cree_le" desc, "d"."id" desc'),
    ],
)
def test_l_ordre_departage_les_egalites_par_l_identifiant_dans_le_meme_sens(tri: Tri, attendu: str) -> None:
    assert ordre(tri).as_string() == attendu


@pytest.mark.parametrize(
    "colonne", ["", "Titre", "titre; drop table x", "a.b.c", "1col", "col ", '"col"', "a-b", "é"]
)
def test_un_tri_refuse_une_colonne_qui_n_est_pas_un_identifiant_simple(colonne: str) -> None:
    with pytest.raises(ValueError, match="Colonne de tri invalide"):
        Tri(nom="x", cle=colonne, type_cle="texte")
    with pytest.raises(ValueError, match="Colonne de tri invalide"):
        Tri(nom="x", cle="titre", type_cle="texte", identifiant=colonne)


@pytest.mark.parametrize("nom", ["", "Majuscule", "avec espace", "a" * 65, "9début", "a;b"])
def test_un_tri_refuse_un_nom_hors_format(nom: str) -> None:
    with pytest.raises(ValueError, match="Nom de tri invalide"):
        Tri(nom=nom, cle="titre", type_cle="texte")


# --- La page -----------------------------------------------------------------------------------------------


class Recette(BaseModel):
    id: UUID
    titre: str


def recettes(n: int) -> list[Recette]:
    return [Recette(id=uuid4(), titre=f"recette {i}") for i in range(n)]


def position_de(recette: Recette) -> Position:
    return Position(recette.titre, recette.id)


@pytest.mark.parametrize("n", [0, 1, 2, 3])
def test_moins_de_lignes_que_la_limite_ou_autant_n_a_pas_de_suite(n: int) -> None:
    page = construit_page(recettes(n), 3, TRI_TEXTE, position_de)
    assert len(page.items) == n
    assert page.next_cursor is None


def test_une_ligne_de_plus_que_la_limite_donne_un_curseur_sur_la_derniere_ligne_gardee() -> None:
    lignes = recettes(4)
    page = construit_page(lignes, 3, TRI_TEXTE, position_de)
    assert page.items == lignes[:3]
    assert page.next_cursor is not None
    assert decode_curseur(TRI_TEXTE, page.next_cursor) == position_de(lignes[2])


@pytest.mark.parametrize("limit", [0, -1])
def test_une_page_d_au_moins_une_ligne(limit: int) -> None:
    with pytest.raises(ValueError, match="au moins une ligne"):
        construit_page(recettes(2), limit, TRI_TEXTE, position_de)


def test_la_page_se_serialise_avec_les_deux_champs_meme_sans_suite() -> None:
    assert (
        construit_page([], 3, TRI_TEXTE, position_de).model_dump_json() == '{"items":[],"next_cursor":null}'
    )


async def test_la_page_generique_type_le_contrat_et_la_reponse() -> None:
    app = FastAPI()
    lignes = recettes(3)

    @app.get("/recettes", response_model=Page[Recette])
    async def liste() -> Page[Recette]:
        return construit_page(lignes, 2, TRI_TEXTE, position_de)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        corps = (await c.get("/recettes")).json()
    assert set(corps) == {"items", "next_cursor"}
    assert [i["titre"] for i in corps["items"]] == ["recette 0", "recette 1"]
    assert isinstance(corps["next_cursor"], str)
    schema = app.openapi()["components"]["schemas"]["Page_Recette_"]
    assert sorted(schema["required"]) == ["items", "next_cursor"]
    assert schema["properties"]["items"]["items"] == {"$ref": "#/components/schemas/Recette"}
    assert {"type": "null"} in schema["properties"]["next_cursor"]["anyOf"]
