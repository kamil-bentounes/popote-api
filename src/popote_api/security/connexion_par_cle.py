"""La connexion par clé d'accès (0.4bis S9 ; migration 0154) : le défi sans personne, puis l'assertion.

Une seule transaction (`base.connexion()`, comme la connexion par code) : elle se VALIDE aussi quand la
connexion est refusée, sinon le défi brûlé, le créneau et l'événement d'un échec s'annuleraient avec elle.
Un refus est donc un RÉSULTAT (`Refusee`), jamais une exception ; une ERREUR (la base, une clé publique
illisible) annule tout, et le défi, consommé dans cette transaction, redevient valable : rien n'est brûlé
par une panne.

Ordre, qui est la sécurité de la route :
1. le créneau de l'IP (`cle_ip`) : un créneau refusé n'appelle JAMAIS la vérification ;
2. le défi, consommé par l'ordre atomique `delete … returning` : on cherche celui que la réponse annonce, on
   vérifie contre celui que la base rend (jamais contre le texte de la réponse) ;
3. la clé par son identifiant, sous le VERROU de la personne (la ligne relue `for update`) ;
4. la vérification de la signature, en Python, sans réseau, pendant que le verrou est tenu : une fermeture de
   toutes les sessions ou la suppression de la clé qui précèdent ont donc déjà eu lieu, une qui suit attend ;
5. le compteur, la session et l'événement : un seul appel SQL.

Tout refus est le même `Refusee` : clé inconnue, signature fausse, origine, défi, UV, `userHandle`,
compteur, BE, personne bannie, supprimée ou sans profil. Le défi brûlé et l'événement restent.
`cle_suspecte` ne s'écrit que si la signature est VALIDE et le `userHandle` bon (`SignalDeClonage` : compteur
ou éligibilité de sauvegarde) : une assertion non signée ne fait pas naître d'alerte. Ni défi, ni assertion,
ni identifiant de clé ne sont journalisés.
"""

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from popote_api.config import Settings
from popote_api.infra.db import Base, Curseur
from popote_api.infra.webauthn import (
    CleDeConnexion,
    CleStockeeIllisible,
    OptionsDeCeremonie,
    PartieDeConfiance,
    ReponseDeCleRefusee,
    SignalDeClonage,
    defi_de_la_reponse,
    identifiant_de_la_cle,
    options_de_connexion,
    verifie_la_connexion,
)
from popote_api.security.appareil import Appareil, resume_agent
from popote_api.security.connexion import Bloquee, Ouverte, Refusee, empreinte_presentee
from popote_api.security.empreintes import Empreintes
from popote_api.security.jeton import jeton_neuf
from popote_api.security.journal_securite import Evenement, journalise_sans_lever
from popote_api.security.limites_base import prendre_un_creneau_de_cle

journal = logging.getLogger(__name__)

# Une personne ne peut pas attendre au-delà d'une minute un défi quand le plafond est atteint : la page
# redemandera.
ATTENTE_DU_PLAFOND_S = 60

CRENEAUX_DE_VERIFICATION = "cle_ip"
CRENEAUX_DE_DEFI = "cle_defi_ip"


@dataclass(frozen=True, slots=True)
class DefiDeConnexion:
    options: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SessionDeLaCle:
    session: UUID
    personne: UUID


ResultatDuDefi = DefiDeConnexion | Bloquee
ResultatDeLaConnexion = Ouverte | Bloquee | Refusee


@dataclass(frozen=True, slots=True)
class CleLue:
    """Ce que rend `cle_pour_connexion` : la clé telle que la base la tient, sous le verrou de sa personne."""

    personne: UUID
    cle: UUID
    cle_de_verification: CleDeConnexion = field(repr=False)


async def cree_un_defi_anonyme(curseur: Curseur, defi: bytes, plafond: int) -> bool:
    """Garde le défi ; faux si le plafond des défis vivants est atteint."""
    await curseur.execute("select public.cree_un_defi_anonyme(%s, %s) as etat", (defi, plafond))
    ligne = await curseur.fetchone()
    if ligne is None:
        raise RuntimeError("cree_un_defi_anonyme n'a rien rendu")
    return bool(ligne["etat"] == "creee")


async def consomme_un_defi_anonyme(curseur: Curseur, defi: bytes) -> bytes | None:
    """Le défi, une seule fois, s'il est de connexion et n'est pas échu."""
    await curseur.execute("select public.consomme_un_defi_anonyme(%s) as defi", (defi,))
    ligne = await curseur.fetchone()
    if ligne is None:
        raise RuntimeError("consomme_un_defi_anonyme n'a rien rendu")
    return None if ligne["defi"] is None else bytes(ligne["defi"])


async def lit_la_cle(curseur: Curseur, identifiant: bytes, session_presentee: bytes | None) -> CleLue | None:
    """La clé de cet identifiant, après avoir pris le verrou de sa personne ; `None` si elle ne peut pas
    entrer."""
    await curseur.execute(
        "select personne, cle, compteur, cle_publique, peut_etre_sauvegardee, identifiant_utilisateur"
        " from public.cle_pour_connexion(%s, %s)",
        (identifiant, session_presentee),
    )
    ligne = await curseur.fetchone()
    if ligne is None:
        return None
    return CleLue(
        personne=ligne["personne"],
        cle=ligne["cle"],
        cle_de_verification=CleDeConnexion(
            identifiant=identifiant,
            cle_publique=bytes(ligne["cle_publique"]),
            compteur=ligne["compteur"],
            peut_etre_sauvegardee=ligne["peut_etre_sauvegardee"],
            identifiant_utilisateur=bytes(ligne["identifiant_utilisateur"]),
        ),
    )


async def ouvre_la_session_de_la_cle(
    curseur: Curseur,
    cle: CleLue,
    *,
    nouveau_compteur: int,
    est_sauvegardee: bool,
    verification_utilisateur: bool,
    empreinte_du_jeton: bytes,
    appareil: Appareil,
    session_presentee: bytes | None,
    request_id: str | None,
) -> SessionDeLaCle | None:
    """Met à jour la clé et ouvre la session (0154) ; `None` si un contrôle de la base échoue (rien n'est
    écrit)."""
    await curseur.execute(
        "select session, personne from public.ouvre_une_session_par_cle(%s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s)",
        (
            cle.cle,
            cle.cle_de_verification.compteur,
            nouveau_compteur,
            est_sauvegardee,
            verification_utilisateur,
            empreinte_du_jeton,
            appareil.navigateur,
            appareil.systeme,
            session_presentee,
            request_id,
        ),
    )
    ligne = await curseur.fetchone()
    if ligne is None:
        return None
    return SessionDeLaCle(ligne["session"], ligne["personne"])


async def demande_un_defi_de_connexion(
    base: Base,
    empreintes: Empreintes,
    reglages: Settings,
    partie: PartieDeConfiance,
    *,
    ip: str | None,
    request_id: str | None,
) -> ResultatDuDefi:
    """Les options de `navigator.credentials.get()` et leur défi gardé, ou `Bloquee` (l'IP, ou le plafond
    global).

    Lève `PoivreAbsentError` sans poivre (la route répond 503 : on ne compte pas sans clé).
    """
    cle_ip = empreintes.cle_ip_requise(ip)
    async with base.connexion() as curseur:
        attente = await prendre_un_creneau_de_cle(
            curseur,
            CRENEAUX_DE_DEFI,
            cle_ip,
            limite=reglages.cle_defis_par_ip,
            fenetre_s=reglages.cle_fenetre_s,
            attente_max_s=reglages.cle_attente_max_s,
        )
        if attente.attente_s:
            return Bloquee(attente.attente_s)
        options: OptionsDeCeremonie = options_de_connexion(partie)
        if not await cree_un_defi_anonyme(curseur, options.defi, reglages.cle_defis_anonymes_max):
            journal.warning(
                "Défis de connexion par clé : plafond atteint (%s).", reglages.cle_defis_anonymes_max
            )
            return Bloquee(ATTENTE_DU_PLAFOND_S)
        return DefiDeConnexion(options.options)


async def tente_la_connexion_par_cle(
    base: Base,
    empreintes: Empreintes,
    reglages: Settings,
    partie: PartieDeConfiance,
    *,
    reponse: dict[str, Any],
    ip: str | None,
    agent: str | None,
    jeton_presente: str | None,
    request_id: str | None,
) -> ResultatDeLaConnexion:
    """Lève `PoivreAbsentError` sans poivre, `CleStockeeIllisible` si la clé lue en base ne se charge pas
    (l'une et l'autre : la route répond 503, la transaction s'annule, le défi reste valable)."""
    cle_ip = empreintes.cle_ip_requise(ip)
    jeton, empreinte_du_nouveau_jeton = jeton_neuf()
    presentee = empreinte_presentee(jeton_presente)
    async with base.connexion() as curseur:
        attente = await prendre_un_creneau_de_cle(
            curseur,
            CRENEAUX_DE_VERIFICATION,
            cle_ip,
            limite=reglages.cle_essais_par_ip,
            fenetre_s=reglages.cle_fenetre_s,
            attente_max_s=reglages.cle_attente_max_s,
        )
        if attente.attente_s:
            # Un seul événement par blocage (B21) : 100 essais refusés n'en écrivent qu'un.
            if attente.nouveau_blocage:
                await journalise_sans_lever(
                    curseur, Evenement.connexion_bloquee, cle_ip=cle_ip, request_id=request_id
                )
            return Bloquee(attente.attente_s)

        ouverte = await _verifie_et_ouvre(
            curseur,
            partie,
            reponse=reponse,
            empreinte_du_jeton=empreinte_du_nouveau_jeton,
            appareil=resume_agent(agent),
            session_presentee=presentee,
            request_id=request_id,
        )
        if ouverte is None:
            await journalise_sans_lever(
                curseur, Evenement.connexion_ratee, cle_ip=cle_ip, request_id=request_id
            )
            return Refusee()
        return Ouverte(jeton, ouverte.session, ouverte.personne)


async def _verifie_et_ouvre(
    curseur: Curseur,
    partie: PartieDeConfiance,
    *,
    reponse: dict[str, Any],
    empreinte_du_jeton: bytes,
    appareil: Appareil,
    session_presentee: bytes | None,
    request_id: str | None,
) -> SessionDeLaCle | None:
    """Défi, clé, signature, session : `None` au premier refus. Le curseur tient la transaction de
    l'appelant."""
    try:
        annonce = defi_de_la_reponse(reponse)
        identifiant = identifiant_de_la_cle(reponse)
    except ReponseDeCleRefusee as erreur:
        _note_le_refus(erreur)
        return None
    defi = await consomme_un_defi_anonyme(curseur, annonce)
    if defi is None:
        return None
    cle = await lit_la_cle(curseur, identifiant, session_presentee)
    if cle is None:
        return None
    try:
        verifiee = verifie_la_connexion(partie, reponse=reponse, defi=defi, cle=cle.cle_de_verification)
    except SignalDeClonage as erreur:
        # Signature valide, `userHandle` bon, compteur qui ne croît pas ou BE changé : un signal de
        # clonage (W3C § 7.2).
        _note_le_refus(erreur)
        await journalise_sans_lever(
            curseur, Evenement.cle_suspecte, personne=cle.personne, request_id=request_id
        )
        return None
    except ReponseDeCleRefusee as erreur:
        _note_le_refus(erreur)
        return None
    except CleStockeeIllisible:
        journal.error("Clé d'accès illisible en base : la connexion n'est pas jugée.")
        raise
    return await ouvre_la_session_de_la_cle(
        curseur,
        cle,
        nouveau_compteur=verifiee.compteur,
        est_sauvegardee=verifiee.est_sauvegardee,
        verification_utilisateur=verifiee.verification_utilisateur,
        empreinte_du_jeton=empreinte_du_jeton,
        appareil=appareil,
        session_presentee=session_presentee,
        request_id=request_id,
    )


def _note_le_refus(erreur: ReponseDeCleRefusee) -> None:
    # Le message d'un refus est fixe ; le type de sa cause seul : le texte de la cause recopie la réponse.
    journal.info("Connexion par clé refusée : %s (%s)", erreur, erreur.type_de_la_cause)
