"""`POST /api/v1/me/reauthentication` : le mot de passe saisi de nouveau, pour les gestes sensibles."""

from typing import Final

from fastapi import APIRouter, Request, Response

from popote_api.errors import MOT_DE_PASSE_INCORRECT, Probleme, reponses_erreur
from popote_api.relais import ip_de
from popote_api.schemas.reauthentification import Reauthentification
from popote_api.security.connexion import Bloquee, Reauthentifiee, tente_la_reauthentification
from popote_api.security.empreintes import PoivreAbsentError
from popote_api.security.session import PersonneDeLaSession

router = APIRouter(prefix="/me/reauthentication", tags=["moi"])

TROP_D_ESSAIS: Final = "Trop d'essais. Réessaie plus tard."
INDISPONIBLE: Final = "La vérification est momentanément indisponible."


@router.post(
    "",
    operation_id="reauthenticate",
    summary="Saisir de nouveau son mot de passe",
    description=(
        "Pose l'instant de réauthentification de la session qui fait la requête : les gestes sensibles "
        "l'acceptent pendant 5 minutes. Mêmes limites d'essais que la connexion, comptées sur le compte "
        "de la personne : cinq mots de passe faux bloquent aussi sa connexion. Sans `Idempotency-Key` : "
        "l'effet (un instant remis à jour) est naturellement idempotent."
    ),
    status_code=204,
    response_class=Response,
    responses={
        204: {"description": "Le mot de passe est le bon ; la session est réauthentifiée."},
        429: {
            **reponses_erreur(429)[429],
            "headers": {
                "Retry-After": {"description": "Secondes à attendre.", "schema": {"type": "integer"}}
            },
        },
        **reponses_erreur(403, 422, 503),
    },
)
async def reauthentifie(
    corps: Reauthentification, request: Request, personne: PersonneDeLaSession
) -> Response:
    # L'adresse se lit sous la session de la personne, comme `GET /me` : jamais du client.
    await personne.curseur.execute("select public.mon_email() as email")
    ligne = await personne.curseur.fetchone()
    assert ligne is not None  # noqa: S101  # `select` de fonction : toujours une ligne
    email: str | None = ligne["email"]
    if email is None:
        raise Probleme(403, "mot_de_passe_incorrect", MOT_DE_PASSE_INCORRECT)  # compte sans adresse
    app = request.app
    try:
        resultat = await tente_la_reauthentification(
            app.state.base,
            app.state.empreintes,
            app.state.settings,
            personne=personne.id,
            session=personne.session,
            email=email,
            mot_de_passe=corps.password,
            ip=ip_de(request),
            request_id=getattr(request.state, "request_id", None),
        )
    except PoivreAbsentError as erreur:
        raise Probleme(503, "service_indisponible", INDISPONIBLE) from erreur
    match resultat:
        case Bloquee(attente_s):
            raise Probleme(429, "trop_de_requetes", TROP_D_ESSAIS, headers={"Retry-After": str(attente_s)})
        case Reauthentifiee():
            return Response(status_code=204)
        case _:
            raise Probleme(403, "mot_de_passe_incorrect", MOT_DE_PASSE_INCORRECT)
