"""Les modèles de `POST /api/v1/password-resets` : une adresse, une réponse toujours identique."""

from typing import Final

from pydantic import Field, field_validator

from popote_api.schemas.base import Entree, Sortie
from popote_api.schemas.connexion import exige_un_email_encodable

MESSAGE_DE_LA_DEMANDE: Final = "Si cette adresse a un compte, un lien vient d'y être envoyé."


class ReinitialisationDemandee(Entree):
    email: str = Field(max_length=254, description="L'adresse du compte.")

    @field_validator("email")
    @classmethod
    def _email_encodable(cls, email: str) -> str:
        return exige_un_email_encodable(email)


class DemandeAcceptee(Sortie):
    message: str = Field(description="Toujours le même texte : la réponse ne dit pas si le compte existe.")
