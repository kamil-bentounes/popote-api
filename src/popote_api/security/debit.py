"""La limite de débit : lecture 120 par minute, écriture 30 par minute, en mémoire, par instance.

Deux limiteurs indépendants, chacun avec ses compteurs :
- `ip`, appliqué à toute requête par une dépendance de l'application, avant qu'aucun cookie soit lu : un
  cookie inventé n'ouvre donc jamais un compteur neuf, la clé est l'adresse que le relais a vue ;
- `personne`, que la dépendance de session appellera avec l'identifiant de la personne, une fois la session
  validée (`limite_par_personne`).

Fenêtre fixe, ouverte à la première requête de la clé : `r` (restant) et `t` (secondes avant le
renouvellement) du brouillon IETF ont ainsi un sens exact. Une rafale à cheval sur deux fenêtres peut
doubler le plafond un instant : c'est suffisant pour un foyer (spec § 3.6).

La mémoire est bornée sans jamais oublier un compteur actif : à la limite de clés on retire les fenêtres
expirées (un compteur expiré n'a plus rien à retenir) ; s'il n'y en a pas, la requête d'une clé nouvelle est
refusée (503) et l'événement est journalisé. L'état se lit et s'écrit sans `await` entre les deux : une
seule boucle d'événements, donc pas de verrou.

En-têtes : brouillon `draft-ietf-httpapi-ratelimit-headers-11` (23/05/2026, non publié en RFC) ; `429` :
RFC 6585 § 4 ; `Retry-After` en secondes entières : RFC 9110 § 10.2.3.
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request, Response

from popote_api.errors import Probleme
from popote_api.relais import ip_de

journal = logging.getLogger(__name__)

MAX_CLES = 10_000
CLE_SANS_IP = "sans-ip"  # clé commune quand l'adresse manque : jamais un compteur par requête
NON_LIMITEES = frozenset({"/api/healthz", "/api/readyz"})
METHODES_QUI_ECRIVENT = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SECONDES_ENTRE_DEUX_ALERTES = 60.0


@dataclass(frozen=True)
class Politique:
    nom: str  # nom du quota dans les en-têtes (une chaîne de champ structuré, ASCII sans guillemet)
    quota: int
    fenetre: int  # secondes


LECTURE = Politique("read", 120, 60)
ECRITURE = Politique("write", 30, 60)


@dataclass
class Fenetre:
    fin: float
    compte: int


@dataclass(frozen=True)
class Verdict:
    politique: Politique
    autorise: bool
    restant: int
    secondes: int  # avant le renouvellement de la fenêtre (entier, au moins 1)

    def en_tetes(self) -> dict[str, str]:
        p = self.politique
        return {
            "RateLimit-Policy": f'"{p.nom}";q={p.quota};w={p.fenetre}',
            "RateLimit": f'"{p.nom}";r={self.restant};t={self.secondes}',
        }


class Limiteur:
    def __init__(self, horloge: Callable[[], float], max_cles: int = MAX_CLES) -> None:
        self._horloge = horloge
        self._max_cles = max_cles
        self._fenetres: dict[tuple[str, str], Fenetre] = {}
        self._rien_a_purger_avant = 0.0
        self._derniere_alerte: float | None = None

    def consomme(self, cle: str, politique: Politique) -> Verdict | None:
        """Compte une requête. `None` : la clé est nouvelle et il n'y a plus de place (refus, journalisé)."""
        maintenant = self._horloge()
        identite = (cle, politique.nom)
        fenetre = self._fenetres.get(identite)
        if fenetre is None or maintenant >= fenetre.fin:
            if fenetre is None and not self._fait_de_la_place(maintenant):
                self._signale_la_saturation(maintenant)
                return None
            fenetre = self._fenetres[identite] = Fenetre(maintenant + politique.fenetre, 0)
        secondes = max(1, math.ceil(fenetre.fin - maintenant))
        if fenetre.compte >= politique.quota:
            return Verdict(politique, False, 0, secondes)
        fenetre.compte += 1
        return Verdict(politique, True, politique.quota - fenetre.compte, secondes)

    def secondes_avant_une_place(self) -> int:
        """Quand la plus ancienne fenêtre expirera (pour `Retry-After` d'un refus de saturation)."""
        maintenant = self._horloge()
        return max(1, math.ceil(max(self._rien_a_purger_avant, maintenant) - maintenant))

    def _fait_de_la_place(self, maintenant: float) -> bool:
        if len(self._fenetres) < self._max_cles:
            return True
        if maintenant < self._rien_a_purger_avant:
            return False  # un balayage récent n'a rien trouvé : pas de nouveau balayage avant l'échéance
        expirees = [identite for identite, f in self._fenetres.items() if maintenant >= f.fin]
        for identite in expirees:
            del self._fenetres[identite]
        if expirees:
            return True
        self._rien_a_purger_avant = min(f.fin for f in self._fenetres.values())
        return False

    def _signale_la_saturation(self, maintenant: float) -> None:
        if (
            self._derniere_alerte is not None
            and maintenant - self._derniere_alerte < SECONDES_ENTRE_DEUX_ALERTES
        ):
            return
        self._derniere_alerte = maintenant
        journal.warning(
            "Limiteur de débit saturé : %s clés actives, une clé nouvelle est refusée.", self._max_cles
        )


class Debit:
    """Les deux limiteurs de l'application, dans `app.state.debit`."""

    def __init__(self, horloge: Callable[[], float] = time.monotonic, max_cles: int = MAX_CLES) -> None:
        self.ip = Limiteur(horloge, max_cles)
        self.personne = Limiteur(horloge, max_cles)


def _politique_de(methode: str) -> Politique:
    return ECRITURE if methode in METHODES_QUI_ECRIVENT else LECTURE


def _applique(limiteur: Limiteur, request: Request, response: Response, cle: str) -> None:
    politique = _politique_de(request.method)
    verdict = limiteur.consomme(cle, politique)
    if verdict is None:
        attente = limiteur.secondes_avant_une_place()
        raise Probleme(
            503,
            "limiteur_sature",
            "Popote est très sollicité en ce moment. Réessaie dans un instant.",
            headers={"Retry-After": str(attente)},
        )
    if not verdict.autorise:
        raise Probleme(
            429,
            "trop_de_requetes",
            f"Trop de requêtes. Réessaie dans {verdict.secondes} secondes.",
            headers={"Retry-After": str(verdict.secondes), **verdict.en_tetes()},
        )
    response.headers.update(verdict.en_tetes())


async def limite_par_ip(request: Request, response: Response) -> None:
    """Dépendance de toute l'application : première barrière, avant la lecture de tout cookie."""
    if request.url.path in NON_LIMITEES:
        return
    _applique(request.app.state.debit.ip, request, response, ip_de(request) or CLE_SANS_IP)


async def limite_par_personne(request: Request, response: Response, personne: str) -> None:
    """Deuxième barrière, à appeler par la dépendance de session une fois la session validée.

    `personne` est l'identifiant lu dans la session validée en base, jamais une valeur du cookie brut.
    """
    _applique(request.app.state.debit.personne, request, response, personne)
