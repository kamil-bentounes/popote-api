"""La clause « après ce curseur » exécutée par Postgres, sur des lignes passées en paramètre.

Lecture seule : les lignes viennent de `unnest(...)`, aucune table n'est créée ni écrite.
"""

import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest
from psycopg import Connection, sql

from popote_api.pagination import (
    Page,
    Position,
    Tri,
    clause_apres,
    construit_page,
    encode_curseur,
    lire_curseur,
    ordre,
)

LOCALE = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
DEBUT = datetime(2026, 11, 1, tzinfo=UTC)

pytestmark = pytest.mark.integration


@pytest.fixture
def connexion() -> Iterator[Connection]:
    with psycopg.connect(LOCALE, autocommit=True) as c:
        yield c


def jeu() -> list[tuple[str, datetime, UUID]]:
    """Deux foyers, des dates qui se répètent (égalités à départager par l'identifiant)."""
    rng = random.Random(12)
    return [
        (rng.choice(["foyer-a", "foyer-b"]), DEBUT + timedelta(hours=rng.randrange(8)), UUID(int=i + 1))
        for i in range(60)
    ]


def page(
    connexion: Connection, tri: Tri, foyer: str, limit: int, curseur: str | None
) -> Page[tuple[datetime, UUID]]:
    lignes = jeu()
    apres, parametres = clause_apres(tri, lire_curseur(tri, curseur))
    requete = sql.SQL(
        "select cree_le, id from unnest(%s::text[], %s::timestamptz[], %s::uuid[]) as t(foyer, cree_le, id) "
        "where foyer = %s and {apres} order by {ordre} limit %s"
    ).format(apres=apres, ordre=ordre(tri))
    lues = connexion.execute(
        requete,
        (
            [f for f, _, _ in lignes],
            [d for _, d, _ in lignes],
            [i for _, _, i in lignes],
            foyer,
            *parametres,
            limit + 1,
        ),
    ).fetchall()
    return construit_page(lues, limit, tri, lambda ligne: Position(ligne[0], ligne[1]))


def tout_lire(connexion: Connection, tri: Tri, foyer: str, limit: int) -> list[tuple[datetime, UUID]]:
    lues: list[tuple[datetime, UUID]] = []
    curseur = None
    while True:
        courante = page(connexion, tri, foyer, limit, curseur)
        lues += courante.items
        curseur = courante.next_cursor
        if curseur is None:
            return lues


@pytest.mark.parametrize("descendant", [False, True])
@pytest.mark.parametrize("limit", [1, 3, 7, 100])
def test_le_parcours_de_toutes_les_pages_rend_chaque_ligne_une_fois_dans_l_ordre(
    connexion: Connection,
    descendant: bool,
    limit: int,
) -> None:
    tri = Tri(nom="test.cree_le", cle="cree_le", type_cle="instant", descendant=descendant)
    attendu = sorted(((d, i) for f, d, i in jeu() if f == "foyer-a"), reverse=descendant)
    assert tout_lire(connexion, tri, "foyer-a", limit) == attendu


def test_un_curseur_forge_vers_un_autre_foyer_ne_fait_pas_sortir_du_perimetre(connexion: Connection) -> None:
    tri = Tri(nom="test.cree_le", cle="cree_le", type_cle="instant")
    des_autres = [(d, i) for f, d, i in jeu() if f == "foyer-b"]
    # Une position valide, prise sur une ligne d'un autre foyer, et une position hors de toute donnée.
    for cle, identifiant in [
        des_autres[0],
        (DEBUT - timedelta(days=3650), UUID(int=0)),
        (DEBUT, UUID(int=2**128 - 1)),
    ]:
        curseur = encode_curseur(tri, Position(cle, identifiant))
        courante = page(connexion, tri, "foyer-a", 100, curseur)
        propres = {i for f, _, i in jeu() if f == "foyer-a"}
        assert {i for _, i in courante.items} <= propres
