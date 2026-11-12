"""La limite de débit, en mémoire, par instance, à deux niveaux.

Par adresse, 600 lectures et 120 écritures par minute : un middleware ASGI pur (`LimiteParAdresse`), placé
après la garde du relais et avant la lecture du corps. Exception assumée à la règle « le débit est une
dépendance » (voir `errors.py`) : un refus doit coûter le moins possible, donc tomber avant que le corps
(1 Mio) soit lu ou décodé, et la limite doit compter aussi les JSON invalides, les routes inconnues (404) et
les méthodes refusées (405), ce qu'une dépendance ne voit pas. Aucun cookie n'est lu à ce niveau : un cookie
inventé n'ouvre jamais un compteur neuf. La clé est l'adresse que le relais a vue, regroupée : une adresse
IPv6 par préfixe /64 (une seule personne en possède des milliards), une adresse IPv4 telle quelle.

Par personne, 120 lectures et 30 écritures par minute : une dépendance, `limite_par_personne`, que la
dépendance de session appellera avec l'identifiant de la personne une fois la session validée. Le plafond par
adresse est plus large : deux téléphones d'un foyer partagent souvent la même adresse.

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
from ipaddress import IPv6Address, ip_address, ip_network

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from popote_api.errors import Probleme, reponse
from popote_api.relais import ip_de
from popote_api.security import METHODES_SURES

journal = logging.getLogger(__name__)

MAX_CLES = 10_000
CLE_SANS_IP = "sans-ip"  # clé commune quand l'adresse manque : jamais un compteur par requête
NON_LIMITEES = frozenset({"/api/healthz", "/api/readyz"})
# `/internal/*` n'a ni relais ni `X-Popote-IP` : tous ses appelants partageraient la clé `sans-ip` avec
# n'importe quel inconnu qui tape l'URL publique du conteneur, et un flot de requêtes non signées ferait
# rendre 429 à un appel signé. La signature (`security.signature`) garde ces routes : le débit n'y compte pas.
PREFIXE_INTERNE = "/internal/"
PREFIXE_IPV6 = 64
CLE_VERDICT_PERSONNE = "verdict_personne"  # dans l'état de la requête
SECONDES_ENTRE_DEUX_ALERTES = 60.0


@dataclass(frozen=True)
class Politique:
    nom: str  # nom du quota dans les en-têtes (une chaîne de champ structuré, ASCII sans guillemet)
    quota: int
    fenetre: int  # secondes


# Par personne.
LECTURE = Politique("read", 120, 60)
ECRITURE = Politique("write", 30, 60)
# Par adresse : plus large, car plusieurs personnes (et leurs téléphones, qui relisent toutes les 3 s)
# peuvent partager une adresse.
LECTURE_PAR_ADRESSE = Politique("read", 600, 60)
ECRITURE_PAR_ADRESSE = Politique("write", 120, 60)


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


def cle_d_adresse(adresse: str | None) -> str:
    """La clé de compteur d'une adresse : IPv6 regroupée par /64, IPv4 telle quelle, sinon la clé commune."""
    if adresse is None:
        return CLE_SANS_IP
    try:
        ip = ip_address(adresse)
    except ValueError:
        return CLE_SANS_IP
    if isinstance(ip, IPv6Address):
        return str(ip_network((ip, PREFIXE_IPV6), strict=False))
    return str(ip)


def _controle(limiteur: Limiteur, politique: Politique, cle: str) -> Verdict | Probleme:
    """Le verdict d'une requête acceptée, ou l'erreur à rendre (non levée : un middleware la rend, une
    dépendance la lève)."""
    verdict = limiteur.consomme(cle, politique)
    if verdict is None:
        return Probleme(
            503,
            "limiteur_sature",
            "Popote est très sollicité en ce moment. Réessaie dans un instant.",
            headers={"Retry-After": str(limiteur.secondes_avant_une_place())},
        )
    if not verdict.autorise:
        return Probleme(
            429,
            "trop_de_requetes",
            f"Trop de requêtes. Réessaie dans {verdict.secondes} secondes.",
            headers={"Retry-After": str(verdict.secondes), **verdict.en_tetes()},
        )
    return verdict


class LimiteParAdresse:
    """Middleware ASGI pur : 429 (ou 503 si le limiteur est saturé) avant toute lecture du corps."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"] in NON_LIMITEES
            or scope["path"].startswith(PREFIXE_INTERNE)
        ):
            await self.app(scope, receive, send)
            return
        sures = scope["method"] in METHODES_SURES
        politique = LECTURE_PAR_ADRESSE if sures else ECRITURE_PAR_ADRESSE
        controle = _controle(scope["app"].state.debit.ip, politique, cle_d_adresse(ip_de(Request(scope))))
        if isinstance(controle, Probleme):
            requete = Request(scope)
            await reponse(requete, controle.status, controle.code, controle.detail, headers=controle.headers)(
                scope, receive, send
            )
            return
        verdict = controle

        async def envoie_avec_les_en_tetes(message: Message) -> None:
            if message["type"] == "http.response.start":
                en_tetes = MutableHeaders(scope=message)
                # Le limiteur par personne, plus fin, annonce son quota sur toute réponse (y compris un
                # `Response` rendu tel quel par la route, que FastAPI ne complète pas) ; sinon, l'adresse.
                verdict_de_la_personne = scope.get("state", {}).get(CLE_VERDICT_PERSONNE)
                if verdict_de_la_personne is not None:
                    for nom, valeur in verdict_de_la_personne.en_tetes().items():
                        en_tetes[nom] = valeur
                else:
                    for nom, valeur in verdict.en_tetes().items():
                        if nom not in en_tetes:  # un refus 429 de la personne porte déjà les siens
                            en_tetes[nom] = valeur
            await send(message)

        await self.app(scope, receive, envoie_avec_les_en_tetes)


async def limite_par_personne(request: Request, personne: str) -> None:
    """Deuxième barrière, à appeler par la dépendance de session une fois la session validée.

    `personne` est l'identifiant lu dans la session validée en base (`person_id`), jamais une valeur du cookie
    brut : deux sessions de la même personne partagent un compteur. Le verdict est posé dans l'état de la
    requête, que `LimiteParAdresse` lit au départ de la réponse pour y écrire les en-têtes de la personne.
    """
    politique = LECTURE if request.method in METHODES_SURES else ECRITURE
    controle = _controle(request.app.state.debit.personne, politique, personne)
    if isinstance(controle, Probleme):
        raise controle
    setattr(request.state, CLE_VERDICT_PERSONNE, controle)
