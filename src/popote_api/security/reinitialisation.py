"""La demande de réinitialisation (T15a ; spec § 4, § 3.6 ; B5, B24). L'usage du lien est T15b.

UNE transaction de contexte connexion : le créneau (3 par heure et par (e-mail, IP), pris même pour une
adresse inconnue), le lien et l'événement. Un refus de limite se RENDRE (il ne s'annule pas avec la
transaction : le compteur doit rester) ; la route le lève après coup. Le jeton est tiré avant la base,
que le compte existe ou non : le travail ne dépend pas de l'existence du compte. L'envoi du mail se
fait après la réponse.
"""

from dataclasses import dataclass, field

from popote_api.config import Settings
from popote_api.infra.db import Base
from popote_api.security.empreintes import Empreintes, email_normalise
from popote_api.security.jeton import jeton_neuf
from popote_api.security.journal_securite import Evenement, journalise
from popote_api.security.limites_base import prendre_un_creneau_de_reinitialisation


@dataclass(frozen=True, slots=True)
class Courrier:
    """Ce qu'il faut envoyer : l'adresse et le jeton. Ni l'un ni l'autre n'entre dans un `repr`."""

    adresse: str = field(repr=False)
    jeton: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Bloquee:
    attente_s: int


@dataclass(frozen=True, slots=True)
class Demandee:
    """`courrier` : `None` si le compte ne reçoit pas de lien (inconnu, banni, supprimé, sans foyer)."""

    courrier: Courrier | None


async def demande_la_reinitialisation(
    base: Base,
    empreintes: Empreintes,
    reglages: Settings,
    *,
    email: str,
    ip: str | None,
    request_id: str | None,
) -> Bloquee | Demandee:
    """Lève `PoivreAbsentError` sans poivre (rien ne se compte sans clé)."""
    cle = empreintes.cle_reinitialisation_requise(email, ip)
    adresse = email_normalise(email)
    jeton, empreinte = jeton_neuf()
    async with base.connexion() as curseur:
        attente = await prendre_un_creneau_de_reinitialisation(curseur, cle, reglages)
        if attente:
            return Bloquee(attente)
        await curseur.execute("select public.cree_reinitialisation(%s, %s) as personne", (adresse, empreinte))
        ligne = await curseur.fetchone()
        if ligne is None:  # une fonction scalaire rend toujours une ligne
            raise RuntimeError("cree_reinitialisation n'a rien rendu")
        personne = ligne["personne"]
        # L'événement ne s'écrit que pour un compte qui reçoit un lien : une adresse inconnue n'écrit qu'un
        # compteur (purgé en 24 h), jamais une ligne gardée 90 jours (sinon une IP remplirait la base).
        if personne is not None:
            await journalise(
                curseur,
                Evenement.reinitialisation_demandee,
                personne=personne,
                cle_compte=empreintes.cle_compte(email),
                cle_ip=empreintes.cle_ip(ip),
                request_id=request_id,
            )
    return Demandee(Courrier(adresse, jeton) if personne is not None else None)
