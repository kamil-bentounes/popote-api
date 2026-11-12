"""Formats communs de l'API (§ 3.8) : types Pydantic à réutiliser dans tous les modèles.

- `Instant` : un instant RFC 3339 **avec décalage** (`2026-11-12T10:00:00+01:00` ou `...Z`). Un instant sans
  décalage est refusé : on ne devine pas le fuseau. En sortie, toujours en UTC avec le décalage `+00:00`.
- `Jour` : un jour du calendrier `YYYY-MM-DD`, toujours au sens de `Europe/Paris` ; `aujourdhui_a_paris`.
- `Montant` : des centimes entiers et `currency: "EUR"`. Jamais de flottant, jamais une autre devise.
"""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, PlainValidator, StrictInt, WithJsonSchema

from popote_api.errors import ValeurRefusee

PARIS = ZoneInfo("Europe/Paris")
# 2**53 - 1 : au-delà, un nombre JSON n'est plus exact dans le navigateur.
CENTIMES_MAX = 2**53 - 1

# RFC 3339 § 5.6 `date-time`. Pas de seconde 60 (Python ne la représente pas) ; au plus 9 décimales.
_INSTANT = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,9})?([Zz]|[+-]([01]\d|2[0-3]):[0-5]\d)",
    re.ASCII,  # `\d` seul accepterait aussi les chiffres arabo-indiens
)
_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def _lit_un_instant(valeur: object) -> datetime:
    if isinstance(valeur, datetime):
        if valeur.utcoffset() is None:
            raise ValeurRefusee("Un instant exige un décalage horaire (`Z` ou `+01:00`).")
        return valeur
    if not isinstance(valeur, str):
        raise ValeurRefusee("Un instant s'écrit en texte RFC 3339, avec son décalage.")
    if not _INSTANT.fullmatch(valeur):
        raise ValeurRefusee("Un instant s'écrit AAAA-MM-JJThh:mm:ss avec un décalage (`Z` ou `+01:00`).")
    try:
        return datetime.fromisoformat(valeur[:-1] + "+00:00" if valeur[-1] in "Zz" else valeur)
    except ValueError as erreur:  # mois 13, 30 février, décalage de plus de 24 h
        raise ValeurRefusee("Cet instant n'existe pas dans le calendrier.") from erreur


def _ecrit_un_instant(instant: datetime) -> str:
    return instant.astimezone(UTC).isoformat()


Instant = Annotated[
    datetime,
    PlainValidator(_lit_un_instant),
    PlainSerializer(_ecrit_un_instant, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date-time",
            "description": "Un instant RFC 3339 avec décalage, ex. 2026-11-12T10:00:00+01:00.",
        }
    ),
]


def _lit_un_jour(valeur: object) -> date:
    if isinstance(valeur, datetime):
        raise ValeurRefusee("Un jour s'écrit AAAA-MM-JJ, sans heure.")
    if isinstance(valeur, date):
        return valeur
    if not isinstance(valeur, str) or not _JOUR.fullmatch(valeur):
        raise ValeurRefusee("Un jour s'écrit AAAA-MM-JJ.")
    try:
        return date.fromisoformat(valeur)
    except ValueError as erreur:  # mois 13, 30 février
        raise ValeurRefusee("Ce jour n'existe pas dans le calendrier.") from erreur


Jour = Annotated[
    date,
    PlainValidator(_lit_un_jour),
    PlainSerializer(lambda jour: jour.isoformat(), return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date",
            "description": "Un jour du calendrier AAAA-MM-JJ, au sens de Europe/Paris.",
        }
    ),
]


def jour_a_paris(instant: datetime) -> date:
    """Le jour du calendrier à Paris (heure d'été comprise) où tombe cet instant."""
    if instant.utcoffset() is None:
        raise ValueError("Un instant sans décalage n'a pas de jour à Paris.")
    return instant.astimezone(PARIS).date()


def _maintenant() -> datetime:
    return datetime.now(UTC)


def aujourdhui_a_paris(horloge: Callable[[], datetime] = _maintenant) -> date:
    """Le jour d'aujourd'hui à Paris ; `horloge` rend un instant avec décalage (injectée dans les tests)."""
    return jour_a_paris(horloge())


class Montant(BaseModel):
    """Une somme d'argent : des centimes entiers (négatif pour un avoir) et la devise, toujours l'euro."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    amount_cents: Annotated[StrictInt, Field(ge=-CENTIMES_MAX, le=CENTIMES_MAX)]
    currency: Literal["EUR"]
