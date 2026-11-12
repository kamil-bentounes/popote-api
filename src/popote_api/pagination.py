"""Pagination par curseur (§ 3.4) : paramètres, curseur opaque validé, clause SQL « après ce curseur ».

Une route de liste fait, dans l'ordre :

    position = lire_curseur(TRI, page.cursor)               # 400 si le curseur est altéré
    apres, parametres = clause_apres(TRI, position)
    lignes = SELECT ... WHERE <périmètre> AND {apres} ORDER BY {ordre(TRI)} LIMIT page.limit + 1
    return construit_page(lignes, page.limit, TRI, lambda ligne: Position(ligne.cree_le, ligne.id))

Pourquoi un curseur validé et non signé (HMAC) : le périmètre d'une liste (le foyer, la personne) vient du
`WHERE` de la route, jamais du curseur ; le curseur n'est qu'une position dans un ordre. Le forger ne peut
donc, au pire, que changer de page parmi les lignes que la personne a déjà le droit de lire. Une signature
n'ajouterait que l'intégrité de cette position, au prix d'un secret de plus à poser et à tourner dans chaque
environnement (sans lui le conteneur ne démarre pas). À la place, le décodage est complet : un curseur n'est
accepté que s'il est exactement ce que `encode_curseur` aurait écrit pour ce tri (voir `decode_curseur`).
Conséquence : le curseur est lisible par le client (base64url d'un JSON) ; n'y mettre que la clé de tri d'une
ligne qu'il a déjà reçue.
"""

import base64
import binascii
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Query
from psycopg import sql
from pydantic import BaseModel

from popote_api.errors import Probleme

LIMITE_PAR_DEFAUT = 20
LIMITE_MAX = 100
# Un texte de tri tient en 200 caractères (le modèle d'entrée de la colonne porte ce `max_length`) : au plus
# 800 octets en UTF-8, soit moins de 1 200 caractères de curseur.
TEXTE_MAX = 200
LONGUEUR_MAX_CURSEUR = 1400
VERSION_CURSEUR = 1
# Bornes du `bigint` de Postgres : une clé entière au-delà ferait échouer la requête.
ENTIER_MIN, ENTIER_MAX = -(2**63), 2**63 - 1

TypeCle = Literal["texte", "entier", "instant"]
CleDeTri = str | int | datetime

_ALPHABET_CURSEUR = re.compile(r"[A-Za-z0-9_-]+")
_NOM_SQL = re.compile(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?")
_NOM_DE_TRI = re.compile(r"[a-z][a-z0-9_.-]{0,63}")


class CurseurInvalide(ValueError):
    """Le curseur n'est pas un curseur que cette liste a pu produire."""


class Page[T](BaseModel):
    """La réponse de toute liste : `{"items": [...], "next_cursor": "…" | null}`."""

    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class Parametres:
    limit: int
    cursor: str | None


def parametres_de_page(
    limit: Annotated[
        int, Query(ge=1, le=LIMITE_MAX, description="Nombre de lignes par page (20 par défaut, 100 au plus).")
    ] = LIMITE_PAR_DEFAUT,
    cursor: Annotated[str | None, Query(description="Curseur opaque rendu par la page précédente.")] = None,
) -> Parametres:
    """Dépendance FastAPI : `limit` hors de 1 à 100 rend `422` (jamais une troncature silencieuse)."""
    return Parametres(limit=limit, cursor=cursor)


@dataclass(frozen=True, slots=True)
class Tri:
    """Un ordre de liste : une colonne de tri, puis l'identifiant pour départager les égalités.

    Tout est écrit dans le code de la route, jamais pris à la requête : `cle` et `identifiant` entrent dans le
    SQL (en identifiants SQL quotés), `nom` lie le curseur à ce tri. Les deux colonnes sont `not null`.
    """

    nom: str
    cle: str
    type_cle: TypeCle
    descendant: bool = False
    identifiant: str = "id"

    def __post_init__(self) -> None:
        if not _NOM_DE_TRI.fullmatch(self.nom):
            raise ValueError(f"Nom de tri invalide : {self.nom!r}.")
        for colonne in (self.cle, self.identifiant):
            if not _NOM_SQL.fullmatch(colonne):
                raise ValueError(f"Colonne de tri invalide : {colonne!r}.")


@dataclass(frozen=True, slots=True)
class Position:
    """Où une page s'arrête : la clé de tri et l'identifiant de sa dernière ligne."""

    cle: CleDeTri
    identifiant: UUID


def _valide_cle(type_cle: TypeCle, cle: object) -> CleDeTri:
    """Rend la clé si elle est du bon type et acceptée par Postgres ; sinon `CurseurInvalide`."""
    match type_cle:
        case "entier":
            if type(cle) is int and ENTIER_MIN <= cle <= ENTIER_MAX:
                return cle
        case "texte":
            if isinstance(cle, str) and len(cle) <= TEXTE_MAX and "\x00" not in cle and _est_utf8(cle):
                return cle
        case "instant":
            if isinstance(cle, datetime) and cle.utcoffset() is not None:
                return cle
    raise CurseurInvalide(f"Clé de tri invalide pour le type {type_cle}.")


def _est_utf8(texte: str) -> bool:
    try:
        texte.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _json_de_la_cle(cle: CleDeTri) -> str | int:
    if isinstance(cle, datetime):
        return cle.astimezone(UTC).isoformat(timespec="microseconds")
    return cle


def _cle_du_json(type_cle: TypeCle, valeur: object) -> CleDeTri:
    if type_cle == "instant":
        if not isinstance(valeur, str):
            raise CurseurInvalide("Un instant s'écrit en texte.")
        try:
            valeur = datetime.fromisoformat(valeur)
        except ValueError as erreur:
            raise CurseurInvalide("Instant illisible.") from erreur
    return _valide_cle(type_cle, valeur)


def encode_curseur(tri: Tri, position: Position) -> str:
    """Le curseur d'une position : base64url sans remplissage d'un JSON compact et canonique."""
    cle = _valide_cle(tri.type_cle, position.cle)
    charge = {"v": VERSION_CURSEUR, "t": tri.nom, "k": _json_de_la_cle(cle), "i": str(position.identifiant)}
    octets = json.dumps(charge, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(octets).decode("ascii").rstrip("=")


def decode_curseur(tri: Tri, curseur: str) -> Position:
    """La position d'un curseur ; `CurseurInvalide` pour tout ce que `encode_curseur` n'écrirait pas.

    Quatre barrières : alphabet et longueur bornés ; JSON d'un objet aux quatre seules clés `v`, `t`, `k`,
    `i` ; version, nom de tri, type de la clé et identifiant UUID vérifiés ; enfin le curseur doit se
    ré-encoder à l'identique (rejette les remplissages, espaces, clés dupliquées, `\\u` inutiles et bits de
    queue du base64 que le décodeur laisserait passer).
    """
    if len(curseur) > LONGUEUR_MAX_CURSEUR or not _ALPHABET_CURSEUR.fullmatch(curseur):
        raise CurseurInvalide("Longueur ou alphabet hors limites.")
    try:
        charge = json.loads(base64.urlsafe_b64decode(curseur + "=" * (-len(curseur) % 4)))
        position = _position_de_la_charge(tri, charge)
        recode = encode_curseur(tri, position)
    except CurseurInvalide:
        raise
    except (binascii.Error, ValueError, OverflowError) as erreur:  # JSON, UTF-8, UUID, instant hors bornes
        raise CurseurInvalide("Curseur illisible.") from erreur
    if recode != curseur:
        raise CurseurInvalide("Curseur non canonique.")
    return position


def _position_de_la_charge(tri: Tri, charge: object) -> Position:
    if not isinstance(charge, dict) or set(charge) != {"v", "t", "k", "i"}:
        raise CurseurInvalide("Contenu inattendu.")
    if type(charge["v"]) is not int or charge["v"] != VERSION_CURSEUR:
        raise CurseurInvalide("Version inconnue.")
    if charge["t"] != tri.nom:
        raise CurseurInvalide("Curseur d'une autre liste.")
    if not isinstance(charge["i"], str):
        raise CurseurInvalide("Identifiant illisible.")
    return Position(_cle_du_json(tri.type_cle, charge["k"]), UUID(charge["i"]))


def lire_curseur(tri: Tri, curseur: str | None) -> Position | None:
    """`None` sans curseur (première page) ; un curseur altéré rend `400 curseur_invalide`."""
    if curseur is None:
        return None
    try:
        return decode_curseur(tri, curseur)
    except CurseurInvalide as erreur:
        raise Probleme(
            400, "curseur_invalide", "Le curseur n'est pas valide : repartez de la première page."
        ) from erreur


def _colonne(nom: str) -> sql.Identifier:
    return sql.Identifier(*nom.split("."))


def ordre(tri: Tri) -> sql.Composable:
    """Le contenu du `ORDER BY` : la clé puis l'identifiant, dans le même sens."""
    sens = sql.SQL("desc" if tri.descendant else "asc")
    return sql.SQL("{cle} {sens}, {identifiant} {sens}").format(
        cle=_colonne(tri.cle), identifiant=_colonne(tri.identifiant), sens=sens
    )


def clause_apres(tri: Tri, position: Position | None) -> tuple[sql.Composable, tuple[Any, ...]]:
    """La condition « strictement après cette position » et ses deux paramètres.

    Pagination par clé : `(cle, id) > (%s, %s)` comparé ligne à ligne, que Postgres sert par l'index
    `(cle, id)`, au contraire d'un `offset` qui relit et jette toutes les lignes précédentes et saute ou
    répète des lignes quand la liste change entre deux pages. Sans position : `true`.
    """
    if position is None:
        return sql.SQL("true"), ()
    operateur = sql.SQL("<" if tri.descendant else ">")
    clause = sql.SQL("({cle}, {identifiant}) {operateur} (%s, %s)").format(
        cle=_colonne(tri.cle), identifiant=_colonne(tri.identifiant), operateur=operateur
    )
    return clause, (_valide_cle(tri.type_cle, position.cle), position.identifiant)


def construit_page[T](
    lignes: Sequence[T], limit: int, tri: Tri, position_de: Callable[[T], Position]
) -> Page[T]:
    """La page d'une requête qui a demandé `limit + 1` lignes : la ligne en trop dit qu'il y a une suite."""
    if limit < 1:
        raise ValueError("Une page porte au moins une ligne.")
    page = list(lignes[:limit])
    suite = len(lignes) > limit
    return Page(items=page, next_cursor=encode_curseur(tri, position_de(page[-1])) if suite else None)
