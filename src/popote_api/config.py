import re
from enum import StrEnum
from functools import lru_cache
from ipaddress import ip_address
from typing import Self

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32
LONGUEUR_MINIMALE_DU_POIVRE = 32
HOTES_LOCAUX = frozenset({"127.0.0.1", "localhost", "::1"})
FORME_D_UN_NOM_D_HOTE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")


def est_valeur_d_en_tete(valeur: str) -> bool:
    """Vrai si la valeur voyage dans un en-tête HTTP sans erreur : ASCII visible, sans espace, non vide.

    Un défaut ferait recopier la valeur, donc la clé, par la bibliothèque HTTP dans son message d'erreur.
    """
    return bool(valeur) and valeur.isascii() and valeur.isprintable() and " " not in valeur


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
    # Le poivre des clés HMAC du journal et des limites (`security/empreintes.py`). Facultatif tant que le
    # conteneur d'essai ne l'a pas : sans lui hors local, les clés manquent (journal sans clés, avertissement
    # au démarrage) ; en local il est tiré au hasard par processus. Posé, il fait 32 caractères au moins.
    identity_pepper: SecretStr | None = None
    # Les limites de connexion, comptées en base (`security/limites_base.py`, migration 0138). Les défauts
    # sont ceux de la spec § 3.6 : 5 essais par compte et 20 par IP en 15 min, blocage de 15 min qui double
    # jusqu'à 60 min ; 3 demandes de réinitialisation par heure et par (e-mail, IP).
    connexion_essais_par_compte: int = Field(default=5, ge=1, le=1000)
    connexion_essais_par_ip: int = Field(default=20, ge=1, le=10000)
    connexion_fenetre_s: int = Field(default=900, ge=1, le=86400)
    connexion_attente_max_s: int = Field(default=3600, ge=1, le=86400)
    reinitialisation_essais: int = Field(default=3, ge=1, le=100)
    reinitialisation_fenetre_s: int = Field(default=3600, ge=1, le=86400)
    # Clés de signature des routes `/internal/*` (spec § 3.10). Facultatives pour l'instant : sans
    # `internal_secret`, toute route interne répond 404 (fermé par défaut) et le démarrage avertit.
    # `internal_secret_precedent` sert la rotation : le nouveau secret va en `internal_secret`, l'ancien ici,
    # puis on retire l'ancien.
    internal_secret: SecretStr | None = None
    internal_secret_precedent: SecretStr | None = None
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
    def secrets_internes(self) -> tuple[bytes, ...]:
        """Les secrets qui signent les routes internes, le courant d'abord ; vide : routes fermées."""
        secrets = (self.internal_secret, self.internal_secret_precedent)
        return tuple(s.get_secret_value().encode("ascii") for s in secrets if s and s.get_secret_value())

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
    def _le_plafond_d_attente_couvre_la_fenetre(self) -> Self:
        # La base refuse un plafond plus court que la fenêtre : échouer au démarrage plutôt qu'à la connexion.
        if self.connexion_attente_max_s < self.connexion_fenetre_s:
            raise ValueError("connexion_attente_max_s : au moins connexion_fenetre_s.")
        return self

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
    def _controle_les_secrets_internes(self) -> Self:
        # Une variable posée à vide vaut « absente » ; un secret posé doit être sûr, dans tout environnement.
        for nom in ("internal_secret", "internal_secret_precedent"):
            valeur = getattr(self, nom)
            secret = valeur.get_secret_value() if valeur else ""
            if secret and not secret.isascii():
                raise ValueError(f"{nom} : caractères ASCII uniquement.")
            if secret and len(secret) < LONGUEUR_MINIMALE_DU_SECRET:
                raise ValueError(f"{nom} : {LONGUEUR_MINIMALE_DU_SECRET} caractères au moins.")
        secrets = self.secrets_internes
        relais = self.relay_secret.get_secret_value().encode() if self.relay_secret else b""
        if len(set(secrets)) < len(secrets) or (relais and relais in secrets):
            # Le Worker du relais connaît `relay_secret` : égal à la clé interne, il pourrait signer.
            raise ValueError("Les secrets internes et celui du relais doivent être trois valeurs distinctes.")
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

    @model_validator(mode="after")
    def _la_liste_de_fuites_reste_active_hors_local(self) -> Self:
        if self.relais_exige and self.breach_check is not BreachCheck.hibp:
            raise ValueError("breach_check : seule la valeur « hibp » est permise hors local.")
        return self
