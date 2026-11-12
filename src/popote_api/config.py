import re
from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32
LONGUEUR_MINIMALE_DU_POIVRE = 32
# Le préfixe `__Host-` impose `Secure`, `Path=/` et aucun `Domain` : le navigateur refuse le cookie sinon.
NOM_DU_COOKIE_DE_SESSION = "__Host-popote_session"
# Un nom de cookie est un `token` (RFC 6265 § 4.1.1) ; on n'admet que lettres, chiffres, `_` et `-`.
FORME_D_UN_NOM_DE_COOKIE = re.compile(r"[A-Za-z0-9_-]{1,64}")

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
    # Le poivre des clés HMAC du journal et des limites (`security/empreintes.py`). Facultatif tant que le
    # conteneur d'essai ne l'a pas : sans lui hors local, les clés manquent (journal sans clés, avertissement
    # au démarrage) ; en local il est tiré au hasard par processus. Posé, il fait 32 caractères au moins.
    identity_pepper: SecretStr | None = None
    # Sous-domaine `workers.dev` du compte Cloudflare, pour reconnaître les aperçus de fusion du front.
    # Essai seulement : la prod n'a pas d'aperçu.
    apercu_compte: str | None = None

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

    @field_validator("identity_pepper", mode="before")
    @classmethod
    def _poivre_vide_vaut_absent(cls, valeur: object) -> object:
        return None if valeur == "" else valeur

    @field_validator("identity_pepper")
    @classmethod
    def _poivre_assez_long(cls, poivre: SecretStr | None) -> SecretStr | None:
        if poivre is None:
            return None
        # Un retour à la ligne de fin (secret lu dans un fichier) ne compte ni dans la longueur ni la clé.
        propre = poivre.get_secret_value().strip()
        if len(propre) < LONGUEUR_MINIMALE_DU_POIVRE:
            raise ValueError(f"identity_pepper : {LONGUEUR_MINIMALE_DU_POIVRE} caractères au moins.")
        return SecretStr(propre)

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

    @model_validator(mode="after")
    def _la_liste_de_fuites_reste_active_hors_local(self) -> Self:
        if self.relais_exige and self.breach_check is not BreachCheck.hibp:
            raise ValueError("breach_check : seule la valeur « hibp » est permise hors local.")
        return self
