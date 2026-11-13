"""Ce qu'une adresse doit être pour devenir un compte (B24).

Une liste fermée de caractères ASCII : l'adresse part telle quelle à Auth et se compare par égalité sur la
casse basse en base, jamais comme un motif. On ne juge que la forme ; l'existence d'un compte est l'affaire
de `public.compte_pour_email`.
"""

import re
from typing import Final

LONGUEUR_MAX: Final = 254
# Partie locale : les caractères ASCII imprimables usuels (RFC 5322 « atext »), points seulement entre deux
# caractères ; domaine : des étiquettes de lettres, chiffres et tirets séparées par des points.
_ADRESSE: Final = re.compile(
    r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
)


def adresse_valide(email_normalise: str) -> bool:
    """Vrai pour une adresse DÉJÀ normalisée (`email_normalise`) : un seul `@`, ASCII, 254 au plus."""
    return len(email_normalise) <= LONGUEUR_MAX and _ADRESSE.fullmatch(email_normalise) is not None
