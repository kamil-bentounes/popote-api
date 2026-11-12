"""Les routes `/internal/*` : appelées par la base (`pg_cron`) ou l'exploitation, jamais par une personne.

Une requête n'y entre que signée (`security.signature`, spec § 3.10) : ni cookie, ni session, ni l'en-tête du
relais ne comptent. Tout refus rend `404` : on ne révèle pas que la route existe.

**Toute route interne est idempotente par construction.** La signature couvre la méthode, le chemin et le
corps, pas un usage unique : une requête interceptée peut être rejouée pendant les 300 secondes de la fenêtre,
et un appelant qui n'a pas reçu la réponse la renvoie. Une route interne ne doit donc rien changer de plus la
seconde fois (travail gardé par une clé naturelle, `upsert`, ou purge qui retrouve la même chose à purger).

Le corps est borné (1 Mio, `limites.TailleMax`, qui lit le corps avant l'application et rend `413` au-delà)
pour toutes les routes, celles-ci comprises : la signature ne se vérifie qu'après lecture du corps.
Un corps JSON invalide rend aussi `404`, même signé : FastAPI le lit avant les dépendances. Un corps bien
formé mais de mauvais type rend `422` à l'appelant signé.

Le routeur porte la dépendance : une route ajoutée par `nouveau_routeur()` ne peut pas y échapper. Un test
énumère les routes de l'application sous `/internal` et échoue si l'une n'a pas la dépendance.
Elles sont hors du contrat OpenAPI (`include_in_schema=False`) : le contrat décrit l'API que le front appelle
derrière le relais, et celle-ci n'est ni publique, ni consommée par un client généré.
"""

import logging

from fastapi import APIRouter, Depends, Request
from starlette.requests import ClientDisconnect

from popote_api.config import Settings
from popote_api.errors import Probleme
from popote_api.security import signature
from popote_api.security.signature import RaisonDeRefus, SignatureRefusee

journal = logging.getLogger(__name__)
# Les refus qui méritent un avertissement : un appelant légitime mal réglé, ou une signature qui ne vient pas
# de nous. Les autres (route sondée, en-tête absent) sont du bruit d'Internet : niveau info.
REFUS_A_SIGNALER = frozenset(
    {RaisonDeRefus.SANS_CLE, RaisonDeRefus.HORS_FENETRE, RaisonDeRefus.SIGNATURE_FAUSSE}
)


SECONDES_ENTRE_DEUX_AVERTISSEMENTS = 60.0


def _journalise_le_refus(request: Request, raison: RaisonDeRefus) -> None:
    """Un avertissement par fenêtre et par motif : un inconnu qui martèle l'URL ne noie pas le journal."""
    if raison not in REFUS_A_SIGNALER:
        journal.info("Requête interne refusée : %s.", raison.value)
        return
    derniers: dict[RaisonDeRefus, float] = request.app.state.derniers_avertissements_internes
    maintenant = request.app.state.horloge_debit()
    depuis = maintenant - derniers.get(raison, -SECONDES_ENTRE_DEUX_AVERTISSEMENTS)
    if depuis < SECONDES_ENTRE_DEUX_AVERTISSEMENTS:
        journal.info("Requête interne refusée : %s (avertissement déjà émis).", raison.value)
        return
    derniers[raison] = maintenant
    journal.warning("Requête interne refusée : %s.", raison.value)


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
    en_tete = signature.lit_l_en_tete(recus[0], request.app.state.horloge_unix())
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
        _journalise_le_refus(request, refus.raison)
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
