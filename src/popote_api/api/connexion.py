"""`POST /api/v1/sessions` : la connexion. Publique ; le jeton ne sort que dans le cookie."""

from typing import Final

from fastapi import APIRouter, Request, Response

from popote_api.errors import Probleme, reponses_erreur
from popote_api.relais import ip_de
from popote_api.routes_publiques import CONNEXION
from popote_api.schemas.connexion import Connexion, SessionOuverte
from popote_api.security.connexion import Bloquee, Ouverte, tente_la_connexion
from popote_api.security.cookie import pose_le_cookie_de_session
from popote_api.security.empreintes import PoivreAbsentError

router = APIRouter(prefix=CONNEXION, tags=["sessions"])

# Le même texte pour tout refus : adresse inconnue, mot de passe faux, compte banni ou supprimé.
IDENTIFIANTS_INCORRECTS: Final = "E-mail ou mot de passe incorrect."
TROP_D_ESSAIS: Final = "Trop d'essais. Réessaie plus tard."
INDISPONIBLE: Final = "La connexion est momentanément indisponible."


@router.post(
    "",
    operation_id="create_session",
    summary="Se connecter",
    description=(
        "Ouvre une session par e-mail et mot de passe. Le jeton n'est jamais dans le corps : "
        "il est posé dans "
        "le cookie `__Host-popote_session` (HttpOnly, Secure, SameSite=Lax). Sans `Idempotency-Key` : "
        "chaque connexion réussie ouvre une session neuve."
    ),
    status_code=201,
    response_model=SessionOuverte,
    response_description="La session est ouverte ; le cookie est posé.",
    responses={
        201: {
            "headers": {
                "Set-Cookie": {"description": "Le cookie de session.", "schema": {"type": "string"}},
            }
        },
        429: {
            **reponses_erreur(429)[429],
            "headers": {
                "Retry-After": {"description": "Secondes à attendre.", "schema": {"type": "integer"}}
            },
        },
        **reponses_erreur(400, 401, 403, 500, 503),
    },
)
async def cree_la_session(corps: Connexion, request: Request, reponse: Response) -> SessionOuverte:
    app = request.app
    try:
        resultat = await tente_la_connexion(
            app.state.base,
            app.state.empreintes,
            app.state.settings,
            email=corps.email,
            mot_de_passe=corps.password,
            ip=ip_de(request),
            agent=request.headers.get("user-agent"),
            jeton_presente=request.cookies.get(app.state.settings.nom_du_cookie_de_session),
            request_id=getattr(request.state, "request_id", None),
        )
    except PoivreAbsentError as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    match resultat:
        case Bloquee(attente_s):
            raise Probleme(429, "trop_de_requetes", TROP_D_ESSAIS, headers={"Retry-After": str(attente_s)})
        case Ouverte(jeton, session, _):
            pose_le_cookie_de_session(reponse, app.state.settings, jeton)
            return SessionOuverte(id=session)
        case _:
            raise Probleme(401, "identifiants_incorrects", IDENTIFIANTS_INCORRECTS)
