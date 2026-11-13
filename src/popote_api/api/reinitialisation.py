"""`POST /api/v1/password-resets` : demander un lien de réinitialisation du mot de passe.

Publique (`ROUTES_PUBLIQUES`) : la personne a oublié son mot de passe. TOUJOURS `202` et le même corps, que
l'adresse ait un compte ou non (et que l'envoi réussisse ou non) : la réponse ne dit rien du compte, et
l'envoi se fait APRÈS la réponse. Sans `Idempotency-Key` : exemption écrite (`docs/normes-api.md`), car
sans personne il n'y a pas de clé d'idempotence, et rejouer une réponse garderait un jeton en base.
"""

import asyncio
import logging
from typing import Final

from fastapi import APIRouter, BackgroundTasks, Request
from starlette.datastructures import State

from popote_api.errors import Probleme, reponses_erreur
from popote_api.infra.mails import MessageReinitialisation, lien_de_reinitialisation
from popote_api.relais import ip_de
from popote_api.routes_publiques import REINITIALISATION
from popote_api.schemas.reinitialisation import (
    MESSAGE_DE_LA_DEMANDE,
    DemandeAcceptee,
    ReinitialisationDemandee,
)
from popote_api.security.empreintes import PoivreAbsentError
from popote_api.security.reinitialisation import Bloquee, Courrier, demande_la_reinitialisation

journal = logging.getLogger(__name__)
router = APIRouter(tags=["reinitialisation"])

TROP_D_ESSAIS: Final = "Trop de demandes. Réessaie plus tard."
INDISPONIBLE: Final = "La réinitialisation est momentanément indisponible."


async def envoie_le_courrier(app_state: State, courrier: Courrier) -> None:
    """Après la réponse : un échec se journalise (son type seul, sans adresse ni lien)."""
    reglages = app_state.settings
    origine = str(reglages.public_base_url) if reglages.public_base_url else None
    lien = lien_de_reinitialisation(origine, courrier.jeton)
    if lien is None:
        journal.error("Mail de réinitialisation non envoyé : POPOTE_PUBLIC_BASE_URL absente")
        return
    try:
        await app_state.mails.envoie_la_reinitialisation(MessageReinitialisation(courrier.adresse, lien))
    except asyncio.CancelledError:
        # Le délai de la requête englobe cette tâche : le lien est écrit, le mail n'est pas parti. On le dit.
        journal.error("Mail de réinitialisation non envoyé : annulé (délai dépassé)")
        raise
    except Exception as erreur:  # un envoi raté ne doit jamais remonter : la réponse est partie
        journal.error("Mail de réinitialisation non envoyé : %s", type(erreur).__name__)


@router.post(
    REINITIALISATION,
    operation_id="request_password_reset",
    summary="Demander un lien de réinitialisation",
    description=(
        "Répond toujours `202` avec le même corps, que l'adresse ait un compte ou non. Pour un compte actif "
        "avec foyer, un lien neuf (30 minutes, usage unique) est envoyé APRÈS la réponse et les précédents "
        "sont révoqués. 3 demandes par heure et par couple (adresse, IP), comptées même pour une adresse "
        "inconnue : `429` pour tous. Sans `Idempotency-Key` (route publique)."
    ),
    status_code=202,
    response_model=DemandeAcceptee,
    response_description="La demande est prise en compte.",
    responses={
        429: {
            **reponses_erreur(429)[429],
            "headers": {
                "Retry-After": {"description": "Secondes à attendre.", "schema": {"type": "integer"}}
            },
        },
        **reponses_erreur(400, 403, 422, 500, 503),
    },
)
async def demande_un_lien(
    corps: ReinitialisationDemandee, request: Request, taches: BackgroundTasks
) -> DemandeAcceptee:
    app = request.app
    try:
        resultat = await demande_la_reinitialisation(
            app.state.base,
            app.state.empreintes,
            app.state.settings,
            email=corps.email,
            ip=ip_de(request),
            request_id=getattr(request.state, "request_id", None),
        )
    except PoivreAbsentError as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    if isinstance(resultat, Bloquee):
        raise Probleme(
            429, "trop_de_requetes", TROP_D_ESSAIS, headers={"Retry-After": str(resultat.attente_s)}
        )
    if resultat.courrier is not None:
        taches.add_task(envoie_le_courrier, app.state, resultat.courrier)
    return DemandeAcceptee(message=MESSAGE_DE_LA_DEMANDE)
