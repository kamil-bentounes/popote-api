import re
from enum import StrEnum
from functools import lru_cache
from ipaddress import ip_address
from typing import Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LONGUEUR_MINIMALE_DU_SECRET = 32
LONGUEUR_MINIMALE_DU_POIVRE = 32
HOTES_LOCAUX = frozenset({"127.0.0.1", "localhost", "::1"})
# L'adresse d'expédition : ASCII, une seule arobase, un domaine à points ; aucun blanc ni saut de ligne
# (elle s'écrit dans le champ `from` de l'envoi).
FORME_D_UNE_ADRESSE_D_EXPEDITION = re.compile(
    r"[A-Za-z0-9_%+-]+(\.[A-Za-z0-9_%+-]+)*@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+"
)
# Le seul domaine vérifié chez TEM : un expéditeur d'un autre domaine est refusé à chaque envoi.
DOMAINE_D_ENVOI_VERIFIE = "notre-popote.fr"
LONGUEUR_MAX_DU_NOM_D_EXPEDITEUR = 60
# Lettres sans glyphe (hangul, braille vide) : un nom qui en porte s'afficherait avec un blanc.
REMPLISSAGES_INVISIBLES = frozenset("\u115f\u1160\u3164\uffa0\u2800")
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
# Clés d'accès (WebAuthn) : le RP ID et les origines d'où le navigateur appelle `navigator.credentials`, par
# environnement. Aucun aperçu `*.workers.dev` : leur hôte ne peut pas avoir pour suffixe le RP ID de l'essai.
# `127.0.0.1` n'y figure pas non plus : une adresse IP n'est pas un RP ID valide (W3C WebAuthn § 5.1.3).
WEBAUTHN_PAR_ENV: dict[str, tuple[str, frozenset[str]]] = {
    "prod": ("notre-popote.fr", frozenset({"https://notre-popote.fr"})),
    "essai": ("essai.notre-popote.fr", frozenset({"https://essai.notre-popote.fr"})),
    "local": ("localhost", frozenset({"http://localhost:5173"})),
}
HOTE_LOCAL_DES_CLES = "localhost"
# Hors local, le RP ID est ce domaine ou un sous-domaine : ni un suffixe public (`workers.dev`) ni le
# domaine de quelqu'un d'autre ne peuvent être posés par erreur.
DOMAINE_DES_CLES = "notre-popote.fr"
PORTS_PAR_DEFAUT = {"http": 80, "https": 443}
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


class MailProvider(StrEnum):
    aucun = "aucun"  # aucun envoi : le code de connexion et les invitations sont inopérants (le défaut)
    local = "local"  # une boîte en mémoire (`BoiteDeTest`) : local seulement
    scaleway = "scaleway"  # l'envoi réel par Scaleway Transactional Email (`infra/mail_scaleway.py`)


class BreachCheck(StrEnum):
    hibp = "hibp"  # Pwned Passwords (API « range »)
    off = "off"  # aucune vérification : local seulement


def _est_une_adresse_ip(hote: str) -> bool:
    try:
        ip_address(hote.strip("[]"))
    except ValueError:
        return False
    return True


def _est_local(hote: str) -> bool:
    return hote == HOTE_LOCAL_DES_CLES or hote.endswith(f".{HOTE_LOCAL_DES_CLES}")


def hote_de_l_origine_de_cle(origine: str, env: Env) -> str:
    """L'hôte d'une origine de clé d'accès, ou `ValueError` si ce n'est pas l'origine que le navigateur écrit.

    Le navigateur écrit `schéma://hôte[:port]` en minuscules, sans barre finale ni port par défaut : la
    bibliothèque compare cette chaîne telle quelle, une origine qui s'en écarte ne servirait jamais.
    Hors local : https seulement, sans port, jamais `localhost` ni une adresse IP. En local : http n'est admis
    que pour `localhost`.
    """
    try:
        morceaux = urlsplit(origine)
        hote, port = morceaux.hostname, morceaux.port
    except ValueError as erreur:
        raise ValueError("une origine mal formée") from erreur
    if hote is None or morceaux.scheme not in PORTS_PAR_DEFAUT or _est_une_adresse_ip(hote):
        raise ValueError("une origine http(s) avec un nom d'hôte, jamais une adresse IP")
    if port == PORTS_PAR_DEFAUT[morceaux.scheme] or port == 0:
        raise ValueError("un port par défaut ou nul ne s'écrit pas dans une origine")
    ecrite = f"{morceaux.scheme}://{hote}" + (f":{port}" if port is not None else "")
    if ecrite != origine or FORME_D_UN_NOM_D_HOTE.fullmatch(hote) is None:
        raise ValueError(
            "l'origine telle que le navigateur l'écrit : schéma://hôte[:port], minuscules, sans chemin"
        )
    if env is not Env.local and (morceaux.scheme != "https" or port is not None or _est_local(hote)):
        raise ValueError("hors local : https, sans port, jamais localhost")
    if env is Env.local and morceaux.scheme == "http" and not _est_local(hote):
        raise ValueError("en local, http ne passe que pour localhost")
    return hote


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
    # jusqu'à 60 min ; `reinitialisation_*` : 3 demandes par heure, réglage mort retiré en S15.
    connexion_essais_par_compte: int = Field(default=5, ge=1, le=1000)
    connexion_essais_par_ip: int = Field(default=20, ge=1, le=10000)
    connexion_fenetre_s: int = Field(default=900, ge=1, le=86400)
    # Routes publiques d'invitation (B11) : par IP (/64 en IPv6) et par lien, par fenêtre, sans escalade.
    invitation_essais_par_ip: int = Field(default=30, ge=1, le=10000)
    invitation_essais_par_lien: int = Field(default=10, ge=1, le=10000)
    invitation_fenetre_s: int = Field(default=900, ge=1, le=86400)
    connexion_attente_max_s: int = Field(default=3600, ge=1, le=86400)
    # La demande de code par mail (`security/code_de_connexion.py`, migration 0147) : 10 demandes par IP et
    # 3 par (adresse, IP) par fenêtre de 15 min, 6 par adresse par heure ; sans escalade (le créneau de trop
    # attend la fin de la fenêtre). Le coupe-circuit global compte les mails envoyés, jamais les demandes.
    code_demandes_par_ip: int = Field(default=10, ge=1, le=10000)
    code_demandes_par_paire: int = Field(default=3, ge=1, le=10000)
    code_demandes_par_compte: int = Field(default=6, ge=1, le=10000)
    code_fenetre_s: int = Field(default=900, ge=1, le=86400)
    code_fenetre_compte_s: int = Field(default=3600, ge=1, le=86400)
    mail_global_par_fenetre: int = Field(default=60, ge=1, le=10000)
    mail_global_fenetre_s: int = Field(default=3600, ge=1, le=86400)
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

    # L'envoi des mails (`infra/mails.py`). `local` ne se pose qu'en local. `scaleway` exige la clé d'envoi
    # et le projet ; sa clé n'est lue que par `infra/mail_scaleway.py` (test d'architecture). Sans fournisseur
    # (`aucun`), hors local, l'application démarre avec un avertissement : le refus n'est armé qu'en S7.
    mail_provider: MailProvider = MailProvider.aucun
    # La clé d'API dédiée à l'envoi (application IAM qui n'a que `TransactionalEmailEmailApiCreate`).
    scaleway_tem_secret_key: SecretStr | None = None
    scaleway_tem_project_id: UUID | None = None
    # L'expéditeur, sur le domaine vérifié chez TEM (`notre-popote.fr`). Sûrs dans tout environnement.
    mail_from_address: str = "bonjour@notre-popote.fr"
    mail_from_name: str = "Popote"
    # L'origine publique du front, où pointent les liens : `<public_base_url>/invitation#<jeton>`.
    public_base_url: AnyHttpUrl | None = None

    # Clés d'accès (`infra/webauthn.py`). Sans valeur, le RP ID et les origines viennent de
    # `WEBAUTHN_PAR_ENV` (`rp_id_webauthn`, `origines_webauthn`) ; les poser sert une adresse d'essai
    # différente, et le démarrage refuse tout ce qui n'est pas une origine https dont le RP ID est un
    # suffixe. `webauthn_origins` : une liste séparée par des virgules.
    webauthn_rp_name: str = Field("Popote", min_length=1, max_length=64)
    webauthn_rp_id: str | None = None
    webauthn_origins: str | None = None

    # Le SHA du commit, posé dans l'image au build : le déploiement s'assure que c'est bien elle qui répond.
    version: str = Field("inconnue", pattern=r"^[A-Za-z0-9._-]{1,64}$")

    # Faux seulement dans les tests : le journal JSON remplace alors la configuration d'uvicorn.
    json_logs: bool = True
    # Le nom du cookie de session ne se change qu'en local, où `__Host-` et `Secure` ne passent pas partout
    # sur `http://localhost` : hors local, c'est `NOM_DU_COOKIE_DE_SESSION`, un autre nom est une erreur.
    session_cookie_name: str | None = None
    # `Secure` ne se retire qu'en local (http://localhost) ; ailleurs, le retirer est une erreur de démarrage.
    session_cookie_secure: bool = True

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

    @field_validator("scaleway_tem_secret_key", "scaleway_tem_project_id", mode="before")
    @classmethod
    def _reglage_d_envoi_vide_vaut_absent(cls, valeur: object) -> object:
        return None if valeur == "" else valeur

    @field_validator("mail_from_address")
    @classmethod
    def _adresse_d_expedition_bien_formee(cls, adresse: str) -> str:
        local = adresse.partition("@")[0]
        if (
            FORME_D_UNE_ADRESSE_D_EXPEDITION.fullmatch(adresse) is None
            or len(local) > 64
            or len(adresse) > 254
            or len(adresse.rpartition(".")[2]) < 2  # un domaine de tête d'une lettre n'existe pas
            or adresse.rpartition("@")[2] != DOMAINE_D_ENVOI_VERIFIE
        ):
            raise ValueError(
                f"mail_from_address : une adresse simple de {DOMAINE_D_ENVOI_VERIFIE} (ASCII, sans blanc)."
            )
        return adresse

    @field_validator("mail_from_name")
    @classmethod
    def _nom_d_expediteur_bien_forme(cls, nom: str) -> str:
        if (
            not nom.strip()
            or len(nom) > LONGUEUR_MAX_DU_NOM_D_EXPEDITEUR
            or not nom.isprintable()  # refuse retours à la ligne et caractères de contrôle
            or any(c in '"<>,;:@\\' for c in nom)  # séparent ou ferment une adresse dans un en-tête `From`
            or nom != nom.strip()
            or any(c in REMPLISSAGES_INVISIBLES for c in nom)
        ):
            raise ValueError(
                f"mail_from_name : un nom affichable, {LONGUEUR_MAX_DU_NOM_D_EXPEDITEUR} caractères au plus."
            )
        return nom

    @model_validator(mode="after")
    def _scaleway_exige_la_cle_et_le_projet(self) -> Self:
        if self.mail_provider is not MailProvider.scaleway:
            return self
        for nom in ("scaleway_tem_secret_key", "scaleway_tem_project_id"):
            if getattr(self, nom) is None:
                raise ValueError(f"{nom} est obligatoire avec mail_provider=scaleway.")
        return self

    @field_validator("webauthn_rp_id", "webauthn_origins", mode="before")
    @classmethod
    def _valeur_de_cle_vide_vaut_absente(cls, valeur: object) -> object:
        return None if valeur == "" else valeur

    @field_validator("public_base_url", mode="before")
    @classmethod
    def _adresse_publique_vide_vaut_absente(cls, valeur: object) -> object:
        return None if valeur == "" else valeur

    @field_validator("public_base_url")
    @classmethod
    def _origine_du_front_seulement(
        cls, adresse: AnyHttpUrl | None, info: ValidationInfo
    ) -> AnyHttpUrl | None:
        """L'origine, rien d'autre : un chemin, une requête ou un fragment fausseraient le lien du mail."""
        if adresse is None:
            return None
        hote = (adresse.host or "").strip("[]")
        if (
            adresse.path not in ("", "/")
            or adresse.query
            or adresse.fragment
            or adresse.username
            or adresse.password
            or not _est_un_hote(hote)
            or adresse.port == 0
        ):
            raise ValueError("public_base_url : l'origine du front seulement, sans chemin ni requête.")
        if adresse.scheme == "http" and not (info.data.get("env") is Env.local and hote in HOTES_LOCAUX):
            raise ValueError(
                "public_base_url : https obligatoire (http seulement vers l'hôte local, en local)."
            )
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
    def rp_id_webauthn(self) -> str:
        """Le RP ID des clés d'accès : celui qui est posé, sinon celui de l'environnement."""
        return self.webauthn_rp_id or WEBAUTHN_PAR_ENV[self.env.value][0]

    @property
    def origines_webauthn(self) -> frozenset[str]:
        """Les origines d'où une réponse de clé est admise : exactes, jamais déduites de la requête."""
        if self.webauthn_origins is None:
            return WEBAUTHN_PAR_ENV[self.env.value][1]
        return frozenset(origine.strip() for origine in self.webauthn_origins.split(","))

    @model_validator(mode="after")
    def _regle_les_cles_d_acces(self) -> Self:
        rp_id = self.rp_id_webauthn
        # Le RP ID est le suffixe de l'hôte de chaque origine (plus bas) : une adresse IP, `localhost` hors
        # local ou une écriture non canonique ne passent donc pas. Reste le nom sans point (`com`).
        if "." not in rp_id and rp_id != HOTE_LOCAL_DES_CLES:
            raise ValueError("webauthn_rp_id : un nom de domaine (localhost en local seulement).")
        if (
            self.env is not Env.local
            and rp_id != DOMAINE_DES_CLES
            and not rp_id.endswith(f".{DOMAINE_DES_CLES}")
        ):
            raise ValueError(f"webauthn_rp_id : {DOMAINE_DES_CLES} ou l'un de ses sous-domaines hors local.")
        for origine in self.origines_webauthn:
            try:
                hote = hote_de_l_origine_de_cle(origine, self.env)
            except ValueError as erreur:
                raise ValueError(f"webauthn_origins : {erreur}.") from erreur
            if hote != rp_id and not hote.endswith(f".{rp_id}"):
                raise ValueError("webauthn_rp_id : l'hôte de chaque origine, ou un domaine parent.")
        return self

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
        if self.env is not Env.local and not self.session_cookie_secure:
            raise ValueError("session_cookie_secure ne se retire qu'en local.")
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
    def _la_boite_locale_reste_locale(self) -> Self:
        if self.relais_exige and self.mail_provider is MailProvider.local:
            raise ValueError("mail_provider : « local » n'est permis qu'en local.")
        return self

    @model_validator(mode="after")
    def _la_liste_de_fuites_reste_active_hors_local(self) -> Self:
        if self.relais_exige and self.breach_check is not BreachCheck.hibp:
            raise ValueError("breach_check : seule la valeur « hibp » est permise hors local.")
        return self
