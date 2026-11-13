"""T9 : `/api/v1/me/sessions` de bout en bout (spec § 4 ; B3, B26). Données inventées."""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from _client import NOM_DU_COOKIE, application_de_test, client_de, cookie
from _fabrique import Fabrique, Personne, SessionDeTest
from psycopg import errors

from popote_api.infra.db import Base

pytestmark = pytest.mark.integration

ECRITURE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}
CHAMPS = {"id", "browser", "os", "created_at", "last_seen_at", "current"}


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


def evenements(fabrique: Fabrique, personne: UUID) -> list[tuple[Any, ...]]:
    return fabrique.admin.execute(
        "select kind, session_id from public.security_event where person_id = %s order by id", (personne,)
    ).fetchall()


async def liste(client: httpx.AsyncClient, session: SessionDeTest, **params: object) -> httpx.Response:
    return await client.get("/api/v1/me/sessions", params=params, headers=cookie(session))  # type: ignore[arg-type]


async def supprime(
    client: httpx.AsyncClient, session: SessionDeTest, chemin: str, **params: str
) -> httpx.Response:
    return await client.delete(chemin, params=params, headers=cookie(session) | ECRITURE)


async def repond_401(client: httpx.AsyncClient, session: SessionDeTest) -> bool:
    return (await client.get("/api/v1/me", headers=cookie(session))).status_code == 401


class TestListe:
    async def test_ne_montre_que_les_sessions_de_la_personne_et_une_seule_courante(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        a, b = fabrique.session(moi.id), fabrique.session(moi.id, vue_il_y_a=timedelta(hours=2))
        d_autre = fabrique.session(autre.id)
        corps = (await liste(client, a)).json()
        ids = [i["id"] for i in corps["items"]]
        assert ids == [str(a.id), str(b.id)]  # la plus récemment active d'abord
        assert str(d_autre.id) not in ids
        assert [i["current"] for i in corps["items"]] == [True, False]
        assert corps["next_cursor"] is None

    async def test_les_revoquees_et_les_echues_sont_absentes(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        vivante = fabrique.session(moi.id)
        fabrique.session(moi.id, revoquee=True)
        fabrique.session(moi.id, echeance_dans=timedelta(seconds=-1))
        fabrique.session(
            moi.id,
            vue_il_y_a=timedelta(days=2),
            echeance_dans=timedelta(seconds=-1),
            absolue_dans=timedelta(seconds=-1),
        )
        ids = [i["id"] for i in (await liste(client, vivante)).json()["items"]]
        assert ids == [str(vivante.id)]

    async def test_champs_exacts_et_rien_d_identifiant(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        session = fabrique.session(moi.id)
        fabrique.admin.execute(
            "update public.login_session set browser = 'firefox', os = 'linux' where id = %s", (session.id,)
        )
        reponse = await liste(client, session)
        assert set(reponse.json()) == {"items", "next_cursor"}
        assert set(reponse.json()["items"][0]) == CHAMPS
        assert reponse.json()["items"][0]["browser"] == "firefox"
        assert reponse.json()["items"][0]["os"] == "linux"
        assert reponse.headers["cache-control"] == "no-store"
        assert session.jeton not in reponse.text
        assert session.empreinte.hex() not in reponse.text

    @pytest.mark.parametrize("limit", [1, 100])
    async def test_limit_valide(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, limit: int
    ) -> None:
        session = fabrique.session(moi.id)
        fabrique.session(moi.id, vue_il_y_a=timedelta(hours=1))
        reponse = await liste(client, session, limit=limit)
        assert reponse.status_code == 200
        assert len(reponse.json()["items"]) == min(limit, 2)

    @pytest.mark.parametrize("limit", [0, 101])
    async def test_limit_hors_bornes(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, limit: int
    ) -> None:
        reponse = await liste(client, fabrique.session(moi.id), limit=limit)
        assert reponse.status_code == 422

    async def test_pagination_complete_sans_trou_ni_doublon(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        sessions = [fabrique.session(moi.id, vue_il_y_a=timedelta(minutes=m)) for m in range(5)]
        vues: list[str] = []
        curseur: str | None = None
        for _ in range(5):
            params: dict[str, object] = {"limit": 2} | ({"cursor": curseur} if curseur else {})
            corps = (await liste(client, sessions[0], **params)).json()
            vues += [i["id"] for i in corps["items"]]
            curseur = corps["next_cursor"]
            if curseur is None:
                break
        assert vues == [str(s.id) for s in sessions]

    async def test_curseur_falsifie(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        reponse = await liste(client, fabrique.session(moi.id), cursor="pas-un-curseur")
        assert reponse.status_code == 400
        assert reponse.json()["code"] == "curseur_invalide"

    async def test_un_curseur_ne_sort_pas_du_perimetre_de_la_personne(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        d_autre = fabrique.session(autre.id, vue_il_y_a=timedelta(hours=5))
        mienne = fabrique.session(moi.id)
        fabrique.session(moi.id, vue_il_y_a=timedelta(hours=1))
        page = (await liste(client, mienne, limit=1)).json()
        suite = (await liste(client, mienne, limit=10, cursor=page["next_cursor"])).json()
        assert str(d_autre.id) not in [i["id"] for i in page["items"] + suite["items"]]


class TestFermerUneSession:
    async def test_fermer_une_autre_session_de_soi(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a, b = fabrique.session(moi.id), fabrique.session(moi.id)
        reponse = await supprime(client, a, f"/api/v1/me/sessions/{b.id}")
        assert reponse.status_code == 204
        assert "set-cookie" not in reponse.headers
        assert await repond_401(client, b)
        assert not await repond_401(client, a)
        assert evenements(fabrique, moi.id) == [("session_fermee", b.id)]

    async def test_la_session_d_une_autre_personne_est_introuvable_et_reste_valide(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        d_autre = fabrique.session(autre.id)
        reponse = await supprime(client, fabrique.session(moi.id), f"/api/v1/me/sessions/{d_autre.id}")
        assert reponse.status_code == 404
        assert reponse.json()["code"] == "session_introuvable"
        assert not await repond_401(client, d_autre)
        assert evenements(fabrique, autre.id) == []

    async def test_identifiant_inconnu(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        reponse = await supprime(client, fabrique.session(moi.id), f"/api/v1/me/sessions/{uuid4()}")
        assert reponse.status_code == 404

    @pytest.mark.parametrize("id", ["pas-un-uuid", "CURRENT", "1234"])
    async def test_identifiant_qui_n_est_pas_un_uuid(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, id: str
    ) -> None:
        reponse = await supprime(client, fabrique.session(moi.id), f"/api/v1/me/sessions/{id}")
        assert reponse.status_code == 422

    async def test_session_deja_fermee(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a, morte = fabrique.session(moi.id), fabrique.session(moi.id, revoquee=True)
        assert (await supprime(client, a, f"/api/v1/me/sessions/{morte.id}")).status_code == 204
        assert evenements(fabrique, moi.id) == []  # rien n'a été fermé : pas d'événement

    async def test_fermer_deux_fois_la_meme_est_idempotent(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a, b = fabrique.session(moi.id), fabrique.session(moi.id)
        for _ in range(2):
            assert (await supprime(client, a, f"/api/v1/me/sessions/{b.id}")).status_code == 204
        assert evenements(fabrique, moi.id) == [("session_fermee", b.id)]

    async def test_sa_propre_session_par_son_uuid_est_une_deconnexion(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a = fabrique.session(moi.id)
        reponse = await supprime(client, a, f"/api/v1/me/sessions/{a.id}")
        assert reponse.status_code == 204
        assert "max-age=0" in reponse.headers["set-cookie"].lower()
        assert evenements(fabrique, moi.id) == [("deconnexion", a.id)]


class TestDeconnexion:
    async def test_current_ferme_la_session_vide_le_cookie_et_journalise(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a, autre_session = fabrique.session(moi.id), fabrique.session(moi.id)
        reponse = await supprime(client, a, "/api/v1/me/sessions/current")
        assert reponse.status_code == 204
        assert reponse.content == b""
        pose = reponse.headers["set-cookie"]
        assert pose.startswith(f"{NOM_DU_COOKIE}=")
        for attribut in ("max-age=0", "path=/", "httponly", "samesite=lax"):
            assert attribut in pose.lower()
        assert "domain" not in pose.lower()
        assert await repond_401(client, a)
        assert not await repond_401(client, autre_session)  # les autres appareils restent connectés
        assert evenements(fabrique, moi.id) == [("deconnexion", a.id)]

    async def test_deuxieme_deconnexion(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a = fabrique.session(moi.id)
        assert (await supprime(client, a, "/api/v1/me/sessions/current")).status_code == 204
        seconde = await supprime(client, a, "/api/v1/me/sessions/current")
        assert seconde.status_code == 401
        assert seconde.json()["code"] == "pas_de_session"

    async def test_deux_deconnexions_paralleles(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        a = fabrique.session(moi.id)
        reponses = await asyncio.gather(
            *[supprime(client, a, "/api/v1/me/sessions/current") for _ in range(2)]
        )
        assert sorted(r.status_code for r in reponses) == [204, 401]
        assert evenements(fabrique, moi.id) == [("deconnexion", a.id)]


class TestFermerLesAutres:
    async def test_garde_la_courante_et_ne_touche_que_soi(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        a = fabrique.session(moi.id)
        autres = [fabrique.session(moi.id), fabrique.session(moi.id)]
        deja_morte = fabrique.session(moi.id, revoquee=True)
        d_autre = fabrique.session(autre.id)
        reponse = await supprime(client, a, "/api/v1/me/sessions", scope="others")
        assert reponse.status_code == 204
        assert "set-cookie" not in reponse.headers
        assert not await repond_401(client, a)
        assert all([await repond_401(client, s) for s in autres])
        assert not await repond_401(client, d_autre)
        fermees = {sid for kind, sid in evenements(fabrique, moi.id) if kind == "session_fermee"}
        assert fermees == {s.id for s in autres}  # un événement par session fermée, pas pour la déjà morte
        assert deja_morte.id not in fermees
        assert evenements(fabrique, autre.id) == []

    @pytest.mark.parametrize("params", [{}, {"scope": "all"}, {"scope": ""}, {"scope": "OTHERS"}])
    async def test_scope_absent_ou_autre(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, params: dict[str, str]
    ) -> None:
        a, b = fabrique.session(moi.id), fabrique.session(moi.id)
        reponse = await supprime(client, a, "/api/v1/me/sessions", **params)
        assert reponse.status_code == 422
        assert not await repond_401(client, b)  # rien n'est fermé


async def test_sans_session_chaque_route_repond_401(client: httpx.AsyncClient) -> None:
    for methode, chemin in [
        ("GET", "/api/v1/me/sessions"),
        ("DELETE", f"/api/v1/me/sessions/{uuid4()}"),
        ("DELETE", "/api/v1/me/sessions/current"),
        ("DELETE", "/api/v1/me/sessions?scope=others"),
    ]:
        reponse = await client.request(methode, chemin, headers=ECRITURE)
        assert reponse.status_code == 401, (methode, chemin)
        assert reponse.json()["code"] == "pas_de_session"


APPELS = (
    "select * from public.mes_sessions(10, null, null)",
    "select public.ferme_un_appareil(gen_random_uuid(), null)",
    "select public.ferme_les_autres_appareils(gen_random_uuid())",
)


class TestDroitsDExecution:
    """Le rôle COURANT (B3) : `anon` et `popote_api` (contexte connexion, sans emprunt) n'exécutent rien."""

    @pytest.mark.parametrize("appel", APPELS)
    def test_anon_est_refuse(self, fabrique: Fabrique, appel: str) -> None:
        with pytest.raises(errors.InsufficientPrivilege), fabrique.admin.transaction():
            fabrique.admin.execute("set local role anon")
            fabrique.admin.execute(appel)  # type: ignore[call-overload]

    @pytest.mark.parametrize("appel", APPELS)
    async def test_popote_api_sans_emprunt_est_refuse(self, base: Base, appel: str) -> None:
        with pytest.raises(errors.InsufficientPrivilege):
            async with base.connexion() as curseur:
                await curseur.execute(appel)  # type: ignore[call-overload]

    async def test_sans_personne_dans_le_contexte_rien_ne_part(self, fabrique: Fabrique) -> None:
        with pytest.raises(errors.InvalidAuthorizationSpecification), fabrique.admin.transaction():
            fabrique.admin.execute("set local role authenticated")
            fabrique.admin.execute("select public.ferme_les_autres_appareils(gen_random_uuid())")
