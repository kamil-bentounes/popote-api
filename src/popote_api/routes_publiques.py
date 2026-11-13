"""Les routes qui répondent sans session (spec § 3.10), chacune avec sa raison.

Une route ajoutée ici se justifie en relecture. `tests/unit/test_routes_fermees.py` lit cette liste : toute
autre route de l'application exige `personne_connectee`. `main.ROUTES_PUBLIQUES` la reprend.
"""

from typing import Final

CONNEXION: Final = "/api/v1/sessions"

ROUTES_PUBLIQUES: Final[dict[str, str]] = {
    "/api/healthz": "le processus répond, sans donnée",
    "/api/readyz": "la base répond, sans donnée ; sert au réveil quotidien du projet",
    CONNEXION: "la connexion : sans session, par définition ; limitée en base avant tout bcrypt",
}
# Sous `/api/v1/`, tant qu'aucune session n'est validée, un `404`, `405` ou `422` se rend `401` (la route
# ne se révèle pas). Les routes publiques de `/api/v1/` rendent leurs propres refus.
PUBLIQUES_DE_V1: Final = frozenset(chemin for chemin in ROUTES_PUBLIQUES if chemin.startswith("/api/v1/"))
