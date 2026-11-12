from enum import StrEnum

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(StrEnum):
    local = "local"
    essai = "essai"
    prod = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POPOTE_", extra="ignore")

    env: Env = Env.local
    database_url: SecretStr | None = None
    relay_secret: SecretStr | None = None

    @property
    def relais_exige(self) -> bool:
        return self.env is not Env.local
