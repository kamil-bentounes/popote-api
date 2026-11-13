"""L'envoi réel des mails par Scaleway Transactional Email (0.4bis S4), derrière `EnvoiMail`.

Source (relue le 13/11/2026) : SDK Go officiel `scaleway-sdk-go/api/tem/v1alpha1/tem_sdk.go` (chemin,
champs de `CreateEmailRequest`, états d'un mail, `send_before`), `internal/auth/token.go` (en-tête
`X-Auth-Token`) et la page « Sending an email using the Transactional Email API » (`html` facultatif ; objet
de 10 caractères au moins). Les liens sont dans `docs/exploitation.md`.

Ce module est le SEUL à lire la clé d'envoi (`scaleway_tem_secret_key`) : un test d'architecture le garde.
Elle ne voyage que dans l'en-tête `X-Auth-Token` d'une requête vers une adresse écrite ici en dur (pas un
réglage : une adresse réglable pourrait détourner la clé). Ni la clé, ni l'adresse du destinataire, ni
l'objet, ni le texte, ni le corps d'une réponse n'entrent dans un journal ou un message d'exception : seuls
le type de l'erreur et la classe du statut HTTP (`4xx`, `5xx`) se disent.

Comportement :
- délai de connexion 3 s, de lecture 5 s, et 15 s au total (reprise et pause comprises) ;
- UNE reprise sur coupure, délai ou `5xx`, après une courte pause (`Retry-After` respecté, plafonné) ;
  AUCUNE sur `4xx` ni redirection (non suivie) ; AUCUNE après un `2xx`, même illisible : le mail a pu partir ;
- succès si le premier mail de la réponse est `new`, `sending` ou `sent` : « accepté par le fournisseur »,
  pas « remis » (l'identifiant du mail n'est pas gardé : un rebond dur ne se voit pas d'ici) ;
- un code porte `send_before` = `enveloppe.expire_le`, l'échéance ABSOLUE fixée une seule fois à la demande du
  code (jamais recalculée ici) : TEM ne le livre pas passé ce délai ; un code déjà expiré n'est pas envoyé ;
- ce module ne voit que l'`Enveloppe` (base `EnvoiParEnveloppe`) : aucun code possible dans l'objet ;
- une panne après l'envoi de la requête (coupure, délai) porte `issue_inconnue` : le mail a pu partir ;
- l'annulation de la tâche (le délai de 25 s de la requête englobe l'envoi) n'est ni avalée ni reprise.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx
from pydantic import SecretStr

from popote_api.config import MailProvider, Settings
from popote_api.infra.mails import EnvoiParEnveloppe, MailIndisponible
from popote_api.infra.mails_textes import Enveloppe

journal = logging.getLogger(__name__)

# TEM n'existe qu'en `fr-par` (documentation, « capabilities and limits »).
URL_DES_MAILS: Final = "https://api.scaleway.com/transactional-email/v1alpha1/regions/fr-par/emails"
DELAI_CONNEXION_S: Final = 3.0
DELAI_LECTURE_S: Final = 5.0
# Les délais d'httpx valent par étape : ce délai-ci borne l'envoi entier, reprise comprise, sous les 25 s
# de la requête (`limites.DELAI_SECONDES`).
DELAI_TOTAL_S: Final = 15.0
ATTENTE_AVANT_LA_REPRISE_S: Final = 0.5
ATTENTE_MAX_S: Final = 3.0
# La réponse de TEM pour un destinataire tient en quelques centaines d'octets : au-delà, ce n'est pas lui.
OCTETS_MAX_REPONSE: Final = 64 * 1024
LONGUEUR_MIN_DE_L_OBJET: Final = 10  # exigence de TEM
ETATS_ACCEPTES: Final = frozenset({"new", "sending", "sent"})


@dataclass(frozen=True, slots=True)
class Expediteur:
    adresse: str
    nom: str


class _ReponseTropGrosse(Exception):
    """Interne : la réponse dépasse `OCTETS_MAX_REPONSE`."""


class _CauseDeTransport(Exception):
    """Interne : le type d'une erreur de transport d'httpx, sans sa requête ni son message."""


@dataclass(frozen=True, slots=True)
class _Reponse:
    statut: int
    attente_s: float
    contenu: bytes | None  # `None` : corps non lu (hors 2xx), illisible ou trop gros


class _Reprise(Exception):
    """Interne : l'échec de cette tentative peut se reprendre ; `attente_s` : la pause avant la suivante."""

    def __init__(
        self, raison: str, attente_s: float = ATTENTE_AVANT_LA_REPRISE_S, *, issue_inconnue: bool = False
    ) -> None:
        super().__init__(raison)
        self.raison, self.attente_s, self.issue_inconnue = raison, attente_s, issue_inconnue


class EnvoiScaleway(EnvoiParEnveloppe):
    """Réalisation d'`EnvoiMail` par l'API de Scaleway TEM. Sans état partagé : un client par envoi."""

    def __init__(
        self,
        cle: SecretStr,
        projet: UUID,
        expediteur: Expediteur,
        origines: frozenset[str],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        maintenant: Callable[[], datetime] = lambda: datetime.now(UTC),
        pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(origines)
        # Un retour à la ligne de fin (secret lu dans un fichier) ne fait pas partie de la clé.
        propre = cle.get_secret_value().strip()
        if not (propre and propre.isascii() and propre.isprintable() and " " not in propre):
            # Sinon h11 recopierait la clé dans son message d'erreur, et ce message finirait au journal.
            raise ValueError("Clé d'envoi Scaleway non transmissible dans un en-tête.")
        self._cle = SecretStr(propre)
        self._projet = projet
        self._expediteur = expediteur
        self._transport = transport
        self._horloge = maintenant  # sert à refuser un code déjà expiré, jamais à fixer son échéance
        self._pause = pause

    def __repr__(self) -> str:
        return "EnvoiScaleway()"

    async def _transmet(self, enveloppe: Enveloppe) -> None:
        objet = enveloppe.objet
        if len(objet) < LONGUEUR_MIN_DE_L_OBJET:
            raise ValueError(f"L'objet d'un mail fait {LONGUEUR_MIN_DE_L_OBJET} caractères au moins (TEM).")
        send_before = enveloppe.expire_le
        if send_before is not None and send_before <= self._horloge():
            journal.warning("Envoi Scaleway TEM abandonné : code déjà expiré")
            raise MailIndisponible("Scaleway TEM : code déjà expiré.")
        charge: dict[str, Any] = {
            "from": {"email": self._expediteur.adresse, "name": self._expediteur.nom},
            "to": [{"email": enveloppe.destinataire}],
            "subject": objet,
            "text": enveloppe.texte,
            "project_id": str(self._projet),
        }
        if send_before is not None:
            # Tronqué à la seconde : jamais plus tard que l'échéance du code.
            charge["send_before"] = send_before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            async with asyncio.timeout(DELAI_TOTAL_S):
                await self._avec_une_reprise(charge)
        except TimeoutError as erreur:
            journal.warning("Envoi Scaleway TEM abandonné : délai total dépassé")
            raise MailIndisponible("Scaleway TEM : délai total dépassé.", issue_inconnue=True) from erreur

    async def _avec_une_reprise(self, charge: dict[str, Any]) -> None:
        try:
            await self._tente(charge)
        except _Reprise as premier:
            journal.warning("Envoi Scaleway TEM : %s, une reprise", premier.raison)
            await self._pause(premier.attente_s)
            try:
                await self._tente(charge)
            except _Reprise as second:
                journal.warning("Envoi Scaleway TEM abandonné : %s", second.raison)
                raise MailIndisponible(
                    f"Scaleway TEM : {second.raison}.", issue_inconnue=second.issue_inconnue
                ) from second.__cause__

    async def _tente(self, charge: dict[str, Any]) -> None:
        """Une tentative. Lève `_Reprise` (reprenable) ou `MailIndisponible` (définitif).

        L'exception d'httpx n'est jamais chaînée : elle porte la requête entière (clé, adresse, texte). On
        n'en garde que le type, dans une cause neuve, et on lève hors du bloc `except` (donc sans contexte).
        """
        try:
            reponse = await self._poste(charge)
        except httpx.TimeoutException as erreur:
            raison, type_de_l_erreur = "délai de lecture ou de connexion", type(erreur).__name__
        except httpx.HTTPError as erreur:
            raison, type_de_l_erreur = "coupure de connexion", type(erreur).__name__
        else:
            _juge(reponse)
            return
        raise _Reprise(raison, issue_inconnue=True) from _CauseDeTransport(type_de_l_erreur)

    async def _poste(self, charge: dict[str, Any]) -> _Reponse:
        en_tetes = {
            "X-Auth-Token": self._cle.get_secret_value(),
            "Accept": "application/json",
            "Accept-Encoding": "identity",  # une réponse de quelques octets : rien à décompresser
        }
        delais = httpx.Timeout(DELAI_LECTURE_S, connect=DELAI_CONNEXION_S, pool=DELAI_CONNEXION_S)
        vue: _Reponse | None = None
        try:
            # trust_env=False : ni HTTP(S)_PROXY ni SSL_CERT_* du poste ne détournent la clé.
            async with (
                httpx.AsyncClient(
                    timeout=delais, transport=self._transport, follow_redirects=False, trust_env=False
                ) as client,
                client.stream("POST", URL_DES_MAILS, headers=en_tetes, json=charge) as reponse,
            ):
                vue = _Reponse(reponse.status_code, _attente_demandee(reponse), None)
                if 200 <= vue.statut < 300:  # le corps ne se lit que sous un 2xx : un 5xx se reprend sans lui
                    try:
                        vue = replace(vue, contenu=await _lit_borne(reponse))
                    except (_ReponseTropGrosse, httpx.HTTPError):
                        pass  # `contenu` reste `None` : `_juge` en fait un échec définitif
                return vue
        except httpx.HTTPError:
            if vue is not None and vue.statut < 500:
                # Statut reçu, puis le corps ou la fermeture casse : sous un 2xx le mail a pu partir, sous un
                # 4xx la reprise ne changerait rien. Jamais de reprise.
                return vue
            raise


def _juge(reponse: _Reponse) -> None:
    """Lève `_Reprise` sous un 5xx, `MailIndisponible` sous tout autre échec ; rend si le mail est accepté."""
    if reponse.statut >= 500:
        raise _Reprise("réponse 5xx", reponse.attente_s)
    if not 200 <= reponse.statut < 300:
        raise _echec_definitif(f"réponse {reponse.statut // 100}xx")
    # Sous un 2xx illisible, TEM a pu accepter le mail : l'issue est inconnue.
    if reponse.contenu is None:
        raise _echec_definitif("réponse illisible ou trop grosse", issue_inconnue=True)
    etat = _etat_du_premier_mail(reponse.contenu)
    if etat is None:
        raise _echec_definitif("réponse illisible", issue_inconnue=True)
    if etat not in ETATS_ACCEPTES:
        raise _echec_definitif("mail non accepté")


def _echec_definitif(raison: str, *, issue_inconnue: bool = False) -> MailIndisponible:
    journal.warning("Envoi Scaleway TEM abandonné : %s", raison)
    return MailIndisponible(f"Scaleway TEM : {raison}.", issue_inconnue=issue_inconnue)


def _etat_du_premier_mail(contenu: bytes) -> str | None:
    """L'état du premier mail de la réponse (`new`, `failed`...), ou `None` si elle n'a pas cette forme."""
    try:
        reponse: Any = json.loads(contenu)
    except (ValueError, RecursionError):  # RecursionError : un corps de 200 000 crochets imbriqués
        return None
    mails = reponse.get("emails") if isinstance(reponse, dict) else None
    if not isinstance(mails, list) or not mails or not isinstance(mails[0], dict):
        return None
    etat = mails[0].get("status")
    return etat if isinstance(etat, str) else None


def _attente_demandee(reponse: httpx.Response) -> float:
    """`Retry-After` en secondes entières (RFC 9110 § 10.2.3), plafonné ; sinon la pause par défaut."""
    valeur = reponse.headers.get("Retry-After", "")
    if valeur.isascii() and valeur.isdigit():
        return min(float(valeur), ATTENTE_MAX_S)
    return ATTENTE_AVANT_LA_REPRISE_S


async def _lit_borne(reponse: httpx.Response) -> bytes:
    """Le corps, borné. Aucun `Content-Encoding` n'est admis : sans lui httpx ne décompresse rien, donc la
    borne porte sur les octets reçus (sinon une bombe de décompression passerait sous la borne)."""
    if reponse.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
        raise _ReponseTropGrosse  # non demandé (`Accept-Encoding: identity`) : ce n'est pas TEM
    corps = bytearray()
    async for morceau in reponse.aiter_bytes():
        corps += morceau
        if len(corps) > OCTETS_MAX_REPONSE:
            raise _ReponseTropGrosse
    return bytes(corps)


def cree_envoi_scaleway(reglages: Settings) -> EnvoiScaleway:
    """L'envoi de l'application. Les réglages sont déjà validés ; on le vérifie encore, sans rien recopier."""
    if (
        reglages.mail_provider is not MailProvider.scaleway
        or reglages.scaleway_tem_secret_key is None
        or reglages.scaleway_tem_project_id is None
    ):
        raise ValueError("Envoi Scaleway : mail_provider=scaleway, clé et projet sont tous requis.")
    return EnvoiScaleway(
        reglages.scaleway_tem_secret_key,
        reglages.scaleway_tem_project_id,
        Expediteur(reglages.mail_from_address, reglages.mail_from_name),
        reglages.origines,
    )
