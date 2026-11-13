from datetime import datetime
from uuid import UUID

from pydantic import Field

from popote_api.schemas.base import Sortie


class InvitationCreee(Sortie):
    """Un lien d'invitation qui vient d'être créé : le jeton n'existe que dans la première réponse."""

    id: UUID
    token: str | None = Field(
        description=(
            "Le jeton du lien (43 caractères base64url), rendu UNE SEULE FOIS ; `null` dans un rejeu "
            "(même `Idempotency-Key`) : la base n'en garde que l'empreinte."
        ),
        repr=False,
    )
    created_at: datetime
    expires_at: datetime = Field(description="Échéance du lien : sept jours après la création.")


class InvitationEnAttente(Sortie):
    """Un lien en attente du foyer : jamais son jeton, son empreinte ni le nom de qui l'a créé."""

    id: UUID
    created_at: datetime
    expires_at: datetime = Field(description="Échéance du lien : sept jours après la création.")
