"""Les modèles des routes des clés d'accès : le défi demandé, les options rendues, la clé enregistrée."""

import unicodedata
from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import AfterValidator, Field

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
