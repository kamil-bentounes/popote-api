"""Les sessions côté base (migration 0139) : créer, faire tourner, fermer, marquer, lire.

Le curseur vient de `base.connexion()` ou de `base.service()` (jamais du contexte personne :
`authenticated` n'a pas l'`execute`). Ici ne passent que des empreintes SHA-256, jamais un jeton. Une seule
transaction par requête :
l'appelant décide quand elle se valide.
"""

from uuid import UUID

from popote_api.infra.db import Curseur, SessionCourante
from popote_api.security.appareil import Appareil

__all__ = [
    "SessionCourante",
    "confirme_le_changement_de_mot_de_passe",
    "cree_session",
    "fait_tourner_et_ferme_les_autres",
    "fait_tourner_session",
    "ferme_session",
    "marque_reauth",
    "session_courante",
]


async def cree_session(
    curseur: Curseur,
    personne: UUID,
    empreinte: bytes,
    appareil: Appareil,
    *,
    session_presentee: bytes | None = None,
) -> UUID:
    """Crée la session ; ferme la plus ancienne au-delà de 10 actives et la session PRÉSENTÉE si valide."""
    await curseur.execute(
        "select public.cree_session(%s, %s, %s, %s, %s) as id",
        (personne, empreinte, appareil.navigateur, appareil.systeme, session_presentee),
    )
    ligne = await curseur.fetchone()
    if ligne is None:
        raise RuntimeError("cree_session n'a rien rendu")
    identifiant: UUID = ligne["id"]
    return identifiant


async def session_courante(curseur: Curseur, empreinte: bytes) -> SessionCourante | None:
    await curseur.execute(
        "select person_id, session_id, reauth_at from public.session_courante(%s)", (empreinte,)
    )
    ligne = await curseur.fetchone()
    if ligne is None:
        return None
    return SessionCourante(ligne["person_id"], ligne["session_id"], ligne["reauth_at"])


async def fait_tourner_session(curseur: Curseur, ancienne: bytes, nouvelle: bytes) -> UUID | None:
    """Change l'empreinte d'une session valide (l'ancienne meurt aussitôt) ; `None` si elle ne l'est pas."""
    await curseur.execute("select public.fait_tourner_session(%s, %s) as id", (ancienne, nouvelle))
    ligne = await curseur.fetchone()
    identifiant: UUID | None = ligne["id"] if ligne is not None else None
    return identifiant


async def ferme_session(curseur: Curseur, empreinte: bytes) -> UUID | None:
    await curseur.execute("select public.ferme_session(%s) as id", (empreinte,))
    ligne = await curseur.fetchone()
    identifiant: UUID | None = ligne["id"] if ligne is not None else None
    return identifiant


async def marque_reauth(curseur: Curseur, session: UUID, personne: UUID) -> bool:
    """Marque la session réauthentifiée ; faux (sans effet) si autre personne ou session fermée."""
    await curseur.execute("select public.marque_reauth(%s, %s) as ok", (session, personne))
    ligne = await curseur.fetchone()
    return bool(ligne is not None and ligne["ok"])


async def fait_tourner_et_ferme_les_autres(curseur: Curseur, ancienne: bytes, nouvelle: bytes) -> UUID | None:
    """Une seule fonction SQL (0141) : fait tourner la session, ferme les autres et celles de Supabase Auth.

    `None` si l'ancienne empreinte ne désigne aucune session valide (un second changement simultané)."""
    await curseur.execute(
        "select public.fait_tourner_et_ferme_les_autres(%s, %s) as id", (ancienne, nouvelle)
    )
    ligne = await curseur.fetchone()
    identifiant: UUID | None = ligne["id"] if ligne is not None else None
    return identifiant


async def confirme_le_changement_de_mot_de_passe(
    curseur: Curseur, personne: UUID, session: UUID, request_id: str | None
) -> None:
    """`password_set`, événement `mot_de_passe_change`, autres sessions refermées (0141)."""
    await curseur.execute(
        "select public.confirme_le_changement_de_mot_de_passe(%s, %s, %s)", (personne, session, request_id)
    )
