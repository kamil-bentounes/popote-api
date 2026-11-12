"""Les limites que subit toute requête HTTP : type, taille, délai, et `no-store` par défaut.

Ce sont des middlewares ASGI purs : ils rendent `reponse(...)` au lieu de lever (une exception de
middleware finit en 500, voir `errors`). De l'extérieur vers l'intérieur : `SansCache`, `Delai`,
`TypeJson`, `TailleMax`. Le délai enveloppe les deux autres, si bien qu'un corps qui n'en finit pas
d'arriver est borné lui aussi.
"""

import asyncio
import logging

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from popote_api.errors import reponse

journal = logging.getLogger(__name__)

TAILLE_MAX_OCTETS = 1024 * 1024  # 1 Mio ; les photos auront leur propre limite (spec § 6.1)
DELAI_SECONDES = 30.0
ATTENTE_APRES_DELAI = 10  # secondes proposées dans `Retry-After`
METHODES_AVEC_CORPS = frozenset({"POST", "PUT", "PATCH"})
TYPE_JSON = "application/json"
TYPE_MERGE_PATCH = "application/merge-patch+json"  # RFC 7396, `PATCH` seulement
# Préfixes de chemin dont le corps n'est pas du JSON. Vide ici : les photos y entreront (spec § 6.1).
PREFIXES_HORS_JSON: tuple[str, ...] = ()
LONGUEUR_MAX_DU_CHIFFRE = 18  # au-delà, la taille déclarée dépasse de toute façon 1 Mio


async def _refuse(
    scope: Scope, receive: Receive, send: Send, status: int, code: str, detail: str, headers: dict[str, str]
) -> None:
    await reponse(Request(scope), status, code, detail, headers=headers)(scope, receive, send)


class SansCache:
    """Pose `Cache-Control: no-store` sur toute réponse qui n'en porte pas (spec § 3.9).

    Une réponse de l'API est privée : un intermédiaire ne doit jamais la garder.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def envoie_sans_cache(message: Message) -> None:
            if message["type"] == "http.response.start":
                en_tetes = MutableHeaders(scope=message)
                if "cache-control" not in en_tetes:
                    en_tetes["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, envoie_sans_cache)


class Delai:
    """Au-delà de `secondes`, la requête est annulée et rend `503 delai_depasse` avec `Retry-After`."""

    def __init__(self, app: ASGIApp, secondes: float = DELAI_SECONDES) -> None:
        self.app = app
        self.secondes = secondes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        reponse_commencee = False

        async def envoie_et_note(message: Message) -> None:
            nonlocal reponse_commencee
            if message["type"] == "http.response.start":
                reponse_commencee = True
            await send(message)

        try:
            async with asyncio.timeout(self.secondes) as echeance:
                await self.app(scope, receive, envoie_et_note)
        except TimeoutError:
            if not echeance.expired():
                raise  # un délai levé par le gestionnaire lui-même n'est pas le nôtre
            if reponse_commencee:
                # Les en-têtes sont partis : on ne peut plus changer le statut. La connexion est coupée.
                journal.warning("Délai de %s s dépassé après le début de la réponse.", self.secondes)
                return
            journal.warning("Délai de %s s dépassé.", self.secondes)
            await _refuse(
                scope,
                receive,
                send,
                503,
                "delai_depasse",
                "Le traitement a pris trop de temps. Réessaie dans un instant.",
                {"Retry-After": str(ATTENTE_APRES_DELAI)},
            )


def _type_json_accepte(valeurs: list[str], methode: str) -> bool:
    """Un seul `Content-Type`, `application/json` (ou merge-patch pour `PATCH`), `charset` utf-8 toléré."""
    if len(valeurs) != 1:
        return False
    type_media, *parametres = (morceau.strip() for morceau in valeurs[0].split(";"))
    acceptes = {TYPE_JSON} | ({TYPE_MERGE_PATCH} if methode == "PATCH" else set())
    if type_media.lower() not in acceptes:
        return False
    for parametre in parametres:
        nom, _, valeur = parametre.partition("=")
        if nom.strip().lower() != "charset" or valeur.strip().strip('"').lower() != "utf-8":
            return False
    return True


class TypeJson:
    """`415` si une écriture qui porte un corps n'est pas en JSON."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._refuse(scope):
            await _refuse(
                scope,
                receive,
                send,
                415,
                "type_non_supporte",
                "Le corps doit être du JSON (application/json).",
                {},
            )
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _refuse(scope: Scope) -> bool:
        if scope["method"] not in METHODES_AVEC_CORPS or scope["path"].startswith(PREFIXES_HORS_JSON):
            return False
        en_tetes = Headers(scope=scope)
        longueur = en_tetes.get("content-length")
        a_un_corps = "transfer-encoding" in en_tetes or (longueur is not None and longueur.strip() != "0")
        return a_un_corps and not _type_json_accepte(en_tetes.getlist("content-type"), scope["method"])


def _depasse_la_taille_declaree(longueur: str) -> bool:
    chiffres = longueur.strip()
    if len(chiffres) > LONGUEUR_MAX_DU_CHIFFRE:
        return True
    return int(chiffres) > TAILLE_MAX_OCTETS


class TailleMax:
    """`413` au-delà de 1 Mio, que `Content-Length` l'annonce ou non.

    Le corps est lu ici, octet compté par octet, avant que l'application ne le voie : une application
    qui lirait le flux elle-même ne pourrait pas rendre une 413 propre (son gestionnaire d'exceptions la
    transformerait en 500). 1 Mio en mémoire au plus par requête : c'est la limite elle-même.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declaree = Headers(scope=scope).get("content-length")
        if declaree is not None:
            if not (declaree.strip().isascii() and declaree.strip().isdigit()):
                await _refuse(scope, receive, send, 400, "requete_mal_formee", "Content-Length invalide.", {})
                return
            if _depasse_la_taille_declaree(declaree):
                await self._trop_gros(scope, receive, send)
                return
        recus = await self._lit_le_corps(receive)
        if recus is None:
            await self._trop_gros(scope, receive, send)
            return
        a_rejouer = iter(recus)

        async def receive_rejoue() -> Message:
            return next(a_rejouer, None) or await receive()

        await self.app(scope, receive_rejoue, send)

    @staticmethod
    async def _lit_le_corps(receive: Receive) -> list[Message] | None:
        """Les messages reçus, ou `None` si le corps dépasse la limite."""
        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                return messages  # déconnexion : on rejoue ce qu'on a, l'application verra la coupure
            total += len(message.get("body", b""))
            if total > TAILLE_MAX_OCTETS:
                return None
            if not message.get("more_body", False):
                return messages

    @staticmethod
    async def _trop_gros(scope: Scope, receive: Receive, send: Send) -> None:
        await _refuse(
            scope,
            receive,
            send,
            413,
            "corps_trop_gros",
            "Le corps dépasse 1 Mio.",
            {"Connection": "close"},  # le reste du corps n'est pas lu : la connexion ne sert plus
        )
