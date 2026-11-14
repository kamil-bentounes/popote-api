"""Les modèles des routes des clés d'accès : le défi demandé, les options rendues, la clé enregistrée."""

import unicodedata
from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from popote_api.errors import ValeurRefusee
from popote_api.schemas.base import Entree, Sortie

LONGUEUR_MAX_DU_NOM: Final = 40


def _nom_de_cle(valeur: str) -> str:
    """Le nom nettoyé : NFC, sans espace autour, 1 à 40 caractères visibles."""
    nom = unicodedata.normalize("NFC", valeur).strip()
    if not 1 <= len(nom) <= LONGUEUR_MAX_DU_NOM:
        raise ValeurRefusee(f"Le nom d'une clé fait de 1 à {LONGUEUR_MAX_DU_NOM} caractères.")
    # Catégories C* (contrôle, format, surrogate, usage privé, non assigné) et séparateurs de ligne ou de
    # paragraphe : le nom s'affiche dans une liste d'appareils, qu'une marque invisible fausserait.
    if any(unicodedata.category(c).startswith("C") or unicodedata.category(c) in ("Zl", "Zp") for c in nom):
        raise ValeurRefusee("Le nom d'une clé ne contient ni retour à la ligne ni caractère invisible.")
    return nom


# Borné avant le nettoyage : une chaîne de plusieurs Mio ne passe pas par la normalisation.
NomDeCle = Annotated[
    str,
    Field(
        max_length=4 * LONGUEUR_MAX_DU_NOM,
        description=f"Le nom de la clé, de 1 à {LONGUEUR_MAX_DU_NOM} caractères visibles.",
    ),
    AfterValidator(_nom_de_cle),
]


class DefiDeCle(Entree):
    purpose: Literal["registration"] = Field(
        description="Le but de la cérémonie : `registration` (créer une clé)."
    )


class OptionsDeCle(Sortie):
    options: dict[str, Any] = Field(
        description=(
            "Les options de `navigator.credentials.create()`, en JSON WebAuthn niveau 3 : à passer à "
            "`PublicKeyCredential.parseCreationOptionsFromJSON`."
        ),
        repr=False,
    )


class OptionsDeConnexion(Sortie):
    options: dict[str, Any] = Field(
        description=(
            "Les options de `navigator.credentials.get()`, en JSON WebAuthn niveau 3 : à passer à "
            "`PublicKeyCredential.parseRequestOptionsFromJSON`. Aucune clé n'est nommée : l'appareil "
            "propose les siennes."
        ),
        repr=False,
    )


class EnregistrementDeCle(Entree):
    credential: dict[str, Any] = Field(
        description="La réponse de `navigator.credentials.create()`, par `PublicKeyCredential.toJSON()`.",
        repr=False,
    )
    name: NomDeCle | None = Field(None, description="Le nom de la clé ; sans lui : « Clé du JJ/MM/AAAA ».")


class CleAjoutee(Sortie):
    id: UUID
    name: str
    created_at: datetime


class CleDeLaPersonne(Sortie):
    """Une clé d'accès, telle que la personne la reconnaît : jamais la clé publique ni son identifiant."""

    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = Field(
        description="Dernière connexion par cette clé ; vide si elle n'a pas servi."
    )
    device_type: Literal["multi_device", "single_device"] = Field(
        description="`multi_device` : synchronisable (iCloud, Google) ; `single_device` : un appareil."
    )
    backed_up: bool = Field(description="Vrai si la clé est actuellement sauvegardée par son fournisseur.")
    transports: list[str]


class ChangementDeCle(Entree):
    """Le corps d'un `PATCH` (RFC 7396) : seul le nom se change, et il ne se retire pas."""

    name: NomDeCle | None = Field(None, description="Le nouveau nom, de 1 à 40 caractères visibles.")

    @model_validator(mode="after")
    def _le_nom_ne_se_retire_pas(self) -> "ChangementDeCle":
        if "name" in self.model_fields_set and self.name is None:
            raise ValeurRefusee("Le nom d'une clé ne se retire pas.")
        return self
