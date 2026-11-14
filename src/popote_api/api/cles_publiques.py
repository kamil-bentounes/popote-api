"""`POST /api/v1/passkey-challenges` : les options de `navigator.credentials.get()`. Publique.

Sans personne : la cérémonie part sans nom d'utilisateur (le navigateur propose les clés qu'il a pour ce
site), donc rien ne dit si un compte existe (W3C § 14.6.2). Le défi, de 32 octets, vit 10 minutes et ne
sert qu'une fois. Sans `Idempotency-Key` : exemption écrite (sans personne il n'y a pas de clé
d'idempotence, et rejouer en crée un autre).
"""

from typing import Final

from fastapi import APIRouter, Request

from popote_api.errors import Probleme, reponses_erreur
from popote_api.infra.webauthn import PartieDeConfiance
from popote_api.relais import ip_de
from popote_api.routes_publiques import DEFIS_DE_CONNEXION
from popote_api.schemas.cles import OptionsDeConnexion
from popote_api.security.connexion import Bloquee
from popote_api.security.connexion_par_cle import demande_un_defi_de_connexion
from popote_api.security.empreintes import PoivreAbsentError

router = APIRouter(prefix=DEFIS_DE_CONNEXION, tags=["sessions"])

ORIGINE_NON_ADMISE: Final = (
    "Les clés d'accès ne sont pas disponibles à cette adresse : utilise le code reçu par mail."
)
TROP_DE_DEMANDES: Final = "Trop de demandes. Réessaie plus tard."
INDISPONIBLE: Final = "La connexion est momentanément indisponible."


@router.post(
    "",
    operation_id="create_passkey_challenge",
    summary="Demander les options pour se connecter avec une clé d'accès",
    description=(
        "Rend les options de `navigator.credentials.get()` : défi de 32 octets valable 10 minutes, "
        "aucune clé "
        "nommée, vérification de l'utilisateur exigée. Sans compte ni nom : la réponse ne dit rien d'un "
        "compte. Une page de Popote dont l'adresse n'admet pas les clés d'accès reçoit `403 "
        "cle_origine_non_admise` (les aperçus de fusion n'offrent que le code). 60 défis par IP et par 15 "
        "minutes, et un plafond de défis vivants : `429`. Sans `Idempotency-Key` (route publique)."
    ),
    response_model=OptionsDeConnexion,
    response_description="Les options à passer au navigateur.",
    responses={
        429: {
            **reponses_erreur(429)[429],
            "headers": {
                "Retry-After": {"description": "Secondes à attendre.", "schema": {"type": "integer"}}
            },
        },
        **reponses_erreur(400, 403, 500, 503),
    },
)
async def demande_un_defi_de_connexion_route(request: Request) -> OptionsDeConnexion:
    app = request.app
    reglages = app.state.settings
    if request.headers.get("origin") not in reglages.origines_webauthn:
        raise Probleme(403, "cle_origine_non_admise", ORIGINE_NON_ADMISE)
    try:
        resultat = await demande_un_defi_de_connexion(
            app.state.base,
            app.state.empreintes,
            reglages,
            PartieDeConfiance.des_reglages(reglages),
            ip=ip_de(request),
            request_id=getattr(request.state, "request_id", None),
        )
    except PoivreAbsentError as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    if isinstance(resultat, Bloquee):
        raise Probleme(
            429, "trop_de_requetes", TROP_DE_DEMANDES, headers={"Retry-After": str(resultat.attente_s)}
        )
    return OptionsDeConnexion(options=resultat.options)
