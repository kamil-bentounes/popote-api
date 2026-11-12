"""Qui est là : lit le cookie de session et ouvre le contexte « personne » (spec § 3.10, § 4).

Montée sur le routeur `/api/v1` : toute route qu'on y ajoute l'exige, sans que son auteur y pense. Elle rend
la personne ET le curseur de la transaction où la session a été lue : la route travaille dans cette
transaction, avec la RLS de la personne (un seul emprunt au pool par requête).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie

from popote_api.config import NOM_DU_COOKIE_DE_SESSION
from popote_api.errors import Probleme, reponses_erreur
from popote_api.infra.db import Base, Curseur, SessionRefuseeError
from popote_api.security.jeton import JetonMalFormeError, empreinte_du_jeton

journal = logging.getLogger(__name__)

# RFC 9110 § 15.5.2 : un `401` porte au moins un défi. Aucun schéma enregistré ne décrit un cookie de
# session ; `Cookie` est un nom à nous (jamais `Basic`, `Digest` ou `Negotiate` : le navigateur ouvrirait
# une fenêtre de saisie).
DEFI_D_AUTHENTIFICATION: Final = 'Cookie realm="popote"'
# Le même texte pour tous les refus : la réponse n'apprend rien sur les jetons.
PAS_DE_SESSION: Final = "Connecte-toi pour continuer."


# Dit au contrat OpenAPI que `/api/v1` s'ouvre par le cookie de session (`securitySchemes`, `security`).
# Sans effet à l'exécution : `auto_error=False`, et la lecture du cookie reste celle de `personne_connectee`,
# qui connaît le nom configuré en local.
COOKIE_DU_CONTRAT: Final = Depends(
    APIKeyCookie(name=NOM_DU_COOKIE_DE_SESSION, scheme_name="session", auto_error=False)
)

# Ce que la dépendance peut rendre à toute route de `/api/v1`, déclaré une fois sur le routeur.
_DEFI_DU_CONTRAT: Final[dict[str, Any]] = {
    "WWW-Authenticate": {"description": 'Le défi : `Cookie realm="popote"`.', "schema": {"type": "string"}}
}
REPONSES_DE_SESSION: Final[dict[int | str, dict[str, Any]]] = {
    **reponses_erreur(500, 503),
    401: {**reponses_erreur(401)[401], "headers": _DEFI_DU_CONTRAT},
}


@dataclass(frozen=True, slots=True)
class PersonneConnectee:
    """La personne de la session, et la transaction qui agit comme elle."""

    id: UUID
    # Ce qui identifie la session sans la révéler : la clé de la limite de débit par personne, prise une fois
    # la session validée, jamais avant (un cookie inventé n'ouvre pas de compteur).
    empreinte_de_session: bytes
    curseur: Curseur


def _refus(raison: str) -> Probleme:
    # La raison seule, jamais le cookie : ni un jeton valide, ni un jeton qu'on vient d'inventer.
    journal.info("Session refusée : %s", raison)
    return Probleme(
        401, "pas_de_session", PAS_DE_SESSION, headers={"WWW-Authenticate": DEFI_D_AUTHENTIFICATION}
    )


async def personne_connectee(request: Request) -> AsyncIterator[PersonneConnectee]:
    """Le contexte « personne » de la requête ; `401 pas_de_session` sans session valide."""
    nom = request.app.state.settings.nom_du_cookie_de_session
    jeton = request.cookies.get(nom)
    if jeton is None:
        raise _refus("absente")
    try:
        empreinte = empreinte_du_jeton(jeton)
    except JetonMalFormeError as erreur:
        raise _refus("mal_formee") from erreur
    base: Base = request.app.state.base
    async with AsyncExitStack() as pile:
        try:
            personne_id, curseur = await pile.enter_async_context(base.session(empreinte))
        except SessionRefuseeError as erreur:
            raise _refus("inconnue") from erreur
        yield PersonneConnectee(personne_id, empreinte, curseur)


# `scope="function"` : la transaction se valide quand la route a fini, AVANT que la réponse parte. Sans cela
# FastAPI garderait la connexion du pool jusqu'à la fin de l'envoi de la réponse.
EXIGE_UNE_PERSONNE: Final = Depends(personne_connectee, scope="function")
# Dans la signature d'une route : `personne: PersonneDeLaSession`. Même `Depends` que celui du routeur, donc
# résolu une seule fois par requête.
PersonneDeLaSession = Annotated[PersonneConnectee, EXIGE_UNE_PERSONNE]
