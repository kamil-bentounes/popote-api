"""Les limites de connexion comptées en base (migration 0138) : l'appel Python des fonctions SQL.

Les compteurs vivent en base, pas en mémoire : plusieurs processus de l'API (et un redémarrage) partagent les
mêmes. La décision est UNE fonction atomique, `public.prend_les_creneaux_de_connexion` (0151) : l'IP d'abord,
puis le compte entier (lu), le couple (compte, IP), le compte entier (compté) ; un créneau refusé n'use jamais
les suivants (B6) et l'IP d'un tiers ne bloque que son couple (S7c). Les clés sont des HMAC
(`security/empreintes.py`) ; les limites viennent de `config.py`.

Le curseur vient de `base.connexion()` ou de `base.service()` (contexte sans personne) : `authenticated`
n'a pas l'`execute` de ces fonctions.
"""

from dataclasses import dataclass
from enum import StrEnum

from popote_api.config import Settings
from popote_api.infra.db import Curseur


class CleBloquee(StrEnum):
    """Quelle clé vient de passer en blocage : seule cette fois-là, `connexion_bloquee` s'écrit (B21)."""

    ip = "ip"
    couple = "couple"
    compte = "account"  # le compte entier, toutes IP confondues


@dataclass(frozen=True, slots=True)
class Creneaux:
    """`attente_s` vaut 0 quand la connexion peut être tentée ; sinon le nombre de secondes à attendre."""

    attente_s: int
    nouveau_blocage: CleBloquee | None

    @property
    def passe(self) -> bool:
        return self.attente_s == 0


async def prendre_les_creneaux(
    curseur: Curseur, cle_couple: bytes, cle_compte: bytes, cle_ip: bytes, reglages: Settings
) -> Creneaux:
    """Prend les créneaux de l'IP, du couple (compte, IP), puis du compte entier, dans cet ordre."""
    await curseur.execute(
        "select attente_s, nouveau_blocage from public.prend_les_creneaux_de_connexion("
        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            cle_couple,
            cle_compte,
            cle_ip,
            reglages.connexion_essais_par_couple,
            reglages.connexion_essais_compte_entier,
            reglages.connexion_essais_par_ip,
            reglages.connexion_fenetre_s,
            reglages.connexion_attente_max_s,
            reglages.connexion_fenetre_compte_entier_s,
            reglages.connexion_blocage_compte_entier_s,
        ),
    )
    ligne = await curseur.fetchone()
    if ligne is None:  # une fonction `returns table` qui rend une ligne : jamais vide
        raise RuntimeError("prend_les_creneaux_de_connexion n'a rendu aucune ligne")
    bloquee = ligne["nouveau_blocage"]
    return Creneaux(ligne["attente_s"], CleBloquee(bloquee) if bloquee is not None else None)


async def liberer_le_couple(curseur: Curseur, cle_couple: bytes, cle_compte: bytes) -> None:
    """Après un succès : le couple à zéro, un refus de moins sur le compte entier, jamais l'IP."""
    await curseur.execute("select public.libere_le_couple(%s, %s)", (cle_couple, cle_compte))


async def prendre_un_creneau_de_reinitialisation(curseur: Curseur, cle: bytes, reglages: Settings) -> int:
    """0 si la demande peut partir, sinon l'attente en secondes. `cle` : `Empreintes.cle_reinitialisation`."""
    await curseur.execute(
        "select public.prend_un_creneau_reinit(%s, %s, %s) as attente_s",
        (cle, reglages.reinitialisation_essais, reglages.reinitialisation_fenetre_s),
    )
    ligne = await curseur.fetchone()
    if ligne is None:
        raise RuntimeError("prend_un_creneau_reinit n'a rien rendu")
    return int(ligne["attente_s"])


async def prendre_les_creneaux_de_demande(
    curseur: Curseur, cle_ip: bytes, cle_paire: bytes, cle_compte: bytes, reglages: Settings
) -> int:
    """0 si la demande de code peut aller plus loin, sinon l'attente en secondes (migration 0147).

    L'IP d'abord, puis (adresse, IP), puis adresse : un refus n'use pas les suivants (B6). Sans escalade :
    un refus ne compte pas et ne prolonge rien. Les clés viennent d'`Empreintes`.
    """
    await curseur.execute(
        "select public.prend_les_creneaux_de_demande(%s, %s, %s, %s, %s, %s, %s, %s) as attente_s",
        (
            cle_ip,
            cle_paire,
            cle_compte,
            reglages.code_demandes_par_ip,
            reglages.code_demandes_par_paire,
            reglages.code_demandes_par_compte,
            reglages.code_fenetre_s,
            reglages.code_fenetre_compte_s,
        ),
    )
    ligne = await curseur.fetchone()
    if ligne is None:  # une fonction scalaire rend toujours une ligne
        raise RuntimeError("prend_les_creneaux_de_demande n'a rien rendu")
    return int(ligne["attente_s"])


async def prendre_un_envoi(curseur: Curseur, reglages: Settings) -> int:
    """0 si le mail peut partir, sinon l'attente en secondes : le coupe-circuit global des mails (0147)."""
    await curseur.execute(
        "select public.prend_un_envoi(%s, %s) as attente_s",
        (reglages.mail_global_par_fenetre, reglages.mail_global_fenetre_s),
    )
    ligne = await curseur.fetchone()
    if ligne is None:
        raise RuntimeError("prend_un_envoi n'a rien rendu")
    return int(ligne["attente_s"])
