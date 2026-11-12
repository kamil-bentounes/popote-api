import re
from enum import StrEnum
from ipaddress import ip_address
from typing import Self

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32
HOTES_LOCAUX = frozenset({"127.0.0.1", "localhost", "::1"})
FORME_D_UN_NOM_D_HOTE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")


def est_valeur_d_en_tete(valeur: str) -> bool:
    """Vrai si la valeur voyage dans un en-tête HTTP sans erreur : ASCII visible, sans espace, non vide.

    Un défaut ferait recopier la valeur, donc la clé, par la bibliothèque HTTP dans son message d'erreur.
    """
    return bool(valeur) and valeur.isascii() and valeur.isprintable() and " " not in valeur


class Env(StrEnum):
    local = "local"
    essai = "essai"
    prod = "prod"


class BreachCheck(StrEnum):
    hibp = "hibp"  # Pwned Passwords (API « range »)
    off = "off"  # aucune vérification : local seulement


def _est_un_hote(hote: str) -> bool:
    """Un nom de domaine usuel ou une adresse IP littérale ; rien d'autre n'entre dans une adresse."""
    if ":" in hote:
        try:
            ip_address(hote)
        except ValueError:
            return False
        return True
    return FORME_D_UN_NOM_D_HOTE.fullmatch(hote) is not None


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

    # L'adresse du projet Supabase (`https://<réf>.supabase.co`). Elle donne la revendication `iss` du
    # contexte personne, que `tg_recipe_photo` lit (spec § 5.1). Sans elle, il refuse.
    supabase_url: AnyHttpUrl | None = None
    # La clé secrète du projet : avec l'adresse, elle ouvre l'administration d'Auth (`infra/auth_admin.py`).
    # Facultative pour l'instant : sans elle, l'adresse sert encore à `iss`, et chaque opération de compte
    # rend 503. Jamais sans l'adresse.
    supabase_secret_key: SecretStr | None = None

    @field_validator("supabase_url", "supabase_secret_key", mode="before")
    @classmethod
    def _valeur_vide_vaut_absente(cls, valeur: object) -> object:
        # Une variable posée à vide (comme `database_url`) vaut « absente », pas une erreur de démarrage.
        return None if valeur == "" else valeur

    @field_validator("supabase_url")
    @classmethod
    def _adresse_du_projet_seulement(
        cls, adresse: AnyHttpUrl | None, info: ValidationInfo
    ) -> AnyHttpUrl | None:
        """L'origine du projet, rien d'autre : elle donne `iss` et reçoit la clé secrète."""
        if adresse is None:
            return None
        hote = (adresse.host or "").strip("[]")
        if (
            adresse.path not in ("", "/")  # un chemin donnerait un `iss` faux sans rien dire
            or adresse.query
            or adresse.fragment
            or adresse.username
            or adresse.password
            or not _est_un_hote(hote)
            or adresse.port == 0
        ):
            raise ValueError("supabase_url : l'adresse du projet seulement, sans chemin ni requête.")
        # La clé secrète voyage vers cette adresse : jamais en clair, sauf vers la pile locale.
        if adresse.scheme == "http" and not (info.data.get("env") is Env.local and hote in HOTES_LOCAUX):
            raise ValueError("supabase_url : https obligatoire (http seulement vers l'hôte local, en local).")
        return adresse

    @property
    def emetteur_des_jetons(self) -> str | None:
        """La revendication `iss` que PostgREST pose pour une personne connectée : `<projet>/auth/v1`."""
        return f"{str(self.supabase_url).rstrip('/')}/auth/v1" if self.supabase_url else None

    @property
    def relais_exige(self) -> bool:
        return self.env is not Env.local

    @field_validator("supabase_secret_key")
    @classmethod
    def _cle_secrete_transmissible(cls, valeur: SecretStr | None) -> SecretStr | None:
        """La clé voyage dans un en-tête : ASCII visible seulement (un défaut serait recopié par httpx)."""
        if valeur is None:
            return None
        if not est_valeur_d_en_tete(valeur.get_secret_value()):
            raise ValueError("supabase_secret_key : caractères ASCII visibles seulement, non vide.")
        return valeur

    @model_validator(mode="after")
    def _la_cle_secrete_exige_l_adresse(self) -> Self:
        if self.supabase_secret_key is not None and self.supabase_url is None:
            raise ValueError("supabase_secret_key sans supabase_url : poser l'adresse du projet aussi.")
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
