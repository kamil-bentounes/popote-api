"""La garde des gestes sensibles : le mot de passe saisi depuis moins de 5 minutes (spec § 4).

`reauth_at` est posé à la connexion et par `POST /api/v1/me/reauthentication` ; la dépendance le lit sur la
session déjà lue (aucun appel de plus à la base). Plus de `FENETRE_S` secondes avant maintenant (l'horloge de
`app.state.horloge`, que les tests avancent) : `403 reauthentification_requise`.
"""

from datetime import timedelta
from typing import Final

from fastapi import Depends, Request

from popote_api.errors import REAUTHENTIFICATION_REQUISE, Probleme
from popote_api.security.session import PersonneDeLaSession

FENETRE_S: Final = 300
FENETRE: Final = timedelta(seconds=FENETRE_S)


async def exige_reauth(request: Request, personne: PersonneDeLaSession) -> None:
    """Passe à exactement 300 s ; refuse au-delà. À déclarer avec `reponses_erreur(403)` sur la route."""
    if request.app.state.horloge() - personne.reauth_at > FENETRE:
        raise Probleme(403, "reauthentification_requise", REAUTHENTIFICATION_REQUISE)


EXIGE_UNE_REAUTHENTIFICATION: Final = Depends(exige_reauth)
