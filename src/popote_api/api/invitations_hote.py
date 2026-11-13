"""`/api/v1/me/invitations` : les liens d'invitation de l'hôte (créer, lister ceux en attente, révoquer).

Contexte « personne » : la fonction SQL (0142) lit `auth.uid()`, la route ne passe jamais l'identifiant de la
personne. Le jeton (256 bits, base64url, 43 caractères) est tiré ICI ; seul son SHA-256 (de la chaîne ASCII
que la personne recevra, et que T13 recevra et hachera de même) part en base. Il n'entre dans aucune adresse
d'API, aucun journal, aucun `repr`, et pas dans la table d'idempotence (`champs_secrets`).

La liste et la révocation (0143) lisent aussi `auth.uid()` : le foyer est celui de la personne, un lien d'un
autre foyer est « inconnu » (`404`). `DELETE` est naturellement idempotent (révoquer deux fois laisse le même
état) : pas d'`Idempotency-Key`, qui ne vaut que pour les `POST` à effet (exemption écrite dans
`docs/normes-api.md`).
"""

import hashlib
import secrets
from typing import Annotated, Final, LiteralString
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from popote_api.errors import Probleme, reponses_erreur
from popote_api.pagination import (
    Page,
    Parametres,
    Position,
    Tri,
    construit_page,
    lire_curseur,
    parametres_de_page,
)
from popote_api.schemas.invitations import InvitationCreee, InvitationEnAttente
from popote_api.security.idempotence import RouteIdempotente
from popote_api.security.session import PersonneDeLaSession

router = APIRouter(
    prefix="/me/invitations",
    tags=["invitations"],
    route_class=RouteIdempotente.avec(champs_secrets=("token",)),
)

OCTETS_DU_JETON: Final = 32
CREE: Final[LiteralString] = (
    "select etat, id, created_at, expires_at, attente from public.cree_invitation(%s)"
)


TRI: Final = Tri(nom="invitations", cle="created_at", type_cle="instant", descendant=True)
LISTE: Final[LiteralString] = "select id, created_at, expires_at from public.mes_invitations(%s, %s, %s)"
REVOQUE: Final[LiteralString] = "select public.revoque_invitation(%s) as etat"


def tire_un_jeton() -> tuple[str, bytes]:
    """Un jeton neuf (43 caractères base64url) et son empreinte SHA-256 (32 octets)."""
    jeton = secrets.token_urlsafe(OCTETS_DU_JETON)
    return jeton, hashlib.sha256(jeton.encode("ascii")).digest()


@router.post(
    "",
    operation_id="create_my_invitation",
    summary="Créer un lien d'invitation pour mon foyer",
    description=(
        "Le jeton du lien n'est rendu qu'UNE fois, dans cette réponse ; un rejeu (même `Idempotency-Key`) "
        "rend le même statut et la même ligne avec `token: null` : l'hôte révoque et recrée si la réponse "
        "s'est perdue. Dix liens par 24 h glissantes pour le foyer, révoqués compris (`429 "
        "quota_invitations` avec `Retry-After`). Sans foyer : `403 aucun_foyer`."
    ),
    status_code=201,
    response_model=InvitationCreee,
    responses={
        201: {
            "description": "Le lien est créé.",
            "headers": {
                "Location": {
                    "description": "La ressource du lien (sans le jeton).",
                    "schema": {"type": "string"},
                }
            },
        },
        **reponses_erreur(403, 429),
    },
)
async def cree_une_invitation(personne: PersonneDeLaSession, response: Response) -> InvitationCreee:
    jeton, empreinte = tire_un_jeton()
    await personne.curseur.execute(CREE, (empreinte,))
    ligne = await personne.curseur.fetchone()
    if ligne is None:
        msg = "cree_invitation rend toujours une ligne."
        raise RuntimeError(msg)
    if ligne["etat"] == "aucun_foyer":
        raise Probleme(403, "aucun_foyer", "Ton compte n'appartient à aucun foyer : rien à inviter.")
    if ligne["etat"] == "quota":
        raise Probleme(
            429,
            "quota_invitations",
            "Dix liens d'invitation par 24 heures et par foyer, révoqués compris : réessaie plus tard.",
            {"Retry-After": str(ligne["attente"])},
        )
    response.headers["Location"] = f"/api/v1/me/invitations/{ligne['id']}"
    return InvitationCreee(
        id=ligne["id"], token=jeton, created_at=ligne["created_at"], expires_at=ligne["expires_at"]
    )


@router.get(
    "",
    operation_id="list_my_invitations",
    summary="Les liens d'invitation en attente de mon foyer",
    response_description="Les liens ni expirés, ni utilisés, ni révoqués, le plus récent d'abord.",
    response_model=Page[InvitationEnAttente],
    responses=reponses_erreur(400, 422),
)
async def liste_les_invitations(
    personne: PersonneDeLaSession, page: Annotated[Parametres, Depends(parametres_de_page)]
) -> Page[InvitationEnAttente]:
    position = lire_curseur(TRI, page.cursor)
    apres = (position.cle, position.identifiant) if position else (None, None)
    await personne.curseur.execute(LISTE, (page.limit + 1, *apres))
    invitations = [InvitationEnAttente.model_validate(ligne) for ligne in await personne.curseur.fetchall()]
    return construit_page(invitations, page.limit, TRI, lambda i: Position(i.created_at, i.id))


@router.delete(
    "/{id}",
    operation_id="revoke_my_invitation",
    summary="Révoquer un lien d'invitation de mon foyer",
    description=(
        "Révoquer un lien déjà révoqué (ou échu) est sans effet (`204`). Un lien d'un autre foyer ou inconnu "
        "est un `404` : il n'est ni révélé ni touché. Un lien déjà accepté ne se révoque pas "
        "(`409 invitation_utilisee`). Pas d'`Idempotency-Key` : l'effet est idempotent."
    ),
    status_code=204,
    response_class=Response,
    responses={204: {"description": "Le lien est révoqué."}, **reponses_erreur(403, 404, 409, 422)},
)
async def revoque_une_invitation(personne: PersonneDeLaSession, id: UUID) -> Response:
    await personne.curseur.execute(REVOQUE, (id,))
    ligne = await personne.curseur.fetchone()
    if ligne is None:
        msg = "revoque_invitation rend toujours une ligne."
        raise RuntimeError(msg)
    if ligne["etat"] == "inconnue":
        raise Probleme(404, "invitation_introuvable", "Cette invitation n'existe pas.")
    if ligne["etat"] == "utilisee":
        raise Probleme(409, "invitation_utilisee", "Ce lien a déjà été utilisé : il ne se révoque plus.")
    return Response(status_code=204)
