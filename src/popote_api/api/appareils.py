"""`/api/v1/me/sessions` : les appareils de la personne (lister, fermer, fermer les autres), la déconnexion.

Contexte « personne » : les fonctions SQL (0140) lisent `auth.uid()`, la route ne passe jamais l'identifiant
de la personne. `DELETE` est naturellement idempotent (fermer deux fois laisse le même état) : pas
d'`Idempotency-Key`, qui ne vaut que pour les `POST` (exemption écrite dans `docs/normes-api.md`).
"""

from typing import Annotated, Final, Literal, LiteralString
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from popote_api.errors import DEFI_D_AUTHENTIFICATION, PAS_DE_SESSION, Probleme, reponses_erreur
from popote_api.pagination import (
    Page,
    Parametres,
    Position,
    Tri,
    construit_page,
    lire_curseur,
    parametres_de_page,
)
from popote_api.schemas.appareils import Appareil
from popote_api.security.cookie import efface_le_cookie_de_session
from popote_api.security.session import PersonneDeLaSession

router = APIRouter(prefix="/me/sessions", tags=["appareils"])

TRI: Final = Tri(nom="sessions", cle="last_seen_at", type_cle="instant", descendant=True)
COURANTE: Final = "current"
# Un UUID ou le mot `current` ; autre chose est un `422`, avant tout accès à la base.
FORME_DE_L_ID: Final = (
    r"^(current|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)

LISTE: Final[LiteralString] = (
    "select id, browser, os, created_at, last_seen_at from public.mes_sessions(%s, %s, %s)"
)
FERME_UN: Final[LiteralString] = "select public.ferme_un_appareil(%s, %s) as etat"
FERME_LES_AUTRES: Final[LiteralString] = "select public.ferme_les_autres_appareils(%s) as nombre"


@router.get(
    "",
    operation_id="list_my_sessions",
    summary="Mes appareils connectés",
    response_description="Les sessions actives de la personne, la plus récemment active d'abord.",
    response_model=Page[Appareil],
    responses=reponses_erreur(400, 422),
)
async def liste_les_appareils(
    personne: PersonneDeLaSession, page: Annotated[Parametres, Depends(parametres_de_page)]
) -> Page[Appareil]:
    position = lire_curseur(TRI, page.cursor)
    apres = (position.cle, position.identifiant) if position else (None, None)
    await personne.curseur.execute(LISTE, (page.limit + 1, *apres))
    lignes = await personne.curseur.fetchall()
    appareils = [
        Appareil.model_validate({**ligne, "current": ligne["id"] == personne.session}) for ligne in lignes
    ]
    return construit_page(appareils, page.limit, TRI, lambda a: Position(a.last_seen_at, a.id))


@router.delete(
    "/{id}",
    operation_id="close_my_session",
    summary="Fermer un appareil, ou se déconnecter",
    description=(
        "`id` est l'identifiant d'une session de la personne, ou `current` : la session qui fait la "
        "requête (déconnexion : le cookie est vidé). Fermer une session déjà fermée est sans effet (`204`). "
        "Une session d'une autre personne ou inconnue est un `404`. Pas d'`Idempotency-Key` : l'effet est "
        "idempotent."
    ),
    status_code=204,
    response_class=Response,
    responses={
        204: {
            "description": "La session est fermée.",
            "headers": {
                "Set-Cookie": {
                    "description": "Pour `current` : le cookie vidé (`Max-Age=0`).",
                    "schema": {"type": "string"},
                }
            },
        },
        **reponses_erreur(403, 404, 422),
    },
)
async def ferme_un_appareil(
    request: Request,
    personne: PersonneDeLaSession,
    id: Annotated[str, Path(pattern=FORME_DE_L_ID, description="UUID de la session, ou `current`.")],
) -> Response:
    est_la_courante = id == COURANTE or UUID(id) == personne.session
    cible = personne.session if id == COURANTE else UUID(id)
    await personne.curseur.execute(FERME_UN, (cible, personne.session))
    ligne = await personne.curseur.fetchone()
    assert ligne is not None  # noqa: S101  # un `select` de fonction rend toujours une ligne
    if ligne["etat"] == "inconnue":
        raise Probleme(404, "session_introuvable", "Cette session n'existe pas.")
    if est_la_courante and ligne["etat"] == "deja_fermee":
        # Une autre requête vient de fermer cette session (déconnexions simultanées) : elle n'est plus là.
        raise Probleme(
            401, "pas_de_session", PAS_DE_SESSION, headers={"WWW-Authenticate": DEFI_D_AUTHENTIFICATION}
        )
    reponse = Response(status_code=204)
    if est_la_courante:
        efface_le_cookie_de_session(reponse, request.app.state.settings)
    return reponse


@router.delete(
    "",
    operation_id="close_my_other_sessions",
    summary="Fermer tous les autres appareils",
    description=(
        "Ferme toutes les sessions de la personne sauf celle qui fait la requête. "
        "`scope=others` est obligatoire."
    ),
    status_code=204,
    response_class=Response,
    responses=reponses_erreur(403, 422),
)
async def ferme_les_autres(
    personne: PersonneDeLaSession,
    scope: Annotated[Literal["others"], Query(description="Seule valeur admise : `others`.")],
) -> Response:
    del scope  # la valeur est unique ; sa présence est le garde-fou contre un `DELETE` nu
    await personne.curseur.execute(FERME_LES_AUTRES, (personne.session,))
    return Response(status_code=204)
