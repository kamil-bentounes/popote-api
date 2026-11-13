"""Les modèles de `POST /api/v1/login-codes` : une adresse, une réponse toujours de même forme."""

from typing import Final
from uuid import UUID

from pydantic import Field, field_validator

from popote_api.schemas.base import Entree, Sortie
from popote_api.schemas.connexion import exige_un_email_encodable
from popote_api.security.empreintes import email_normalise

LONGUEUR_MAX_DE_L_ADRESSE_EN_OCTETS: Final = 254

MESSAGE_DE_LA_DEMANDE: Final = "Si cette adresse a un compte, un code vient d'y être envoyé."


class CodeDemande(Entree):
    email: str = Field(max_length=254, description="L'adresse du compte.")

    @field_validator("email")
    @classmethod
    def _email_encodable(cls, email: str) -> str:
        exige_un_email_encodable(email)
        # La base compte des octets, sur la forme normalisée (NFKC peut l'allonger) : un refus net ici, avant
        # tout créneau, plutôt qu'une erreur de la base qui annulerait aussi les créneaux déjà pris.
        if len(email_normalise(email).encode("utf-8")) > LONGUEUR_MAX_DE_L_ADRESSE_EN_OCTETS:
            raise ValueError("Adresse trop longue.")
        return email


class CodeDemandeAccepte(Sortie):
    code_request_id: UUID = Field(
        description="L'identifiant de la demande : l'ouverture de session le redemande (le code y est lié)."
    )
    expires_in_s: int = Field(description="Les secondes de validité du code.")
    resend_after_s: int = Field(description="Les secondes avant qu'une nouvelle demande remplace le code.")
    message: str = Field(description="Toujours le même texte : la réponse ne dit pas si le compte existe.")
