"""Les fixtures des tests contre la base : foyers de test, pools, `Base`. Reprises par les conftest."""

from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from _connexions import (
    ADMIN_LOCAL,
    DSN_ADMIN,
    DSN_API,
    DSN_API_DISTANT,
    DSN_INTERNAL,
    DSN_INTERNAL_DISTANT,
)
from _fabrique import Fabrique

from popote_api.infra.db import Base, Pool, cree_pool


@pytest.fixture(scope="session", autouse=True)
def mots_de_passe_locaux() -> None:
    """Pose les mots de passe locaux, seulement quand aucune adresse distante n'est fournie."""
    if DSN_API_DISTANT or DSN_INTERNAL_DISTANT:
        if not (DSN_API_DISTANT and DSN_INTERNAL_DISTANT):
            pytest.fail("POPOTE_TEST_DSN_API et POPOTE_TEST_DSN_INTERNAL vont ensemble")
        return
    with psycopg.connect(ADMIN_LOCAL, autocommit=True) as cx:
        cx.execute("alter role popote_api password 'essai-local'")
        cx.execute("alter role popote_internal password 'essai-local'")


@pytest.fixture
def fabrique() -> Iterator[Fabrique]:
    """Des foyers et des personnes de test ; ils sont retirés à la fin du test, même s'il échoue."""
    with psycopg.connect(DSN_ADMIN, autocommit=True) as admin:
        fabrique = Fabrique(admin)
        try:
            yield fabrique
        finally:
            fabrique.nettoie()


@pytest.fixture
async def pools() -> AsyncIterator[tuple[Pool, Pool]]:
    """Les deux pools, ouverts, tels que l'application les bâtit ; `Base` les enveloppe dans le test."""
    api, interne = cree_pool(DSN_API, 5), cree_pool(DSN_INTERNAL, 2)
    await api.open(wait=False)
    await interne.open(wait=False)
    try:
        yield api, interne
    finally:
        await api.close()
        await interne.close()


@pytest.fixture
def base(pools: tuple[Pool, Pool]) -> Base:
    return Base(*pools)
