"""Les textes des mails : du texte clair, court, en français. Pur : ni réseau, ni horloge, ni journal.

Chaque réalisation d'`EnvoiMail` (`infra/mails.py`) écrit ses mails avec ces fonctions, jamais avec ses
propres phrases. Deux règles : le code n'est JAMAIS dans l'objet (le fournisseur garde l'objet), et un
prénom n'entre jamais dans un texte sans passer par `prenom_affichable`.
"""

import unicodedata
from datetime import datetime
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # `mails` importe ce module : l'import ne se fait que pour le typage
    from popote_api.infra.mails import MessageCode, MessageInvitation

# TEM exige un objet d'au moins 10 caractères.
OBJET_DU_CODE: Final = "Ton code de connexion Popote"
OBJET_DE_L_INVITATION: Final = "Invitation à rejoindre un foyer sur Popote"
REPLI_DU_PRENOM: Final = "Quelqu'un"
LONGUEUR_MAX_DU_PRENOM: Final = 30
_SEPARATEURS_DU_PRENOM: Final = frozenset(" -'\u2019")  # espace, tiret, apostrophes droite et typographique
MARQUES_DE_SUITE_MAX: Final = (
    3  # voyelles et tons des écritures indiennes ou thaïe : trois au plus sur une lettre
)
# Catégorie Lo mais invisibles : un prénom fait de ces seuls caractères s'afficherait vide.
_REMPLISSAGES_INVISIBLES: Final = frozenset("\u115f\u1160\u3164\uffa0")
_FUSEAU: Final = ZoneInfo("Europe/Paris")


def prenom_valide(texte: str) -> str | None:
    """Le prénom nettoyé s'il est présentable, sinon `None`.

    Présentable : des lettres Unicode, chacune suivie d'au plus trois marques combinantes (écritures
    indiennes, thaïe, arabe vocalisé), des espaces, des tirets et des apostrophes (droite ou typographique),
    30 caractères au plus, une lettre visible au moins. NFC d'abord : « é » décomposé vaut « é ».
    """
    prenom = unicodedata.normalize("NFC", texte).strip()
    if not prenom or len(prenom) > LONGUEUR_MAX_DU_PRENOM:
        return None
    marques = 0
    sur_une_lettre = False  # une marque combinante suit une lettre, jamais le début ni un séparateur
    for caractere in prenom:
        if unicodedata.category(caractere) in ("Mn", "Mc"):
            marques += 1
            if not sur_une_lettre or marques > MARQUES_DE_SUITE_MAX:
                return None
        elif caractere.isalpha() or caractere in _SEPARATEURS_DU_PRENOM:
            marques = 0
            sur_une_lettre = caractere.isalpha()
        else:
            return None
    return prenom if _a_une_lettre_visible(prenom) else None


def _a_une_lettre_visible(prenom: str) -> bool:
    return any(c.isalpha() and c not in _REMPLISSAGES_INVISIBLES for c in prenom)


def prenom_affichable(texte: str) -> str:
    """Le prénom à écrire dans un mail : le sien s'il est présentable, sinon un repli neutre."""
    return prenom_valide(texte) or REPLI_DU_PRENOM


def texte_du_code(message: "MessageCode") -> str:
    minutes = f"{message.validite_min} minute{'s' if message.validite_min > 1 else ''}"
    return (
        f"Ton code Popote est {message.code}. Il est valable {minutes}. "
        "Si tu n'as rien demandé, ignore ce message."
    )


def _date(quand: datetime) -> str:
    return quand.astimezone(_FUSEAU).strftime("%d/%m/%Y à %H h %M")


def texte_de_l_invitation(message: "MessageInvitation") -> str:
    invite = prenom_valide(message.prenom_invite)
    hote = prenom_affichable(message.prenom_hote)
    return "\n\n".join(
        [
            f"Bonjour {invite}," if invite else "Bonjour,",
            f"{hote} t'invite à rejoindre son foyer sur Popote.",
            f"Pour accepter, ouvre ce lien : {message.lien}",
            f"Ce lien est valable jusqu'au {_date(message.expire_le)}. Si tu en as reçu un autre avant, "
            "celui-ci le remplace. Si tu ne connais pas cette personne, ignore ce message.",
        ]
    )
