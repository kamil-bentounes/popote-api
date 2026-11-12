from enum import StrEnum
from typing import Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32


class Env(StrEnum):
    local = "local"
    essai = "essai"
    prod = "prod"


class Settings(BaseSettings):
    # hide_input_in_errors : l'erreur de démarrage ne doit jamais recopier un secret mal formé.
    model_config = SettingsConfigDict(env_prefix="POPOTE_", extra="ignore", hide_input_in_errors=True)

    # Pas de valeur par défaut : une faute dans le nom de POPOTE_ENV doit empêcher de démarrer,
    # pas démarrer en `local`, qui n'exige pas le relais.
    env: Env
    # Rôle `popote_api` (contexte personne), exigé hors local.
    database_url: SecretStr | None = None
    # Rôle `popote_internal` (contexte service). Facultatif tant que le conteneur d'essai ne l'a pas : sans
    # elle, l'application démarre avec un avertissement et `Base.service()` rend `503 service_indisponible`.
    database_url_internal: SecretStr | None = None
    relay_secret: SecretStr | None = None
    # Faux seulement dans les tests : le journal JSON remplace alors la configuration d'uvicorn.
    json_logs: bool = True

    @property
    def relais_exige(self) -> bool:
        return self.env is not Env.local

    @model_validator(mode="after")
    def _exige_le_necessaire_hors_local(self) -> Self:
        secret = self.relay_secret.get_secret_value() if self.relay_secret else ""
        if not secret.isascii():
            # L'en-tête HTTP reçu est comparé en octets : un secret hors ASCII ne se transmet pas sûrement.
            raise ValueError("relay_secret : caractères ASCII uniquement.")
        if not self.relais_exige:
            return self
        if len(secret) < LONGUEUR_MINIMALE_DU_SECRET:
            raise ValueError(
                f"relay_secret est obligatoire hors local, {LONGUEUR_MINIMALE_DU_SECRET} caractères au moins."
            )
        if self.database_url is None:
            raise ValueError("database_url est obligatoire hors local.")
        return self
