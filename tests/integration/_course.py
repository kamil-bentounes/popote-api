"""Le harnais des courses déterministes (0.4bis S6 ; règle d'exécution du plan).

Jamais un `sleep` comme preuve. Une connexion A prend le verrou et ne valide pas ; B démarre ; on attend que
`pg_stat_activity` montre B en attente d'un verrou ; A valide ; on rend le sort de B. Un test qui veut prouver
que B n'attend PAS passe par `ne_fait_pas_attendre`.
"""

import asyncio
from collections.abc import Awaitable, Callable

import psycopg
from _connexions import DSN_API, connecte

Ligne = tuple[object, ...]
PATIENCE_S = 10.0


async def attend_un_verrou(admin: psycopg.Connection[Ligne], motif: str, bloque_par: int) -> int:
    """Rend le pid du backend dont la requête contient `motif`, quand A (`bloque_par`) le fait attendre.

    Le pid de A est exact : une autre suite sur la même base ne sert jamais de fausse barrière."""
    async with asyncio.timeout(PATIENCE_S):
        while True:
            ligne = admin.execute(
                "select pid from pg_stat_activity where %s = any(pg_blocking_pids(pid)) and query like %s",
                (bloque_par, f"%{motif}%"),
            ).fetchone()
            if ligne is not None:
                return int(ligne[0])  # type: ignore[call-overload]
            await asyncio.sleep(0.01)  # la boucle d'événements laisse B avancer ; la preuve est dans la base


async def course[T](
    admin: psycopg.Connection[Ligne],
    ouvre_a: Callable[[psycopg.Connection[Ligne]], object],
    b: Callable[[], Awaitable[T]],
    motif_de_b: str,
) -> T:
    """A (`popote_api`) joue `ouvre_a` sans valider ; B attend sans avoir écrit ; A valide ; rend B."""
    with connecte(DSN_API) as a:
        ouvre_a(a)
        tache = asyncio.create_task(b())
        try:
            pid = await attend_un_verrou(admin, motif_de_b, a.info.backend_pid)
            # Le verrou d'abord, avant toute ligne : B attend sans avoir écrit (pas d'identifiant de
            # transaction), sinon il tiendrait une ligne en attendant la personne (ordre du plan).
            ecrit = admin.execute(
                "select 1 from pg_locks where pid = %s and locktype = 'transactionid' and granted", (pid,)
            ).fetchone()
            assert ecrit is None, "B a écrit une ligne avant de prendre le verrou de la personne"
        except BaseException:
            tache.cancel()
            a.rollback()
            await asyncio.gather(tache, return_exceptions=True)
            raise
        a.commit()
        return await tache


async def ne_fait_pas_attendre[T](
    ouvre_a: Callable[[psycopg.Connection[Ligne]], object], b: Callable[[], Awaitable[T]]
) -> T:
    """A prend son verrou sans valider ; B doit aboutir tout de suite (5 s de borne : l'échec seulement)."""
    with connecte(DSN_API) as a:
        ouvre_a(a)
        try:
            return await asyncio.wait_for(b(), timeout=5)
        finally:
            a.rollback()
