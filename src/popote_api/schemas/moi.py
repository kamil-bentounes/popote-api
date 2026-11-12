from uuid import UUID

from pydantic import Field

from popote_api.schemas.base import Sortie


class FoyerResume(Sortie):
    id: UUID
    name: str


class Moi(Sortie):
    """La personne connectée, telle qu'elle se voit : de quoi afficher son nom, son foyer et son adresse."""

    id: UUID
    email: str | None = Field(description="L'adresse de connexion ; absente si le compte n'en a pas.")
    display_name: str | None = Field(description="Le prénom affiché ; absent sans profil.")
    household: FoyerResume | None = Field(description="Le foyer de la personne ; absent sans profil.")
