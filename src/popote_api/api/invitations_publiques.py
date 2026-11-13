"""`POST /api/v1/invitations/inspections` et `/acceptances` : lire et accepter un lien d'invitation.

Publiques (`ROUTES_PUBLIQUES`) : la personne invitée n'a pas encore de compte. Sans `Idempotency-Key` :
exemption écrite (`docs/normes-api.md`), car sans personne il n'y a pas de clé d'idempotence, et rejouer une
réponse garderait en base le cookie d'une session. Le lien voyage dans le CORPS de la requête, jamais dans
l'adresse : il n'entre dans aucun journal d'accès, aucune table d'idempotence, aucun `repr`.
"""

import logging
from typing import Final

from fastapi import APIRouter, Request, Response

from popote_api.errors import CODE_COMPTE_EXISTANT, Probleme, reponse, reponses_erreur
from popote_api.infra.fuites import Fuites
from popote_api.relais import ip_de
from popote_api.routes_publiques import ACCEPTATION, INSPECTION
from popote_api.schemas.connexion import SessionOuverte
from popote_api.schemas.invitations import (
    AcceptationDemandee,
    InspectionDemandee,
    InvitationInspectee,
)
from popote_api.security.acceptation_invitation import (
    Bloquee,
    CompteExistant,
    CompteOrphelinANettoyer,
    EtatDuLien,
    Inconnue,
    Inspectee,
    LienRefuse,
    MotDePasseRefuse,
    Refusee,
    accepte,
    inspecte,
)
from popote_api.security.connexion import Ouverte
from popote_api.security.cookie import pose_le_cookie_de_session
from popote_api.security.empreintes import PoivreAbsentError

journal = logging.getLogger(__name__)
router = APIRouter(tags=["invitations"])

INCONNUE: Final = "Ce lien d'invitation n'existe pas."
TROP_D_ESSAIS: Final = "Trop d'essais. Réessaie plus tard."
INDISPONIBLE: Final = "L'invitation est momentanément indisponible."
MOTS: Final = {
    EtatDuLien.expiree: ("invitation_expiree", "Ce lien d'invitation a expiré."),
    EtatDuLien.utilisee: ("invitation_utilisee", "Ce lien d'invitation a déjà servi."),
    EtatDuLien.revoquee: ("invitation_revoquee", "Ce lien d'invitation a été annulé."),
}
ENTETE_RETRY_AFTER: Final = {
    "headers": {"Retry-After": {"description": "Secondes à attendre.", "schema": {"type": "integer"}}}
}


def _refus_du_lien(refus: Bloquee | Inconnue | LienRefuse) -> Probleme:
    match refus:
        case Bloquee(attente_s):
            return Probleme(429, "trop_de_requetes", TROP_D_ESSAIS, headers={"Retry-After": str(attente_s)})
        case LienRefuse(etat):
            code, detail = MOTS[etat]
            return Probleme(410, code, detail)
        case _:
            return Probleme(404, "invitation_inconnue", INCONNUE)


@router.post(
    INSPECTION,
    operation_id="inspect_invitation",
    summary="Lire un lien d'invitation",
    description=(
        "Dit si le lien est valide, et le prénom de qui invite. Aucun effet, jamais d'adresse. Un jeton "
        "inconnu ou mal formé rend le même `404`. Sans `Idempotency-Key` (route publique)."
    ),
    response_model=InvitationInspectee,
    responses={
        429: {**reponses_erreur(429)[429], **ENTETE_RETRY_AFTER},
        **reponses_erreur(400, 403, 404, 410, 500, 503),
    },
)
async def inspecte_le_lien(corps: InspectionDemandee, request: Request) -> InvitationInspectee:
    app = request.app
    try:
        resultat = await inspecte(
            app.state.base, app.state.empreintes, app.state.settings, jeton=corps.token, ip=ip_de(request)
        )
    except PoivreAbsentError as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    if isinstance(resultat, Inspectee):
        return InvitationInspectee(invited_by=resultat.invited_by, expires_at=resultat.expires_at)  # type: ignore[arg-type]
    raise _refus_du_lien(resultat)


@router.post(
    ACCEPTATION,
    operation_id="accept_invitation",
    summary="Accepter une invitation",
    description=(
        "Crée le compte et la session de la personne invitée (cookie `__Host-popote_session`). Refus si "
        "l'adresse a déjà un compte (`409`, lien non consommé). Une erreur après la consommation brûle le "
        "lien, sauf la course d'adresse. Sans `Idempotency-Key` (route publique)."
    ),
    status_code=201,
    response_model=SessionOuverte,
    responses={
        201: {
            "headers": {
                "Set-Cookie": {"description": "Le cookie de session.", "schema": {"type": "string"}},
            }
        },
        429: {**reponses_erreur(429)[429], **ENTETE_RETRY_AFTER},
        **reponses_erreur(400, 403, 404, 409, 410, 422, 500, 503),
    },
)
async def accepte_le_lien(
    corps: AcceptationDemandee, request: Request, reponse_http: Response
) -> Response | SessionOuverte:
    app = request.app
    fuites: Fuites = app.state.fuites
    try:
        resultat = await accepte(
            app.state.base,
            app.state.empreintes,
            app.state.settings,
            fuites,
            app.state.auth_admin,
            jeton=corps.token,
            email=corps.email,
            mot_de_passe=corps.password,
            ip=ip_de(request),
            agent=request.headers.get("user-agent"),
            request_id=getattr(request.state, "request_id", None),
        )
    except PoivreAbsentError as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    except CompteOrphelinANettoyer as erreur:
        journal.error("compte_orphelin_a_nettoyer personne=%s", erreur.personne)
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    match resultat:
        case Ouverte(jeton, session, _):
            pose_le_cookie_de_session(reponse_http, app.state.settings, jeton)
            return SessionOuverte(id=session)
        case Refusee(erreurs):
            return reponse(
                request,
                422,
                "donnees_invalides",
                "L'adresse ou le mot de passe est refusé.",
                errors=[{"pointer": e.pointer, "message": e.message} for e in erreurs],
            )
        case MotDePasseRefuse():
            return reponse(
                request,
                422,
                "donnees_invalides",
                "Le mot de passe est refusé.",
                errors=[
                    {"pointer": "/password", "message": "Ce mot de passe est refusé : choisis-en un autre."}
                ],
            )
        case CompteExistant():
            raise Probleme(409, CODE_COMPTE_EXISTANT, "Un compte existe déjà pour cette adresse.")
        case _:
            raise _refus_du_lien(resultat)
