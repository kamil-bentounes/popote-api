"""Les textes des mails : du texte clair, court, en français. Pur : ni réseau, ni horloge, ni journal.

Chaque réalisation d'`EnvoiMail` (`infra/mails.py`) écrit ses mails avec ces fonctions, jamais avec ses
propres phrases. Deux règles : le code n'est JAMAIS dans l'objet (le fournisseur garde l'objet), et un
prénom n'entre jamais dans un texte sans passer par `prenom_affichable`.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from popote_api.config import HOTES_LOCAUX
from popote_api.infra.comptes import adresse_valide

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
# Invisibles ou sans largeur, de toute catégorie : un prénom qui en porte un, où que ce soit, est refusé (un
# « Marc\u3164Support » s'afficherait « Marc Support » : il imiterait un nom officiel).
_INVISIBLES: Final = _REMPLISSAGES_INVISIBLES | frozenset(
    "\u2800\u2060\u2061\u2062\u2063\u2064\ufeff" + "".join(chr(c) for c in range(0x200B, 0x2010))
)
# Marques combinantes qui ne dessinent rien (sélecteurs de variante, jonction de graphèmes, voyelles khmères
# inhérentes, sélecteurs mongols) : elles passeraient la règle des marques et s'afficheraient comme du vide.
_MARQUES_INVISIBLES: Final = frozenset(
    "".join(chr(c) for c in (0x034F, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180F, *range(0xFE00, 0xFE10)))
)
# Un prénom n'a qu'UNE écriture (latin, grec, cyrillique, devanagari...) : un « Popote » aux omicrons grecs,
# des lettres pleine chasse ou mathématiques (leur nom ne commence pas par LATIN) ou un titlo cyrillique sur
# une lettre latine passeraient pour un prénom officiel. Une marque « COMBINING <ÉCRITURE> … » compte pour
# son écriture.
_ECRITURES_DES_MARQUES: Final = frozenset({"LATIN", "GREEK", "CYRILLIC"})
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
    if unicodedata.normalize("NFKC", prenom) != prenom:  # pleine chasse, mathématiques, ligatures...
        return None
    marques = 0
    sur_une_lettre = False  # une marque combinante suit une lettre, jamais le début ni un séparateur
    for caractere in prenom:
        if caractere in _INVISIBLES or caractere in _MARQUES_INVISIBLES:
            return None
        if unicodedata.category(caractere) in ("Mn", "Mc"):
            marques += 1
            if not sur_une_lettre or marques > MARQUES_DE_SUITE_MAX:
                return None
        elif caractere.isalpha() or caractere in _SEPARATEURS_DU_PRENOM:
            marques = 0
            sur_une_lettre = caractere.isalpha()
        else:
            return None
    if not _a_une_lettre_visible(prenom) or len(_ecritures(prenom)) > 1:
        return None
    return prenom


def _ecritures(prenom: str) -> set[str]:
    """Les écritures du prénom : le premier mot du nom Unicode de chaque lettre ou marque d'une écriture."""
    ecritures: set[str] = set()
    for caractere in prenom:
        if not (caractere.isalpha() or unicodedata.category(caractere) in ("Mn", "Mc")):
            continue
        mots = unicodedata.name(caractere, "").split(" ")
        if mots[0] == "COMBINING":
            mots = mots[1:2] if mots[1:2] and mots[1] in _ECRITURES_DES_MARQUES else []
        ecritures.update(mots[:1])
    return ecritures


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


# --- L'enveloppe rendue : la seule chose que les réalisations envoient ---------------------------------

OBJETS_AUTORISES: Final = frozenset({OBJET_DU_CODE, OBJET_DE_L_INVITATION})
_CACHET: Final = object()  # seul ce module le détient : une enveloppe ne se fabrique pas ailleurs
FORME_DU_JETON_DE_LIEN: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")
CHEMIN_DU_LIEN: Final = "/invitation"


LONGUEUR_MAX_DE_LA_PARTIE_LOCALE: Final = 64


def destinataire_valide(valeur: object) -> bool:
    """Une seule adresse : ASCII, sans virgule ni caractère de contrôle ou de direction, 254 au plus, un
    domaine à point (`infra.comptes.adresse_valide`, plus le point : aucun domaine sans point n'est admis)."""
    if not isinstance(valeur, str) or not adresse_valide(valeur):
        return False
    local, _, domaine = valeur.rpartition("@")
    return len(local) <= LONGUEUR_MAX_DE_LA_PARTIE_LOCALE and "." in domaine


@dataclass(frozen=True, slots=True)
class Enveloppe:
    """Ce qu'une réalisation d'`EnvoiMail` transmet au fournisseur : destinataire, objet, texte, rien d'autre.

    Seules `enveloppe_du_code` et `enveloppe_de_l_invitation` la fabriquent (le cachet est privé à ce module,
    un test d'architecture cherche tout autre appel) : l'objet est donc l'un des objets autorisés, constants,
    sans code ni prénom ni lien. Le `repr` masque tout : adresse, code et lien s'y trouveraient.
    """

    destinataire: str
    objet: str
    texte: str
    cachet: object = field(repr=False, compare=False)
    # Un code : l'heure après laquelle il est refusé ; le fournisseur ne le livre pas après (`send_before`).
    expire_le: datetime | None = None

    def __post_init__(self) -> None:
        if self.cachet is not _CACHET:
            raise TypeError("Enveloppe : fabriquée par les fonctions de mails_textes, pas autrement.")
        if type(self.objet) is not str or self.objet not in OBJETS_AUTORISES:  # pas une sous-classe de str
            raise ValueError("Enveloppe : objet hors de l'ensemble autorisé (constant, sans code ni prénom).")
        if not destinataire_valide(self.destinataire) or not self.texte:
            raise ValueError("Enveloppe : destinataire invalide ou texte vide.")
        if self.expire_le is not None and self.expire_le.utcoffset() is None:
            raise ValueError("Enveloppe : expire_le doit porter un fuseau horaire.")

    def __repr__(self) -> str:
        return "Enveloppe(destinataire=…, objet=…, texte=…)"


def enveloppe_du_code(message: "MessageCode", maintenant: datetime) -> Enveloppe:
    """`maintenant` (avec fuseau) : l'instant de l'envoi ; le code expire `validite_min` minutes plus tard."""
    expire_le = maintenant + timedelta(minutes=message.validite_min)
    return Enveloppe(message.destinataire, OBJET_DU_CODE, texte_du_code(message), _CACHET, expire_le)


def lien_d_invitation_admis(lien: str, origines: frozenset[str]) -> bool:
    """Vrai si le lien est `<origine du front>/invitation#<jeton>` : une origine de la liste, rien d'autre.

    Refuse une partie utilisateur (`https://notre-popote.fr@evil.example/…` : l'hôte suit l'`@`), un port non
    admis, un autre chemin, une requête, et `http` ailleurs que vers l'hôte local.
    """
    if not isinstance(lien, str):
        return False
    try:
        parties = urlsplit(lien)
        parties.port  # noqa: B018 (une lecture qui lève `ValueError` si le port est invalide)
    except ValueError:
        return False
    # `urlsplit` retire en silence tabulations, sauts de ligne et blancs de tête, et une requête vide (`?#`) :
    # la forme rendue doit être celle reçue.
    if parties.geturl() != lien:
        return False
    if "@" in parties.netloc or parties.scheme not in ("https", "http"):
        return False
    if parties.scheme == "http" and (parties.hostname or "") not in HOTES_LOCAUX:
        return False
    return (
        f"{parties.scheme}://{parties.netloc.lower()}" in origines
        and parties.path == CHEMIN_DU_LIEN
        and not parties.query
        and FORME_DU_JETON_DE_LIEN.fullmatch(parties.fragment) is not None
    )


def enveloppe_de_l_invitation(message: "MessageInvitation", origines: frozenset[str]) -> Enveloppe:
    """`origines` : celles du front de l'environnement (`Settings.origines`)."""
    if not lien_d_invitation_admis(message.lien, origines):
        raise ValueError("Invitation : le lien n'est pas celui d'une origine du front.")
    return Enveloppe(message.destinataire, OBJET_DE_L_INVITATION, texte_de_l_invitation(message), _CACHET)
