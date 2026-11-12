"""L'idempotence des `POST` d'une personne connectée (spec § 3.5).

Brouillon IETF `draft-ietf-httpapi-idempotency-key-header-08` (dernière version au 12/11/2026). Une route qui
crée ou déclenche un effet que le client peut renvoyer se déclare sur un routeur de cette classe :

    routeur = APIRouter(prefix="/depenses", route_class=RouteIdempotente)

et ne change pas d'une ligne : le `POST` exige alors l'en-tête `Idempotency-Key`, et son effet et la réponse
gardée partagent UNE transaction, celle de la personne (`Base.session`). Les routes qui ne sont ni `POST` ni
`PATCH` d'un tel routeur restent ce qu'elles sont.

Un envoi, dans l'ordre :
  - pas d'en-tête, ou mal formé : `400 cle_idempotence_manquante` / `cle_idempotence_invalide` ;
  - un autre envoi de la même clé tient le verrou (`idempotence_verrouille`, 0135) : `409 requete_en_cours` ;
  - une ligne non échue existe : même empreinte, on rend sa réponse sans refaire l'effet ; autre empreinte,
    `422 cle_idempotence_reutilisee` ;
  - sinon la route s'exécute, puis la ligne s'écrit avant la validation de la transaction : une erreur, de la
    route ou de l'écriture, annule les deux, et un nouvel envoi refait l'effet.

Ne sont PAS concernés les `POST` sans session (connexion, acceptation d'une invitation) : ils n'ont pas de
personne à qui rattacher une clé, et leur jeton à usage unique les protège du double envoi (spec § 3.5). Les
effets longs (appel au modèle) sont des travaux asynchrones (§ 3.7) : leur `POST` de création est court, donc
idempotent ici (variante transactionnelle seulement).
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Final

from fastapi import Depends, Request, Response
from fastapi.routing import APIRoute

from popote_api.errors import Probleme, reponses_erreur
from popote_api.infra.db import Curseur
from popote_api.security.session import PersonneDeLaSession

journal = logging.getLogger(__name__)

NOM_DE_L_EN_TETE: Final = "Idempotency-Key"
LONGUEUR_MAX_DE_LA_CLE: Final = 255
METHODES_A_CLE: Final = frozenset({"POST", "PATCH"})
# Ce qui se rejoue d'une réponse, avec son statut et son corps : rien d'autre (jamais un `set-cookie`).
EN_TETES_REJOUES: Final = ("content-type", "location", "etag")
# La table borne le corps à 64 Kio : une route idempotente rend un accusé de création, pas une liste.
TAILLE_MAX_DU_CORPS: Final = 65_536
LONGUEUR_MAX_DU_CHEMIN: Final = 2048

# sf-string de la RFC 9651 § 3.3.3 : des guillemets, autour d'ASCII imprimable (%x20-7E) où seuls `"` et
# `\` ont besoin d'un échappement. Pas de paramètre (`;a=1`), pas de liste : l'en-tête est UNE chaîne.
# Classe écrite en points de code (%x20-21, %x23-5B, %x5D-7E) : disjointe de l'échappement `\\` qui suit, donc
# aucun retour arrière exponentiel ; l'en-tête est de plus borné en longueur avant la correspondance.
CHAINE_DE_CHAMP: Final = re.compile(r'"((?:[\x20\x21\x23-\x5b\x5d-\x7e]|\\["\\])*)"')
ECHAPPEMENT: Final = re.compile(r'\\(["\\])')

DETAIL_MANQUANT: Final = (
    "Ajoute l'en-tête Idempotency-Key, une chaîne entre guillemets, unique pour cet envoi."
)
DETAIL_INVALIDE: Final = (
    "Idempotency-Key doit être une seule chaîne entre guillemets (RFC 9651), "
    f"de 1 à {LONGUEUR_MAX_DE_LA_CLE} caractères ASCII imprimables."
)

REPONSES_DE_L_IDEMPOTENCE: Final = reponses_erreur(400, 409, 422)
EN_TETE_DU_CONTRAT: Final[dict[str, Any]] = {
    "name": NOM_DE_L_EN_TETE,
    "in": "header",
    "required": True,
    "description": (
        "Clé d'idempotence du `POST` : une chaîne entre guillemets (RFC 9651), ASCII imprimable, 1 à 255 "
        "caractères, unique par envoi voulu. Le même envoi rejoué rend la même réponse sans refaire "
        "l'effet ; la même clé avec un autre contenu rend `422`, pendant que le premier envoi tourne `409`."
    ),
    "schema": {"type": "string", "minLength": 3, "maxLength": 2 * LONGUEUR_MAX_DE_LA_CLE + 2},
    "example": '"depense-2026-11-12-0001"',
}


def lit_la_cle(valeurs: list[str]) -> str:
    """La clé de l'en-tête (ses lignes, déjà séparées par le serveur) ; `400` si absente ou mal formée."""
    if not valeurs:
        raise Probleme(400, "cle_idempotence_manquante", DETAIL_MANQUANT)
    # Une deuxième ligne fait une liste, et la liste n'est pas un élément simple.
    if len(valeurs) > 1 or len(valeurs[0]) > 2 * LONGUEUR_MAX_DE_LA_CLE + 2:
        raise Probleme(400, "cle_idempotence_invalide", DETAIL_INVALIDE)
    correspondance = CHAINE_DE_CHAMP.fullmatch(valeurs[0])
    if correspondance is None:
        raise Probleme(400, "cle_idempotence_invalide", DETAIL_INVALIDE)
    cle = ECHAPPEMENT.sub(r"\1", correspondance.group(1))
    if not 1 <= len(cle) <= LONGUEUR_MAX_DE_LA_CLE:
        raise Probleme(400, "cle_idempotence_invalide", DETAIL_INVALIDE)
    return cle


def empreinte_de_la_requete(methode: str, chemin: bytes, requete: bytes, corps: bytes) -> str:
    """SHA-256 (hexadécimal) de la méthode, du chemin brut, de la chaîne de requête et du corps.

    Un octet nul sépare les parties : il n'a de place ni dans un chemin ni dans une requête. La chaîne de
    requête en fait partie (le plan dit méthode, chemin, corps) : deux envois qui ne diffèrent que par elle ne
    sont pas le même envoi.
    """
    resume = hashlib.sha256()
    for partie in (methode.encode(), chemin, requete):
        resume.update(partie + b"\0")
    resume.update(corps)
    return resume.hexdigest()


@dataclass(frozen=True, slots=True)
class EnvoiAGarder:
    """Un premier envoi : ce qu'on écrira, dans la transaction de la route, une fois sa réponse connue."""

    cle: str
    empreinte: str
    methode: str
    chemin: str
    curseur: Curseur


class RejeuIdempotent(Exception):
    """Levée par la dépendance quand la réponse existe déjà ; la classe de route la rend telle quelle."""

    def __init__(self, reponse: Response) -> None:
        super().__init__("rejeu")
        self.reponse = reponse


async def cherche_la_ligne(curseur: Curseur, cle: str) -> dict[str, Any] | None:
    """La ligne non échue de cette clé pour la personne du contexte, ou `None`."""
    # La ligne échue de CETTE clé n'est plus une ligne : elle cède la place (la purge n'est pas passée).
    # La RLS borne les deux requêtes à la personne.
    await curseur.execute("delete from public.idempotency_key where key = %s and expires_at <= now()", (cle,))
    await curseur.execute(
        "select fingerprint, status, headers, body from public.idempotency_key where key = %s", (cle,)
    )
    return await curseur.fetchone()


def _reponse_gardee(ligne: dict[str, Any]) -> Response:
    en_tetes: dict[str, str] = ligne["headers"]
    return Response(content=bytes(ligne["body"]), status_code=ligne["status"], headers=en_tetes)


async def exige_la_cle(request: Request, personne: PersonneDeLaSession) -> None:
    """Dépendance de `RouteIdempotente` : la clé, le verrou, le rejeu ou le refus, sinon l'envoi à garder."""
    cle = lit_la_cle(request.headers.getlist(NOM_DE_L_EN_TETE))
    curseur = personne.curseur
    await curseur.execute("select public.idempotence_verrouille(%s) as pris", (cle,))
    verrou = await curseur.fetchone()
    if verrou is None or not verrou["pris"]:
        raise Probleme(
            409, "requete_en_cours", "Un envoi avec cette clé est en cours : réessaie dans un instant."
        )
    empreinte = empreinte_de_la_requete(
        request.method, request.scope["raw_path"], request.scope["query_string"], await request.body()
    )
    ligne = await cherche_la_ligne(curseur, cle)
    if ligne is not None:
        if ligne["fingerprint"] != empreinte:
            raise Probleme(
                422,
                "cle_idempotence_reutilisee",
                "Cette clé a déjà servi pour une autre requête : change de clé.",
            )
        raise RejeuIdempotent(_reponse_gardee(ligne))
    request.state.envoi_a_garder = EnvoiAGarder(
        cle,
        empreinte,
        request.method,
        request.scope["raw_path"].decode("ascii", "replace")[:LONGUEUR_MAX_DU_CHEMIN],
        curseur,
    )


async def garde_la_reponse(envoi: EnvoiAGarder, reponse: Response) -> None:
    """Écrit la réponse de la route dans la transaction de son effet ; une erreur ici annule aussi l'effet."""
    # Une route idempotente lève `Probleme` pour échouer : une réponse d'erreur rendue ferait valider l'effet
    # sans pouvoir le rejouer. C'est une faute de programmation, rendue bruyante, et l'effet est annulé.
    if not 200 <= reponse.status_code < 300:
        msg = f"Une route idempotente doit lever Probleme, pas rendre {reponse.status_code}."
        raise RuntimeError(msg)
    corps = getattr(reponse, "body", None)
    if not isinstance(corps, bytes) or len(corps) > TAILLE_MAX_DU_CORPS:
        msg = (
            f"La réponse d'une route idempotente tient en {TAILLE_MAX_DU_CORPS} octets, corps connu d'avance."
        )
        raise RuntimeError(msg)
    en_tetes = {nom: reponse.headers[nom] for nom in EN_TETES_REJOUES if nom in reponse.headers}
    await envoi.curseur.execute(
        "insert into public.idempotency_key"
        " (person_id, key, method, path, fingerprint, status, headers, body)"
        " values (auth.uid(), %s, %s, %s, %s, %s, %s::jsonb, %s)",
        (
            envoi.cle,
            envoi.methode,
            envoi.chemin,
            envoi.empreinte,
            reponse.status_code,
            json.dumps(en_tetes),
            corps,
        ),
    )


class RouteIdempotente(APIRoute):
    """Une route dont le `POST` (ou `PATCH`) exige `Idempotency-Key` et garde sa réponse 24 h."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **options: Any) -> None:
        methodes = {m.upper() for m in options.get("methods") or ()}
        self._a_une_cle = bool(METHODES_A_CLE & methodes)
        if self._a_une_cle and methodes - METHODES_A_CLE:
            # Le contrat et la dépendance valent pour la route entière : une méthode sûre y exigerait la clé.
            msg = (
                f"{path} : une route idempotente ne porte que des méthodes à clé ({sorted(METHODES_A_CLE)})."
            )
            raise ValueError(msg)
        if self._a_une_cle:
            # La clé d'abord : un rejeu ne doit réveiller aucune autre dépendance de la route.
            options["dependencies"] = [Depends(exige_la_cle), *(options.get("dependencies") or ())]
            options["responses"] = {**REPONSES_DE_L_IDEMPOTENCE, **(options.get("responses") or {})}
            extra = options.get("openapi_extra") or {}
            options["openapi_extra"] = {
                **extra,
                "parameters": [*extra.get("parameters", ()), EN_TETE_DU_CONTRAT],
            }
        super().__init__(path, endpoint, **options)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        gestionnaire = super().get_route_handler()
        if not self._a_une_cle:
            return gestionnaire

        async def gestionnaire_idempotent(request: Request) -> Response:
            # Les dépendances à portée de fonction (la transaction de la personne) ne se défont qu'APRÈS le
            # retour d'ici : le curseur est ouvert, et la validation viendra après l'écriture.
            try:
                reponse = await gestionnaire(request)
            except RejeuIdempotent as rejeu:
                return rejeu.reponse
            envoi: EnvoiAGarder = request.state.envoi_a_garder
            await garde_la_reponse(envoi, reponse)
            return reponse

        return gestionnaire_idempotent
