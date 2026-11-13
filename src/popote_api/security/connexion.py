"""L'orchestration d'une connexion par e-mail et mot de passe (spec § 4, « Session », « Mots de passe »).

Une seule transaction (`base.connexion()`, A16) : elle se VALIDE aussi quand la connexion est refusée,
sinon le compteur d'essais et l'événement de sécurité d'un échec s'annuleraient avec lui. Le résultat est
donc rendu, jamais levé, tant que la transaction est ouverte ; la route le traduit en réponse.

Ordre, qui est la sécurité de la route : clés HMAC -> créneaux (l'IP d'abord, B6) -> `verifie_mot_de_passe`.
Un créneau refusé n'appelle JAMAIS la vérification (donc aucun `crypt()` pour un tiers qui martèle), et un
compte inconnu prend un créneau, une vérification et un événement comme un compte connu : rien ne dit
si l'adresse existe. Le jeton est tiré ici, jamais lu du client.

La réauthentification (T10, `tente_la_reauthentification`) partage les créneaux (`_prend_les_creneaux`) et
le blocage unique par fenêtre (B21) ; `ouvre_une_session` est la partie « succès » de la connexion (jeton
neuf, session, événements).
"""

from dataclasses import dataclass
from uuid import UUID

from popote_api.config import Settings
from popote_api.infra.db import Base, Curseur
from popote_api.security.appareil import resume_agent
from popote_api.security.empreintes import Empreintes, email_normalise
from popote_api.security.jeton import JetonMalFormeError, empreinte_du_jeton, jeton_neuf
from popote_api.security.journal_securite import Evenement, journalise
from popote_api.security.limites_base import CleBloquee, liberer_le_compte, prendre_les_creneaux
from popote_api.security.mots_de_passe import candidats_de_connexion
from popote_api.security.sessions_base import (
    confirme_le_changement_de_mot_de_passe,
    cree_session,
    fait_tourner_et_ferme_les_autres,
    marque_reauth,
)


@dataclass(frozen=True, slots=True)
class Ouverte:
    jeton: str  # pour le cookie, une seule fois ; la base n'en garde que l'empreinte
    session: UUID
    personne: UUID


@dataclass(frozen=True, slots=True)
class Bloquee:
    attente_s: int


@dataclass(frozen=True, slots=True)
class Refusee:
    """Identifiants incorrects : la raison (inconnu, faux, banni, supprimé...) n'est jamais distinguée."""


Resultat = Ouverte | Bloquee | Refusee


@dataclass(frozen=True, slots=True)
class Reauthentifiee:
    """Le mot de passe est le bon : `reauth_at` de la session de la personne est à l'instant."""


ResultatDeReauthentification = Reauthentifiee | Bloquee | Refusee


async def ouvre_une_session(
    curseur: Curseur,
    personne: UUID,
    *,
    agent: str | None,
    jeton_presente: str | None,
    request_id: str | None,
) -> Ouverte:
    """Jeton neuf, session, et révocation de la session PRÉSENTÉE si elle est valide (B22)."""
    empreinte_presentee = _empreinte_presentee(jeton_presente)
    jeton, empreinte = jeton_neuf()
    # La base révoque la session présentée si elle est valide et écrit elle-même `session_fermee` (0139).
    session = await cree_session(
        curseur, personne, empreinte, resume_agent(agent), session_presentee=empreinte_presentee
    )
    await journalise(
        curseur, Evenement.connexion_reussie, personne=personne, session=session, request_id=request_id
    )
    return Ouverte(jeton, session, personne)


async def tente_la_connexion(
    base: Base,
    empreintes: Empreintes,
    reglages: Settings,
    *,
    email: str,
    mot_de_passe: str,
    ip: str | None,
    agent: str | None,
    jeton_presente: str | None,
    request_id: str | None,
) -> Resultat:
    """Lève `PoivreAbsentError` sans poivre (la route répond 503 : on ne compte pas sans clé)."""
    cle_compte = empreintes.cle_compte_requise(email)
    cle_ip = empreintes.cle_ip_requise(ip)
    async with base.connexion() as curseur:
        bloquee = await _prend_les_creneaux(curseur, reglages, cle_compte, cle_ip, request_id)
        if bloquee is not None:
            return bloquee
        personne = await _verifie(curseur, email_normalise(email), mot_de_passe)
        if personne is None:
            await journalise(curseur, Evenement.connexion_ratee, cle_compte=cle_compte, request_id=request_id)
            return Refusee()
        await liberer_le_compte(curseur, cle_compte)  # le compte seul : jamais l'IP
        return await ouvre_une_session(
            curseur, personne, agent=agent, jeton_presente=jeton_presente, request_id=request_id
        )


async def tente_la_reauthentification(
    base: Base,
    empreintes: Empreintes,
    reglages: Settings,
    *,
    personne: UUID,
    session: UUID,
    email: str,
    mot_de_passe: str,
    ip: str | None,
    request_id: str | None,
) -> ResultatDeReauthentification:
    """Mêmes créneaux que la connexion, sur le compte de la personne puis l'IP : une session volée ne peut
    donc pas forcer le mot de passe. `email` est celui de la personne, lu par la route sous sa session.

    Succès : le compteur du compte est remis à zéro et `reauth_at` de SA session seulement est posé.
    Lève `PoivreAbsentError` sans poivre (la route répond 503).
    """
    cle_compte = empreintes.cle_compte_requise(email)
    cle_ip = empreintes.cle_ip_requise(ip)
    async with base.connexion() as curseur:
        bloquee = await _prend_les_creneaux(curseur, reglages, cle_compte, cle_ip, request_id)
        if bloquee is not None:
            return bloquee
        if not await _verifie_de(curseur, personne, mot_de_passe):
            await journalise(
                curseur,
                Evenement.reauthentification_ratee,
                personne=personne,
                session=session,
                cle_compte=cle_compte,
                request_id=request_id,
            )
            return Refusee()
        await liberer_le_compte(curseur, cle_compte)  # le compte seul : jamais l'IP
        await marque_reauth(curseur, session, personne)
        await journalise(
            curseur,
            Evenement.reauthentification_reussie,
            personne=personne,
            session=session,
            request_id=request_id,
        )
        return Reauthentifiee()


@dataclass(frozen=True, slots=True)
class Tournee:
    jeton: str  # le nouveau jeton, pour le cookie ; la base n'en garde que l'empreinte
    session: UUID


async def fait_tourner_la_session_et_ferme_les_autres(
    base: Base, empreinte_courante: bytes
) -> Tournee | None:
    """Étape 2 du changement de mot de passe : une transaction, validée avant l'appel à Auth.

    `None` : l'empreinte ne désigne plus de session valide (un autre changement vient de la faire tourner) ;
    la route répond `401` sans cookie."""
    jeton, empreinte = jeton_neuf()
    async with base.connexion() as curseur:
        session = await fait_tourner_et_ferme_les_autres(curseur, empreinte_courante, empreinte)
    return None if session is None else Tournee(jeton, session)


async def confirme_le_mot_de_passe_change(
    base: Base, personne: UUID, session: UUID, request_id: str | None
) -> None:
    """Étape 4, après le succès d'Auth seulement : `password_set`, l'événement, et les autres sessions
    refermées (une connexion faite avec l'ancien mot de passe pendant l'appel à Auth ne survit pas)."""
    async with base.connexion() as curseur:
        await confirme_le_changement_de_mot_de_passe(curseur, personne, session, request_id)


async def journalise_la_liste_de_fuites_indisponible(
    base: Base, personne: UUID, request_id: str | None
) -> None:
    """B23 : la liste est hors service, le mot de passe est accepté et l'événement le dit (sans valeur)."""
    async with base.connexion() as curseur:
        await journalise(
            curseur,
            Evenement.verification_fuites_indisponible,
            personne=personne,
            request_id=request_id,
        )


async def _prend_les_creneaux(
    curseur: Curseur, reglages: Settings, cle_compte: bytes, cle_ip: bytes, request_id: str | None
) -> Bloquee | None:
    """Les créneaux, l'IP d'abord (B6) ; `Bloquee` s'il en manque un, et alors rien d'autre ne s'exécute."""
    creneaux = await prendre_les_creneaux(curseur, cle_compte, cle_ip, reglages)
    if creneaux.passe:
        return None
    # Un seul événement par fenêtre de blocage (B21) : 100 essais refusés n'en écrivent qu'un.
    if creneaux.nouveau_blocage is not None:
        # La clé qui vient de bloquer, et elle seule : un blocage d'IP ne marque pas le compte visé.
        par_ip = creneaux.nouveau_blocage is CleBloquee.ip
        await journalise(
            curseur,
            Evenement.connexion_bloquee,
            cle_compte=None if par_ip else cle_compte,
            cle_ip=cle_ip if par_ip else None,
            request_id=request_id,
        )
    return Bloquee(creneaux.attente_s)


def _empreinte_presentee(jeton: str | None) -> bytes | None:
    if jeton is None:
        return None
    try:
        return empreinte_du_jeton(jeton)
    except JetonMalFormeError:
        return None  # un cookie invalide est ignoré, sans erreur


async def _verifie(curseur: Curseur, email: str, mot_de_passe: str) -> UUID | None:
    # Aucun candidat (plus de 72 octets, nul...) : refus sans appel à la base ; la forme normalisée d'abord.
    for candidat in candidats_de_connexion(mot_de_passe):
        personne = await verifie_un_candidat(curseur, email, candidat)
        if personne is not None:
            return personne
    return None


async def verifie_un_candidat(curseur: Curseur, email: str, candidat: str) -> UUID | None:
    """Un seul appel à `public.verifie_mot_de_passe` : le seul `crypt()` de la connexion."""
    await curseur.execute("select public.verifie_mot_de_passe(%s, %s) as personne", (email, candidat))
    ligne = await curseur.fetchone()
    personne: UUID | None = ligne["personne"] if ligne is not None else None
    return personne


async def _verifie_de(curseur: Curseur, personne: UUID, mot_de_passe: str) -> bool:
    # Mêmes candidats que la connexion (forme normalisée d'abord, puis telle quelle) : un mot de passe
    # ancien non normalisé s'accepte ici aussi.
    for candidat in candidats_de_connexion(mot_de_passe):
        if await verifie_un_candidat_de(curseur, personne, candidat):
            return True
    return False


async def verifie_un_candidat_de(curseur: Curseur, personne: UUID, candidat: str) -> bool:
    """Un seul appel à `public.verifie_mot_de_passe_de` : le seul `crypt()` de la réauthentification."""
    await curseur.execute("select public.verifie_mot_de_passe_de(%s, %s) as ok", (personne, candidat))
    ligne = await curseur.fetchone()
    return bool(ligne is not None and ligne["ok"])
