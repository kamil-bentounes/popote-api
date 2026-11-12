"""Requêtes conditionnelles : `ETag`, `If-Match`, `If-None-Match` (RFC 9110 § 8.8.3, § 13).

Deux gestes pour une route :
- une écriture sur une ressource versionnée (`PUT`, `PATCH`, `DELETE`) appelle `exige_if_match` ;
- une lecture qui se relit (`GET`) rend `repond_ou_304`.

À appeler une fois la ressource trouvée et la personne autorisée (un `404` ou un `403` passent avant
toute précondition, § 13.2.1) ; `etag_actuel` est l'`ETag` de la ressource à cet instant.

Choix qui complètent la RFC :
- un en-tête conditionnel mal formé rend `400` (jamais ignoré : ignorer un `If-Match` ouvrirait la mise à
  jour perdue) ; une valeur vide est une liste vide, donc aucune correspondance ;
- une précondition fausse rend toujours `412`, sans le « succès » facultatif d'une écriture déjà
  appliquée (§ 13.1.1) : deux personnes d'un foyer qui éditent ensemble doivent voir le conflit ;
- `If-Modified-Since`, `If-Unmodified-Since`, `Range` et `If-Range` sont ignorés : nos ressources n'ont
  pas de date de modification.
"""

import base64
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, assert_never

from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from popote_api.errors import Probleme

METHODES_SURES = frozenset({"GET", "HEAD"})
# § 15.4.5 : en plus de `ETag` et `Cache-Control`, un `304` reprend ces champs d'un `200`.
EN_TETES_DE_VALIDATION = frozenset({"content-location", "vary", "expires"})
OCTETS_DE_CONTENU = 16  # 128 bits du SHA-256 : assez pour qu'une collision soit hors de portée.

# `entity-tag = [ "W/" ] DQUOTE *etagc DQUOTE`, `etagc` = VCHAR sauf `"`, plus obs-text (§ 8.8.3).
# Les octets 0x80-0xFF arrivent en latin-1 : c'est ainsi que Starlette décode les en-têtes.
_ETIQUETTE = re.compile(r'(W/)?"([\x21\x23-\x7e\x80-\xff]*)"')


class ConditionMalFormee(ValueError):
    """La valeur d'un en-tête conditionnel ne suit pas la grammaire de la RFC."""


@dataclass(frozen=True, slots=True)
class Etiquette:
    """Une étiquette d'entité : sa marque `W/` et sa valeur opaque, sans les guillemets."""

    faible: bool
    opaque: str


@dataclass(frozen=True, slots=True)
class Condition:
    """Le contenu de `If-Match` ou `If-None-Match` : `*` seul, ou une liste (éventuellement vide)."""

    etoile: bool
    etiquettes: tuple[Etiquette, ...]


class Verdict(Enum):
    CONTINUER = auto()
    ECHOUEE = auto()
    NON_MODIFIEE = auto()


def etag_de_version(version: int) -> str:
    """L'`ETag` fort d'une ressource versionnée : `"v3"`."""
    if version < 0:
        raise ValueError("Une version est un entier positif ou nul.")
    return f'"v{version}"'


def etag_de_contenu(octets: bytes) -> str:
    """L'`ETag` fort d'un contenu : un SHA-256 tronqué, en base64url sans remplissage (alphabet permis)."""
    condense = hashlib.sha256(octets).digest()[:OCTETS_DE_CONTENU]
    return '"' + base64.urlsafe_b64encode(condense).decode("ascii").rstrip("=") + '"'


def _etiquette_lue(trouvee: re.Match[str]) -> Etiquette:
    return Etiquette(faible=trouvee.group(1) is not None, opaque=trouvee.group(2))


def analyse_etiquette(valeur: str) -> Etiquette:
    """Lit une seule étiquette d'entité, rien d'autre autour."""
    trouvee = _ETIQUETTE.fullmatch(valeur)
    if trouvee is None:
        raise ConditionMalFormee("Étiquette d'entité mal formée.")
    return _etiquette_lue(trouvee)


def _apres_espaces(valeur: str, position: int) -> int:
    while position < len(valeur) and valeur[position] in " \t":  # OWS
        position += 1
    return position


def _lire_element(valeur: str, position: int) -> tuple[Etiquette | None, int]:
    """Un élément à `position` : `None` pour le `*`. Rend aussi la position qui suit."""
    if valeur[position] == "*":
        return None, position + 1
    trouvee = _ETIQUETTE.match(valeur, position)
    if trouvee is None:
        raise ConditionMalFormee("Étiquette d'entité mal formée.")
    return _etiquette_lue(trouvee), trouvee.end()


def analyse_condition(valeur: str) -> Condition:
    """Lit `"*" / #entity-tag` (§ 13.1.1, § 13.1.2) ; les éléments vides d'une liste sont ignorés (§ 5.6.1.2).

    Une virgule peut se trouver dans une étiquette (`"a,b"`) : on lit étiquette par étiquette, on ne
    découpe pas sur les virgules.
    """
    elements: list[Etiquette | None] = []  # None : le `*`
    position = _apres_espaces(valeur, 0)
    while position < len(valeur):
        if valeur[position] == ",":
            position = _apres_espaces(valeur, position + 1)
            continue
        element, position = _lire_element(valeur, position)
        elements.append(element)
        position = _apres_espaces(valeur, position)
        if position < len(valeur) and valeur[position] != ",":
            raise ConditionMalFormee("Deux éléments ne sont pas séparés par une virgule.")
    if None in elements:
        if len(elements) > 1:
            raise ConditionMalFormee("`*` ne se combine avec aucune autre valeur.")
        return Condition(etoile=True, etiquettes=())
    return Condition(etoile=False, etiquettes=tuple(e for e in elements if e is not None))


def correspond_fort(a: Etiquette, b: Etiquette) -> bool:
    """Comparaison forte (§ 8.8.3.2) : aucune des deux n'est faible, valeurs opaques identiques."""
    return not a.faible and not b.faible and a.opaque == b.opaque


def correspond_faible(a: Etiquette, b: Etiquette) -> bool:
    """Comparaison faible (§ 8.8.3.2) : valeurs opaques identiques, `W/` ou non."""
    return a.opaque == b.opaque


def _lire(request: Request, nom: str) -> Condition | None:
    """La condition d'un en-tête ; `None` s'il est absent. Plusieurs lignes valent une liste (§ 5.3)."""
    lignes = request.headers.getlist(nom)
    if not lignes:
        return None
    try:
        return analyse_condition(",".join(lignes))
    except ConditionMalFormee as erreur:
        raise Probleme(400, "requete_mal_formee", f"L'en-tête {nom} n'est pas valide.") from erreur


def _evalue(request: Request, etag_actuel: str) -> Verdict:
    """Les préconditions dans l'ordre du § 13.2.2 : `If-Match` (étape 1), puis `If-None-Match` (étape 3)."""
    actuelle = analyse_etiquette(etag_actuel)  # une étiquette mal formée vient de notre code : 500
    if_match = _lire(request, "If-Match")
    if_none_match = _lire(request, "If-None-Match")
    if if_match is not None and not (
        if_match.etoile or any(correspond_fort(e, actuelle) for e in if_match.etiquettes)
    ):
        return Verdict.ECHOUEE
    if if_none_match is not None and (
        if_none_match.etoile or any(correspond_faible(e, actuelle) for e in if_none_match.etiquettes)
    ):
        return Verdict.NON_MODIFIEE if request.method in METHODES_SURES else Verdict.ECHOUEE
    return Verdict.CONTINUER


def _precondition_echouee(etag_actuel: str) -> Probleme:
    return Probleme(
        412,
        "precondition_echouee",
        "La ressource a changé depuis que vous l'avez lue : relisez-la avant de réessayer.",
        headers={"ETag": etag_actuel},
    )


def exige_if_match(request: Request, etag_actuel: str) -> None:
    """Pour `PUT`, `PATCH`, `DELETE` : `If-Match` obligatoire (`428`), comparé fortement (`412` sinon).

    `*` correspond à toute ressource existante. Un `If-None-Match` qui correspond rend aussi `412`.
    """
    if request.method in METHODES_SURES:
        raise ValueError("exige_if_match garde une écriture ; une lecture passe par repond_ou_304.")
    if not request.headers.getlist("if-match"):
        raise Probleme(
            428,
            "precondition_requise",
            "Cette modification exige l'en-tête If-Match avec la version que vous avez lue.",
        )
    if _evalue(request, etag_actuel) is not Verdict.CONTINUER:
        raise _precondition_echouee(etag_actuel)


def repond_ou_304(
    request: Request,
    etag: str,
    corps: Any,
    *,
    cache_control: str = "no-store",
    en_tetes: Mapping[str, str] | None = None,
) -> Response:
    """Rend `corps` en `200`, ou un `304` sans corps si `If-None-Match` correspond (comparaison faible).

    `corps` est du JSON déjà sérialisable. Le `200` et le `304` portent le même `ETag` et le même
    `Cache-Control` (§ 15.4.5) ; `en_tetes` ne peut porter que `Content-Location`, `Vary` et `Expires`,
    repris eux aussi sur le `304`. Un `If-Match` qui ne correspond pas rend `412` avant tout (§ 13.2.2).
    """
    intrus = {nom for nom in en_tetes or {} if nom.lower() not in EN_TETES_DE_VALIDATION}
    if intrus:
        raise ValueError(f"En-têtes non repris sur un 304 : {sorted(intrus)}")
    communs = {**(en_tetes or {}), "ETag": etag, "Cache-Control": cache_control}
    verdict = _evalue(request, etag)
    match verdict:
        case Verdict.CONTINUER:
            return JSONResponse(corps, headers=communs)
        case Verdict.NON_MODIFIEE:
            return Response(status_code=304, headers=communs)
        case Verdict.ECHOUEE:
            raise _precondition_echouee(etag)
        case _:
            assert_never(verdict)
