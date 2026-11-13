"""Le modèle de `POST /api/v1/me/reauthentication` : le mot de passe, rien d'autre."""

from pydantic import Field

from popote_api.schemas.base import Entree


class Reauthentification(Entree):
    # Borné comme à la connexion : un corps de plusieurs Mio n'atteint ni la base ni bcrypt.
    password: str = Field(
        max_length=256, description="Le mot de passe actuel.", json_schema_extra={"format": "password"}
    )
