import re
from enum import StrEnum
from typing import Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32
# Le préfixe `__Host-` impose `Secure`, `Path=/` et aucun `Domain` : le navigateur refuse le cookie sinon.
NOM_DU_COOKIE_DE_SESSION = "__Host-popote_session"
# Un nom de cookie est un `token` (RFC 6265 § 4.1.1) ; on n'admet que lettres, chiffres, `_` et `-`.
FORME_D_UN_NOM_DE_COOKIE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class Env(StrEnum):
    local = "local"
    essai = "essai"
    prod = "prod"


class BreachCheck(StrEnum):
    hibp = "hibp"  # Pwned Passwords (API « range »)
    off = "off"  # aucune vérification : local seulement


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
    # La liste de fuites ne se remplace qu'en local : ailleurs, désactiver la vérification est refusé.
    breach_check: BreachCheck = BreachCheck.hibp

    # Le SHA du commit, posé dans l'image au build : le déploiement s'assure que c'est bien elle qui répond.
    version: str = Field("inconnue", pattern=r"^[A-Za-z0-9._-]{1,64}$")

    # Faux seulement dans les tests : le journal JSON remplace alors la configuration d'uvicorn.
    json_logs: bool = True
    # Le nom du cookie de session ne se change qu'en local, où `__Host-` et `Secure` ne passent pas partout
    # sur `http://localhost` : hors local, c'est `NOM_DU_COOKIE_DE_SESSION`, un autre nom est une erreur.
    session_cookie_name: str | None = None

    # L'adresse du projet Supabase (`https://<réf>.supabase.co`). Elle donne la revendication `iss` du
    # contexte personne, que `tg_recipe_photo` lit (spec § 5.1). Sans elle, il refuse.
    supabase_url: AnyHttpUrl | None = None

    @field_validator("supabase_url", mode="before")
    @classmethod
    def _adresse_vide_vaut_absente(cls, valeur: object) -> object:
        # Une variable posée à vide (comme `database_url`) vaut « absente », pas une erreur de démarrage.
        return None if valeur == "" else valeur

    @field_validator("supabase_url")
    @classmethod
    def _adresse_du_projet_seulement(cls, adresse: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if adresse is not None and (adresse.path not in ("", "/") or adresse.query or adresse.fragment):
            # Un chemin donnerait un `iss` faux sans rien dire : le déclencheur refuserait toute photo.
            raise ValueError("supabase_url : l'adresse du projet seulement, sans chemin ni requête.")
        return adresse

    @property
    def emetteur_des_jetons(self) -> str | None:
        """La revendication `iss` que PostgREST pose pour une personne connectée : `<projet>/auth/v1`."""
        return f"{str(self.supabase_url).rstrip('/')}/auth/v1" if self.supabase_url else None

    @property
    def relais_exige(self) -> bool:
        return self.env is not Env.local

    @property
    def nom_du_cookie_de_session(self) -> str:
        return self.session_cookie_name or NOM_DU_COOKIE_DE_SESSION

    @model_validator(mode="after")
    def _regle_le_cookie_de_session(self) -> Self:
        nom = self.session_cookie_name
        if nom is None:
            return self
        if self.env is not Env.local and nom != NOM_DU_COOKIE_DE_SESSION:
            raise ValueError("session_cookie_name ne se change qu'en local.")
        if FORME_D_UN_NOM_DE_COOKIE.fullmatch(nom) is None:
            raise ValueError("session_cookie_name : lettres, chiffres, _ et - seulement (64 au plus).")
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

    @model_validator(mode="after")
    def _la_liste_de_fuites_reste_active_hors_local(self) -> Self:
        if self.relais_exige and self.breach_check is not BreachCheck.hibp:
            raise ValueError("breach_check : seule la valeur « hibp » est permise hors local.")
        return self
