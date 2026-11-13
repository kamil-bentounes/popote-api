"""T14a : `delete_my_account()` d'avant et `efface_mes_donnees()` + suppression de `auth.users` laissent les
MÊMES lignes dans chaque table de `public` (l'appli en ligne appelle `delete_my_account`). Une graine, deux
transactions annulées : mêmes identifiants, aucune différence due au hasard. Les colonnes d'horodatage sont
écartées (`now()` diffère d'une transaction à l'autre) ; les tables du journal et des sessions, que seule la
nouvelle fonction écrit ou vide, sont comparées à part (test_suppression_compte).
"""

from pathlib import Path

import psycopg
import pytest
from _fabrique import Fabrique
from _suppression import FoyerSeme, en_tant_que, seme_foyer

pytestmark = pytest.mark.integration

RACINE = Path(__file__).resolve().parents[2]
EXCLUES = {"security_event", "login_session"}
Instantane = dict[str, tuple[int, str]]


def instantane(admin: psycopg.Connection[tuple[object, ...]]) -> Instantane:
    """Par table de `public` : le nombre de lignes et une somme de contrôle (sans les horodatages)."""
    colonnes = admin.execute(
        "select c.table_name, string_agg(format('%I', c.column_name), ', ' order by c.ordinal_position)"
        " from information_schema.columns c join information_schema.tables t"
        "   on t.table_schema = c.table_schema and t.table_name = c.table_name"
        "  and t.table_type = 'BASE TABLE'"
        " where c.table_schema = 'public' and c.data_type not like 'timestamp%%'"
        " group by c.table_name order by c.table_name"
    ).fetchall()
    resultat: Instantane = {}
    for table, cols in colonnes:
        if table in EXCLUES:
            continue
        ligne = admin.execute(
            f"select count(*), coalesce(md5(string_agg(h, '' order by h)), '') from"  # noqa: S608
            f" (select md5(row({cols})::text) as h from public.{table}) q"
        ).fetchone()
        assert ligne is not None
        resultat[str(table)] = (int(str(ligne[0])), str(ligne[1]))
    return resultat


def joue(
    admin: psycopg.Connection[tuple[object, ...]], graine: FoyerSeme, qui: str, ancienne: bool
) -> Instantane:
    personne = graine.a if qui == "a" else graine.b
    assert personne is not None
    with pytest.raises(_Annule):
        with admin.transaction():
            en_tant_que(admin, personne.id)
            if ancienne:
                admin.execute("reset role")
                admin.execute(corps_de_0112())
                en_tant_que(admin, personne.id)
                admin.execute("select public.delete_my_account_0112()")
            else:
                admin.execute("select public.efface_mes_donnees()")
                admin.execute("reset role")
                admin.execute("delete from auth.users where id = %s", (personne.id,))
            admin.execute("reset role")
            # Dans la transaction : la lecture voit les deux états, puis l'annulation les rend.
            _instantane_pris.append(instantane(admin))
            raise _Annule
    return _instantane_pris.pop()


def corps_de_0112() -> str:
    """Le corps d'origine de `delete_my_account` (migration 0112), renommé : c'est lui qu'on rejoue."""
    texte = (RACINE / "supabase/migrations/0112_budget_depart.sql").read_text(encoding="utf-8")
    debut = texte.index("create or replace function public.delete_my_account()")
    fin = texte.index("end $$;", debut) + len("end $$;")
    return texte[debut:fin].replace("public.delete_my_account()", "public.delete_my_account_0112()", 1)


class _Annule(Exception):
    pass


_instantane_pris: list[Instantane] = []


@pytest.mark.parametrize(
    ("a_deux", "qui"),
    [(False, "a"), (True, "a"), (True, "b")],
    ids=["seul", "a_deux_part_le_premier", "a_deux_part_le_second"],
)
def test_les_deux_chemins_laissent_les_memes_lignes(fabrique: Fabrique, a_deux: bool, qui: str) -> None:
    graine = seme_foyer(fabrique, a_deux=a_deux)
    admin = fabrique.admin
    avant = instantane(admin)
    ancienne = joue(admin, graine, qui, ancienne=True)
    nouvelle = joue(admin, graine, qui, ancienne=False)
    assert ancienne == nouvelle
    # La comparaison n'est pas vide : la suppression a bien changé quelque chose.
    assert ancienne != avant
    assert avant["charge"][0] > 0
    assert avant["facture"][0] > 0
    assert avant["cloture"][0] > 0
    assert instantane(admin) == avant, "les transactions annulées ne laissent rien"
