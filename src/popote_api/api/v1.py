"""Le routeur `/api/v1` : fermé par défaut (spec § 3.10). Toute route montée ici exige une session.

Les routes sans session (connexion, invitation, réinitialisation : 0.4) se montent ailleurs, hors de ce
routeur, et s'écrivent dans la liste blanche de `tests/unit/test_routes_fermees.py`.
"""

from fastapi import APIRouter

from popote_api.api import appareils, invitations_hote, moi, reauthentification
from popote_api.security.session import COOKIE_DU_CONTRAT, EXIGE_UNE_PERSONNE, REPONSES_DE_SESSION

# Les routes de chaque domaine, ajoutées au fil des étapes ; lue à la construction de l'application.
SOUS_ROUTEURS: tuple[APIRouter, ...] = (
    moi.router,
    appareils.router,
    reauthentification.router,
    invitations_hote.router,
)


def cree_routeur() -> APIRouter:
    routeur = APIRouter(
        prefix="/api/v1",
        dependencies=[EXIGE_UNE_PERSONNE, COOKIE_DU_CONTRAT],
        responses=REPONSES_DE_SESSION,
    )
    for sous_routeur in SOUS_ROUTEURS:
        routeur.include_router(sous_routeur)
    return routeur
