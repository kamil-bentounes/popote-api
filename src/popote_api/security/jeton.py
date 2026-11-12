"""Le jeton de session que porte le cookie : 32 octets tirés au hasard, écrits en base64url sans remplissage.

La base ne garde que son empreinte SHA-256 (spec § 4) : une fuite de la table ne donne aucune session.
Le jeton lui-même naît à la connexion (étape 0.4) ; ici on ne sait que le reconnaître et en tirer l'empreinte.
"""

import base64
import hashlib
import re

# 32 octets en base64url sans remplissage : 43 caractères (RFC 4648 § 5).
FORME_DU_JETON = re.compile(r"[A-Za-z0-9_-]{43}")


class JetonMalFormeError(ValueError):
    """Le cookie n'est pas un jeton que nous aurions écrit. Son contenu n'est jamais recopié ici."""


def empreinte_du_jeton(jeton: str) -> bytes:
    """Le SHA-256 des 32 octets du jeton ; lève `JetonMalFormeError` si ce n'est pas un jeton.

    Le décodage est strict : alphabet et taille exacts, et le jeton doit se ré-encoder à l'identique (les
    derniers bits d'un jeton de 43 caractères sont toujours nuls) : une seule écriture par jeton, et celles
    que nous n'aurions pas produites sont écartées.
    """
    if FORME_DU_JETON.fullmatch(jeton) is None:
        raise JetonMalFormeError("Un jeton fait 43 caractères de l'alphabet base64url.")
    octets = base64.urlsafe_b64decode(jeton + "=")  # la forme est vérifiée : ne peut pas lever
    if base64.urlsafe_b64encode(octets).decode("ascii") != jeton + "=":
        raise JetonMalFormeError("Jeton non canonique.")
    return hashlib.sha256(octets).digest()
