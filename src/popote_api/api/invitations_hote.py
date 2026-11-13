"""`/api/v1/me/invitations` : les liens d'invitation de l'hôte (création ; liste et révocation : T12b).

Contexte « personne » : la fonction SQL (0142) lit `auth.uid()`, la route ne passe jamais l'identifiant de la
personne. Le jeton (256 bits, base64url, 43 caractères) est tiré ICI ; seul son SHA-256 (de la chaîne ASCII
que la personne recevra, et que T13 recevra et hachera de même) part en base. Il n'entre dans aucune adresse
d'API, aucun journal, aucun `repr`, et pas dans la table d'idempotence (`champs_secrets`).
"""

import hashlib
import secrets
from typing import Final, LiteralString

from fastapi import APIRouter, Response

from popote_api.errors import Probleme, reponses_erreur
from popote_api.schemas.invitations import InvitationCreee
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
