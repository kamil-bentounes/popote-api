"""Accès à Postgres. Pour 0.2, seulement la vérification de disponibilité."""

import psycopg


async def repond(dsn: str) -> bool:
    try:
        async with await psycopg.AsyncConnection.connect(
            dsn, connect_timeout=5, prepare_threshold=None
        ) as connexion:
            await connexion.execute("select 1")
        return True
    except psycopg.Error:
        return False
