"""L'envoi des mails, derrière une interface (0.4bis S3 ; l'envoi réel vient avec S4).

Le reste de l'application ne connaît que `EnvoiMail` : deux messages, le code de connexion et l'invitation.
Un message ne se retrouve JAMAIS dans un journal : le code et le lien sont des secrets, l'adresse est une
donnée personnelle (`__repr__` les masque, et les journaux de ce module ne nomment que le type d'une erreur).

Ce que l'appelant peut compter dessus (la demande de code, S5, et l'invitation, S12, s'y appuient) :
- l'envoi se fait APRÈS la réponse HTTP, en tâche d'arrière-plan : un échec ne change jamais la réponse ;
- une réalisation n'envoie que l'`Enveloppe` rendue par `mails_textes` (objet constant, destinataire strict) ;
- un envoi qui échoue lève `MailIndisponible` ; l'appelant l'enveloppe dans `envoie_sans_remonter`, qui
  journalise le type de l'erreur seul (jamais l'adresse, le code ni le lien) et ne laisse remonter que
  l'annulation ;
- le délai de 25 s de la requête (`limites.Delai`) englobe la tâche d'arrière-plan : un envoi trop long est
  annulé ; `envoie_sans_remonter` a de plus son propre délai (20 s) ;
- un envoi retourné sans erreur veut dire « accepté par le fournisseur », pas « remis » ;
- les textes viennent de `mails_textes.py`, jamais d'une phrase écrite dans une réalisation.
"""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from popote_api.config import MailProvider, Settings
from popote_api.infra import mails_textes as textes
from popote_api.infra.mails_textes import Enveloppe, destinataire_valide

journal = logging.getLogger(__name__)
CHIFFRES_DU_CODE = re.compile(r"[0-9]{6}")
LIEN_WEB = re.compile(r"https?://\S+")


class MailIndisponible(Exception):
    """L'envoi n'a pas pu partir (aucun fournisseur, panne). Son message ne porte ni adresse, ni secret.

    `issue_inconnue` : la requête est partie et la réponse manque (coupure, délai) ; le fournisseur a pu
    accepter le mail. Le journal le dit alors, et ne dit jamais « non envoyé ».
    """

    def __init__(self, message: str = "", *, issue_inconnue: bool = False) -> None:
        super().__init__(message)
        self.issue_inconnue = issue_inconnue


@dataclass(frozen=True, slots=True)
class MessageCode:
    """Le code à six chiffres de connexion ; `validite_min` : combien de minutes il vaut (le texte du mail) ;
    `expire_le` : l'instant ABSOLU où la base le refuse (avec fuseau), fixé à la demande et jamais recalculé à
    l'envoi : le fournisseur ne livre pas un code après lui (`send_before`).

    Les tests comparent le texte rendu ou `validite_min`, pas deux messages : le diff d'une assertion qui
    échoue afficherait les codes.
    """

    destinataire: str
    code: str
    validite_min: int
    expire_le: datetime

    def __post_init__(self) -> None:
        # Le code et l'adresse s'écrivent tels quels dans un mail : rien d'autre n'y entre.
        if not _correspond(CHIFFRES_DU_CODE, self.code):
            raise ValueError("MessageCode : le code fait six chiffres, rien d'autre")
        if not destinataire_valide(self.destinataire):
            raise ValueError("MessageCode : destinataire : une seule adresse, forme stricte")
        if type(self.validite_min) is not int or self.validite_min < 1:
            raise ValueError("MessageCode : validite_min est un entier d'au moins 1")
        if not isinstance(self.expire_le, datetime) or self.expire_le.utcoffset() is None:
            raise ValueError("MessageCode : expire_le est une date avec fuseau horaire")

    def __repr__(self) -> str:
        return "MessageCode(destinataire=…, code=…, validite_min=…, expire_le=…)"


@dataclass(frozen=True, slots=True)
class MessageInvitation:
    """L'invitation d'un foyer ; `lien` : `<public_base_url>/invitation#<jeton>` ; `expire_le` a un fuseau."""

    destinataire: str
    prenom_invite: str
    prenom_hote: str
    lien: str
    expire_le: datetime

    def __post_init__(self) -> None:
        if not destinataire_valide(self.destinataire):
            raise ValueError("MessageInvitation : destinataire : une seule adresse, forme stricte")
        if not _correspond(LIEN_WEB, self.lien):
            raise ValueError("MessageInvitation : lien web attendu, sans blanc")
        if self.expire_le.utcoffset() is None:
            raise ValueError("MessageInvitation : expire_le doit porter un fuseau horaire")

    def __repr__(self) -> str:
        return "MessageInvitation(destinataire=…, prenom_invite=…, prenom_hote=…, lien=…, expire_le=…)"


def _correspond(motif: re.Pattern[str], valeur: object) -> bool:
    return isinstance(valeur, str) and motif.fullmatch(valeur) is not None


class EnvoiMail(Protocol):
    async def envoie_le_code(self, message: MessageCode) -> None:
        """Lève `MailIndisponible` si le message n'est pas parti."""

    async def envoie_l_invitation(self, message: MessageInvitation) -> None:
        """Lève `MailIndisponible` si le message n'est pas parti."""


@dataclass(slots=True)
class BoiteDeTest:
    """Garde les messages en mémoire : les tests et le local les relisent."""

    codes: list[MessageCode] = field(default_factory=list)
    invitations: list[MessageInvitation] = field(default_factory=list)
    en_panne: bool = (
        False  # vrai : chaque envoi lève `MailIndisponible`, comme un fournisseur qui ne répond plus
    )

    async def envoie_le_code(self, message: MessageCode) -> None:
        self._verifie_la_panne()
        self.codes.append(message)

    async def envoie_l_invitation(self, message: MessageInvitation) -> None:
        self._verifie_la_panne()
        self.invitations.append(message)

    def _verifie_la_panne(self) -> None:
        if self.en_panne:
            raise MailIndisponible("Boîte de test en panne.")


class MailAbsent:
    """Aucun fournisseur : chaque envoi échoue proprement."""

    async def envoie_le_code(self, message: MessageCode) -> None:
        raise MailIndisponible("Aucun fournisseur de mail configuré (POPOTE_MAIL_PROVIDER=aucun).")

    async def envoie_l_invitation(self, message: MessageInvitation) -> None:
        raise MailIndisponible("Aucun fournisseur de mail configuré (POPOTE_MAIL_PROVIDER=aucun).")


class EnvoiParEnveloppe(ABC):
    """Base de toute réalisation qui envoie pour de bon : elle ne voit QUE l'`Enveloppe`.

    Les deux méthodes de `EnvoiMail` rendent l'enveloppe par `mails_textes` (objet constant, texte,
    destinataire strict, lien d'une origine du front) et la passent à `_transmet`, que la réalisation écrit :
    elle n'a ni le code, ni le lien, ni le prénom sous les yeux, donc ne peut pas les mettre dans l'objet.
    """

    def __init__(self, origines: frozenset[str]) -> None:
        self._origines = origines  # celles du front de l'environnement (`Settings.origines`)

    async def envoie_le_code(self, message: MessageCode) -> None:
        await self._transmet(textes.enveloppe_du_code(message))

    async def envoie_l_invitation(self, message: MessageInvitation) -> None:
        await self._transmet(textes.enveloppe_de_l_invitation(message, self._origines))

    @abstractmethod
    async def _transmet(self, enveloppe: Enveloppe) -> None:
        """Lève `MailIndisponible` si l'enveloppe n'est pas partie."""


def cree_envoi_mail(reglages: Settings) -> EnvoiMail:
    return BoiteDeTest() if reglages.mail_provider is MailProvider.local else MailAbsent()


class TypeDeMail(StrEnum):
    """Les seuls noms écrits au journal : un par sorte de mail, jamais un texte libre."""

    code = "code"
    invitation = "invitation"


# Sous les 25 s de la requête (`limites.DELAI_SECONDES`) et au-dessus des 15 s de l'envoi réel (S4) : un envoi
# bloqué ne garde jamais la tâche ni sa connexion au-delà.
DELAI_D_UN_ENVOI_S = 20.0
# Ce qu'un appelant écrit : l'énumération, ou ses deux littéraux (convertis et vérifiés à l'exécution).
Sorte = TypeDeMail | Literal["code", "invitation"]
MESSAGE_PAR_SORTE: dict[TypeDeMail, type] = {
    TypeDeMail.code: MessageCode,
    TypeDeMail.invitation: MessageInvitation,
}


async def envoie_sans_remonter[Message: (MessageCode, MessageInvitation)](
    envoyer: Callable[[Message], Awaitable[None]], message: Message, quoi: Sorte
) -> bool:
    """Envoie un message APRÈS la réponse : vrai s'il est parti, faux s'il a échoué (journalisé).

    Le journal ne porte que `quoi` (un `TypeDeMail`, vérifié ici : une chaîne libre, qui pourrait contenir une
    adresse ou un code, lève `ValueError`) et le type de l'erreur. L'envoi est borné par son propre délai.
    Une annulation ou un délai pendant l'appel, ou une panne après l'envoi de la requête
    (`MailIndisponible.issue_inconnue`), laisse l'issue INCONNUE : le journal le dit, jamais « non envoyé ».
    L'annulation se journalise puis repart, jamais avalée, même si la réalisation l'a traduite en erreur.
    """
    sorte = TypeDeMail(quoi)  # `ValueError` hors de la liste fermée, même si l'appelant ne type pas
    if type(message) is not MESSAGE_PAR_SORTE[sorte]:
        raise ValueError("Le type de mail ne correspond pas au message.")
    limite = asyncio.timeout(DELAI_D_UN_ENVOI_S)
    try:
        async with limite:
            await envoyer(message)
    except asyncio.CancelledError:
        journal.error("Mail (%s) : annulé pendant l'envoi, issue inconnue (il a pu partir)", sorte.value)
        raise
    except Exception as erreur:  # une tâche d'arrière-plan ne fait jamais échouer une réponse déjà partie
        _laisse_remonter_l_annulation(sorte)
        if limite.expired():
            journal.error(
                "Mail (%s) : délai de l'envoi dépassé, issue inconnue (il a pu partir)", sorte.value
            )
        elif getattr(erreur, "issue_inconnue", False):
            journal.error(
                "Mail (%s) : %s, issue inconnue (il a pu partir)", sorte.value, type(erreur).__name__
            )
        else:
            journal.error("Mail (%s) non envoyé : %s", sorte.value, type(erreur).__name__)
        return False
    _laisse_remonter_l_annulation(sorte)
    return True


def _laisse_remonter_l_annulation(sorte: TypeDeMail) -> None:
    """Une annulation demandée du dehors repart même si la réalisation l'a traduite en erreur ou avalée."""
    tache = asyncio.current_task()
    if tache is not None and tache.cancelling():
        journal.error("Mail (%s) : annulé pendant l'envoi, issue inconnue (il a pu partir)", sorte.value)
        raise asyncio.CancelledError
