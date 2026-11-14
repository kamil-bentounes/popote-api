"""L'enregistrement d'une clé d'accès, côté base (migration 0153) : défi, consommation, écriture.

Tout se joue dans la transaction de la personne (`personne.curseur`), sous `authenticated` : les fonctions
lisent `auth.uid()`, jamais un identifiant donné par la route. La session se désigne par l'EMPREINTE de son
cookie, pas par son identifiant (qu'un simple jeton d'accès GoTrue lit par `mes_sessions`).

Un refus est un RÉSULTAT (`Refus`), jamais une exception : la route le traduit. Mais la route, elle, lève
`Probleme` (la classe de route idempotente l'exige) : la transaction s'annule alors, et le défi consommé
redevient valable jusqu'à son échéance ; rien ne s'est écrit.

Ni identifiant de clé, ni clé publique, ni défi, ni option ne sont journalisés : les `repr` des objets de
`infra/webauthn.py` les cachent, et aucun message d'erreur d'ici ne les cite.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from popote_api.infra.db import Curseur
from popote_api.infra.webauthn import (
    CleEnregistree,
    CleExistante,
    PartieDeConfiance,
    options_d_enregistrement,
)

BUT_D_ENREGISTREMENT: Final = "registration"
TAILLE_DE_L_IDENTIFIANT_D_UTILISATEUR: Final = 64


class Refus(StrEnum):
    """Les valeurs sont celles de `etat` côté base (hors `creee`)."""

    session_perimee = "session_perimee"
    preuve_perimee = "preuve_perimee"
    trop_de_cles = "trop_de_cles"
    cle_deja_enregistree = "cle_deja_enregistree"


@dataclass(frozen=True, slots=True)
class DefiCree:
    options: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class CleAjoutee:
    id: UUID
    created_at: datetime


MON_IDENTIFIANT = "select public.mon_identifiant_webauthn(%s) as identifiant"
MES_CLES = "select identifiant, transports from public.mes_identifiants_de_cle()"
CREE_UN_DEFI = "select public.cree_un_defi(%s, %s, %s) as etat"
CONSOMME_UN_DEFI = "select public.consomme_un_defi(%s, %s, %s) as defi"
ENREGISTRE = (
    "select etat, id, created_at"
    " from public.enregistre_une_cle(%s, %s, %s, %s, %s::text[], %s, %s, %s, %s, %s, %s)"
)


async def _une_ligne(curseur: Curseur, requete: str, valeurs: tuple[object, ...]) -> dict[str, Any]:
    await curseur.execute(requete, valeurs)
    ligne = await curseur.fetchone()
    if ligne is None:
        msg = "Une fonction de clé rend toujours une ligne."
        raise RuntimeError(msg)
    return ligne


async def demande_un_defi_d_enregistrement(
    curseur: Curseur,
    partie: PartieDeConfiance,
    *,
    empreinte_de_session: bytes,
    nom_d_utilisateur: str,
    nom_affiche: str,
) -> DefiCree | Refus:
    """Les options de `create()` et leur défi gardé ; `Refus` si la session est périmée ou dix clés prises.

    L'identifiant d'utilisateur se crée sous le verrou de personne AVANT les options : deux onglets pour la
    première clé repartent avec le même, sinon la seconde clé serait refusée sur son `userHandle`.
    """
    candidat = secrets.token_bytes(TAILLE_DE_L_IDENTIFIANT_D_UTILISATEUR)
    identifiant = (await _une_ligne(curseur, MON_IDENTIFIANT, (candidat,)))["identifiant"]
    await curseur.execute(MES_CLES)
    existantes = [
        CleExistante(bytes(ligne["identifiant"]), tuple(ligne["transports"]))
        for ligne in await curseur.fetchall()
    ]
    options = options_d_enregistrement(
        partie,
        identifiant_utilisateur=bytes(identifiant),
        nom_d_utilisateur=nom_d_utilisateur,
        nom_affiche=nom_affiche,
        cles_existantes=existantes,
    )
    etat = (
        await _une_ligne(curseur, CREE_UN_DEFI, (empreinte_de_session, BUT_D_ENREGISTREMENT, options.defi))
    )["etat"]
    if etat == "creee":
        return DefiCree(options.options)
    return Refus(etat)


async def consomme_le_defi(curseur: Curseur, *, empreinte_de_session: bytes, defi: bytes) -> bytes | None:
    """Le défi, une seule fois, s'il a été demandé par cette personne et cette session et n'est pas échu."""
    ligne = await _une_ligne(curseur, CONSOMME_UN_DEFI, (empreinte_de_session, BUT_D_ENREGISTREMENT, defi))
    return None if ligne["defi"] is None else bytes(ligne["defi"])


async def enregistre_la_cle(
    curseur: Curseur, *, empreinte_de_session: bytes, cle: CleEnregistree, nom: str, request_id: str | None
) -> CleAjoutee | Refus:
    """Écrit la clé sous le verrou de personne, la session et sa preuve relues en base (`Refus` sinon)."""
    ligne = await _une_ligne(
        curseur,
        ENREGISTRE,
        (
            empreinte_de_session,
            cle.identifiant,
            cle.cle_publique,
            cle.compteur,
            list(cle.transports),
            cle.peut_etre_sauvegardee,
            cle.est_sauvegardee,
            cle.verification_initialisee,
            UUID(cle.aaguid),
            nom,
            request_id,
        ),
    )
    if ligne["etat"] == "creee":
        return CleAjoutee(ligne["id"], ligne["created_at"])
    return Refus(ligne["etat"])
