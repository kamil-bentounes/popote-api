"""`GET /api/v1/me` : la personne connectée, son adresse et son foyer."""

import logging
from typing import Any, Final, LiteralString

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from popote_api.conditionnel import EN_TETES_CONDITIONNELS, REPONSE_304, etag_de_contenu, repond_ou_304
from popote_api.errors import (
    CODE_AUTH_INDISPONIBLE,
    DEFI_D_AUTHENTIFICATION,
    PAS_DE_SESSION,
    Probleme,
    reponse,
    reponses_erreur,
)
from popote_api.infra.auth_admin import AuthIndisponible, MotDePasseRefuseParAuth
from popote_api.infra.fuites import EtatFuite
from popote_api.schemas.moi import ChangementDeMotDePasse, Moi
from popote_api.security.connexion import (
    confirme_le_mot_de_passe_change,
    fait_tourner_la_session_et_ferme_les_autres,
    journalise_la_liste_de_fuites_indisponible,
)
from popote_api.security.cookie import pose_le_cookie_de_session
from popote_api.security.mots_de_passe import normalise, verifie_nouveau
from popote_api.security.reauth import EXIGE_UNE_REAUTHENTIFICATION
from popote_api.security.session import PersonneDeLaSession

journal = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["moi"])

# Sous la RLS de la personne : `user_profile` et `household` ne rendent que son foyer. L'adresse n'est pas
# dans `user_profile`, et `authenticated` ne lit pas `auth.users` : elle vient de `mon_email()` (0134).
# Sans profil, la jointure rend le foyer et le prénom absents ; la ligne existe toujours.
LIT_MOI: Final[LiteralString] = """
    select public.mon_email() as email, p.display_name, h.id as household_id, h.name as household_name
      from (select 1) as moi
      left join public.user_profile p on p.id = auth.uid()
      left join public.household h on h.id = p.household_id
"""


def _corps(personne: PersonneDeLaSession, ligne: dict[str, Any]) -> dict[str, Any]:
    foyer = {"id": ligne["household_id"], "name": ligne["household_name"]} if ligne["household_id"] else None
    moi = Moi.model_validate(
        {
            "id": personne.id,
            "email": ligne["email"],
            "display_name": ligne["display_name"],
            "household": foyer,
        }
    )
    return moi.model_dump(mode="json")


@router.get(
    "",
    operation_id="get_me",
    summary="La personne connectée",
    response_description="La personne, son adresse et son foyer.",
    response_model=Moi,
    dependencies=[EN_TETES_CONDITIONNELS],
    responses={
        200: {
            "headers": {"ETag": {"description": "Empreinte du contenu (fort).", "schema": {"type": "string"}}}
        },
        304: REPONSE_304,
        **reponses_erreur(400, 412),
    },
)
async def lire_moi(request: Request, personne: PersonneDeLaSession) -> Response:
    await personne.curseur.execute(LIT_MOI)
    ligne = await personne.curseur.fetchone()
    assert ligne is not None  # noqa: S101  # `select … from (select 1)` rend toujours une ligne
    corps = _corps(personne, ligne)
    # L'`ETag` est celui des octets que `repond_ou_304` enverra : il change quand la représentation change.
    etag = etag_de_contenu(bytes(JSONResponse(corps).body))
    return repond_ou_304(request, etag, corps)


MOT_DE_PASSE_FUITE: Final = (
    "Ce mot de passe figure dans une liste de mots de passe volés : choisis-en un autre."
)
AUTH_EN_PANNE: Final = (
    "Le mot de passe n'a pas été changé : réessaie dans un instant. Ta session reste ouverte, "
    "tes autres appareils ont été déconnectés."
)


@router.put(
    "/password",
    operation_id="change_password",
    summary="Changer son mot de passe",
    description=(
        "Exige une réauthentification de moins de 5 minutes. Les règles de fond et la liste de fuites sont "
        "refusées en `422` (pointeur `/new_password`) AVANT tout changement. Le jeton de la session courante "
        "tourne (l'ancien cookie ne sert plus ; un second changement simultané avec lui reçoit `401`), les "
        "autres sessions et celles de Supabase Auth sont fermées, puis le mot de passe est écrit dans Auth. "
        "Si Auth ne répond pas : `503` AVEC le nouveau cookie, mot de passe inchangé. Liste de fuites "
        "indisponible : le mot de passe est accepté et l'événement `verification_fuites_indisponible` est "
        "écrit. Sans `Idempotency-Key` : un `PUT` est naturellement idempotent, et rejouer une réponse "
        "garderait un mot de passe en base."
    ),
    status_code=204,
    response_class=Response,
    dependencies=[EXIGE_UNE_REAUTHENTIFICATION],
    responses={
        204: {
            "description": "Le mot de passe est changé ; le cookie de session est remplacé.",
            "headers": {"Set-Cookie": {"description": "Le nouveau jeton.", "schema": {"type": "string"}}},
        },
        503: {
            **reponses_erreur(503)[503],
            "headers": {
                "Set-Cookie": {
                    "description": "Le nouveau jeton, car la session a déjà tourné.",
                    "schema": {"type": "string"},
                }
            },
        },
        **reponses_erreur(403, 422),
    },
)
async def change_le_mot_de_passe(
    corps: ChangementDeMotDePasse, request: Request, personne: PersonneDeLaSession
) -> Response:
    app = request.app
    request_id = getattr(request.state, "request_id", None)
    # (1) Avant tout changement d'état : règles de fond, puis liste de fuites.
    defauts = verifie_nouveau(corps.new_password, "/new_password")
    if defauts:
        return reponse(
            request,
            422,
            "donnees_invalides",
            "Le mot de passe est refusé.",
            errors=[defaut.en_erreur_de_champ() for defaut in defauts],
        )
    forme = normalise(corps.new_password)  # la forme que la connexion essaie d'abord
    verdict = await app.state.fuites.verifie(forme)
    if verdict.etat is EtatFuite.fuite:
        return reponse(
            request,
            422,
            "donnees_invalides",
            "Le mot de passe est refusé.",
            errors=[{"pointer": "/new_password", "message": MOT_DE_PASSE_FUITE}],
        )
    if verdict.etat is EtatFuite.indisponible:
        # B23 : on accepte, et on le dit. Ni la valeur ni son empreinte ne sont journalisées.
        journal.warning("Liste de fuites indisponible (%s) : mot de passe accepté", verdict.cause)
        await journalise_la_liste_de_fuites_indisponible(app.state.base, personne.id, request_id)
    # (2) La rotation fait aussi verrou : un second changement avec l'ancien cookie ne trouve plus de session.
    tournee = await fait_tourner_la_session_et_ferme_les_autres(app.state.base, personne.empreinte_de_session)
    if tournee is None:
        raise Probleme(
            401, "pas_de_session", PAS_DE_SESSION, headers={"WWW-Authenticate": DEFI_D_AUTHENTIFICATION}
        )
    nouveau_cookie = Response()
    pose_le_cookie_de_session(nouveau_cookie, app.state.settings, tournee.jeton)
    # (3) Auth. Un échec laisse le mot de passe inchangé ; la session a tourné : le client reçoit son cookie.
    try:
        await app.state.auth_admin.change_mot_de_passe(personne.id, forme)
    except (AuthIndisponible, MotDePasseRefuseParAuth) as erreur:
        # Le texte de l'exception ne porte que le statut et le code d'Auth (ni e-mail ni mot de passe).
        journal.warning("Changement de mot de passe refusé ou impossible : %s", erreur)
        raise Probleme(
            503,
            CODE_AUTH_INDISPONIBLE,
            AUTH_EN_PANNE,
            headers={"Set-Cookie": nouveau_cookie.headers["set-cookie"]},
        ) from erreur
    # (4) Le succès : `password_set` et l'événement.
    await confirme_le_mot_de_passe_change(app.state.base, personne.id, request_id)
    nouveau_cookie.status_code = 204
    return nouveau_cookie
