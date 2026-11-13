"""L'envoi des mails, derrière une interface (T15a ; l'envoi réel vient avec T16).

Le reste de l'application ne connaît que `EnvoiMail`. Un message ne se retrouve JAMAIS dans un journal : le
lien porte le jeton, l'adresse est une donnée personnelle (`__repr__` les masque, et les journaux de ce module
ne nomment que le type d'une erreur).
"""

from dataclasses import dataclass, field
from typing import Protocol

from popote_api.config import MailProvider, Settings


class MailIndisponible(Exception):
    """L'envoi n'a pas pu partir (aucun fournisseur, panne). Son message ne porte ni adresse ni lien."""


@dataclass(frozen=True, slots=True)
class MessageReinitialisation:
    destinataire: str
    lien: str  # `<public_base_url>/reinitialisation#<jeton>`

    def __repr__(self) -> str:
        return "MessageReinitialisation(destinataire=…, lien=…)"


class EnvoiMail(Protocol):
    async def envoie_la_reinitialisation(self, message: MessageReinitialisation) -> None:
        """Lève `MailIndisponible` si le message n'est pas parti."""


@dataclass(slots=True)
class BoiteDeTest:
    """Garde les messages en mémoire : les tests et le local les relisent."""

    messages: list[MessageReinitialisation] = field(default_factory=list)

    async def envoie_la_reinitialisation(self, message: MessageReinitialisation) -> None:
        self.messages.append(message)


class MailAbsent:
    """Aucun fournisseur : chaque envoi échoue proprement."""

    async def envoie_la_reinitialisation(self, message: MessageReinitialisation) -> None:
        raise MailIndisponible("Aucun fournisseur de mail configuré (POPOTE_MAIL_PROVIDER=aucun).")


def cree_envoi_mail(reglages: Settings) -> EnvoiMail:
    return BoiteDeTest() if reglages.mail_provider is MailProvider.local else MailAbsent()


def lien_de_reinitialisation(origine: str | None, jeton: str) -> str | None:
    """`<origine>/reinitialisation#<jeton>` : le jeton après `#`, que le navigateur n'envoie à personne."""
    if origine is None:
        return None
    return f"{origine.rstrip('/')}/reinitialisation#{jeton}"
