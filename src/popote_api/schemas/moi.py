from uuid import UUID

from pydantic import Field

from popote_api.schemas.base import Entree, Sortie


class FoyerResume(Sortie):
    id: UUID
    name: str


class Moi(Sortie):
    """La personne connectée, telle qu'elle se voit : de quoi afficher son nom, son foyer et son adresse."""

    id: UUID
    email: str | None = Field(description="L'adresse de connexion ; absente si le compte n'en a pas.")
    display_name: str | None = Field(description="Le prénom affiché ; absent sans profil.")
    household: FoyerResume | None = Field(description="Le foyer de la personne ; absent sans profil.")


class ChangementDeMotDePasse(Entree):
    # Borné : un corps de plusieurs Mio n'atteint ni la liste de fuites ni Auth. Les règles de fond
    # (15 à 64 caractères, 72 octets) sont dans `security/mots_de_passe.py` et rendent un `422` à pointeur.
    # `repr=False` : le mot de passe n'apparaît dans aucun `repr` du modèle.
    new_password: str = Field(
        max_length=256,
        repr=False,
        description="Le nouveau mot de passe : 15 à 64 caractères, 72 octets UTF-8 au plus.",
        json_schema_extra={"format": "password"},
    )
