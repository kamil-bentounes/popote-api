"""La demande de code de connexion (0.4bis S5 ; spec § 3.6, § 4 ; D3, B6, B24). La vérification est S7.

UNE transaction de contexte connexion : les créneaux, puis `demande_un_code`, qui fait le même travail pour
une adresse connue et inconnue. Un refus de limite se RENDRE (la transaction se valide : le compteur doit
rester) ; la route le lève après coup. Le code et son empreinte sont tirés avant la base, que le compte
existe ou non : le travail ne dépend pas de l'existence du compte. Le mail part après la réponse, pour une
personne réelle et un code neuf seulement ; le coupe-circuit global se prend là, à l'envoi réel : une
adresse inventée n'y compte pas.
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from starlette.datastructures import State

from popote_api.config import Settings
from popote_api.infra.db import Base
from popote_api.infra.mails import MessageCode, envoie_sans_remonter
from popote_api.security.codes import VALIDITE_DU_CODE_MIN, code_neuf
from popote_api.security.empreintes import Empreintes, email_normalise
from popote_api.security.limites_base import prendre_les_creneaux_de_demande, prendre_un_envoi

journal = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Courrier:
    """Ce qu'il faut envoyer : l'adresse et le code. Ni l'un ni l'autre n'entre dans un `repr`."""

    adresse: str = field(repr=False)
    code: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Bloquee:
    attente_s: int


@dataclass(frozen=True, slots=True)
class Demandee:
    """`code_request_id` : celui de la demande en cours (le même pendant 60 s). `courrier` : `None` si rien
    ne part (adresse inconnue, bannie, supprimée, sans profil, ou code parti il y a moins de 60 s)."""

    code_request_id: UUID
    courrier: Courrier | None


async def demande_le_code(
    base: Base,
    empreintes: Empreintes,
    reglages: Settings,
    *,
    email: str,
    ip: str | None,
    request_id: str | None,
) -> Bloquee | Demandee:
    """Lève `PoivreAbsentError` sans poivre (rien ne se compte ni ne s'écrit sans clé)."""
    cle_compte = empreintes.cle_compte_requise(email)
    cle_ip = empreintes.cle_ip_requise(ip)
    cle_paire = empreintes.cle_paire_de_code_requise(email, ip)
    adresse = email_normalise(email)
    code, identifiant = code_neuf(), uuid4()
    empreinte = empreintes.empreinte_du_code(identifiant, cle_compte, code)
    async with base.connexion() as curseur:
        attente = await prendre_les_creneaux_de_demande(curseur, cle_ip, cle_paire, cle_compte, reglages)
        if attente:
            return Bloquee(attente)
        await curseur.execute(
            "select personne, demande, nouveau from public.demande_un_code(%s, %s, %s, %s, %s, %s)",
            (adresse, cle_compte, identifiant, empreinte, cle_ip, request_id),
        )
        ligne = await curseur.fetchone()
        if ligne is None:  # une fonction qui rend toujours une ligne
            raise RuntimeError("demande_un_code n'a rien rendu")
    envoyer = ligne["personne"] is not None and ligne["nouveau"]
    return Demandee(ligne["demande"], Courrier(adresse, code) if envoyer else None)


async def envoie_le_courrier(app_state: State, courrier: Courrier) -> None:
    """Après la réponse : le coupe-circuit global, puis l'envoi. Rien n'en remonte à la réponse déjà partie.

    Un échec se journalise par son type seul (jamais l'adresse ni le code). Un coupe-circuit ouvert, comme une
    erreur de la base en le prenant, jette le mail : le code reste valable, la clé d'accès fonctionne.
    """
    try:
        async with app_state.base.connexion() as curseur:
            attente = await prendre_un_envoi(curseur, app_state.settings)
    except Exception as erreur:  # une tâche d'arrière-plan ne fait jamais échouer une réponse déjà partie
        journal.error("Mail (code) non envoyé : coupe-circuit illisible (%s)", type(erreur).__name__)
        return
    if attente:
        journal.error("Mail (code) non envoyé : coupe-circuit global ouvert")
        return
    try:
        message = MessageCode(courrier.adresse, courrier.code, VALIDITE_DU_CODE_MIN)
    except ValueError as erreur:  # une adresse de compte avec un blanc : le mail n'est pas écrit
        journal.error("Mail (code) non envoyé : message invalide (%s)", type(erreur).__name__)
        return
    await envoie_sans_remonter(app_state.mails.envoie_le_code, message, "code")
