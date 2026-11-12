"""Migration 0135 : la table `idempotency_key`, son verrou et sa purge, prouvés EN BASE (spec § 3.5).

Rien n'est créé hors des tables du produit : les personnes viennent de la fabrique (retirées en fin de test,
leurs lignes d'idempotence avec elles, `on delete cascade`).
"""

import hashlib
from typing import Any
from uuid import UUID

import psycopg
import pytest
from _connexions import DSN_ADMIN
from _fabrique import Fabrique

from popote_api.infra.db import Base, Curseur

pytestmark = pytest.mark.integration

EMPREINTE = hashlib.sha256(b"POST/essai{}").hexdigest()

INSERE = """
insert into public.idempotency_key (person_id, key, method, path, fingerprint, status, headers, body)
values (%(personne)s, %(cle)s, 'POST', '/api/v1/essai', %(empreinte)s, %(statut)s,
        %(en_tetes)s::jsonb, %(corps)s)
"""


async def garde(curseur: Curseur, personne: UUID, cle: str = "k1", **valeurs: Any) -> None:
    """Écrit une ligne d'idempotence sous le contexte de la personne (la RLS joue)."""
    parametres: dict[str, Any] = {
        "personne": personne,
        "cle": cle,
        "empreinte": EMPREINTE,
        "statut": 201,
        "en_tetes": "{}",
        "corps": b"{}",
    } | valeurs
    await curseur.execute(INSERE, parametres)


async def compte(curseur: Curseur, personne: UUID | None = None) -> int:
    await curseur.execute(
        "select count(*) as n from public.idempotency_key where %(p)s::uuid is null or person_id = %(p)s",
        {"p": personne},
    )
    ligne = await curseur.fetchone()
    assert ligne is not None
    return int(ligne["n"])


# ── La forme des lignes ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cle",
    ["", "x" * 256, "é", "a\tb", "a\nb", "tab\x7f"],
    ids=["vide", "256-signes", "non-ascii", "tabulation", "retour-ligne", "del"],
)
async def test_une_cle_hors_de_la_forme_est_refusee(base: Base, fabrique: Fabrique, cle: str) -> None:
    personne = fabrique.personne(fabrique.foyer())
    with pytest.raises(psycopg.errors.CheckViolation):
        async with base.personne(personne.id) as curseur:
            await garde(curseur, personne.id, cle)


@pytest.mark.parametrize(
    "cle", ["a", "x" * 255, 'avec des espaces ~!"\\', " "], ids=["1", "255", "ponctuation", "espace"]
)
async def test_une_cle_ascii_imprimable_de_1_a_255_signes_passe(
    base: Base, fabrique: Fabrique, cle: str
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await garde(curseur, personne.id, cle)
        assert await compte(curseur, personne.id) == 1


@pytest.mark.parametrize(
    "valeurs",
    [
        {"statut": 301},
        {"statut": 404},
        {"statut": 500},
        {"en_tetes": '{"set-cookie": "x"}'},
        {"en_tetes": '{"content-type": "a", "x-trace": "b"}'},
        {"en_tetes": "[]"},
        {"empreinte": "pas-un-hash"},
        {"empreinte": "A" * 64},
        {"corps": b"x" * 65537},
    ],
    ids=[
        "301",
        "404",
        "500",
        "set-cookie",
        "en-tete-hors-liste",
        "tableau",
        "empreinte",
        "majuscules",
        "corps-trop-gros",
    ],
)
async def test_une_ligne_hors_de_la_forme_est_refusee(
    base: Base, fabrique: Fabrique, valeurs: dict[str, Any]
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    with pytest.raises(psycopg.errors.CheckViolation):
        async with base.personne(personne.id) as curseur:
            await garde(curseur, personne.id, **valeurs)


async def test_la_liste_fermee_des_en_tetes_passe(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await garde(
            curseur, personne.id, en_tetes='{"content-type": "a", "location": "/b", "etag": "\\"c\\""}'
        )
        assert await compte(curseur, personne.id) == 1


async def test_une_ligne_garde_24_heures_et_le_meme_couple_ne_se_double_pas(
    base: Base, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await garde(curseur, personne.id)
        await curseur.execute("select expires_at - created_at as duree from public.idempotency_key")
        ligne = await curseur.fetchone()
    assert ligne is not None
    assert ligne["duree"].total_seconds() == 24 * 3600
    with pytest.raises(psycopg.errors.UniqueViolation):
        async with base.personne(personne.id) as curseur:
            await garde(curseur, personne.id)
            await garde(curseur, personne.id)


# ── La RLS : chacun ses clés ────────────────────────────────────────────────


async def test_la_meme_cle_chez_une_autre_personne_est_une_autre_ligne(
    base: Base, fabrique: Fabrique
) -> None:
    foyer = fabrique.foyer()
    a, b = fabrique.personne(foyer), fabrique.personne(foyer)
    async with base.personne(a.id) as curseur:
        await garde(curseur, a.id, "partagee")
    async with base.personne(b.id) as curseur:
        await garde(curseur, b.id, "partagee")
        assert await compte(curseur) == 1  # la sienne seulement, pas celle de A (même foyer)


async def test_une_personne_ne_lit_pas_ne_ecrit_pas_ne_efface_pas_la_ligne_de_l_autre(
    base: Base, fabrique: Fabrique
) -> None:
    foyer = fabrique.foyer()
    a, b = fabrique.personne(foyer), fabrique.personne(foyer)
    async with base.personne(a.id) as curseur:
        await garde(curseur, a.id)
    async with base.personne(b.id) as curseur:
        assert await compte(curseur, a.id) == 0
        await curseur.execute("delete from public.idempotency_key where person_id = %s", (a.id,))
        assert curseur.rowcount == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):  # `with check` de la politique d'insertion
        async with base.personne(b.id) as curseur:
            await garde(curseur, a.id, "forgee")
    async with base.personne(a.id) as curseur:
        assert await compte(curseur, a.id) == 1  # intacte


async def test_authenticated_ne_modifie_pas_une_ligne_et_service_role_n_a_aucun_droit_sur_la_table(
    base: Base, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        await garde(curseur, personne.id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with base.personne(personne.id) as curseur:
            await curseur.execute("update public.idempotency_key set status = 200")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with base.personne(personne.id) as curseur:
            await curseur.execute("truncate public.idempotency_key")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with base.service() as curseur:
            await curseur.execute("select 1 from public.idempotency_key")


def test_anon_et_public_n_ont_aucun_droit_sur_la_table() -> None:
    tous = "select, insert, update, delete, truncate"  # vrai dès qu'UN de ces droits est tenu
    with psycopg.connect(DSN_ADMIN) as admin:
        ligne = admin.execute(
            """
            select has_table_privilege('anon', 'public.idempotency_key', %(tous)s),
                   has_table_privilege('service_role', 'public.idempotency_key', %(tous)s),
                   has_function_privilege('anon', 'public.idempotence_verrouille(text)', 'execute'),
                   has_function_privilege('authenticated', 'public.idempotence_purge()', 'execute'),
                   (select relforcerowsecurity from pg_class where oid = 'public.idempotency_key'::regclass)
            """,
            {"tous": tous},
        ).fetchone()
    assert ligne == (False, False, False, False, True)


# ── Le verrou ───────────────────────────────────────────────────────────────

PREND_LE_VERROU = "select public.idempotence_verrouille(%s) as pris"


async def pris(curseur: Curseur, cle: str) -> bool:
    await curseur.execute(PREND_LE_VERROU, (cle,))
    ligne = await curseur.fetchone()
    assert ligne is not None
    return bool(ligne["pris"])


async def test_le_verrou_d_une_cle_tenue_est_refuse_a_un_second_envoi_sans_attente(
    base: Base, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as premier:
        assert await pris(premier, "cle") is True
        async with base.personne(personne.id) as second:
            assert await pris(second, "cle") is False


async def test_le_verrou_est_libere_a_la_fin_de_la_transaction(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as premier:
        assert await pris(premier, "cle") is True
    async with base.personne(personne.id) as suivant:
        assert await pris(suivant, "cle") is True


async def test_le_verrou_d_une_autre_cle_ou_d_une_autre_personne_est_independant(
    base: Base, fabrique: Fabrique
) -> None:
    foyer = fabrique.foyer()
    a, b = fabrique.personne(foyer), fabrique.personne(foyer)
    async with base.personne(a.id) as chez_a:
        assert await pris(chez_a, "cle") is True
        async with base.personne(a.id) as autre_cle, base.personne(b.id) as chez_b:
            assert await pris(autre_cle, "autre") is True
            assert await pris(chez_b, "cle") is True


async def test_le_verrou_est_celui_a_deux_entiers_de_l_idempotence(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    async with base.personne(personne.id) as curseur:
        assert await pris(curseur, "cle") is True
        await curseur.execute(
            """
            select classid, objid, objsubid from pg_locks
            where locktype = 'advisory' and pid = pg_backend_pid() and granted
            """
        )
        verrous = await curseur.fetchall()
        await curseur.execute(
            "select hashtext('idempotence')::oid::int8 as classe,"
            " hashtext(%s::text || 'cle')::oid::int8 as objet",
            (personne.id,),
        )
        attendu = await curseur.fetchone()
    assert attendu is not None
    assert [(v["classid"], v["objid"], v["objsubid"]) for v in verrous] == [
        (attendu["classe"], attendu["objet"], 2)  # objsubid 2 : la forme à deux entiers
    ]


async def test_le_verrou_exige_une_personne_connectee(base: Base) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with base.service() as curseur:
            await curseur.execute(PREND_LE_VERROU, ("cle",))


# ── La purge ────────────────────────────────────────────────────────────────


async def test_la_purge_efface_les_lignes_echues_et_elles_seules(base: Base, fabrique: Fabrique) -> None:
    foyer = fabrique.foyer()
    a, b = fabrique.personne(foyer), fabrique.personne(foyer)
    echue = {"created_at": "2000-01-01", "expires_at": "2000-01-02"}
    for personne in (a, b):
        async with base.personne(personne.id) as curseur:
            await garde(curseur, personne.id, "vivante")
            await curseur.execute(
                "insert into public.idempotency_key (person_id, key, method, path, fingerprint, status, body,"
                " created_at, expires_at) values (%s, 'echue', 'POST', '/p', %s, 201, '', %s, %s)",
                (personne.id, EMPREINTE, echue["created_at"], echue["expires_at"]),
            )
    async with base.service() as curseur:
        await curseur.execute("select public.idempotence_purge() as n")
        effacees = await curseur.fetchone()
    assert effacees is not None
    assert effacees["n"] >= 2  # d'autres bancs peuvent avoir laissé des lignes échues
    for personne in (a, b):
        async with base.personne(personne.id) as curseur:
            await curseur.execute("select key from public.idempotency_key")
            assert [ligne["key"] for ligne in await curseur.fetchall()] == ["vivante"]


async def test_une_personne_ne_lance_pas_la_purge(base: Base, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with base.personne(personne.id) as curseur:
            await curseur.execute("select public.idempotence_purge()")


def test_la_purge_nocturne_est_planifiee_quand_pg_cron_est_la() -> None:
    with psycopg.connect(DSN_ADMIN) as admin:
        extension = admin.execute("select 1 from pg_extension where extname = 'pg_cron'").fetchone()
        if extension is None:
            pytest.skip("pg_cron absent : la migration passe sans planifier, et le dit en avertissement")
        job = admin.execute(
            "select schedule, command, active from cron.job where jobname = 'idempotence-purge'"
        ).fetchone()
    assert job == ("17 3 * * *", "select public.idempotence_purge()", True)
