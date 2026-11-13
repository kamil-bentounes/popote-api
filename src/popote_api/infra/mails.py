"""L'envoi des mails, derrière une interface (0.4bis S3 ; l'envoi réel vient avec S4).

Le reste de l'application ne connaît que `EnvoiMail` : deux messages, le code de connexion et l'invitation.
Un message ne se retrouve JAMAIS dans un journal : le code et le lien sont des secrets, l'adresse est une
donnée personnelle (`__repr__` les masque, et les journaux de ce module ne nomment que le type d'une erreur).

Ce que l'appelant peut compter dessus (la demande de code, S5, et l'invitation, S12, s'y appuient) :
- l'envoi se fait APRÈS la réponse HTTP, en tâche d'arrière-plan : un échec ne change jamais la réponse ;
- un envoi qui échoue lève `MailIndisponible` ; l'appelant l'enveloppe dans `envoie_sans_remonter`, qui
  journalise le type de l'erreur seul (jamais l'adresse, le code ni le lien) et ne laisse remonter que
  l'annulation ;
- le délai de 25 s de la requête (`limites.Delai`) englobe la tâche d'arrière-plan : un envoi trop long est
  annulé ;
- un envoi retourné sans erreur veut dire « accepté par le fournisseur », pas « remis » ;
- les textes viennent de `mails_textes.py`, jamais d'une phrase écrite dans une réalisation.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from popote_api.config import MailProvider, Settings

journal = logging.getLogger(__name__)
CHIFFRES_DU_CODE = re.compile(r"[0-9]{6}")
SANS_BLANC = re.compile(r"\S+")
LIEN_WEB = re.compile(r"https?://\S+")


class MailIndisponible(Exception):
    """L'envoi n'a pas pu partir (aucun fournisseur, panne). Son message ne porte ni adresse, ni secret."""


@dataclass(frozen=True, slots=True)
class MessageCode:
    """Le code à six chiffres de connexion ; `validite_min` : combien de minutes il vaut.

    Les tests comparent le texte rendu ou `validite_min`, pas deux messages : le diff d'une assertion qui
    échoue afficherait les codes.
    """

    destinataire: str
    code: str
    validite_min: int

    def __post_init__(self) -> None:
        # Le code et l'adresse s'écrivent tels quels dans un mail : rien d'autre n'y entre.
        if not _correspond(CHIFFRES_DU_CODE, self.code):
            raise ValueError("MessageCode : le code fait six chiffres, rien d'autre")
        if not _correspond(SANS_BLANC, self.destinataire):
            raise ValueError("MessageCode : destinataire vide ou avec un blanc")
        if type(self.validite_min) is not int or self.validite_min < 1:
            raise ValueError("MessageCode : validite_min est un entier d'au moins 1")

    def __repr__(self) -> str:
        return "MessageCode(destinataire=…, code=…, validite_min=…)"


@dataclass(frozen=True, slots=True)
class MessageInvitation:
    """L'invitation d'un foyer ; `lien` : `<public_base_url>/invitation#<jeton>` ; `expire_le` a un fuseau."""

    destinataire: str
    prenom_invite: str
    prenom_hote: str
    lien: str
    expire_le: datetime

    def __post_init__(self) -> None:
        if not _correspond(SANS_BLANC, self.destinataire):
            raise ValueError("MessageInvitation : destinataire vide ou avec un blanc")
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


def cree_envoi_mail(reglages: Settings) -> EnvoiMail:
    return BoiteDeTest() if reglages.mail_provider is MailProvider.local else MailAbsent()


async def envoie_sans_remonter[Message: (MessageCode, MessageInvitation)](
    envoyer: Callable[[Message], Awaitable[None]], message: Message, quoi: str
) -> bool:
    """Envoie un message APRÈS la réponse : vrai s'il est parti, faux s'il a échoué (journalisé).

    Le journal ne porte que `quoi` (un nom fixe : « code », « invitation ») et le type de l'erreur.
    L'annulation (le délai de 25 s de la requête englobe la tâche) se journalise puis repart : jamais avalée.
    """
    try:
        await envoyer(message)
    except asyncio.CancelledError:
        journal.error("Mail (%s) non envoyé : annulé (délai dépassé)", quoi)
        raise
    except Exception as erreur:  # une tâche d'arrière-plan ne fait jamais échouer une réponse déjà partie
        journal.error("Mail (%s) non envoyé : %s", quoi, type(erreur).__name__)
        return False
    return True
