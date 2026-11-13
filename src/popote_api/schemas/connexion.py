"""Les modèles de `POST /api/v1/sessions` : un e-mail et un mot de passe, une session sans jeton."""

from uuid import UUID

from pydantic import Field

from popote_api.schemas.base import Entree, Sortie


class Connexion(Entree):
    # Bornés : un corps de plusieurs Mio ne atteint ni Auth ni bcrypt. 254 : longueur maximale d'une adresse.
    email: str = Field(max_length=254, description="L'adresse du compte.")
    password: str = Field(
        max_length=256, description="Le mot de passe.", json_schema_extra={"format": "password"}
    )


class SessionOuverte(Sortie):
    id: UUID = Field(description="L'identifiant de la session (le jeton, lui, ne voyage que dans le cookie).")
