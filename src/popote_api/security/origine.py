"""La garde d'origine : une écriture n'est reçue que d'une page de Popote (CSRF, spec § 4).

Ce que la garde protège : un site tiers ouvert dans le navigateur d'une personne connectée ne peut pas
écrire en son nom, même si le cookie de session suit la requête. Trois preuves, toutes exigées : `Origin`
est celle de l'environnement, `Sec-Fetch-Site` (posé par le navigateur, que la page ne peut pas modifier)
vaut `same-origin` quand il est présent, et l'en-tête `X-Popote-Client: web` est là (une requête
inter-sites simple, comme un formulaire, ne peut pas en poser un). Elle ne protège pas d'un client hors
navigateur (curl, un script) : il écrit les trois en-têtes à la main. Ce client-là doit de toute façon
présenter une session valide, c'est elle qui l'arrête.

C'est une dépendance FastAPI de l'application entière : une route d'écriture ajoutée plus tard est
gardée sans qu'on y pense.
"""

import logging

from fastapi import Request

from popote_api.config import Settings
from popote_api.errors import Probleme

journal = logging.getLogger(__name__)

METHODES_QUI_ECRIVENT = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Les routes internes n'ont ni cookie ni navigateur : leur signature HMAC les garde (T10).
PREFIXES_EXEMPTES = ("/internal/",)
EN_TETE_CLIENT = "x-popote-client"
VALEUR_CLIENT = "web"


def _raison_du_refus(request: Request, settings: Settings) -> str | None:
    """Le nom de la preuve qui manque, ou `None` si les trois sont là."""
    origines = request.headers.getlist("origin")
    if len(origines) != 1 or not settings.origine_admise(origines[0]):
        return "origine"
    if request.headers.get("sec-fetch-site", "same-origin") != "same-origin":
        return "sec-fetch-site"
    if request.headers.get(EN_TETE_CLIENT) != VALEUR_CLIENT:
        return "x-popote-client"
    return None


async def garde_origine(request: Request) -> None:
    if request.method not in METHODES_QUI_ECRIVENT or request.url.path.startswith(PREFIXES_EXEMPTES):
        return
    raison = _raison_du_refus(request, request.app.state.settings)
    if raison is None:
        return
    # La valeur reçue n'est pas journalisée : elle vient de l'appelant. Seule la preuve manquante l'est.
    journal.warning("Écriture refusée par la garde d'origine : preuve manquante ou fausse (%s).", raison)
    raise Probleme(403, "origine_refusee", "Cette requête ne vient pas d'une page de Popote.")
