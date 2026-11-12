"""Les erreurs de la base, traduites une seule fois, à la frontière HTTP (spec § 8.2).

Les couches internes laissent passer l'exception de psycopg telle quelle. Ici elle devient un Problem
Details, et le journal reçoit `sqlstate`, contrainte et table : JAMAIS le message du serveur, dont le
`DETAIL` recopie des valeurs (un montant, un prénom, une adresse).

- `23505` : `409 conflit`.
- `23503`, `23514`, `22P02` : `422 donnees_invalides`, sans pointeur (la base ne sait pas quel champ).
- `40001`, `40P01`, `55P03` : `503 reessayer`, avec `Retry-After: 1`.
- `57014` : `503 delai_depasse` (`statement_timeout`, ou requête annulée).
- Classes `08` et `53`, `57P01` à `57P03`, `OperationalError` ou `InterfaceError` sans SQLSTATE (pool épuisé
  ou fermé, connexion coupée), pas de pool `popote_api` : `503 base_indisponible`.
- Pas de pool `popote_internal` : `503 service_indisponible`.
- `42501` : `500 erreur_interne` ; `404 introuvable` seulement dans `refus_vaut_introuvable()`.
- Tout autre : `500 erreur_interne` par le gestionnaire d'erreur inattendue, dont le journal JSON ne porte ni
  message ni `DETAIL`, seulement `sqlstate`, contrainte, table et pile.
"""

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from popote_api.errors import Probleme, reponse
from popote_api.infra.db import BaseError, BaseIndisponibleError, ServiceIndisponibleError

journal = logging.getLogger(__name__)

SQLSTATE_DROIT_REFUSE = "42501"
RETRY_AFTER = {"Retry-After": "1"}
CLASSES_DE_PANNE = (
    "08",
    "53",
)  # exception de connexion ; ressources insuffisantes (53300 trop de connexions)
PANNES_DU_SERVEUR = {"57P01", "57P02", "57P03"}  # arrêt administrateur, arrêt brutal, pas encore prêt
# L'objet d'un refus de droit : un nom, jamais une valeur (le message d'un 42501 n'en porte pas).
OBJET_REFUSE = re.compile(
    r'(?:permission denied for \w+|row-level security policy(?: \(\w+\))? for table) "?([\w.]+)"?'
)


@dataclass(frozen=True)
class Traduction:
    status: int
    code: str
    detail: str
    headers: dict[str, str] | None = None


INDISPONIBLE = Traduction(503, "base_indisponible", "La base ne répond pas pour l'instant.")
REESSAYER = Traduction(503, "reessayer", "Réessaie dans un instant.", RETRY_AFTER)
DONNEES_INVALIDES = Traduction(422, "donnees_invalides", "Certaines données ne sont pas valides.")
PAR_SQLSTATE: dict[str, Traduction] = {
    "23505": Traduction(409, "conflit", "Cette donnée existe déjà ou vient de changer."),
    "23503": DONNEES_INVALIDES,
    "23514": DONNEES_INVALIDES,
    "22P02": DONNEES_INVALIDES,
    "40001": REESSAYER,
    "40P01": REESSAYER,
    "55P03": REESSAYER,
    "57014": Traduction(503, "delai_depasse", "La base a mis trop de temps à répondre."),
}
SERVICE_INDISPONIBLE = Traduction(
    503, "service_indisponible", "Ce service n'est pas disponible pour l'instant."
)


def traduit(erreur: psycopg.Error | BaseError) -> Traduction | None:
    """La réponse HTTP d'une erreur de la base, ou `None` si elle n'a pas de traduction (bogue : 500)."""
    if isinstance(erreur, ServiceIndisponibleError):
        return SERVICE_INDISPONIBLE
    if isinstance(erreur, BaseIndisponibleError):
        return INDISPONIBLE
    if isinstance(erreur, BaseError):
        return None
    sqlstate = erreur.sqlstate
    if sqlstate in PAR_SQLSTATE:
        return PAR_SQLSTATE[sqlstate]
    if sqlstate is None:
        # Pas de SQLSTATE : l'erreur vient du client (pool épuisé ou fermé, connexion coupée), pas du serveur.
        return INDISPONIBLE if isinstance(erreur, psycopg.OperationalError | psycopg.InterfaceError) else None
    if sqlstate.startswith(CLASSES_DE_PANNE) or sqlstate in PANNES_DU_SERVEUR:
        return INDISPONIBLE
    return None


def _champs(erreur: psycopg.Error | BaseError) -> str:
    """Ce qu'on peut écrire de l'erreur : jamais son message ni son `DETAIL`."""
    if isinstance(erreur, BaseError):
        return f"type={type(erreur).__name__}"
    diagnostic = erreur.diag
    champs = {
        "type": type(erreur).__name__,
        "sqlstate": erreur.sqlstate,
        "contrainte": diagnostic.constraint_name,
        "table": diagnostic.table_name,
    }
    return " ".join(f"{nom}={valeur}" for nom, valeur in champs.items() if valeur)


def _objet_refuse(erreur: psycopg.Error) -> str:
    correspondance = OBJET_REFUSE.search(erreur.diag.message_primary or "")
    return correspondance.group(1) if correspondance else "inconnu"


def _journalise_le_refus(erreur: psycopg.Error, *, rendu: int) -> None:
    # Toujours un avertissement, avec l'objet : un droit manquant sur l'essai ne doit pas passer pour un
    # « introuvable » ordinaire.
    journal.warning(
        "Droit refusé par la base : objet=%s %s rendu=%s", _objet_refuse(erreur), _champs(erreur), rendu
    )


@contextmanager
def refus_vaut_introuvable() -> Iterator[None]:
    """Pour une lecture ou une écriture CIBLÉE (un élément par son identifiant) : un droit refusé, ou une
    écriture que la RLS refuse, se rend `404`, sans rien révéler. Hors de ce cadre, un `42501` est un droit
    manquant, donc un bogue de configuration : `500`.
    """
    try:
        yield
    except psycopg.errors.InsufficientPrivilege as erreur:
        _journalise_le_refus(erreur, rendu=404)
        raise Probleme(404, "introuvable", "Cet élément n'existe pas.") from erreur


def installe(app: FastAPI) -> None:
    async def _base(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, psycopg.Error | BaseError):
            raise exc
        traduction = traduit(exc)
        if traduction is None:
            if isinstance(exc, psycopg.Error) and exc.sqlstate == SQLSTATE_DROIT_REFUSE:
                _journalise_le_refus(exc, rendu=500)
            # Sans traduction : le gestionnaire d'erreur inattendue (500) la journalise (le formateur JSON
            # n'écrit ni message ni DETAIL, seulement sqlstate, contrainte et table) et la rend. Appelé ici,
            # non relevé : une exception relevée repasserait par ce gestionnaire à chaque niveau de Starlette.
            generique = request.app.exception_handlers[Exception]
            return await generique(request, exc)  # type: ignore[no-any-return]
        niveau = logging.WARNING if traduction.status >= 500 else logging.INFO
        journal.log(
            niveau,
            "Erreur de la base : %s rendu=%s code=%s",
            _champs(exc),
            traduction.status,
            traduction.code,
        )
        return reponse(
            request, traduction.status, traduction.code, traduction.detail, headers=traduction.headers
        )

    app.add_exception_handler(psycopg.Error, _base)
    app.add_exception_handler(BaseError, _base)
