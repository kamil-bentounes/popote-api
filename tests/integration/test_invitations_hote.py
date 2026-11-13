"""T12 : les liens d'invitation de l'hôte, de bout en bout : création (T12a), liste et révocation (T12b).

(spec § 4, § 3.5, § 3.6 ; B3, B8, B14, B19). Données inventées.
"""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from _client import application_de_test, client_de, cookie
from _fabrique import Fabrique, Personne
from psycopg import errors

from popote_api.infra.db import Base

pytestmark = pytest.mark.integration

ECRITURE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}
CHEMIN = "/api/v1/me/invitations"
CHAMPS = {"id", "token", "created_at", "expires_at"}
CHAMPS_LISTE = {"id", "created_at", "expires_at"}
CREE_A = "select * from private.cree_invitation(%s, %s, %s)"


@pytest.fixture
def client(base: Base, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    return client_de(application_de_test(base, monkeypatch))


@pytest.fixture
def moi(fabrique: Fabrique) -> Iterator[Personne]:
    personne = fabrique.personne(fabrique.foyer())
    yield personne
    fabrique.admin.execute("delete from public.security_event where person_id = %s", (personne.id,))


@pytest.fixture
def autre(fabrique: Fabrique) -> Personne:
    return fabrique.personne(fabrique.foyer())


@pytest.fixture
def orpheline(fabrique: Fabrique) -> Iterator[UUID]:
    """Une personne sans foyer (ni profil) : elle a une session, mais aucun foyer à inviter."""
    identifiant = uuid4()
    fabrique.admin.execute(
        "insert into auth.users (instance_id, id, aud, role, email, email_confirmed_at, created_at,"
        " updated_at) values ('00000000-0000-0000-0000-000000000000', %s, 'authenticated',"
        " 'authenticated', %s, now(), now(), now())",
        (identifiant, f"{identifiant.hex[:12]}@test.local"),
    )
    yield identifiant
    fabrique.admin.execute("delete from auth.users where id = %s", (identifiant,))


def empreinte() -> bytes:
    return hashlib.sha256(uuid4().bytes).digest()


def entetes(fabrique: Fabrique, personne: UUID, cle: str | None = '"cle-1"') -> dict[str, str]:
    en_tetes = cookie(fabrique.session(personne)) | ECRITURE
    if cle is not None:
        en_tetes["Idempotency-Key"] = cle
    return en_tetes


async def cree(
    client: httpx.AsyncClient, fabrique: Fabrique, personne: UUID, cle: str | None = '"cle-1"'
) -> Any:
    return await client.post(CHEMIN, headers=entetes(fabrique, personne, cle))


def lignes(fabrique: Fabrique, foyer: UUID) -> list[tuple[Any, ...]]:
    return fabrique.admin.execute(
        "select id, token_hash, created_by, created_at, expires_at from public.invite_link"
        " where household_id = %s order by created_at",
        (foyer,),
    ).fetchall()


def cree_en_base(fabrique: Fabrique, personne: Personne, a: datetime) -> tuple[Any, ...]:
    ligne = fabrique.admin.execute(CREE_A, (personne.id, empreinte(), a)).fetchone()
    assert ligne is not None
    return ligne


class TestCreation:
    async def test_cree_un_lien_et_ne_garde_que_l_empreinte(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        reponse = await cree(client, fabrique, moi.id)
        assert reponse.status_code == 201
        corps = reponse.json()
        assert set(corps) == CHAMPS
        assert len(corps["token"]) == 43
        assert reponse.headers["location"] == f"{CHEMIN}/{corps['id']}"
        assert corps["token"] not in reponse.headers["location"]
        assert reponse.headers["cache-control"] == "no-store"
        [(id_, token_hash, cree_par, cree_le, echeance)] = lignes(fabrique, moi.foyer_id)
        assert str(id_) == corps["id"]
        assert cree_par == moi.id
        assert bytes(token_hash) == hashlib.sha256(corps["token"].encode("ascii")).digest()
        assert abs((echeance - cree_le) - timedelta(days=7)) < timedelta(seconds=5)

    async def test_le_jeton_n_est_dans_aucune_colonne_ni_dans_l_idempotence(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        jeton = (await cree(client, fabrique, moi.id)).json()["token"]
        for table in ("public.invite_link", "public.idempotency_key", "public.security_event"):
            assert jeton not in fabrique.admin.execute(f"select t::text from {table} t").fetchall().__repr__()  # noqa: S608
        corps = fabrique.admin.execute(
            "select body from public.idempotency_key where person_id = %s", (moi.id,)
        ).fetchone()
        assert corps is not None
        assert b'"token":null' in bytes(corps[0])

    async def test_deux_liens_ont_deux_jetons(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a = (await cree(client, fabrique, moi.id, '"a"')).json()
        b = (await cree(client, fabrique, moi.id, '"b"')).json()
        assert a["token"] != b["token"]
        assert len(lignes(fabrique, moi.foyer_id)) == 2

    async def test_l_evenement_invitation_creee_est_ecrit(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        corps = (await cree(client, fabrique, moi.id)).json()
        assert fabrique.admin.execute(
            "select kind, invitation_id, account_key, ip_hash from public.security_event"
            " where person_id = %s",
            (moi.id,),
        ).fetchall() == [("invitation_creee", UUID(corps["id"]), None, None)]

    async def test_le_check_refuse_huit_jours(self, fabrique: Fabrique, moi: Personne) -> None:
        with pytest.raises(errors.CheckViolation):
            fabrique.admin.execute(
                "insert into public.invite_link (household_id, token_hash, created_at, expires_at)"
                " values (%s, %s, now(), now() + interval '8 days')",
                (moi.foyer_id, empreinte()),
            )

    @pytest.mark.parametrize("longueur", [0, 31, 33])
    async def test_le_check_refuse_une_empreinte_qui_n_a_pas_32_octets(
        self, fabrique: Fabrique, moi: Personne, longueur: int
    ) -> None:
        with pytest.raises(errors.CheckViolation):
            fabrique.admin.execute(
                "insert into public.invite_link (household_id, token_hash) values (%s, %s)",
                (moi.foyer_id, b"x" * longueur),
            )

    async def test_sans_foyer_c_est_403(self, client: httpx.AsyncClient, fabrique: Fabrique) -> None:
        orpheline = uuid4()
        fabrique.admin.execute(
            "insert into auth.users (instance_id, id, aud, role, email, email_confirmed_at, created_at,"
            " updated_at) values ('00000000-0000-0000-0000-000000000000', %s, 'authenticated',"
            " 'authenticated', %s, now(), now(), now())",
            (orpheline, f"{orpheline.hex[:12]}@test.local"),
        )
        try:
            reponse = await cree(client, fabrique, orpheline)
            assert reponse.status_code == 403
            assert reponse.json()["code"] == "aucun_foyer"
            assert (
                fabrique.admin.execute("select count(*) from public.idempotency_key").fetchone() is not None
            )
        finally:
            fabrique.admin.execute("delete from auth.users where id = %s", (orpheline,))


class TestIdempotence:
    async def test_sans_cle_c_est_400(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        reponse = await cree(client, fabrique, moi.id, None)
        assert reponse.status_code == 400
        assert reponse.json()["code"] == "cle_idempotence_manquante"
        assert lignes(fabrique, moi.foyer_id) == []

    async def test_un_rejeu_rend_la_meme_ligne_sans_jeton(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        premiere = await cree(client, fabrique, moi.id)
        rejeu = await cree(client, fabrique, moi.id)
        assert rejeu.status_code == premiere.status_code == 201
        assert rejeu.json() == premiere.json() | {"token": None}
        assert rejeu.headers["location"] == premiere.headers["location"]
        assert len(lignes(fabrique, moi.foyer_id)) == 1

    async def test_meme_cle_autre_corps_est_422(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        await cree(client, fabrique, moi.id)
        autre_corps = await client.post(CHEMIN, headers=entetes(fabrique, moi.id), json={"x": 1})
        assert autre_corps.status_code == 422
        assert autre_corps.json()["code"] == "cle_idempotence_reutilisee"

    async def test_deux_envois_simultanes_de_la_meme_cle_font_201_et_409(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        # Un autre envoi de la même clé « en cours » : son verrou est tenu par une autre connexion.
        verrou = f'{moi.id}"cle-1"'.replace('"', "")
        fabrique.admin.execute("select pg_advisory_lock(hashtext('idempotence'), hashtext(%s))", (verrou,))
        try:
            refus = await cree(client, fabrique, moi.id)
            assert refus.status_code == 409
            assert refus.json()["code"] == "requete_en_cours"
            assert lignes(fabrique, moi.foyer_id) == []
        finally:
            fabrique.admin.execute(
                "select pg_advisory_unlock(hashtext('idempotence'), hashtext(%s))", (verrou,)
            )
        assert (await cree(client, fabrique, moi.id)).status_code == 201

    async def test_la_meme_cle_chez_une_autre_personne_est_independante(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        a = await cree(client, fabrique, moi.id)
        b = await cree(client, fabrique, autre.id)
        assert (a.status_code, b.status_code) == (201, 201)
        assert a.json()["id"] != b.json()["id"]
        assert b.json()["token"] is not None


class TestQuota:
    async def test_dix_passent_le_onzieme_est_429_revoquees_comprises(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        for i in range(10):
            assert (await cree(client, fabrique, moi.id, f'"k{i}"')).status_code == 201
        # Révoquer ne rend pas le créneau.
        fabrique.admin.execute(
            "update public.invite_link set revoked_at = now() where household_id = %s", (moi.foyer_id,)
        )
        refus = await cree(client, fabrique, moi.id, '"k10"')
        assert refus.status_code == 429
        assert refus.json()["code"] == "quota_invitations"
        assert 1 <= int(refus.headers["retry-after"]) <= 86_400
        assert len(lignes(fabrique, moi.foyer_id)) == 10
        # Le refus n'est pas gardé : la même clé, une fois la place revenue, crée le lien.
        assert fabrique.admin.execute(
            "select count(*) from public.idempotency_key where person_id = %s and key = 'k10'", (moi.id,)
        ).fetchone() == (0,)

    async def test_le_quota_est_celui_du_foyer_pas_de_la_personne(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        deuxieme = fabrique.personne(moi.foyer_id)
        for i in range(10):
            personne = moi if i % 2 else deuxieme
            assert (await cree(client, fabrique, personne.id, f'"k{i}"')).status_code == 201
        assert (await cree(client, fabrique, moi.id, '"k10"')).status_code == 429
        assert (await cree(client, fabrique, deuxieme.id, '"k10"')).status_code == 429

    async def test_le_quota_d_un_autre_foyer_est_independant(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        for i in range(10):
            await cree(client, fabrique, moi.id, f'"k{i}"')
        assert (await cree(client, fabrique, autre.id)).status_code == 201

    async def test_quinze_creations_paralleles_en_laissent_passer_dix(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        en_tetes = [entetes(fabrique, moi.id, f'"p{i}"') for i in range(15)]
        reponses = await asyncio.gather(*(client.post(CHEMIN, headers=h) for h in en_tetes))
        assert sorted(r.status_code for r in reponses) == [201] * 10 + [429] * 5
        assert len(lignes(fabrique, moi.foyer_id)) == 10

    def test_le_quota_se_libere_a_24_heures(self, fabrique: Fabrique, moi: Personne) -> None:
        debut = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        for i in range(10):
            assert cree_en_base(fabrique, moi, debut + timedelta(minutes=i))[0] == "creee"
        refus = fabrique.admin.execute(CREE_A, (moi.id, empreinte(), debut + timedelta(hours=23))).fetchone()
        assert refus is not None
        assert refus[0] == "quota"
        assert refus[4] == 3600  # le premier (12:00) sort à 12:00 le lendemain : dans 1 h
        # Pile à 24 h, la première ligne ne compte plus (fenêtre ouverte) : une place se libère.
        libre = fabrique.admin.execute(CREE_A, (moi.id, empreinte(), debut + timedelta(hours=24))).fetchone()
        assert libre is not None
        assert libre[0] == "creee"
        encore = fabrique.admin.execute(
            CREE_A, (moi.id, empreinte(), debut + timedelta(hours=24, seconds=1))
        ).fetchone()
        assert encore is not None
        assert encore[0] == "quota"

    def test_l_attente_est_celle_de_la_dixieme_plus_recente(self, fabrique: Fabrique, moi: Personne) -> None:
        debut = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        for i in range(10):
            cree_en_base(fabrique, moi, debut + timedelta(minutes=i))
        refus = fabrique.admin.execute(CREE_A, (moi.id, empreinte(), debut + timedelta(hours=1))).fetchone()
        assert refus is not None
        # Un créneau revient quand la plus ancienne (12:00) sort : à 12:00 le lendemain, soit 23 h plus tard.
        assert refus[4] == 23 * 3600


async def liste(client: httpx.AsyncClient, fabrique: Fabrique, personne: UUID, **params: object) -> Any:
    return await client.get(CHEMIN, params=params, headers=cookie(fabrique.session(personne)))  # type: ignore[arg-type]


async def revoque(client: httpx.AsyncClient, fabrique: Fabrique, personne: UUID, id_: object) -> Any:
    return await client.delete(f"{CHEMIN}/{id_}", headers=cookie(fabrique.session(personne)) | ECRITURE)


def evenements_de_revocation(fabrique: Fabrique, personne: UUID) -> list[tuple[Any, ...]]:
    return fabrique.admin.execute(
        "select invitation_id, account_key, ip_hash from public.security_event"
        " where person_id = %s and kind = 'invitation_revoquee'",
        (personne,),
    ).fetchall()


def etat_du_lien(fabrique: Fabrique, id_: UUID) -> tuple[Any, ...]:
    ligne = fabrique.admin.execute(
        "select revoked_at is not null, accepted_at is not null from public.invite_link where id = %s", (id_,)
    ).fetchone()
    assert ligne is not None
    return ligne


class TestListe:
    async def test_les_seuls_liens_en_attente_du_foyer_aux_champs_exacts(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        maintenant = datetime.now(UTC)
        en_attente = cree_en_base(fabrique, moi, maintenant)
        cree_en_base(fabrique, autre, maintenant)  # un autre foyer : jamais listé
        cree_en_base(fabrique, moi, maintenant - timedelta(days=8))  # échu depuis un jour
        utilise = cree_en_base(fabrique, moi, maintenant)
        fabrique.admin.execute(
            "update public.invite_link set accepted_at = now(), accepted_by = %s where id = %s",
            (autre.id, utilise[1]),
        )
        revoque_en_base = cree_en_base(fabrique, moi, maintenant)
        fabrique.admin.execute(
            "update public.invite_link set revoked_at = now() where id = %s", (revoque_en_base[1],)
        )
        reponse = await liste(client, fabrique, moi.id)
        assert reponse.status_code == 200
        assert reponse.headers["cache-control"] == "no-store"
        corps = reponse.json()
        assert set(corps) == {"items", "next_cursor"}
        assert corps["next_cursor"] is None
        assert [i["id"] for i in corps["items"]] == [str(en_attente[1])]
        assert set(corps["items"][0]) == CHAMPS_LISTE
        assert str(moi.id) not in reponse.text
        assert str(autre.id) not in reponse.text

    async def test_ni_jeton_ni_empreinte_dans_la_liste(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        creee = (await cree(client, fabrique, moi.id)).json()
        texte = (await liste(client, fabrique, moi.id)).text
        assert creee["token"] not in texte
        empreinte_du_lien = hashlib.sha256(creee["token"].encode("ascii")).digest()
        assert empreinte_du_lien.hex() not in texte
        assert "token" not in texte

    async def test_les_deux_membres_du_foyer_voient_les_memes_liens(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cree_en_base(fabrique, moi, datetime.now(UTC))
        conjoint = fabrique.personne(moi.foyer_id)
        assert len((await liste(client, fabrique, conjoint.id)).json()["items"]) == 1

    async def test_sans_foyer_la_liste_est_vide(
        self, client: httpx.AsyncClient, fabrique: Fabrique, orpheline: UUID
    ) -> None:
        reponse = await liste(client, fabrique, orpheline)
        assert reponse.status_code == 200
        assert reponse.json() == {"items": [], "next_cursor": None}

    async def test_le_curseur_pagine_du_plus_recent_au_plus_ancien(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        maintenant = datetime.now(UTC)
        ids = [cree_en_base(fabrique, moi, maintenant - timedelta(minutes=i))[1] for i in range(5)]
        vus: list[str] = []
        curseur = None
        for _ in range(3):
            params = {"limit": 2} | ({"cursor": curseur} if curseur else {})
            corps = (await liste(client, fabrique, moi.id, **params)).json()
            vus += [i["id"] for i in corps["items"]]
            curseur = corps["next_cursor"]
            if curseur is None:
                break
        assert vus == [str(i) for i in ids]
        assert curseur is None

    async def test_un_curseur_falsifie_est_400(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        reponse = await liste(client, fabrique, moi.id, cursor="n-importe-quoi")
        assert reponse.status_code == 400
        assert reponse.json()["code"] == "curseur_invalide"

    @pytest.mark.parametrize("limit", [0, 101])
    async def test_limit_hors_bornes(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, limit: int
    ) -> None:
        assert (await liste(client, fabrique, moi.id, limit=limit)).status_code == 422

    async def test_sans_session_c_est_401(self, client: httpx.AsyncClient) -> None:
        assert (await client.get(CHEMIN)).status_code == 401


class TestRevocation:
    async def test_le_sien_est_revoque_204_et_sort_de_la_liste(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        lien = cree_en_base(fabrique, moi, datetime.now(UTC))
        reponse = await revoque(client, fabrique, moi.id, lien[1])
        assert reponse.status_code == 204
        assert reponse.headers["cache-control"] == "no-store"
        assert etat_du_lien(fabrique, lien[1]) == (True, False)
        assert (await liste(client, fabrique, moi.id)).json()["items"] == []

    async def test_le_conjoint_peut_le_revoquer(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        lien = cree_en_base(fabrique, moi, datetime.now(UTC))
        conjoint = fabrique.personne(moi.foyer_id)
        assert (await revoque(client, fabrique, conjoint.id, lien[1])).status_code == 204
        assert etat_du_lien(fabrique, lien[1]) == (True, False)

    async def test_celui_d_un_autre_foyer_est_404_et_reste_valide(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        lien = cree_en_base(fabrique, moi, datetime.now(UTC))
        reponse = await revoque(client, fabrique, autre.id, lien[1])
        assert reponse.status_code == 404
        assert reponse.json()["code"] == "invitation_introuvable"
        assert etat_du_lien(fabrique, lien[1]) == (False, False)
        assert len((await liste(client, fabrique, moi.id)).json()["items"]) == 1
        assert evenements_de_revocation(fabrique, autre.id) == []

    async def test_un_lien_inconnu_est_404(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        assert (await revoque(client, fabrique, moi.id, uuid4())).status_code == 404

    async def test_sans_foyer_c_est_404(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, orpheline: UUID
    ) -> None:
        lien = cree_en_base(fabrique, moi, datetime.now(UTC))
        assert (await revoque(client, fabrique, orpheline, lien[1])).status_code == 404
        assert etat_du_lien(fabrique, lien[1]) == (False, False)

    async def test_deja_revoque_est_204_sans_second_evenement(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        lien = cree_en_base(fabrique, moi, datetime.now(UTC))
        assert (await revoque(client, fabrique, moi.id, lien[1])).status_code == 204
        assert (await revoque(client, fabrique, moi.id, lien[1])).status_code == 204
        assert len(evenements_de_revocation(fabrique, moi.id)) == 1

    async def test_un_lien_echu_est_204_sans_effet(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        echu = cree_en_base(fabrique, moi, datetime.now(UTC) - timedelta(days=8))
        assert (await revoque(client, fabrique, moi.id, echu[1])).status_code == 204
        assert etat_du_lien(fabrique, echu[1]) == (False, False)
        assert evenements_de_revocation(fabrique, moi.id) == []

    async def test_un_lien_deja_accepte_est_409_et_reste_accepte(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        lien = cree_en_base(fabrique, moi, datetime.now(UTC))
        fabrique.admin.execute(
            "update public.invite_link set accepted_at = now(), accepted_by = %s where id = %s",
            (autre.id, lien[1]),
        )
        reponse = await revoque(client, fabrique, moi.id, lien[1])
        assert reponse.status_code == 409
        assert reponse.json()["code"] == "invitation_utilisee"
        assert etat_du_lien(fabrique, lien[1]) == (False, True)
        assert evenements_de_revocation(fabrique, moi.id) == []

    async def test_un_identifiant_qui_n_est_pas_un_uuid_est_422(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        assert (await revoque(client, fabrique, moi.id, "pas-un-uuid")).status_code == 422

    async def test_sans_session_c_est_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.delete(f"{CHEMIN}/{uuid4()}", headers=ECRITURE)
        assert reponse.status_code == 401

    async def test_l_evenement_invitation_revoquee_est_ecrit_sans_donnee_en_plus(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        lien = cree_en_base(fabrique, moi, datetime.now(UTC))
        await revoque(client, fabrique, moi.id, lien[1])
        assert evenements_de_revocation(fabrique, moi.id) == [(lien[1], None, None)]

    async def test_revoquer_ne_rend_pas_le_creneau_du_quota(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        for i in range(10):
            assert (await cree(client, fabrique, moi.id, f'"k{i}"')).status_code == 201
        premier = (await liste(client, fabrique, moi.id)).json()["items"][0]["id"]
        assert (await revoque(client, fabrique, moi.id, premier)).status_code == 204
        assert (await cree(client, fabrique, moi.id, '"k10"')).status_code == 429


class TestDroits:
    def test_l_acces_direct_a_la_table_par_authenticated_est_refuse(self, fabrique: Fabrique) -> None:
        with fabrique.admin.transaction(), pytest.raises(errors.InsufficientPrivilege):
            fabrique.admin.execute("set local role authenticated")
            fabrique.admin.execute("select * from public.invite_link")

    @pytest.mark.parametrize("role", ["anon", "service_role"])
    def test_ni_anon_ni_le_service_ne_creent(self, fabrique: Fabrique, role: str) -> None:
        with fabrique.admin.transaction(), pytest.raises(errors.InsufficientPrivilege):
            fabrique.admin.execute(f"set local role {role}")
            fabrique.admin.execute("select * from public.cree_invitation(%s)", (empreinte(),))

    def test_authenticated_sans_personne_est_refuse(self, fabrique: Fabrique) -> None:
        with fabrique.admin.transaction(), pytest.raises(errors.InvalidAuthorizationSpecification):
            fabrique.admin.execute("set local role authenticated")
            fabrique.admin.execute("select * from public.cree_invitation(%s)", (empreinte(),))

    @pytest.mark.parametrize("role", ["anon", "service_role"])
    @pytest.mark.parametrize(
        "appel",
        ["select * from public.mes_invitations()", "select public.revoque_invitation(gen_random_uuid())"],
    )
    def test_ni_anon_ni_le_service_ne_listent_ni_ne_revoquent(
        self, fabrique: Fabrique, role: str, appel: str
    ) -> None:
        with fabrique.admin.transaction(), pytest.raises(errors.InsufficientPrivilege):
            fabrique.admin.execute(f"set local role {role}")
            fabrique.admin.execute(appel)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "appel",
        ["select * from public.mes_invitations()", "select public.revoque_invitation(gen_random_uuid())"],
    )
    async def test_popote_api_sans_emprunt_est_refuse(self, base: Base, appel: str) -> None:
        with pytest.raises(errors.InsufficientPrivilege):
            async with base.connexion() as curseur:
                await curseur.execute(appel)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "appel",
        ["select * from public.mes_invitations()", "select public.revoque_invitation(gen_random_uuid())"],
    )
    def test_authenticated_sans_personne_est_refuse_pour_la_liste_et_la_revocation(
        self, fabrique: Fabrique, appel: str
    ) -> None:
        with fabrique.admin.transaction(), pytest.raises(errors.InvalidAuthorizationSpecification):
            fabrique.admin.execute("set local role authenticated")
            fabrique.admin.execute(appel)  # type: ignore[call-overload]

    def test_authenticated_n_execute_pas_la_variante_a_horloge(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        with fabrique.admin.transaction(), pytest.raises(errors.InsufficientPrivilege):
            fabrique.admin.execute("set local role authenticated")
            fabrique.admin.execute(CREE_A, (moi.id, empreinte(), datetime.now(UTC)))


class TestSuppressionDeCompte:
    def test_un_membre_qui_a_accepte_un_lien_supprime_son_compte(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        invite = fabrique.personne(moi.foyer_id)
        ligne = cree_en_base(fabrique, moi, datetime.now(UTC))
        fabrique.admin.execute(
            "update public.invite_link set accepted_at = now(), accepted_by = %s where id = %s",
            (invite.id, ligne[1]),
        )
        fabrique.admin.execute("delete from auth.users where id = %s", (invite.id,))
        assert fabrique.admin.execute(
            "select accepted_by, accepted_at is not null, created_by from public.invite_link where id = %s",
            (ligne[1],),
        ).fetchone() == (None, True, moi.id)

    def test_l_hote_supprime_son_compte_le_lien_reste(self, fabrique: Fabrique, moi: Personne) -> None:
        autre_membre = fabrique.personne(moi.foyer_id)
        ligne = cree_en_base(fabrique, moi, datetime.now(UTC))
        fabrique.admin.execute("delete from auth.users where id = %s", (moi.id,))
        assert fabrique.admin.execute(
            "select created_by from public.invite_link where id = %s", (ligne[1],)
        ).fetchone() == (None,)
        assert autre_membre.foyer_id == moi.foyer_id

    async def test_les_lignes_d_idempotence_partent_avec_le_compte(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        assert (await cree(client, fabrique, moi.id)).status_code == 201
        fabrique.admin.execute("delete from auth.users where id = %s", (moi.id,))
        assert fabrique.admin.execute(
            "select count(*) from public.idempotency_key where person_id = %s", (moi.id,)
        ).fetchone() == (0,)
        assert len(lignes(fabrique, moi.foyer_id)) == 1


class TestPurge:
    def test_la_purge_efface_fin_de_vie_plus_trente_jours(self, fabrique: Fabrique, moi: Personne) -> None:
        maintenant = datetime(2026, 12, 25, tzinfo=UTC)
        vieux = cree_en_base(fabrique, moi, maintenant - timedelta(days=38))  # échu depuis 31 jours
        recent = cree_en_base(fabrique, moi, maintenant - timedelta(days=36))  # échu depuis 29 jours
        revoque = cree_en_base(fabrique, moi, maintenant - timedelta(days=5))
        fabrique.admin.execute(
            "update public.invite_link set revoked_at = %s where id = %s",
            (maintenant - timedelta(days=31), revoque[1]),
        )
        attente = cree_en_base(fabrique, moi, maintenant - timedelta(days=1))
        # Acceptés : la fin de vie est l'acceptation, avant l'échéance (31 jours : effacé ; 29 jours : gardé).
        accepte_vieux = cree_en_base(fabrique, moi, maintenant - timedelta(days=33))
        accepte_recent = cree_en_base(fabrique, moi, maintenant - timedelta(days=33))
        for ligne, jours in ((accepte_vieux, 31), (accepte_recent, 29)):
            fabrique.admin.execute(
                "update public.invite_link set accepted_at = %s where id = %s",
                (maintenant - timedelta(days=jours), ligne[1]),
            )
        efface = fabrique.admin.execute("select private.purge_invite_link(%s, 1)", (maintenant,)).fetchone()
        assert efface == (3,)
        restants = {r[0] for r in lignes(fabrique, moi.foyer_id)}
        assert restants == {recent[1], attente[1], accepte_recent[1]}
        assert {vieux[1], revoque[1], accepte_vieux[1]}.isdisjoint(restants)
