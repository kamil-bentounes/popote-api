"""Le code de connexion par mail : six chiffres tirés au hasard, et ce que la demande promet (0.4bis S5).

Les valeurs sont celles du plan : un code vaut 10 minutes (borne haute de NIST SP 800-63B-4 § 3.1.3.2 et de
l'ASVS 6.5.5, et `CHECK` de `login_code.expires_at`) ; un code de moins de 60 s n'est pas remplacé (la base le
décide, `demande_un_code`). Pur : ni base, ni réseau, ni horloge.
"""

import secrets
from typing import Final

CHIFFRES_DU_CODE: Final = 6
VIE_DU_CODE_S: Final = 600
VALIDITE_DU_CODE_MIN: Final = VIE_DU_CODE_S // 60
RENVOI_APRES_S: Final = 60


def code_neuf() -> str:
    """Un code de six chiffres, zéros de tête compris, tiré par le générateur cryptographique (ASVS 6.5.3)."""
    return f"{secrets.randbelow(10**CHIFFRES_DU_CODE):0{CHIFFRES_DU_CODE}d}"
