"""Le cookie de session : le seul endroit qui écrit ses attributs (spec § 4, « Session »).

`HttpOnly` (le script de la page ne le lit jamais), `Secure` et `__Host-` (le navigateur refuse tout autre
`Path` ou un `Domain`), `SameSite=Lax`. `Max-Age` de 90 jours : le serveur tient en plus les 30 jours
d'inactivité, le navigateur n'a pas à le savoir. La connexion, la réauthentification et le changement de mot
de passe passent par cette fabrique : un seul jeu d'attributs.
"""

from typing import Final

from fastapi import Response

from popote_api.config import Settings

DUREE_DU_COOKIE_S: Final = 90 * 24 * 3600


def pose_le_cookie_de_session(reponse: Response, reglages: Settings, jeton: str) -> None:
    """Pose `Set-Cookie` sur la réponse ; sans `Domain`, `Path=/`."""
    reponse.set_cookie(
        key=reglages.nom_du_cookie_de_session,
        value=jeton,
        max_age=DUREE_DU_COOKIE_S,
        path="/",
        secure=reglages.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def efface_le_cookie_de_session(reponse: Response, reglages: Settings) -> None:
    """Vide le cookie (`Max-Age=0`) avec les mêmes attributs que `pose_le_cookie_de_session`.

    Sans eux le navigateur ne reconnaît pas le cookie à remplacer (`__Host-` veut `Secure` et `Path=/`)."""
    reponse.delete_cookie(
        key=reglages.nom_du_cookie_de_session,
        path="/",
        secure=reglages.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
