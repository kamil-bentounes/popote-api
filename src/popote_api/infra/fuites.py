"""Liste de mots de passe fuités : l'API « range » de Pwned Passwords (voir docs/securite.md).

Seuls les 5 premiers caractères du SHA-1 partent (modèle k-anonymat) ; le reste de l'empreinte est comparé
ici. Ce module ne journalise rien et ne lève rien pour une panne de la liste : il rend un `ResultatFuite`
explicite, et l'appelant décide et journalise (décision B23 : mot de passe accepté, événement écrit).
Le résultat ne contient que des codes fermés : jamais le mot de passe, l'empreinte ni un message d'erreur.
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, Self

import httpx

from popote_api.config import BreachCheck, Settings

# Constantes : ni l'hôte ni le chemin ne viennent d'une entrée (pas de SSRF).
URL_DES_PLAGES = "https://api.pwnedpasswords.com/range/"
LONGUEUR_DE_LA_PLAGE = 5
# L'API exige un agent utilisateur ; on n'y met ni version ni nom d'hôte.
AGENT_UTILISATEUR = "popote"
DELAI_TOTAL_S = 3.0  # connexion, envoi et lecture de la réponse comprises
TAILLE_MAXIMALE_OCTETS = 1024 * 1024  # une réponse bourrée fait environ 40 Kio

# httpx écrit chaque requête à INFO, adresse comprise, donc la plage : on le tait.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Un suffixe SHA-1 (35 caractères hexadécimaux), deux-points, un compte.
LIGNE = re.compile(r"([0-9A-F]{35}):([0-9]+)", re.IGNORECASE)


class EtatFuite(StrEnum):
    sain = "sain"
    fuite = "fuite"
    indisponible = "indisponible"


class CauseIndisponibilite(StrEnum):
    delai = "delai"
    reseau = "reseau"
    redirection = "redirection"
    statut = "statut"
    trop_gros = "trop_gros"
    mal_forme = "mal_forme"


@dataclass(frozen=True)
class ResultatFuite:
    """Le verdict de la liste. `cause` n'existe que si la liste est indisponible."""

    etat: EtatFuite
    cause: CauseIndisponibilite | None = None

    def __post_init__(self) -> None:
        if (self.etat is EtatFuite.indisponible) != (self.cause is not None):
            raise ValueError("cause : exactement quand la liste est indisponible.")

    @classmethod
    def sain(cls) -> Self:
        return cls(EtatFuite.sain)

    @classmethod
    def fuite(cls) -> Self:
        return cls(EtatFuite.fuite)

    @classmethod
    def indisponible(cls, cause: CauseIndisponibilite) -> Self:
        return cls(EtatFuite.indisponible, cause)


class Fuites(Protocol):
    async def verifie(self, mot_de_passe: str) -> ResultatFuite:
        """Le verdict pour un mot de passe qui a déjà passé `verifie_nouveau` (donc encodable en UTF-8).

        Ne lève pas pour une panne de la liste : voir `EtatFuite.indisponible`.
        """
        ...


class _Indisponible(Exception):
    def __init__(self, cause: CauseIndisponibilite) -> None:
        super().__init__(cause.value)
        self.cause = cause


class PwnedPasswords:
    """La réalisation de `Fuites` sur https://api.pwnedpasswords.com/range/. Sans état partagé.

    `transport` ne sert qu'aux tests (transport httpx factice) : aucun appel réseau réel.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def verifie(self, mot_de_passe: str) -> ResultatFuite:
        # SHA-1 n'est pas une protection ici, c'est le format de la liste : `usedforsecurity=False`
        # le déclare (ruff S324) ; semgrep, qui ne le lit pas, est écarté pour cette seule ligne.
        # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        empreinte = hashlib.sha1(mot_de_passe.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
        plage, suffixe = empreinte[:LONGUEUR_DE_LA_PLAGE], empreinte[LONGUEUR_DE_LA_PLAGE:]
        try:
            async with asyncio.timeout(DELAI_TOTAL_S):
                corps = await self._lit(plage)
        except _Indisponible as indisponible:
            return ResultatFuite.indisponible(indisponible.cause)
        except (TimeoutError, httpx.TimeoutException):
            return ResultatFuite.indisponible(CauseIndisponibilite.delai)
        except httpx.HTTPError:
            # Le message de httpx recopierait l'adresse demandée, donc la plage : on n'en garde que le type.
            return ResultatFuite.indisponible(CauseIndisponibilite.reseau)
        try:
            presents = _suffixes_presents(corps)
        except _Indisponible as indisponible:
            return ResultatFuite.indisponible(indisponible.cause)
        return ResultatFuite.fuite() if suffixe in presents else ResultatFuite.sain()

    async def _lit(self, plage: str) -> bytes:
        # follow_redirects=False est le défaut de httpx ; écrit pour qu'on le voie.
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=DELAI_TOTAL_S,
            follow_redirects=False,
            headers={"User-Agent": AGENT_UTILISATEUR, "Add-Padding": "true"},
        ) as client:
            async with client.stream("GET", URL_DES_PLAGES + plage) as reponse:
                if reponse.is_redirect:
                    raise _Indisponible(CauseIndisponibilite.redirection)
                if reponse.status_code != httpx.codes.OK:
                    raise _Indisponible(CauseIndisponibilite.statut)
                corps = bytearray()
                async for morceau in reponse.aiter_bytes():
                    corps += morceau
                    if len(corps) > TAILLE_MAXIMALE_OCTETS:
                        raise _Indisponible(CauseIndisponibilite.trop_gros)
                return bytes(corps)


def _suffixes_presents(corps: bytes) -> set[str]:
    """Les suffixes (majuscules) de compte non nul ; les lignes à 0 sont le bourrage (`Add-Padding`).

    Toute ligne mal formée rend la réponse entière suspecte : on ne conclut pas « sain » d'un corps qu'on
    ne comprend pas, ni d'un corps vide (l'API bourre toujours la réponse).
    """
    try:
        texte = corps.decode("ascii")
    except UnicodeDecodeError:
        raise _Indisponible(CauseIndisponibilite.mal_forme) from None
    lignes = texte.split("\n")
    if lignes[-1] == "":
        lignes.pop()
    if not lignes:
        raise _Indisponible(CauseIndisponibilite.mal_forme)
    presents: set[str] = set()
    for ligne in lignes:
        correspondance = LIGNE.fullmatch(ligne.removesuffix("\r"))
        if correspondance is None:
            raise _Indisponible(CauseIndisponibilite.mal_forme)
        suffixe, compte = correspondance.groups()
        if compte.strip("0"):  # pas d'int() : un compte de 100 000 chiffres lèverait ValueError
            presents.add(suffixe.upper())
    return presents


class FuitesDesactivees:
    """Local seulement (`POPOTE_BREACH_CHECK=off`, refusé hors local par `Settings`) : tout est sain."""

    async def verifie(self, mot_de_passe: str) -> ResultatFuite:
        return ResultatFuite.sain()


def fuites_pour(reglages: Settings) -> Fuites:
    match reglages.breach_check:
        case BreachCheck.hibp:
            return PwnedPasswords()
        case BreachCheck.off:
            return FuitesDesactivees()
    raise AssertionError(reglages.breach_check)  # pragma: no cover
