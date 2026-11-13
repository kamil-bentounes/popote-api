"""Lire et accepter une invitation (T13 ; spec § 4, § 5.1 ; B1, B10, B11, B20, B23, B24).

L'ordre est la sécurité de la route, et rien d'autre ne s'exécute avant l'étape qui le précède :

  (1) créneau `invitation_ip` ; (2) lecture SANS EFFET du lien : inconnu ou mal formé -> `Inconnue`, expiré,
  utilisé, révoqué -> `LienRefuse`, avant tout le reste (un jeton inconnu n'apprend rien sur les adresses, ne
  coûte ni liste de fuites ni appel à Auth) ; (3) créneau `invitation_link` ; (4) adresse valide, règles du
  mot de passe, liste de fuites ; (5) l'adresse a-t-elle un compte -> `CompteExistant` (lien NON consommé), ou
  reprise d'un orphelin (B10) ; (6) consommation atomique ; (7) création du compte, puis profil, session.

Les transactions sont courtes et distinctes : aucune ne reste ouverte pendant un appel externe (Pwned
Passwords, Auth). Un échec après (6) brûle le lien ; la seule exception est la course d'adresse (B20) : Auth
rend `CompteDejaExistant`, le lien est rouvert. Un échec du profil supprime le compte créé (compensation) ; si
elle échoue aussi, `CompteOrphelinANettoyer` porte l'identifiant de la personne (jamais son adresse).

Ni le jeton, ni son empreinte, ni l'adresse, ni le mot de passe ne sont journalisés.
"""

import hashlib
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, LiteralString
from uuid import UUID

from popote_api.config import Settings
from popote_api.infra.auth_admin import AuthAdmin, CompteDejaExistant
from popote_api.infra.auth_admin import MotDePasseRefuseParAuth as RefusDAuth
from popote_api.infra.comptes import adresse_valide
from popote_api.infra.db import Base, Curseur
from popote_api.infra.fuites import EtatFuite, Fuites
from popote_api.security.connexion import Ouverte, ouvre_une_session
from popote_api.security.empreintes import Empreintes, email_normalise
from popote_api.security.jeton import FORME_DU_JETON
from popote_api.security.journal_securite import Evenement, journalise
from popote_api.security.mots_de_passe import Defaut, normalise, verifie_nouveau

journal = logging.getLogger(__name__)

SCOPE_IP: Final = "invitation_ip"
SCOPE_LIEN: Final = "invitation_link"
# `display_name` vide et `entre_le` au 1er du mois prochain à Paris : les règles de l'ancien `accept-invite`
# (pas de prénom fabriqué depuis l'adresse ; pas d'inscription aux charges communes d'un mois où la personne
# n'habite pas encore là).
PROFIL: Final[LiteralString] = (
    "insert into public.user_profile (id, household_id, display_name, entre_le, password_set) "
    "values (%s, %s, '', "
    "(date_trunc('month', now() at time zone 'Europe/Paris') + interval '1 month')::date, true)"
)


class EtatDuLien(StrEnum):
    valide = "valide"
    expiree = "expiree"
    utilisee = "utilisee"
    revoquee = "revoquee"
    inconnue = "inconnue"


@dataclass(frozen=True, slots=True)
class Bloquee:
    attente_s: int


@dataclass(frozen=True, slots=True)
class Inconnue:
    """Jeton inconnu OU mal formé : une seule réponse pour les deux."""


@dataclass(frozen=True, slots=True)
class LienRefuse:
    etat: EtatDuLien  # expiree, utilisee ou revoquee


@dataclass(frozen=True, slots=True)
class Inspectee:
    invited_by: str | None
    expires_at: object  # datetime ; typé large pour que le modèle de sortie le valide


@dataclass(frozen=True, slots=True)
class ChampRefuse:
    pointer: str
    message: str


@dataclass(frozen=True, slots=True)
class Refusee:
    """Adresse ou mot de passe refusé : le lien n'est pas consommé."""

    erreurs: tuple[ChampRefuse, ...]


@dataclass(frozen=True, slots=True)
class CompteExistant:
    """L'adresse a déjà un compte (ou vient d'en recevoir un) : le lien n'est pas consommé."""


@dataclass(frozen=True, slots=True)
class MotDePasseRefuse:
    """Auth a refusé le mot de passe (après les règles locales) : le lien est brûlé."""


Resultat = Ouverte | Bloquee | Inconnue | LienRefuse | Refusee | CompteExistant | MotDePasseRefuse


class CompteOrphelinANettoyer(Exception):
    """Le profil n'a pas pu être écrit et le compte n'a pas pu être retiré : à nettoyer à la main
    (`docs/exploitation.md`). `personne` : l'identifiant du compte, jamais son adresse."""

    def __init__(self, personne: UUID) -> None:
        super().__init__(f"compte_orphelin_a_nettoyer personne={personne}")
        self.personne = personne


def empreinte_du_lien(jeton: str) -> bytes | None:
    """Le SHA-256 de la chaîne ASCII du jeton (comme `tire_un_jeton`), `None` si ce n'est pas un jeton."""
    if FORME_DU_JETON.fullmatch(jeton) is None:
        return None
    return hashlib.sha256(jeton.encode("ascii")).digest()


async def _creneau(curseur: Curseur, scope: str, cle: bytes, limite: int, fenetre_s: int) -> int:
    await curseur.execute(
        "select public.prend_un_creneau_invitation(%s, %s, %s, %s) as attente_s",
        (scope, cle, limite, fenetre_s),
    )
    ligne = await curseur.fetchone()
    if ligne is None:
        raise RuntimeError("prend_un_creneau_invitation n'a rien rendu")
    return int(ligne["attente_s"])


async def _etat(curseur: Curseur, empreinte: bytes) -> tuple[EtatDuLien, str | None, object]:
    await curseur.execute("select etat, invited_by, expires_at from public.etat_invitation(%s)", (empreinte,))
    ligne = await curseur.fetchone()
    if ligne is None:
        raise RuntimeError("etat_invitation n'a rien rendu")
    return EtatDuLien(ligne["etat"]), ligne["invited_by"], ligne["expires_at"]


async def inspecte(
    base: Base, empreintes: Empreintes, reglages: Settings, *, jeton: str, ip: str | None
) -> Inspectee | Bloquee | Inconnue | LienRefuse:
    """Lecture sans effet d'un lien. Lève `PoivreAbsentError` sans poivre (la route répond 503)."""
    cle_ip = empreintes.cle_ip_requise(ip)
    empreinte = empreinte_du_lien(jeton)
    async with base.connexion() as curseur:
        attente = await _creneau(
            curseur, SCOPE_IP, cle_ip, reglages.invitation_essais_par_ip, reglages.invitation_fenetre_s
        )
        if attente:
            return Bloquee(attente)
        if empreinte is None:
            return Inconnue()
        etat, invite_par, echeance = await _etat(curseur, empreinte)
    if etat is EtatDuLien.inconnue:
        return Inconnue()
    if etat is not EtatDuLien.valide:
        return LienRefuse(etat)
    return Inspectee(invite_par, echeance)


async def accepte(
    base: Base,
    empreintes: Empreintes,
    reglages: Settings,
    fuites: Fuites,
    auth: AuthAdmin,
    *,
    jeton: str,
    email: str,
    mot_de_passe: str,
    ip: str | None,
    agent: str | None,
    request_id: str | None,
) -> Resultat:
    """Les sept étapes. Lève `PoivreAbsentError`, `AuthIndisponible`, `CompteOrphelinANettoyer` et les
    erreurs de la base ; les autres issues se rendent."""
    cle_ip = empreintes.cle_ip_requise(ip)
    empreinte = empreinte_du_lien(jeton)
    # (1) à (3) : une transaction courte, validée avant tout appel externe (les compteurs survivent).
    async with base.service() as curseur:
        attente = await _creneau(
            curseur, SCOPE_IP, cle_ip, reglages.invitation_essais_par_ip, reglages.invitation_fenetre_s
        )
        if attente:
            return Bloquee(attente)
        if empreinte is None:
            return Inconnue()
        etat, _, _ = await _etat(curseur, empreinte)
        if etat is EtatDuLien.inconnue:
            return Inconnue()
        if etat is not EtatDuLien.valide:
            return LienRefuse(etat)
        attente = await _creneau(
            curseur,
            SCOPE_LIEN,
            empreintes.cle_lien_requise(empreinte),
            reglages.invitation_essais_par_lien,
            reglages.invitation_fenetre_s,
        )
        if attente:
            return Bloquee(attente)
    # (4) l'adresse et le mot de passe : aucun effet encore.
    adresse = email_normalise(email)
    if not adresse_valide(adresse):
        return Refusee((ChampRefuse("/email", "Cette adresse n'est pas valide."),))
    defauts: list[Defaut] = verifie_nouveau(mot_de_passe, "/password")
    if defauts:
        return Refusee(
            tuple(
                ChampRefuse(d.en_erreur_de_champ()["pointer"], d.en_erreur_de_champ()["message"])
                for d in defauts
            )
        )
    forme = normalise(mot_de_passe)
    verdict = await fuites.verifie(forme)
    if verdict.etat is EtatFuite.fuite:
        return Refusee((ChampRefuse("/password", MOT_DE_PASSE_FUITE),))
    fuites_indisponibles = verdict.etat is EtatFuite.indisponible
    if fuites_indisponibles:
        journal.warning("Liste de fuites indisponible (%s) : mot de passe accepté", verdict.cause)
    # (5) l'adresse a-t-elle un compte ? Sous la réservation de l'adresse (60 s) : deux liens visant la même
    # adresse (compte neuf ou reprise) ne s'exécutent jamais ensemble, et le perdant n'appelle pas Auth.
    cle = empreintes.cle_compte_requise(adresse)
    async with base.service() as curseur:
        await curseur.execute("select public.reserve_reprise(%s) as prise", (cle,))
        ligne = await curseur.fetchone()
    if ligne is None or not ligne["prise"]:
        return CompteExistant()  # un autre lien vise la même adresse : le sien n'est pas consommé
    try:
        async with base.service() as curseur:
            await curseur.execute("select id, orphelin from public.compte_pour_email(%s)", (adresse,))
            compte = await curseur.fetchone()
        if compte is None:
            return await _cree(
                base,
                auth,
                empreinte,
                adresse,
                forme,
                fuites_indisponibles,
                agent=agent,
                request_id=request_id,
            )
        if not compte["orphelin"]:
            return CompteExistant()
        return await _reprend(
            base,
            auth,
            empreinte,
            compte["id"],
            forme,
            fuites_indisponibles,
            agent=agent,
            request_id=request_id,
        )
    finally:
        await _libere(base, cle)


MOT_DE_PASSE_FUITE: Final = (
    "Ce mot de passe figure dans des fuites de données publiques : choisis-en un autre."
)


async def _consomme(base: Base, empreinte: bytes) -> tuple[UUID, UUID] | LienRefuse | Inconnue:
    """(6) Un seul `update` atomique. Rien : le lien a changé d'état depuis la lecture, on le relit."""
    async with base.service() as curseur:
        await curseur.execute("select id, household_id from public.consomme_invitation(%s)", (empreinte,))
        ligne = await curseur.fetchone()
        if ligne is not None:
            return ligne["id"], ligne["household_id"]
        etat, _, _ = await _etat(curseur, empreinte)
    if etat in (EtatDuLien.valide, EtatDuLien.inconnue):  # ne devrait pas arriver : refus sans détail
        return Inconnue()
    return LienRefuse(etat)


async def _cree(
    base: Base,
    auth: AuthAdmin,
    empreinte: bytes,
    adresse: str,
    forme: str,
    fuites_indisponibles: bool,
    *,
    agent: str | None,
    request_id: str | None,
) -> Resultat:
    consomme = await _consomme(base, empreinte)
    if isinstance(consomme, LienRefuse | Inconnue):
        return consomme
    lien, foyer = consomme
    try:
        personne = await auth.cree_compte(adresse, forme)
    except CompteDejaExistant:
        await _rouvre(base, lien)  # B20 : l'adresse a été prise entre-temps, le lien n'y est pour rien
        return CompteExistant()
    except RefusDAuth:
        return MotDePasseRefuse()
    # Les autres échecs (Auth en panne, mot de passe refusé) brûlent le lien : l'exception remonte.
    try:
        return await _termine(
            base,
            lien,
            foyer,
            personne,
            fuites_indisponibles,
            reprise=False,
            agent=agent,
            request_id=request_id,
        )
    except Exception:
        try:
            await auth.supprime_compte(personne)
        except Exception as echec:
            journal.error("Compensation impossible : %s", type(echec).__name__)
            raise CompteOrphelinANettoyer(personne) from echec
        raise


async def _reprend(
    base: Base,
    auth: AuthAdmin,
    empreinte: bytes,
    personne: UUID,
    forme: str,
    fuites_indisponibles: bool,
    *,
    agent: str | None,
    request_id: str | None,
) -> Resultat:
    """B10 : un compte sans profil ni mot de passe (reste d'un ancien lien magique : rien à prendre)."""
    consomme = await _consomme(base, empreinte)
    if isinstance(consomme, LienRefuse | Inconnue):
        return consomme
    lien, foyer = consomme
    try:
        await auth.change_mot_de_passe(personne, forme, confirme_l_email=True)
    except RefusDAuth:
        return MotDePasseRefuse()
    try:
        return await _termine(
            base,
            lien,
            foyer,
            personne,
            fuites_indisponibles,
            reprise=True,
            agent=agent,
            request_id=request_id,
        )
    except Exception as echec:
        # Le mot de passe est posé et le profil manque : à nettoyer à la main (on ne supprime pas un compte
        # qui existait avant ce lien).
        journal.error("Reprise inachevée : %s", type(echec).__name__)
        raise CompteOrphelinANettoyer(personne) from echec


async def _termine(
    base: Base,
    lien: UUID,
    foyer: UUID,
    personne: UUID,
    fuites_indisponibles: bool,
    *,
    reprise: bool,
    agent: str | None,
    request_id: str | None,
) -> Ouverte:
    """(7) Une transaction : profil dans le foyer du lien, session, `accepted_by`, événements."""
    async with base.service() as curseur:
        await curseur.execute(PROFIL, (personne, foyer))
        await curseur.execute("select public.termine_invitation(%s, %s) as fait", (lien, personne))
        ligne = await curseur.fetchone()
        if ligne is None or not ligne["fait"]:
            raise RuntimeError("Le lien n'est plus un lien consommé non terminé")
        ouverte = await ouvre_une_session(
            curseur, personne, agent=agent, jeton_presente=None, request_id=request_id
        )
        if reprise:
            await journalise(curseur, Evenement.compte_repris, personne=personne, request_id=request_id)
        if fuites_indisponibles:
            await journalise(
                curseur, Evenement.verification_fuites_indisponible, personne=personne, request_id=request_id
            )
        await journalise(
            curseur, Evenement.invitation_acceptee, personne=personne, invitation=lien, request_id=request_id
        )
        return ouverte


async def _rouvre(base: Base, lien: UUID) -> None:
    async with base.service() as curseur:
        await curseur.execute("select public.rend_invitation(%s)", (lien,))


async def _libere(base: Base, cle: bytes) -> None:
    try:
        async with base.service() as curseur:
            await curseur.execute("select public.libere_reprise(%s)", (cle,))
    except Exception as echec:  # la réservation expire seule en 60 s
        journal.warning("Réservation de reprise non libérée : %s", type(echec).__name__)
