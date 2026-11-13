"""L'orchestration d'une connexion par e-mail et mot de passe (spec § 4, « Session », « Mots de passe »).

Une seule transaction (`base.connexion()`, A16) : elle se VALIDE aussi quand la connexion est refusée,
sinon le compteur d'essais et l'événement de sécurité d'un échec s'annuleraient avec lui. Le résultat est
donc rendu, jamais levé, tant que la transaction est ouverte ; la route le traduit en réponse.

Ordre, qui est la sécurité de la route : clés HMAC -> créneaux (l'IP d'abord, B6) -> `verifie_mot_de_passe`.
Un créneau refusé n'appelle JAMAIS la vérification (donc aucun `crypt()` pour un tiers qui martèle), et un
compte inconnu prend un créneau, une vérification et un événement comme un compte connu : rien ne dit
si l'adresse existe. Le jeton est tiré ici, jamais lu du client.

Réutilisée par la réauthentification (T10) pour la fabrique de session ; `ouvre_une_session` en est la
partie « succès » (jeton neuf, session, événements).
"""

from dataclasses import dataclass
from uuid import UUID

from popote_api.config import Settings
from popote_api.infra.db import Base, Curseur
from popote_api.security.appareil import resume_agent
from popote_api.security.empreintes import Empreintes, email_normalise
from popote_api.security.jeton import JetonMalFormeError, empreinte_du_jeton, jeton_neuf
from popote_api.security.journal_securite import Evenement, journalise
from popote_api.security.limites_base import liberer_le_compte, prendre_les_creneaux
from popote_api.security.mots_de_passe import candidats_de_connexion
from popote_api.security.sessions_base import cree_session


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
        creneaux = await prendre_les_creneaux(curseur, cle_compte, cle_ip, reglages)
        if not creneaux.passe:
            # Un seul événement par fenêtre de blocage (B21) : 100 essais refusés n'en écrivent qu'un.
            if creneaux.nouveau_blocage is not None:
                await journalise(
                    curseur, Evenement.connexion_bloquee, cle_compte=cle_compte, request_id=request_id
                )
            return Bloquee(creneaux.attente_s)
        personne = await _verifie(curseur, email_normalise(email), mot_de_passe)
        if personne is None:
            await journalise(curseur, Evenement.connexion_ratee, cle_compte=cle_compte, request_id=request_id)
            return Refusee()
        await liberer_le_compte(curseur, cle_compte)  # le compte seul : jamais l'IP
        return await ouvre_une_session(
            curseur, personne, agent=agent, jeton_presente=jeton_presente, request_id=request_id
        )


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
