"""Le résumé de l'agent utilisateur gardé avec une session : un navigateur et un système, en familles courtes.

Le texte brut de l'agent n'est ni stocké ni journalisé (ses versions précises distinguent un
appareil) ; aucune adresse IP ni localisation n'est gardée avec la session. Les familles sont celles des
contraintes `login_session.browser` et `login_session.os` (migration 0139) : un test compare les listes.
"""

from dataclasses import dataclass
from typing import Final

NAVIGATEURS: Final = ("chrome", "firefox", "safari", "edge", "autre")
SYSTEMES: Final = ("windows", "macos", "linux", "android", "ios", "autre")
# Un agent plus long n'est pas lu : borne le travail fait sur une valeur envoyée par le client.
LONGUEUR_LUE: Final = 512


@dataclass(frozen=True, slots=True)
class Appareil:
    navigateur: str = "autre"
    systeme: str = "autre"


def resume_agent(agent: str | None) -> Appareil:
    """Familles reconnues dans l'en-tête `User-Agent`, `autre` sinon ; jamais d'erreur, jamais le texte."""
    if not agent:
        return Appareil()
    texte = agent[:LONGUEUR_LUE].lower()
    # L'ordre compte : Edge et Chrome se disent aussi « safari » ; iOS se dit aussi « mac os x ».
    if "edg/" in texte or "edga/" in texte or "edgios/" in texte:
        navigateur = "edge"
    elif "firefox/" in texte or "fxios/" in texte:
        navigateur = "firefox"
    elif "chrome/" in texte or "crios/" in texte:
        navigateur = "chrome"
    elif "safari/" in texte:
        navigateur = "safari"
    else:
        navigateur = "autre"
    if "iphone" in texte or "ipad" in texte or "ipod" in texte:
        systeme = "ios"
    elif "android" in texte:
        systeme = "android"
    elif "windows" in texte:
        systeme = "windows"
    elif "mac os x" in texte or "macintosh" in texte:
        systeme = "macos"
    elif "linux" in texte or "x11" in texte:
        systeme = "linux"
    else:
        systeme = "autre"
    return Appareil(navigateur, systeme)
