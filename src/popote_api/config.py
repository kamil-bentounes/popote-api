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
    # Clés de signature des routes `/internal/*` (spec § 3.10). Facultatives pour l'instant : sans
    # `internal_secret`, toute route interne répond 404 (fermé par défaut) et le démarrage avertit.
    # `internal_secret_precedent` sert la rotation : le nouveau secret va en `internal_secret`, l'ancien ici,
    # puis on retire l'ancien.
    internal_secret: SecretStr | None = None
    internal_secret_precedent: SecretStr | None = None
    # Faux seulement dans les tests : le journal JSON remplace alors la configuration d'uvicorn.
    json_logs: bool = True

    @property
    def secrets_internes(self) -> tuple[bytes, ...]:
        """Les secrets qui signent les routes internes, le courant d'abord ; vide : routes fermées."""
        secrets = (self.internal_secret, self.internal_secret_precedent)
        return tuple(s.get_secret_value().encode("ascii") for s in secrets if s and s.get_secret_value())

    @property
    def relais_exige(self) -> bool:
        return self.env is not Env.local

    @model_validator(mode="after")
    def _controle_les_secrets_internes(self) -> Self:
        # Une variable posée à vide vaut « absente » ; un secret posé doit être sûr, dans tout environnement.
        for nom in ("internal_secret", "internal_secret_precedent"):
            valeur = getattr(self, nom)
            secret = valeur.get_secret_value() if valeur else ""
            if secret and not secret.isascii():
                raise ValueError(f"{nom} : caractères ASCII uniquement.")
            if secret and len(secret) < LONGUEUR_MINIMALE_DU_SECRET:
                raise ValueError(f"{nom} : {LONGUEUR_MINIMALE_DU_SECRET} caractères au moins.")
        if len(self.secrets_internes) == 1 and self.internal_secret_precedent:
            raise ValueError("internal_secret_precedent sans internal_secret : la rotation pose les deux.")
        return self

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
