"""Les modèles de `POST /api/v1/sessions` : un e-mail et un mot de passe, une session sans jeton."""

from uuid import UUID

from pydantic import Field, field_validator

from popote_api.schemas.base import Entree, Sortie


class Connexion(Entree):
    # Bornés : un corps de plusieurs Mio ne atteint ni Auth ni bcrypt. 254 : longueur maximale d'une adresse.
    email: str = Field(max_length=254, description="L'adresse du compte.")
    password: str = Field(
        max_length=256, description="Le mot de passe.", json_schema_extra={"format": "password"}
    )

    @field_validator("email")
    @classmethod
    def _email_encodable(cls, email: str) -> str:
        # Un nul ou un substitut isolé ferait lever le pilote de la base : un 500 au lieu d'un refus.
        try:
            email.encode("utf-8")
        except UnicodeEncodeError as erreur:
            raise ValueError("Adresse illisible.") from erreur
        if "\x00" in email:
            raise ValueError("Adresse illisible.")
        return email


class SessionOuverte(Sortie):
    id: UUID = Field(description="L'identifiant de la session (le jeton, lui, ne voyage que dans le cookie).")
