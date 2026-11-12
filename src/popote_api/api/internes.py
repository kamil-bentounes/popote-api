"""Les routes `/internal/*` : appelées par la base (`pg_cron`) ou l'exploitation, jamais par une personne.

Une requête n'y entre que signée (`security.signature`, spec § 3.10) : ni cookie, ni session, ni l'en-tête du
relais ne comptent. Tout refus rend `404` : on ne révèle pas que la route existe.

**Toute route interne est idempotente par construction.** La signature couvre la méthode, le chemin et le
corps, pas un usage unique : une requête interceptée peut être rejouée pendant les 300 secondes de la fenêtre,
et un appelant qui n'a pas reçu la réponse la renvoie. Une route interne ne doit donc rien changer de plus la
seconde fois (travail gardé par une clé naturelle, `upsert`, ou purge qui retrouve la même chose à purger).

Un corps JSON invalide rend aussi `404`, même signé : FastAPI le lit avant les dépendances. Un corps bien
formé mais de mauvais type rend `422` à l'appelant signé.

Le routeur porte la dépendance : une route ajoutée par `nouveau_routeur()` ne peut pas y échapper. Un test
énumère les routes de l'application sous `/internal` et échoue si l'une n'a pas la dépendance.
Elles sont hors du contrat OpenAPI (`include_in_schema=False`) : le contrat décrit l'API que le front appelle
derrière le relais, et celle-ci n'est ni publique, ni consommée par un client généré.
"""

import logging
import re

from fastapi import APIRouter, Depends, Request
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from popote_api.config import Settings
from popote_api.errors import Probleme, reponse
from popote_api.security import signature
from popote_api.security.signature import RaisonDeRefus, SignatureRefusee

journal = logging.getLogger(__name__)
_CHIFFRES = re.compile(r"[0-9]{1,18}")  # au plus 18 chiffres : `int()` d'une chaîne plus longue lève
# Les refus qui méritent un avertissement : un appelant légitime mal réglé, ou une signature qui ne vient pas
# de nous. Les autres (route sondée, en-tête absent) sont du bruit d'Internet : niveau info.
REFUS_A_SIGNALER = frozenset(
    {RaisonDeRefus.SANS_CLE, RaisonDeRefus.HORS_FENETRE, RaisonDeRefus.SIGNATURE_FAUSSE}
)


def _journalise_le_refus(raison: RaisonDeRefus) -> None:
    niveau = logging.WARNING if raison in REFUS_A_SIGNALER else logging.INFO
    journal.log(niveau, "Requête interne refusée : %s.", raison.value)


class CorpsTropGros(Exception):
    """Le corps d'une requête interne dépasse `CORPS_MAX_OCTETS` ; `CorpsBorne` le rend en 404."""


class CorpsBorne:
    """Middleware ASGI pur : sous `/internal/`, borne le corps avant que quiconque le lise.

    FastAPI lit (et analyse) le corps d'une route à paramètre de corps avant d'appeler les dépendances, et la
    signature ne se vérifie qu'après lecture du corps : sans cette borne, un inconnu sans secret ferait
    charger en mémoire un corps de la taille qu'il veut. `/internal/` est hors du relais, donc de ses limites.
    La taille déclarée trop grosse ou mal formée est refusée d'emblée ; sans `Content-Length` (chunked), les
    octets sont comptés au fil de la lecture et la requête est coupée au-delà.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(signature.PREFIXE_INTERNE):
            await self.app(scope, receive, send)
            return
        if self._declaration_refusee(scope):
            await self._refuse(scope, receive, send)
            return
        recus = 0
        reponse_commencee = False

        async def receive_borne() -> Message:
            nonlocal recus
            message = await receive()
            if message["type"] == "http.request":
                recus += len(message.get("body", b""))
                if recus > signature.CORPS_MAX_OCTETS:
                    raise CorpsTropGros
            return message

        async def send_suivi(message: Message) -> None:
            nonlocal reponse_commencee
            if message["type"] == "http.response.start":
                reponse_commencee = True
            await send(message)

        try:
            await self.app(scope, receive_borne, send_suivi)
        except CorpsTropGros:
            if reponse_commencee:
                raise
            await self._refuse(scope, receive, send)

    @staticmethod
    def _declaration_refusee(scope: Scope) -> bool:
        longueur = Headers(scope=scope).get("content-length", "0").strip()
        return not _CHIFFRES.fullmatch(longueur) or int(longueur) > signature.CORPS_MAX_OCTETS

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send) -> None:
        _journalise_le_refus(RaisonDeRefus.CORPS_TROP_GROS)
        refus = reponse(Request(scope), 404, "introuvable", "Cette adresse n'existe pas.")
        await refus(scope, receive, send)


def _refus_de_forme(request: Request) -> RaisonDeRefus | None:
    """Ce qui se voit avant de lire le corps : un refus ici ne coûte aucune lecture."""
    settings: Settings = request.app.state.settings
    if not settings.secrets_internes:
        return RaisonDeRefus.SANS_CLE
    if request.scope.get("raw_path") is None:
        return RaisonDeRefus.CHEMIN_BRUT_ABSENT
    if request.scope["query_string"]:
        return RaisonDeRefus.REQUETE_PRESENTE
    return None


async def _controle(request: Request) -> None:
    refus = _refus_de_forme(request)
    if refus is not None:
        raise SignatureRefusee(refus)
    recus = request.headers.getlist(signature.EN_TETE)
    if not recus:
        raise SignatureRefusee(RaisonDeRefus.EN_TETE_ABSENT)
    if len(recus) > 1:
        raise SignatureRefusee(RaisonDeRefus.EN_TETE_REPETE)
    en_tete = signature.lit_l_en_tete(recus[0], request.app.state.horloge())
    try:
        corps = await request.body()
    except ClientDisconnect as erreur:
        raise SignatureRefusee(RaisonDeRefus.CORPS_INCOMPLET) from erreur
    secrets = request.app.state.settings.secrets_internes
    signature.verifie(secrets, en_tete, request.method, request.scope["raw_path"], corps)


async def exige_la_signature(request: Request) -> None:
    """Dépendance du routeur interne : `404` sans signature valide, sinon marque la requête comme vérifiée."""
    try:
        await _controle(request)
    except SignatureRefusee as refus:
        _journalise_le_refus(refus.raison)
        raise Probleme(404, "introuvable", "Cette adresse n'existe pas.") from refus
    setattr(request.state, signature.ETAT_SIGNATURE_VERIFIEE, True)


def nouveau_routeur() -> APIRouter:
    """Un routeur `/internal` dont chaque route exige la signature (les tests y montent leurs routes)."""
    return APIRouter(
        prefix="/internal",
        dependencies=[Depends(exige_la_signature)],
        include_in_schema=False,
    )


# Aucune route réelle aujourd'hui : la première (purge, rappels) l'ajoutera ici, et son module à la liste
# fermée des appelants de `Base.service()` (`tests/unit/test_architecture.py`).
router = nouveau_routeur()
