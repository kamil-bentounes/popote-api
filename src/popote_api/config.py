import re
from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32
# Les origines (schéma, hôte, port) d'où le front de chaque environnement appelle l'API.
ORIGINES_PAR_ENV: dict[str, frozenset[str]] = {
    "prod": frozenset({"https://notre-popote.fr"}),
    "essai": frozenset({"https://essai.notre-popote.fr"}),
    "local": frozenset({"http://localhost:5173", "http://127.0.0.1:5173"}),
}
# Le Worker du front d'essai (`name` de `popote-web/wrangler.jsonc`) : seul son nom entre dans le motif.
WORKER_DU_FRONT = "popote-web-essai"
# Un sous-domaine `workers.dev` est une étiquette DNS : minuscules, chiffres, tirets, 63 au plus.
SOUS_DOMAINE_WORKERS = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


@lru_cache
def motif_des_apercus(compte: str) -> re.Pattern[str]:
    """Les URL d'aperçu (« version URLs ») de Cloudflare Workers du seul Worker du front, sur ce compte.

    Format : `https://<préfixe>-<worker>.<sous-domaine du compte>.workers.dev` (Cloudflare, « Preview URLs »).
    Le préfixe est l'alias (minuscules, chiffres, tirets, commençant par une lettre) ou l'empreinte de la
    version (hexadécimal) ; l'étiquette entière tient en 63 caractères. Le sous-domaine du compte est
    écrit en entier : le Worker d'un autre compte qui porterait le même nom ne passe pas.
    """
    nom = re.escape(WORKER_DU_FRONT)
    maximum = 63 - len(WORKER_DU_FRONT) - 1  # la longueur du préfixe, tiret exclu
    return re.compile(
        rf"https://[a-z0-9][a-z0-9-]{{0,{maximum - 1}}}-{nom}\.{re.escape(compte)}\.workers\.dev"
    )


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
    # Sous-domaine `workers.dev` du compte Cloudflare, pour reconnaître les aperçus de fusion du front.
    # Essai seulement : la prod n'a pas d'aperçu.
    apercu_compte: str | None = None

    @property
    def relais_exige(self) -> bool:
        return self.env is not Env.local

    @property
    def origines(self) -> frozenset[str]:
        return ORIGINES_PAR_ENV[self.env.value]

    def origine_admise(self, origine: str) -> bool:
        """Une origine exacte de l'environnement, ou, sur l'essai, une URL d'aperçu du front."""
        if origine in self.origines:
            return True
        return (
            self.apercu_compte is not None
            and motif_des_apercus(self.apercu_compte).fullmatch(origine) is not None
        )

    @model_validator(mode="after")
    def _apercu_seulement_sur_l_essai(self) -> Self:
        if self.apercu_compte is None:
            return self
        if self.env is not Env.essai:
            raise ValueError("apercu_compte : réservé à l'essai, la prod et le local n'ont pas d'aperçu.")
        if not SOUS_DOMAINE_WORKERS.fullmatch(self.apercu_compte):
            raise ValueError("apercu_compte : un sous-domaine workers.dev (minuscules, chiffres, tirets).")
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
