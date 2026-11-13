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
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx
from pydantic import SecretStr

from popote_api.config import DOMAINE_D_ENVOI_VERIFIE, MailProvider, Settings
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
FORME_D_UNE_CLE: Final = re.compile(r"[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")
ETATS_ACCEPTES: Final = frozenset({"new", "sending", "sent"})
ETATS_REFUSES: Final = frozenset({"failed", "canceled"})  # les seuls états qui excluent un envoi
PASSERELLES: Final = frozenset({502, 504})


@dataclass(frozen=True, slots=True)
class Expediteur:
    """L'expéditeur : une adresse du domaine vérifié chez TEM, sinon chaque envoi serait refusé (4xx)."""

    adresse: str
    nom: str

    def __post_init__(self) -> None:
        if self.adresse.rpartition("@")[2] != DOMAINE_D_ENVOI_VERIFIE:
            raise ValueError(
                f"Expéditeur : une adresse de {DOMAINE_D_ENVOI_VERIFIE} (domaine vérifié chez TEM)."
            )


class _ReponseTropGrosse(Exception):
    """Interne : la réponse dépasse `OCTETS_MAX_REPONSE`."""


class _CauseDeTransport(Exception):
    """Interne : le type d'une erreur de transport d'httpx, sans sa requête ni son message."""


@dataclass(frozen=True, slots=True)
class _Reponse:
    statut: int
    attente_s: float
    contenu: bytes | None = field(repr=False)  # `None` : corps non lu (hors 2xx), illisible ou trop gros


@dataclass(frozen=True, slots=True)
class _Issue:
    """Le résultat d'une tentative : pas une exception, qui garderait sa pile et donc `charge`."""

    acceptee: bool
    raison: str = ""
    reprenable: bool = False
    inconnue: bool = False  # le mail a pu partir
    attente_s: float = ATTENTE_AVANT_LA_REPRISE_S
    type_de_la_cause: str | None = None  # le type d'une erreur de transport, jamais son texte


@dataclass(slots=True)
class _Suivi:
    """Ce que l'envoi sait de ses tentatives, pour dire si le mail a pu partir quand le délai total tombe."""

    en_vol: bool = False  # une requête est partie et sa réponse n'est pas revenue
    inconnue: bool = False  # une tentative terminée a laissé l'issue inconnue


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
        if FORME_D_UNE_CLE.fullmatch(propre) is None:
            # Une clé Scaleway est un UUID ; toute autre forme est une faute de dépôt, ou, avec un blanc ou
            # un caractère hors ASCII, ferait recopier la clé par h11 dans son message (donc au journal).
            raise ValueError("Clé d'envoi Scaleway : un UUID est attendu.")
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
        # TEM compte à la seconde : on compare les deux heures tronquées, comme le fournisseur les verra.
        send_before = _a_la_seconde(enveloppe.expire_le) if enveloppe.expire_le is not None else None
        if send_before is not None and send_before <= _a_la_seconde(self._horloge()):
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
            charge["send_before"] = send_before.strftime("%Y-%m-%dT%H:%M:%SZ")
        suivi = _Suivi()
        issue: _Issue | None = None
        try:
            async with asyncio.timeout(DELAI_TOTAL_S):
                issue = await self._essaie(charge, suivi)
        except TimeoutError:
            pass  # `issue` reste `None` ; on lève plus bas, hors du bloc : ni cause ni contexte
        if issue is None:
            journal.warning("Envoi Scaleway TEM abandonné : délai total dépassé")
            # Une requête en vol, ou une tentative déjà incertaine : le mail a pu partir.
            raise MailIndisponible(
                "Scaleway TEM : délai total dépassé.", issue_inconnue=suivi.en_vol or suivi.inconnue
            )
        if issue.acceptee:
            return
        journal.warning("Envoi Scaleway TEM abandonné : %s", issue.raison)
        cause = _CauseDeTransport(issue.type_de_la_cause) if issue.type_de_la_cause else None
        raise MailIndisponible(f"Scaleway TEM : {issue.raison}.", issue_inconnue=issue.inconnue) from cause

    async def _essaie(self, charge: dict[str, Any], suivi: _Suivi) -> _Issue:
        """Une tentative, puis au plus une reprise ; rend l'issue finale (`inconnue` cumule les deux)."""
        issue = await self._tente(charge, suivi)
        if issue.reprenable:
            journal.warning("Envoi Scaleway TEM : %s, une reprise", issue.raison)
            await self._pause(issue.attente_s)
            issue = await self._tente(charge, suivi)
        # Une première tentative sans réponse a pu faire partir le mail, quoi que dise la seconde.
        return replace(issue, inconnue=suivi.inconnue)

    async def _tente(self, charge: dict[str, Any], suivi: _Suivi) -> _Issue:
        """Une tentative. Rend son issue ; aucune exception d'httpx ne sort (elle porte la requête)."""
        suivi.en_vol = True
        issue: _Issue
        try:
            issue = _juge(await self._poste(charge))
        except httpx.TimeoutException as erreur:
            issue = _Issue(
                False, "délai de lecture ou de connexion", True, True, type_de_la_cause=type(erreur).__name__
            )
        except httpx.HTTPError as erreur:
            issue = _Issue(False, "coupure de connexion", True, True, type_de_la_cause=type(erreur).__name__)
        except Exception as erreur:  # un transport qui lève autre chose qu'httpx : jamais de reprise
            issue = _Issue(False, "erreur inattendue", False, True, type_de_la_cause=type(erreur).__name__)
        suivi.en_vol = False
        suivi.inconnue = suivi.inconnue or issue.inconnue
        return issue

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
                        pass  # `contenu` reste `None` : `_juge` en fait une issue inconnue
                return vue
        except httpx.HTTPError:
            if vue is not None:
                # Un statut est arrivé, puis le corps ou la fermeture casse : le statut décide (sous un 2xx le
                # mail a pu partir, sous un 4xx la reprise ne changerait rien, un 5xx se reprend).
                return vue
            raise


def _a_la_seconde(quand: datetime) -> datetime:
    """UTC, microsecondes retirées : jamais plus tard que l'instant reçu."""
    return quand.astimezone(UTC).replace(microsecond=0)


def _juge(reponse: _Reponse) -> _Issue:
    """L'issue d'une réponse reçue : acceptée, à reprendre (5xx) ou définitive."""
    if reponse.statut >= 500:
        # Une passerelle (502, 504) peut répondre après que TEM a accepté le mail : issue inconnue.
        return _Issue(False, "réponse 5xx", True, reponse.statut in PASSERELLES, reponse.attente_s)
    if not 200 <= reponse.statut < 300:
        return _Issue(False, f"réponse {reponse.statut // 100}xx")
    # Sous un 2xx illisible, TEM a pu accepter le mail : l'issue est inconnue.
    if reponse.contenu is None:
        return _Issue(False, "réponse illisible ou trop grosse", inconnue=True)
    etat = _etat_du_premier_mail(reponse.contenu)
    if etat in ETATS_ACCEPTES:
        return _Issue(True)
    if etat in ETATS_REFUSES:
        return _Issue(False, "mail non accepté")
    return _Issue(False, "réponse illisible", inconnue=True)  # corps sans état, ou « unknown » de TEM


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
