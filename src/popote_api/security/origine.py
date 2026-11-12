"""La garde d'origine : une écriture n'est reçue que d'une page de Popote (CSRF, spec § 4).

Ce que la garde protège : un site tiers ouvert dans le navigateur d'une personne connectée ne peut pas
écrire en son nom, même si le cookie de session suit la requête. Trois preuves, toutes exigées : `Origin`
est celle de l'environnement, `Sec-Fetch-Site` (posé par le navigateur, que la page ne peut pas modifier)
vaut `same-origin` quand il est présent, et l'en-tête `X-Popote-Client: web` est là (une requête
inter-sites simple, comme un formulaire, ne peut pas en poser un). Elle ne protège pas d'un client hors
navigateur (curl, un script) : il écrit les trois en-têtes à la main. Ce client-là doit de toute façon
présenter une session valide, c'est elle qui l'arrête.

C'est une dépendance FastAPI de l'application entière : une route d'écriture ajoutée plus tard est
gardée sans qu'on y pense. Elle vaut aussi pour la poignée de main d'un websocket (`GET` avec cookie, donc
détournable depuis un site tiers) : `Origin` et `Sec-Fetch-Site` y sont exigés, mais pas `X-Popote-Client`,
qu'un navigateur ne peut pas poser sur un websocket.
"""

import logging

from fastapi import WebSocketException
from starlette.requests import HTTPConnection

from popote_api.config import Settings
from popote_api.errors import Probleme

journal = logging.getLogger(__name__)

# Tout ce qui n'est pas sûr est gardé : une méthode inattendue (`PROPPATCH`, `TRACE`…) ne passe pas.
METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS"})
REFUS_WEBSOCKET = 1008  # code RFC 6455 « violation de politique »
# Les routes internes n'ont ni cookie ni navigateur : leur signature HMAC les garde (T10).
PREFIXES_EXEMPTES = ("/internal/",)
EN_TETE_CLIENT = "x-popote-client"
VALEUR_CLIENT = "web"


def _raison_du_refus(connexion: HTTPConnection, settings: Settings) -> str | None:
    """Le nom de la preuve qui manque, ou `None` si elles sont toutes là."""
    origines = connexion.headers.getlist("origin")
    if len(origines) != 1 or not settings.origine_admise(origines[0]):
        return "origine"
    if connexion.headers.get("sec-fetch-site", "same-origin") != "same-origin":
        return "sec-fetch-site"
    est_websocket = connexion.scope["type"] == "websocket"
    if not est_websocket and connexion.headers.get(EN_TETE_CLIENT) != VALEUR_CLIENT:
        return "x-popote-client"
    return None


async def garde_origine(connexion: HTTPConnection) -> None:
    # Un websocket n'a pas de méthode dans sa portée : il n'est jamais « sûr », sa poignée de main est gardée.
    if connexion.scope.get("method") in METHODES_SURES:
        return
    if connexion.url.path.startswith(PREFIXES_EXEMPTES):
        return
    raison = _raison_du_refus(connexion, connexion.app.state.settings)
    if raison is None:
        return
    est_websocket = connexion.scope["type"] == "websocket"
    # La valeur reçue n'est pas journalisée : elle vient de l'appelant. Seule la preuve manquante l'est.
    journal.warning("Écriture refusée par la garde d'origine : preuve manquante ou fausse (%s).", raison)
    if est_websocket:
        # Un `Probleme` ne se rend pas sur un websocket : on ferme la poignée de main (le client voit un 403).
        raise WebSocketException(code=REFUS_WEBSOCKET)
    raise Probleme(403, "origine_refusee", "Cette requête ne vient pas d'une page de Popote.")
