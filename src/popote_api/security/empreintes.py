"""Les clés HMAC du journal de sécurité et des limites : une adresse ou une IP ne s'y lit jamais.

`cle_compte` et `cle_ip` rendent 32 octets (HMAC-SHA256 avec le poivre) : de quoi relier des événements d'un
même compte ou d'une même IP, sans pouvoir remonter à l'adresse ni tester une adresse sans le poivre. Chacune
a son étiquette : la clé d'un compte et celle d'une IP ne peuvent pas se confondre.

SANS POIVRE (`POPOTE_IDENTITY_PEPPER` absent hors local) : le conteneur d'essai ne l'a pas encore. Les deux
clés rendent alors `None`, le journal écrit l'événement sans clé (colonnes nulles : on perd le lien entre
événements, pas l'événement), et un avertissement part au démarrage. Un appelant qui COMPTE par clé (les
limites de connexion) ne peut pas se contenter de `None` : il doit refuser, jamais compter « sans clé » (une
limite qui ne limite personne). En local le poivre est tiré au hasard par processus : les clés sont stables le
temps du processus, et ne survivent pas à son arrêt.
"""

import hashlib
import hmac
import secrets
import unicodedata
from ipaddress import IPv6Address, IPv6Network, ip_address

from pydantic import SecretStr

from popote_api.config import Env, Settings

LONGUEUR_DU_POIVRE_LOCAL = 32
# Étiquettes de séparation : une clé de compte n'est jamais une clé d'IP, même si les textes se ressemblent.
ETIQUETTE_COMPTE = b"popote/compte/v1\x00"
ETIQUETTE_IP = b"popote/ip/v1\x00"
# Une requête sans adresse (relais absent ou invalide) : une clé commune, jamais « personne ».
IP_ABSENTE = "sans-ip"
PREFIXE_IPV6 = 64  # une IPv6 se regroupe par /64 : un foyer reçoit au moins un /64 (B12)


def email_normalise(email: str) -> str:
    """La seule forme d'une adresse : NFKC, minuscules, espaces de bord retirés.

    Elle sert à la clé de limite, à la recherche en base et à la création du compte (B24) : jamais deux formes
    pour un même compte. Idempotente. Ne juge pas la validité de l'adresse.
    """
    forme = unicodedata.normalize("NFKC", email).lower()
    return unicodedata.normalize("NFKC", forme).strip()


def ip_canonique(ip: str | None) -> str:
    """L'IPv4 entière, l'IPv6 réduite à son /64, `::ffff:a.b.c.d` ramenée à l'IPv4 ; `sans-ip` si absente."""
    if ip is None:
        return IP_ABSENTE
    adresse = ip_address(ip.strip())
    if isinstance(adresse, IPv6Address):
        if adresse.ipv4_mapped is not None:
            return str(adresse.ipv4_mapped)
        reseau = IPv6Network((adresse.packed, PREFIXE_IPV6), strict=False)
        return str(reseau)
    return str(adresse)


class Empreintes:
    """Fabrique de clés HMAC. Une instance par application ; le poivre n'apparaît dans aucun `repr`."""

    def __init__(self, poivre: SecretStr | None) -> None:
        self._poivre = poivre.get_secret_value().encode() if poivre is not None else None

    @classmethod
    def depuis(cls, reglages: Settings) -> "Empreintes":
        if reglages.identity_pepper is not None:
            return cls(reglages.identity_pepper)
        if reglages.env is Env.local:
            return cls(SecretStr(secrets.token_hex(LONGUEUR_DU_POIVRE_LOCAL)))
        return cls(None)

    @property
    def disponible(self) -> bool:
        return self._poivre is not None

    def _hmac(self, etiquette: bytes, valeur: str) -> bytes | None:
        if self._poivre is None:
            return None
        # `surrogatepass` : un substitut isolé garde une clé distincte plutôt que de lever.
        message = etiquette + valeur.encode("utf-8", "surrogatepass")
        return hmac.new(self._poivre, message, hashlib.sha256).digest()

    def cle_compte(self, email: str) -> bytes | None:
        return self._hmac(ETIQUETTE_COMPTE, email_normalise(email))

    def cle_ip(self, ip: str | None) -> bytes | None:
        return self._hmac(ETIQUETTE_IP, ip_canonique(ip))

    def __repr__(self) -> str:
        return f"Empreintes(disponible={self.disponible})"
