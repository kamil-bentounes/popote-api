"""Règles des mots de passe (NIST SP 800-63B-4, § 3.1.1.2 ; voir docs/securite.md).

Python pur : aucune entrée-sortie, aucun journal. Un mot de passe ne sort jamais de ces fonctions que
sous la forme de sa version normalisée, et aucun message de défaut ne le recopie.
"""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

LONGUEUR_MINIMALE = 15  # caractères (points de code après NFKC) : mot de passe seul facteur, § 3.1.1.2
LONGUEUR_MAXIMALE = 64  # NIST demande d'en permettre au moins 64
OCTETS_MAXIMAUX = 72  # bcrypt (GoTrue, pgcrypto) ne lit pas au-delà : refuser plutôt que tronquer
POINTEUR_PAR_DEFAUT = "/password"


class CodeDeDefaut(StrEnum):
    trop_court = "trop_court"
    trop_long = "trop_long"
    trop_d_octets = "trop_d_octets"
    caractere_nul = "caractere_nul"
    non_encodable = "non_encodable"


MESSAGES: dict[CodeDeDefaut, str] = {
    CodeDeDefaut.trop_court: f"Trop court : {LONGUEUR_MINIMALE} caractères au minimum.",
    CodeDeDefaut.trop_long: f"Trop long : {LONGUEUR_MAXIMALE} caractères au maximum.",
    CodeDeDefaut.trop_d_octets: (
        f"Trop long : {OCTETS_MAXIMAUX} octets au maximum (les caractères accentués ou spéciaux en prennent "
        "plusieurs)."
    ),
    CodeDeDefaut.caractere_nul: "Le caractère nul n'est pas permis.",
    CodeDeDefaut.non_encodable: "Un caractère n'est pas valide.",
}


@dataclass(frozen=True)
class Defaut:
    """Un défaut du mot de passe proposé. Ne contient jamais le mot de passe."""

    pointeur: str  # JSON Pointer (RFC 6901) du champ du corps, tel que l'attend `ErreurDeChamp.pointer`
    code: CodeDeDefaut
    message: str

    def en_erreur_de_champ(self) -> dict[str, str]:
        """La forme d'un élément de `errors` pour `reponse(..., errors=[...])` (`errors.py`)."""
        return {"pointer": self.pointeur, "message": self.message}


def normalise(mot_de_passe: str) -> str:
    """NFKC. Les espaces sont conservés, jamais coupés."""
    return unicodedata.normalize("NFKC", mot_de_passe)


def _octets(texte: str) -> bytes | None:
    """Les octets UTF-8, ou `None` si le texte n'est pas encodable (substitut isolé)."""
    try:
        return texte.encode("utf-8")
    except UnicodeEncodeError:
        return None


def verifie_nouveau(mot_de_passe: str, pointeur: str = POINTEUR_PAR_DEFAUT) -> list[Defaut]:
    """Les défauts d'un nouveau mot de passe (création, changement, réinitialisation), liste vide si aucun.

    Aucune règle de composition ni de changement imposé (§ 3.1.1.2). Les longueurs se comptent en points de
    code après NFKC. La limite en octets ne se signale que si la limite en caractères passe : un mot de passe
    trop long n'a pas deux défauts pour une même cause.
    """
    normalise_ = normalise(mot_de_passe)
    codes: list[CodeDeDefaut] = []
    if len(normalise_) < LONGUEUR_MINIMALE:
        codes.append(CodeDeDefaut.trop_court)
    if len(normalise_) > LONGUEUR_MAXIMALE:
        codes.append(CodeDeDefaut.trop_long)
    if "\x00" in normalise_:
        codes.append(CodeDeDefaut.caractere_nul)
    octets = _octets(normalise_)
    if octets is None:
        codes.append(CodeDeDefaut.non_encodable)
    elif len(octets) > OCTETS_MAXIMAUX and len(normalise_) <= LONGUEUR_MAXIMALE:
        codes.append(CodeDeDefaut.trop_d_octets)
    return [Defaut(pointeur, code, MESSAGES[code]) for code in codes]


def candidats_de_connexion(mot_de_passe: str) -> tuple[str, ...]:
    """Les formes à essayer contre le hachage enregistré, la normalisée d'abord.

    Les anciens mots de passe ont été hachés bruts par GoTrue : la forme brute suit si elle diffère. Un
    candidat de plus de 72 octets, avec un caractère nul ou non encodable, est écarté : il ne peut pas
    correspondre à un hachage bcrypt et on ne le tronque jamais (tronquer ferait accepter n'importe quelle
    suite). Le corps de la requête borne déjà la taille du mot de passe reçu.
    """
    formes = [normalise(mot_de_passe)]
    if mot_de_passe != formes[0]:
        formes.append(mot_de_passe)
    return tuple(f for f in formes if _essayable(f))


def _essayable(candidat: str) -> bool:
    octets = _octets(candidat)
    return octets is not None and len(octets) <= OCTETS_MAXIMAUX and "\x00" not in candidat
