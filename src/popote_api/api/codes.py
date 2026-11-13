"""`POST /api/v1/login-codes` : demander un code de connexion par mail.

Publique (`ROUTES_PUBLIQUES`) : la personne n'a pas encore de session. TOUJOURS `202` et le même corps, que
l'adresse ait un compte ou non, que le mail parte ou non : la réponse ne dit rien du compte. Le mail part
APRÈS la réponse, pour une personne réelle seulement. Sans `Idempotency-Key` : exemption écrite, car sans
personne il n'y a pas de clé d'idempotence, et rejouer une réponse garderait un identifiant de demande.
"""

from typing import Final

from fastapi import APIRouter, BackgroundTasks, Request

from popote_api.errors import Probleme, reponses_erreur
from popote_api.relais import ip_de
from popote_api.routes_publiques import CODES_DE_CONNEXION
from popote_api.schemas.codes import MESSAGE_DE_LA_DEMANDE, CodeDemande, CodeDemandeAccepte
from popote_api.security.code_de_connexion import Bloquee, demande_le_code, envoie_le_courrier
from popote_api.security.codes import RENVOI_APRES_S, VIE_DU_CODE_S
from popote_api.security.empreintes import PoivreAbsentError

router = APIRouter(prefix=CODES_DE_CONNEXION, tags=["sessions"])

TROP_DE_DEMANDES: Final = "Trop de demandes. Réessaie plus tard."
INDISPONIBLE: Final = "La demande de code est momentanément indisponible."


@router.post(
    "",
    operation_id="request_login_code",
    summary="Demander un code de connexion",
    description=(
        "Répond toujours `202` avec le même corps, que l'adresse ait un compte ou non. Pour un compte actif, "
        "un code à six chiffres (10 minutes, 5 essais, usage unique) est envoyé APRÈS la réponse et le "
        "précédent est révoqué ; un code de moins de 60 secondes n'est pas remplacé (le même "
        "`code_request_id` revient, aucun mail ne part). 10 demandes par IP et 3 par couple (adresse, IP) "
        "par 15 minutes, 6 par adresse par heure, comptées même pour une adresse inconnue : `429` pour tous. "
        "Sans `Idempotency-Key` (route publique)."
    ),
    status_code=202,
    response_model=CodeDemandeAccepte,
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
async def demande_un_code(
    corps: CodeDemande, request: Request, taches: BackgroundTasks
) -> CodeDemandeAccepte:
    app = request.app
    try:
        resultat = await demande_le_code(
            app.state.base,
            app.state.empreintes,
            app.state.settings,
            email=corps.email,
            ip=ip_de(request),
            request_id=getattr(request.state, "request_id", None),
            maintenant=app.state.horloge(),
        )
    except PoivreAbsentError as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    if isinstance(resultat, Bloquee):
        raise Probleme(
            429, "trop_de_requetes", TROP_DE_DEMANDES, headers={"Retry-After": str(resultat.attente_s)}
        )
    if resultat.courrier is not None:
        taches.add_task(envoie_le_courrier, app.state, resultat.courrier)
    return CodeDemandeAccepte(
        code_request_id=resultat.code_request_id,
        expires_in_s=VIE_DU_CODE_S,
        resend_after_s=RENVOI_APRES_S,
        message=MESSAGE_DE_LA_DEMANDE,
    )
