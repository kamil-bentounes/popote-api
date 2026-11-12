"""La signature HMAC des requêtes internes (spec § 3.10) : le format, sa lecture, sa vérification.

`X-Popote-Signature: t=<secondes unix>,v1=<hex>` ;
`v1 = HMAC-SHA256(secret, "<t>.<MÉTHODE>.<chemin brut>.<sha256 hex du corps>")`.
Le chemin est celui des octets reçus (`raw_path`), jamais le chemin décodé : deux écritures d'une même adresse
ne se confondent pas. Ce module est pur (ni requête, ni horloge, ni journal) ; la dépendance FastAPI qui s'en
sert est `api.internes`. Le message est séparé par des points ; la méthode et le chemin n'en sont pas
protégés, mais aucune route n'accepte une méthode inventée et le chemin commence toujours par `/internal/`.
"""

import hashlib
import hmac
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

PREFIXE_INTERNE = "/internal/"
EN_TETE = "X-Popote-Signature"
FENETRE_S = 300  # écart d'horloge toléré, dans les deux sens (spec § 3.10)
LONGUEUR_MAX_DE_L_EN_TETE = 512
NOMBRE_MAX_DE_V1 = 4  # le secret courant, le précédent, et de la marge
# Posée sur l'état de la requête par la dépendance quand la signature est bonne. Les gestionnaires d'erreurs
# s'en servent : une erreur qui précède la dépendance (méthode, corps mal formé) ne révèle pas la route.
ETAT_SIGNATURE_VERIFIEE = "signature_verifiee"

_INSTANT = re.compile(r"0|[1-9][0-9]{0,11}")  # sans zéro de tête : une seule écriture par instant
_EMPREINTE = re.compile(r"[0-9a-f]{64}")
_CLE_DE_VERSION = re.compile(r"v[0-9]+")


class RaisonDeRefus(StrEnum):
    """Pourquoi une requête interne est refusée. Journalisée seule : jamais une valeur reçue."""

    SANS_CLE = "sans_cle"
    CHEMIN_BRUT_ABSENT = "chemin_brut_absent"
    REQUETE_PRESENTE = "chaine_de_requete"
    EN_TETE_ABSENT = "en_tete_absent"
    EN_TETE_REPETE = "en_tete_repete"
    EN_TETE_MAL_FORME = "en_tete_mal_forme"
    HORS_FENETRE = "hors_fenetre"
    CORPS_INCOMPLET = "corps_incomplet"
    SIGNATURE_FAUSSE = "signature_fausse"


class SignatureRefusee(Exception):
    """La requête interne n'est pas authentique. `raison` dit pourquoi, pour le journal seulement."""

    def __init__(self, raison: RaisonDeRefus) -> None:
        super().__init__(raison.value)
        self.raison = raison


@dataclass(frozen=True)
class EnTeteSigne:
    instant: int
    empreintes: tuple[bytes, ...]  # les `v1` reçus, décodés : 32 octets chacun


def _message(instant: int, methode: str, chemin: bytes, corps: bytes) -> bytes:
    return f"{instant}.{methode}.".encode() + chemin + b"." + hashlib.sha256(corps).hexdigest().encode()


def _empreinte(secret: bytes, instant: int, methode: str, chemin: bytes, corps: bytes) -> bytes:
    return hmac.digest(secret, _message(instant, methode, chemin, corps), "sha256")


def signe(secret: bytes, methode: str, chemin: bytes, corps: bytes, instant: int) -> str:
    """La valeur de l'en-tête `X-Popote-Signature` pour cette requête, signée à l'`instant` donné."""
    empreinte = _empreinte(secret, instant, methode.upper(), chemin, corps).hex()
    return f"t={instant},v1={empreinte}"


def lit_l_en_tete(valeur: str, maintenant: float) -> EnTeteSigne:
    """Lit et contrôle la forme et la fraîcheur de l'en-tête, sans toucher au corps ni au secret.

    Refuse tout ce qui n'est pas exactement `t=<chiffres ASCII>` suivi d'au moins un `v1=<64 hex minuscules>`
    : un autre champ, un champ répété, un instant signé ou en chiffres non ASCII. Les `v<n>` d'une autre
    version sont ignorés (la forme peut évoluer), mais bornés comme le reste.
    """
    if len(valeur) > LONGUEUR_MAX_DE_L_EN_TETE:
        raise SignatureRefusee(RaisonDeRefus.EN_TETE_MAL_FORME)
    instants: list[str] = []
    empreintes: list[str] = []
    for morceau in valeur.split(","):
        cle, separateur, contenu = morceau.partition("=")
        if not separateur:
            raise SignatureRefusee(RaisonDeRefus.EN_TETE_MAL_FORME)
        if cle == "t":
            instants.append(contenu)
        elif cle == "v1":
            empreintes.append(contenu)
        elif not _CLE_DE_VERSION.fullmatch(cle):
            raise SignatureRefusee(RaisonDeRefus.EN_TETE_MAL_FORME)
    if (
        len(instants) != 1
        or not _INSTANT.fullmatch(instants[0])
        or not 1 <= len(empreintes) <= NOMBRE_MAX_DE_V1
        or not all(_EMPREINTE.fullmatch(e) for e in empreintes)
    ):
        raise SignatureRefusee(RaisonDeRefus.EN_TETE_MAL_FORME)
    instant = int(instants[0])
    if abs(maintenant - instant) > FENETRE_S:
        raise SignatureRefusee(RaisonDeRefus.HORS_FENETRE)
    return EnTeteSigne(instant, tuple(bytes.fromhex(e) for e in empreintes))


def verifie(
    secrets: Sequence[bytes], en_tete: EnTeteSigne, methode: str, chemin: bytes, corps: bytes
) -> None:
    """Lève `SignatureRefusee` si aucun `v1` ne s'obtient avec l'un des secrets (courant, précédent).

    Chaque couple est comparé, sans court-circuit, par `hmac.compare_digest` sur des octets : le temps ne dit
    ni quel secret ni quel octet a manqué.
    """
    reconnue = False
    for secret in secrets:
        attendue = _empreinte(secret, en_tete.instant, methode, chemin, corps)
        for recue in en_tete.empreintes:
            reconnue |= hmac.compare_digest(attendue, recue)
    if not reconnue:
        raise SignatureRefusee(RaisonDeRefus.SIGNATURE_FAUSSE)
