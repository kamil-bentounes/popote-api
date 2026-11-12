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

from popote_api.config import Settings
from popote_api.errors import Probleme
from popote_api.security import signature
from popote_api.security.signature import RaisonDeRefus, SignatureRefusee

journal = logging.getLogger(__name__)
_CHIFFRES = re.compile(r"[0-9]{1,18}")


def _refus_de_forme(request: Request) -> RaisonDeRefus | None:
    """Ce qui se voit avant de lire le corps : un refus ici ne coûte aucune lecture."""
    settings: Settings = request.app.state.settings
    if not settings.secrets_internes:
        return RaisonDeRefus.SANS_CLE
    if request.scope.get("raw_path") is None:
        return RaisonDeRefus.CHEMIN_BRUT_ABSENT
    if request.scope["query_string"]:
        return RaisonDeRefus.REQUETE_PRESENTE
    longueur = request.headers.get("content-length", "0").strip()
    # Au plus 18 chiffres : `int()` d'une chaîne plus longue lève. Un corps sans `Content-Length` (chunked)
    # est borné par la limite de taille de toute requête, pas ici.
    if not _CHIFFRES.fullmatch(longueur) or int(longueur) > signature.CORPS_MAX_OCTETS:
        return RaisonDeRefus.CORPS_TROP_GROS
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
    corps = await request.body()
    secrets = request.app.state.settings.secrets_internes
    signature.verifie(secrets, en_tete, request.method, request.scope["raw_path"], corps)


async def exige_la_signature(request: Request) -> None:
    """Dépendance du routeur interne : `404` sans signature valide, sinon marque la requête comme vérifiée."""
    try:
        await _controle(request)
    except SignatureRefusee as refus:
        journal.warning("Requête interne refusée : %s.", refus.raison.value)
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
