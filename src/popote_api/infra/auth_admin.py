"""Le client d'administration de Supabase Auth (GoTrue) : créer, changer le mot de passe, supprimer un compte.

L'API ne détient jamais un mot de passe : elle le passe ici, une fois, à Auth, puis l'oublie (spec § 4).
Ce module est le seul, avec celui des photos, à lire la clé secrète du projet (spec § 5.1).

Choix de l'en-tête : la clé `sb_secret_…` va dans `apikey` seul. La preuve 1 (`docs/preuves-0.2.md`) montre
que les routes d'administration l'acceptent seule ou doublée d'un `Authorization: Bearer` ; un seul en-tête
c'est une seule place où la clé voyage, et `Authorization` attend un JWT, ce que cette clé n'est pas.

Garde-fous : délais finis, aucune reprise (un `cree_compte` rejoué pourrait créer un compte que l'appelant
ne connaît pas), redirections refusées (la clé ne suit pas un `Location`), et jamais le message d'Auth :
il recopie l'adresse e-mail. Seuls le statut HTTP et le `error_code` d'Auth, s'il a la forme d'un code,
sont gardés dans l'exception ; elle se journalise sans risque.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from fastapi import Request
from pydantic import SecretStr

from popote_api.config import Settings, est_valeur_d_en_tete

journal = logging.getLogger(__name__)

DELAI_CONNEXION_S = 3.0
DELAI_LECTURE_S = 10.0
# Les délais d'httpx valent par étape : un serveur qui goutte à goutte les relancerait sans fin.
DELAI_TOTAL_S = 15.0
# Une réponse d'administration tient en quelques centaines d'octets : au-delà, ce n'est pas Auth.
OCTETS_MAX_REPONSE = 64 * 1024
OCTETS_MAX_MOT_DE_PASSE = 72  # au-delà, bcrypt tronque en silence : Auth refuse, nous aussi, avant l'appel
MARQUE_CREATEUR = "popote-api"
CHEMIN_DES_COMPTES = "/auth/v1/admin/users"
CODES_COMPTE_EXISTANT = frozenset({"email_exists", "user_already_exists"})
CODE_MOT_DE_PASSE_FAIBLE = "weak_password"
CODE_COMPTE_INCONNU = "user_not_found"
# Un code d'Auth est de l'ASCII en minuscules ; tout autre texte ne passe pas dans une exception.
FORME_D_UN_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


class AuthAdminError(Exception):
    """Base des erreurs de l'administration d'Auth. Le texte n'en contient ni e-mail ni mot de passe."""


class AuthIndisponible(AuthAdminError):
    """Auth n'a pas pu faire l'opération : non configuré, injoignable, trop lent ou en erreur. Rend 503."""


class ReponseAuthInattendue(AuthIndisponible):
    """Auth a répondu autrement que par un succès ou une erreur connue (statut ou corps imprévu)."""

    def __init__(self, status: int, code_auth: str | None, message: str) -> None:
        super().__init__(f"{message} (HTTP {status}, code={code_auth})")
        self.status, self.code_auth = status, code_auth


class CompteDejaExistant(AuthAdminError):
    """Un compte porte déjà cette adresse (`email_exists`)."""


class MotDePasseRefuseParAuth(AuthAdminError):
    """Le mot de passe est inutilisable : refusé par Auth (`weak_password`) ou non transmissible."""


def _transmissible(texte: str) -> bool:
    """Vrai si le texte part en UTF-8 sans NUL : un substitut isolé ou un NUL n'a pas de bonne forme."""
    try:
        texte.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return "\x00" not in texte


@dataclass(frozen=True)
class Retour:
    """Ce qu'Auth a répondu : le statut et un corps déjà borné. Pas de lecture sans limite."""

    status: int
    corps: bytes

    @property
    def reussi(self) -> bool:
        return 200 <= self.status < 300

    def objet_json(self) -> dict[str, Any] | None:
        """Le corps s'il est un objet JSON, sinon `None` (page de mandataire, tableau, texte)."""
        try:
            contenu: Any = json.loads(self.corps)
        except (ValueError, RecursionError):  # RecursionError : un corps de 200 000 crochets imbriqués
            return None
        return contenu if isinstance(contenu, dict) else None

    def code_d_auth(self) -> str | None:
        code = (self.objet_json() or {}).get("error_code")
        return code if isinstance(code, str) and FORME_D_UN_CODE.fullmatch(code) else None


class AuthAdmin:
    """Les trois opérations d'administration d'Auth. Sans état partagé : un client HTTP par appel.

    Une opération est rare (création, changement, suppression d'un compte) : une connexion neuve par appel
    coûte moins qu'un client à fermer et à surveiller. Non configuré (`url` ou `cle` à `None`), chaque
    opération lève `AuthIndisponible` sans rien envoyer.
    """

    def __init__(
        self,
        url: str | None,
        cle: SecretStr | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if cle is not None and not est_valeur_d_en_tete(cle.get_secret_value()):
            # Sinon h11 recopierait la clé dans son message d'erreur, et ce message finirait au journal.
            raise ValueError("Clé d'administration non transmissible dans un en-tête.")
        self._url = url
        self._cle = cle
        self._transport = transport

    def __repr__(self) -> str:
        return f"AuthAdmin(configure={self._url is not None and self._cle is not None})"

    async def cree_compte(self, email: str, mot_de_passe: str) -> UUID:
        """Crée un compte (e-mail confirmé, aucun message envoyé, marque `app_metadata.cree_par`).

        `email` est déjà normalisé par l'appelant. Rend l'identifiant du compte. Lève `CompteDejaExistant`,
        `MotDePasseRefuseParAuth`, `AuthIndisponible`. Jamais rejoué : après `AuthIndisponible` le compte
        peut exister quand même, c'est à l'appelant de compenser ou de contrôler. Une réponse `200` dont
        l'identifiant est illisible lève `ReponseAuthInattendue` alors que le compte existe.
        """
        if not _transmissible(email):
            raise ValueError("Adresse non transmissible à Auth.")
        self._exige_un_mot_de_passe_transmissible(mot_de_passe)
        reponse = await self._appelle(
            "POST",
            CHEMIN_DES_COMPTES,
            {
                "email": email,
                "password": mot_de_passe,
                "email_confirm": True,
                "app_metadata": {"cree_par": MARQUE_CREATEUR},
            },
        )
        if not reponse.reussi:
            raise self._echec(reponse)
        try:
            return UUID((reponse.objet_json() or {})["id"])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ReponseAuthInattendue(
                reponse.status, None, "Réponse d'Auth illisible à la création d'un compte"
            ) from None

    async def change_mot_de_passe(self, identifiant: UUID, mot_de_passe: str) -> None:
        """Remplace le mot de passe du compte. Lève `MotDePasseRefuseParAuth` ou `AuthIndisponible`.

        Un identifiant que Auth ne connaît pas lève `ReponseAuthInattendue` (`code=user_not_found`).
        """
        self._exige_un_mot_de_passe_transmissible(mot_de_passe)
        reponse = await self._appelle("PUT", _chemin_du_compte(identifiant), {"password": mot_de_passe})
        if not reponse.reussi:
            raise self._echec(reponse)
        # Auth rend le compte modifié : sa présence, avec le bon identifiant, distingue un vrai succès
        # d'une page de mandataire ou de portail captif répondue en 200.
        if (reponse.objet_json() or {}).get("id") != str(identifiant):
            raise ReponseAuthInattendue(reponse.status, None, "Réponse d'Auth illisible au changement")

    async def supprime_compte(self, identifiant: UUID) -> None:
        """Supprime le compte ; déjà supprimé (`404 user_not_found`) vaut succès. Lève `AuthIndisponible`.

        Un `404` d'une autre origine (mauvaise adresse, mandataire) n'est pas un succès.
        """
        reponse = await self._appelle("DELETE", _chemin_du_compte(identifiant), None)
        if reponse.status == 404 and reponse.code_d_auth() == CODE_COMPTE_INCONNU:
            return
        if not reponse.reussi:
            raise self._echec(reponse)
        if reponse.corps and reponse.objet_json() is None:  # un corps vide est admis, une page HTML non
            raise ReponseAuthInattendue(reponse.status, None, "Réponse d'Auth illisible à la suppression")

    @staticmethod
    def _exige_un_mot_de_passe_transmissible(mot_de_passe: str) -> None:
        # Le contenu n'entre jamais dans le message : seul le motif est dit.
        if not _transmissible(mot_de_passe) or len(mot_de_passe.encode()) > OCTETS_MAX_MOT_DE_PASSE:
            raise MotDePasseRefuseParAuth("Mot de passe non transmissible à Auth (octets, nul ou encodage).")

    async def _appelle(self, methode: str, chemin: str, corps: dict[str, Any] | None) -> Retour:
        if self._url is None or self._cle is None:
            raise AuthIndisponible("L'administration d'Auth n'est pas configurée.")
        en_tetes = {
            "apikey": self._cle.get_secret_value(),
            "Accept": "application/json",
            "Accept-Encoding": "identity",  # Auth n'a rien à compresser : on ne le demande pas
        }
        delais = httpx.Timeout(DELAI_LECTURE_S, connect=DELAI_CONNEXION_S, pool=DELAI_CONNEXION_S)
        try:
            async with asyncio.timeout(DELAI_TOTAL_S):
                # trust_env=False : ni HTTP(S)_PROXY ni SSL_CERT_* du poste ne détournent la clé secrète.
                async with httpx.AsyncClient(
                    timeout=delais, transport=self._transport, follow_redirects=False, trust_env=False
                ) as client:
                    async with client.stream(
                        methode, self._url + chemin, headers=en_tetes, json=corps
                    ) as reponse:
                        return Retour(reponse.status_code, await _lit_borne(reponse))
        except (httpx.HTTPError, httpx.InvalidURL, TimeoutError) as erreur:
            raise AuthIndisponible("Auth est injoignable ou trop lent.") from erreur

    @staticmethod
    def _echec(reponse: Retour) -> AuthAdminError:
        code = reponse.code_d_auth()
        if code in CODES_COMPTE_EXISTANT:
            return CompteDejaExistant("Un compte existe déjà pour cette adresse.")
        if code == CODE_MOT_DE_PASSE_FAIBLE:
            return MotDePasseRefuseParAuth("Auth a refusé le mot de passe.")
        return ReponseAuthInattendue(reponse.status, code, "Auth a refusé l'opération")


async def _lit_borne(reponse: httpx.Response) -> bytes:
    corps = bytearray()
    async for morceau in reponse.aiter_bytes():
        corps += morceau
        if len(corps) > OCTETS_MAX_REPONSE:
            raise ReponseAuthInattendue(reponse.status_code, None, "Réponse d'Auth trop grosse")
    return bytes(corps)


def _chemin_du_compte(identifiant: UUID) -> str:
    """Le chemin d'un compte. Un identifiant qui n'est pas un UUID n'entre jamais dans une adresse."""
    if not isinstance(identifiant, UUID):
        raise TypeError("L'identifiant d'un compte est un UUID.")
    return f"{CHEMIN_DES_COMPTES}/{identifiant}"


def cree_auth_admin(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> AuthAdmin:
    """Le client de l'application. Non configuré : un avertissement au démarrage, 503 à chaque usage."""
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        journal.warning(
            "Administration d'Auth non configurée (POPOTE_SUPABASE_URL, POPOTE_SUPABASE_SECRET_KEY) : "
            "toute opération sur un compte rendra 503."
        )
        return AuthAdmin(None, None, transport=transport)
    return AuthAdmin(settings.supabase_url, settings.supabase_secret_key, transport=transport)


def auth_admin_de(request: Request) -> AuthAdmin:
    """La dépendance FastAPI qui rend le client de l'application (`app.state.auth_admin`)."""
    admin: AuthAdmin = request.app.state.auth_admin
    return admin
