"""`POST /api/v1/sessions` : la connexion. Publique ; le jeton ne sort que dans le cookie."""

from typing import Final

from fastapi import APIRouter, Request, Response

from popote_api.errors import Probleme, reponses_erreur
from popote_api.infra.webauthn import CleStockeeIllisible, PartieDeConfiance
from popote_api.relais import ip_de
from popote_api.routes_publiques import CONNEXION
from popote_api.schemas.connexion import ConnexionDemandee, ConnexionParCle, SessionOuverte
from popote_api.security.connexion import Bloquee, Ouverte, Resultat, tente_la_connexion_par_code
from popote_api.security.connexion_par_cle import tente_la_connexion_par_cle
from popote_api.security.cookie import pose_le_cookie_de_session
from popote_api.security.empreintes import PoivreAbsentError

router = APIRouter(prefix=CONNEXION, tags=["sessions"])

# Le même texte pour tout refus : demande inconnue, d'une autre adresse, code faux, échu, utilisé, révoqué,
# compte banni, supprimé ou sans profil, adresse sans compte.
CODE_INCORRECT: Final = "Code incorrect ou expiré."
# Le même texte pour tout refus d'une clé : inconnue, signature fausse, origine, défi, vérification, compteur,
# compte banni, supprimé ou sans profil.
CLE_REFUSEE: Final = "Clé d'accès refusée. Utilise le code reçu par mail."
TROP_D_ESSAIS: Final = "Trop d'essais. Réessaie plus tard."
INDISPONIBLE: Final = "La connexion est momentanément indisponible."


@router.post(
    "",
    operation_id="create_session",
    summary="Se connecter par le code reçu par mail ou par une clé d'accès",
    description=(
        "Ouvre une session avec le code à six chiffres demandé par `POST /login-codes` (`method` : "
        "`email_code`) ou avec la réponse de `navigator.credentials.get()` aux options de `POST "
        "/passkey-challenges` (`method` : `passkey`, 16 Kio au plus, aucune adresse). Le jeton n'est "
        "jamais dans le corps : il est posé dans le cookie "
        "`__Host-popote_session` (HttpOnly, Secure, SameSite=Lax). Un seul refus pour tout ce qui n'est "
        "pas un code valable (`401 code_incorrect` : mêmes statut, corps et en-têtes, jamais de cookie) ; "
        "cinq essais par compte et par code, un code ne sert qu'une fois ; une seule réponse aussi pour tout "
        "ce qui n'est pas une clé valable (`401 cle_refusee`) ; au-delà des limites (20 vérifications de clé "
        "par IP et par 15 minutes), `429` sans aucune vérification. Sans `Idempotency-Key` : chaque "
        "connexion réussie ouvre une session neuve."
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
async def cree_la_session(corps: ConnexionDemandee, request: Request, reponse: Response) -> SessionOuverte:
    app = request.app
    reglages = app.state.settings
    jeton_presente = request.cookies.get(reglages.nom_du_cookie_de_session)
    try:
        if isinstance(corps, ConnexionParCle):
            resultat: Resultat = await tente_la_connexion_par_cle(
                app.state.base,
                app.state.empreintes,
                reglages,
                PartieDeConfiance.des_reglages(reglages),
                reponse=corps.credential,
                ip=ip_de(request),
                agent=request.headers.get("user-agent"),
                jeton_presente=jeton_presente,
                request_id=getattr(request.state, "request_id", None),
            )
        else:
            resultat = await tente_la_connexion_par_code(
                app.state.base,
                app.state.empreintes,
                reglages,
                email=corps.email,
                code_request_id=corps.code_request_id,
                code=corps.code,
                ip=ip_de(request),
                agent=request.headers.get("user-agent"),
                jeton_presente=jeton_presente,
                request_id=getattr(request.state, "request_id", None),
            )
    except (PoivreAbsentError, CleStockeeIllisible) as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    match resultat:
        case Bloquee(attente_s):
            raise Probleme(429, "trop_de_requetes", TROP_D_ESSAIS, headers={"Retry-After": str(attente_s)})
        case Ouverte(jeton, session, _):
            pose_le_cookie_de_session(reponse, reglages, jeton)
            return SessionOuverte(id=session)
        case _ if isinstance(corps, ConnexionParCle):
            raise Probleme(401, "cle_refusee", CLE_REFUSEE)
        case _:
            raise Probleme(401, "code_incorrect", CODE_INCORRECT)
