"""Les modèles de `POST /api/v1/sessions` : un code reçu par mail, une session sans jeton."""

import json
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import Field, field_validator

from popote_api.schemas.base import Entree, Sortie

# Une assertion WebAuthn tient en quelques centaines d'octets ; 16 Kio laisse de la marge aux extensions et
# refuse le reste avant tout travail (le plafond général de 1 Mio est celui du serveur).
TAILLE_MAX_D_UNE_ASSERTION: Final = 16 * 1024


def exige_un_email_encodable(email: str) -> str:
    """Un nul ou un substitut isolé ferait lever le pilote de la base : un 500 au lieu d'un refus."""
    try:
        email.encode("utf-8")
    except UnicodeEncodeError as erreur:
        raise ValueError("Adresse illisible.") from erreur
    if "\x00" in email:
        raise ValueError("Adresse illisible.")
    return email


class ConnexionParCode(Entree):
    """L'ouverture par le code reçu par mail : la demande (`code_request_id`), l'adresse, les six chiffres."""

    method: Literal["email_code"] = Field(description="La preuve présentée : le code reçu par mail.")
    email: str = Field(max_length=254, description="L'adresse du compte.")
    code_request_id: UUID = Field(description="L'identifiant rendu par `POST /login-codes`.")
    # Six chiffres ASCII exactement, ni espace ni saut de ligne : `\d` accepterait d'autres chiffres Unicode.
    code: str = Field(
        pattern=r"^[0-9]{6}$",
        description="Le code à six chiffres.",
        json_schema_extra={"format": "password"},
    )

    @field_validator("email")
    @classmethod
    def _email_encodable(cls, email: str) -> str:
        return exige_un_email_encodable(email)


class ConnexionParCle(Entree):
    """L'ouverture par clé d'accès : la réponse de `navigator.credentials.get()`, sans adresse ni nom."""

    method: Literal["passkey"] = Field(description="La preuve présentée : une clé d'accès.")
    credential: dict[str, Any] = Field(
        description=(
            "La réponse de `navigator.credentials.get()`, par `PublicKeyCredential.toJSON()` "
            "(16 Kio au plus)."
        ),
        repr=False,
    )

    @field_validator("credential")
    @classmethod
    def _assertion_de_taille_raisonnable(cls, credential: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(credential, separators=(",", ":")).encode()) > TAILLE_MAX_D_UNE_ASSERTION:
            raise ValueError("Réponse trop grande.")
        return credential


ConnexionDemandee = Annotated[ConnexionParCode | ConnexionParCle, Field(discriminator="method")]


class SessionOuverte(Sortie):
    id: UUID = Field(description="L'identifiant de la session (le jeton, lui, ne voyage que dans le cookie).")
