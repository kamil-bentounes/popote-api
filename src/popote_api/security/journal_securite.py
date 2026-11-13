"""Le journal de sécurité (migration 0136) : la liste fermée des événements et l'écriture.

L'écriture se fait par `public.journalise`, dans la transaction de l'appelant : le curseur vient de
`base.connexion()` ou de `base.service()` (jamais du contexte personne : `authenticated` n'a pas l'`execute`).
Un événement ne porte ni e-mail, ni IP, ni agent : des clés HMAC (`security/empreintes.py`) et des
identifiants.
"""

from enum import StrEnum
from uuid import UUID

from popote_api.infra.db import Curseur


class Evenement(StrEnum):
    """Les valeurs sont celles de la contrainte `security_event.kind` : un test compare les deux listes."""

    connexion_reussie = "connexion_reussie"
    connexion_ratee = "connexion_ratee"
    connexion_bloquee = "connexion_bloquee"
    deconnexion = "deconnexion"
    reauthentification_reussie = "reauthentification_reussie"
    reauthentification_ratee = "reauthentification_ratee"
    session_fermee = "session_fermee"
    mot_de_passe_change = "mot_de_passe_change"
    reinitialisation_demandee = "reinitialisation_demandee"
    reinitialisation_utilisee = "reinitialisation_utilisee"
    invitation_creee = "invitation_creee"
    invitation_acceptee = "invitation_acceptee"
    invitation_revoquee = "invitation_revoquee"
    compte_supprime = "compte_supprime"
    compte_repris = "compte_repris"
    verification_fuites_indisponible = "verification_fuites_indisponible"
    code_demande = "code_demande"


async def journalise(
    curseur: Curseur,
    evenement: Evenement,
    *,
    personne: UUID | None = None,
    session: UUID | None = None,
    invitation: UUID | None = None,
    cle_compte: bytes | None = None,
    cle_ip: bytes | None = None,
    request_id: str | None = None,
) -> None:
    """Écrit un événement dans la transaction du curseur. `cle_compte` et `cle_ip` viennent d'`Empreintes`."""
    await curseur.execute(
        "select public.journalise(%s, %s, %s, %s, %s, %s, %s)",
        (str(evenement), personne, session, invitation, cle_compte, cle_ip, request_id),
    )
