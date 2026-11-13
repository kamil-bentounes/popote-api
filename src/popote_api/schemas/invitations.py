from datetime import datetime
from uuid import UUID

from pydantic import Field

from popote_api.schemas.base import Entree, Sortie


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


class InspectionDemandee(Entree):
    """Le lien à lire, dans le corps : jamais dans l'adresse de la route (journaux d'accès)."""

    token: str = Field(max_length=256, description="Le jeton du lien.", repr=False)


class InvitationInspectee(Sortie):
    """Ce que voit la personne invitée avant de créer son compte : jamais d'adresse."""

    invited_by: str | None = Field(description="Le prénom de qui invite, ou `null`.")
    expires_at: datetime = Field(description="Échéance du lien.")


class AcceptationDemandee(Entree):
    token: str = Field(max_length=256, description="Le jeton du lien.", repr=False)
    email: str = Field(max_length=254, description="L'adresse du compte à créer.", repr=False)
    password: str = Field(
        max_length=256,
        description="Le mot de passe du compte à créer.",
        json_schema_extra={"format": "password"},
        repr=False,
    )
