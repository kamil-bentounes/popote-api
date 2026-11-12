"""Accès à Postgres. Pour 0.2, seulement la vérification de disponibilité."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import LiteralString

import psycopg

DELAI_TOTAL_S = 3  # connexion et requête comprises
DUREE_DU_CACHE_S = 5.0


async def repond(dsn: str, requete: LiteralString = "select 1") -> bool:
    try:
        async with asyncio.timeout(DELAI_TOTAL_S):
            async with await psycopg.AsyncConnection.connect(
                dsn, connect_timeout=5, prepare_threshold=None
            ) as connexion:
                await connexion.execute(requete)
        return True
    except (psycopg.Error, TimeoutError):
        return False


class SondeBase:
    """La disponibilité de la base, mise en cache pour ne pas ouvrir une connexion par sondage.

    Le résultat, succès ou échec, reste valable `DUREE_DU_CACHE_S` secondes, et un seul sondage
    est en vol à la fois : un afflux de requêtes sur /readyz n'épuise pas les connexions.
    """

    def __init__(
        self,
        dsn: str | None,
        *,
        verifie: Callable[[str], Awaitable[bool]] | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dsn = dsn
        self._verifie = verifie
        self._horloge = horloge
        self._verrou = asyncio.Lock()
        self._valable_jusqu_a: float | None = None
        self._resultat = False

    async def disponible(self) -> bool:
        if self._dsn is None:
            return False
        async with self._verrou:
            if self._valable_jusqu_a is not None and self._horloge() < self._valable_jusqu_a:
                return self._resultat
            verifie = self._verifie or repond  # `repond` résolu à l'appel : le test peut le remplacer
            self._resultat = await verifie(self._dsn)
            self._valable_jusqu_a = self._horloge() + DUREE_DU_CACHE_S
            return self._resultat
