from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32
HOTES_LOCAUX = frozenset({"127.0.0.1", "localhost", "::1"})


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
    database_url: SecretStr | None = None
    relay_secret: SecretStr | None = None
    # Administration de Supabase Auth (`infra/auth_admin.py`). Facultatives pour l'instant : sans elles,
    # l'application démarre et chaque opération de compte rend 503. Aucune valeur par défaut qui pointerait
    # vers un autre projet. Les deux vont ensemble.
    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = None

    @property
    def relais_exige(self) -> bool:
        return self.env is not Env.local

    @field_validator("supabase_url")
    @classmethod
    def _url_de_supabase_nue(cls, valeur: str | None, info: ValidationInfo) -> str | None:
        """Ramène l'adresse à son origine ; le chemin des routes d'Auth est écrit dans le client."""
        if valeur is None:
            return None
        morceaux = urlsplit(valeur.strip())
        try:
            hote, port = morceaux.hostname, morceaux.port
        except ValueError:  # le message de la bibliothèque recopierait l'adresse
            raise ValueError("supabase_url : adresse mal formée.") from None
        origine_nue = morceaux.path in ("", "/") and not (
            morceaux.query or morceaux.fragment or morceaux.username or morceaux.password
        )
        if not hote or not origine_nue or morceaux.scheme not in ("http", "https"):
            raise ValueError("supabase_url : une origine http(s) seule est attendue (sans chemin ni accès).")
        # La clé secrète voyage vers cette adresse : jamais en clair, sauf vers la pile locale.
        if morceaux.scheme == "http" and not (info.data.get("env") is Env.local and hote in HOTES_LOCAUX):
            raise ValueError("supabase_url : https obligatoire (http seulement vers l'hôte local, en local).")
        origine = f"{morceaux.scheme}://{'[' + hote + ']' if ':' in hote else hote}"
        return origine + (f":{port}" if port else "")

    @field_validator("supabase_secret_key")
    @classmethod
    def _cle_secrete_transmissible(cls, valeur: SecretStr | None) -> SecretStr | None:
        """La clé voyage dans un en-tête : ASCII visible seulement (un défaut serait recopié par httpx)."""
        if valeur is None:
            return None
        cle = valeur.get_secret_value()
        if not cle or not cle.isascii() or not cle.isprintable() or " " in cle:
            raise ValueError("supabase_secret_key : caractères ASCII visibles seulement, non vide.")
        return valeur

    @model_validator(mode="after")
    def _supabase_va_par_deux(self) -> Self:
        if (self.supabase_url is None) != (self.supabase_secret_key is None):
            raise ValueError("supabase_url et supabase_secret_key vont ensemble : poser les deux ou aucun.")
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
