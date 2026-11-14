"""0.4bis S10 : lister, renommer et supprimer ses clés d'accès (migration 0155), de bout en bout.

`GET`, `PATCH` et `DELETE /api/v1/me/passkeys`, puis `GET /api/v1/me/sessions` (`opened_with`), sur la
base locale, données inventées. Les clés se posent en direct (`Fabrique.cle`) : l'enregistrement par
l'authentificateur logiciel est éprouvé à part (`test_enregistrement_de_cle.py`). Les fonctions se jouent
aussi comme le fait l'API : en `popote_api`, sous le rôle `authenticated`, avec l'horloge des variantes de
`private` quand le temps compte.
"""

import base64
import logging
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from _client import NOM_DU_COOKIE, application_de_test, client_de, cookie
from _connexions import DSN_API, connecte
from _fabrique import Fabrique, Personne, SessionDeTest
from psycopg import errors
from test_connexion import Banc as BancDeCode
from test_verifie_mot_de_passe import Comptes

from popote_api.infra.db import Base

pytestmark = pytest.mark.integration

ORIGINE = "http://localhost:5173"
ECRITURE = {"Origin": ORIGINE, "X-Popote-Client": "web"}
MERGE_PATCH = "application/merge-patch+json"
CLES = "/api/v1/me/passkeys"
CHAMPS = {"id", "name", "created_at", "last_used_at", "device_type", "backed_up", "transports"}
Ligne = tuple[Any, ...]
T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
DIX_ANS = timedelta(days=3650)
SUPPRIME = "select etat, sessions_fermees, courante_fermee from public.supprime_ma_cle(%s, %s, %s)"
SUPPRIME_A = "select etat, sessions_fermees, courante_fermee from private.supprime_ma_cle(%s, %s, %s, %s, %s)"


@pytest.fixture
def client(base: Base, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    return client_de(application_de_test(base, monkeypatch))


@pytest.fixture
def moi(fabrique: Fabrique) -> Iterator[Personne]:
    personne = fabrique.personne(fabrique.foyer())
    yield personne
    fabrique.admin.execute("delete from public.security_event where person_id = %s", (personne.id,))


@pytest.fixture
def autre(fabrique: Fabrique) -> Iterator[Personne]:
    personne = fabrique.personne(fabrique.foyer())
    yield personne
    fabrique.admin.execute("delete from public.security_event where person_id = %s", (personne.id,))


def en_tete(cle: str | None = None, **plus: str) -> dict[str, str]:
    return ECRITURE | {"Idempotency-Key": f'"{cle or uuid4()}"'} | plus


async def liste(client: httpx.AsyncClient, session: SessionDeTest) -> httpx.Response:
    return await client.get(CLES, headers=cookie(session))


async def renomme(
    client: httpx.AsyncClient, session: SessionDeTest, cle: UUID | str, corps: Any, **plus: str
) -> httpx.Response:
    return await client.patch(
        f"{CLES}/{cle}", json=corps, headers=cookie(session) | en_tete(**{"Content-Type": MERGE_PATCH} | plus)
    )


async def supprime(client: httpx.AsyncClient, session: SessionDeTest, cle: UUID | str) -> httpx.Response:
    return await client.delete(f"{CLES}/{cle}", headers=cookie(session) | ECRITURE)


def lignes(fabrique: Fabrique, requete: str, *valeurs: object) -> list[Ligne]:
    return fabrique.admin.execute(requete, valeurs).fetchall()  # type: ignore[arg-type]


def session_vivante(fabrique: Fabrique, session: SessionDeTest) -> bool:
    (ligne,) = lignes(
        fabrique, "select revoked_at is null from public.login_session where id = %s", session.id
    )
    return bool(ligne[0])


def nom_de(fabrique: Fabrique, cle: UUID) -> str | None:
    trouvees = lignes(fabrique, "select name from public.webauthn_credential where id = %s", cle)
    return str(trouvees[0][0]) if trouvees else None


def un(curseur: psycopg.Cursor[Ligne]) -> Ligne:
    ligne = curseur.fetchone()
    assert ligne is not None
    return ligne


def formes_de(octets: bytes) -> list[str]:
    """Les écritures sous lesquelles des octets secrets pourraient sortir : hexadécimal, base64, base64url."""
    return [
        octets.hex(),
        base64.b64encode(octets).decode(),
        base64.urlsafe_b64encode(octets).decode().rstrip("="),
    ]


@contextmanager
def en_tant_que(personne: UUID) -> Iterator[psycopg.Cursor[Ligne]]:
    """Une transaction `popote_api` qui agit comme la personne (rôle `authenticated`), validée en sortie."""
    with connecte(DSN_API) as cx:
        curseur = cx.cursor()
        curseur.execute("set local role authenticated")
        curseur.execute(
            "select set_config('request.jwt.claims', %s, true)",
            (f'{{"sub": "{personne}", "role": "authenticated"}}',),
        )
        yield curseur
        cx.commit()


# ── La liste ────────────────────────────────────────────────────────────────


class TestListe:
    async def test_chaque_cle_montre_ses_champs_et_jamais_la_cle_publique_ni_les_identifiants(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        session = fabrique.session(moi.id)
        cle = fabrique.cle(moi.id, nom="Mon téléphone", multi_appareil=True)
        identifiant_brut, cle_publique, aaguid = lignes(
            fabrique,
            "select credential_id, public_key, aaguid::text from public.webauthn_credential where id = %s",
            cle,
        )[0]
        secrets_de_la_cle = [
            *formes_de(bytes(identifiant_brut)),
            *formes_de(bytes(cle_publique)),
            aaguid,
            aaguid.replace("-", ""),
        ]
        reponse = await liste(client, session)
        assert reponse.status_code == 200
        assert reponse.headers["cache-control"] == "no-store"
        assert set(reponse.json()) == {"items", "next_cursor"}
        assert reponse.json()["next_cursor"] is None
        (item,) = reponse.json()["items"]
        assert set(item) == CHAMPS
        assert (item["id"], item["name"], item["device_type"], item["backed_up"]) == (
            str(cle),
            "Mon téléphone",
            "multi_device",
            True,
        )
        assert item["transports"] == ["internal"]
        assert item["last_used_at"] is None
        for secret in secrets_de_la_cle:
            assert secret not in reponse.text

    async def test_une_cle_d_un_seul_appareil_et_la_derniere_utilisation(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        fabrique.admin.execute(
            "update public.webauthn_credential set last_used_at = now() where id = %s", (cle,)
        )
        (item,) = (await liste(client, fabrique.session(moi.id))).json()["items"]
        assert (item["device_type"], item["backed_up"]) == ("single_device", False)
        assert item["last_used_at"] is not None

    async def test_la_liste_ne_montre_que_les_cles_de_la_personne_de_la_plus_ancienne_a_la_plus_recente(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        premiere, seconde = fabrique.cle(moi.id, nom="A"), fabrique.cle(moi.id, nom="B")
        chez_l_autre = fabrique.cle(autre.id)
        fabrique.admin.execute(
            "update public.webauthn_credential set created_at = now() - interval '1 day' where id = %s",
            (seconde,),
        )
        items = (await liste(client, fabrique.session(moi.id))).json()["items"]
        assert [i["id"] for i in items] == [str(seconde), str(premiere)]
        assert str(chez_l_autre) not in (await liste(client, fabrique.session(moi.id))).text

    async def test_la_liste_s_arrete_a_dix_cles(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        for _ in range(11):
            fabrique.cle(moi.id)
        assert len((await liste(client, fabrique.session(moi.id))).json()["items"]) == 10

    async def test_sans_cle_la_liste_est_vide(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        assert (await liste(client, fabrique.session(moi.id))).json() == {"items": [], "next_cursor": None}


# ── Renommer ────────────────────────────────────────────────────────────────


class TestRenommer:
    async def test_le_nom_change_en_merge_patch_et_la_liste_le_montre(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        session, cle = fabrique.session(moi.id), fabrique.cle(moi.id, nom="Avant")
        reponse = await renomme(client, session, cle, {"name": "  Clé du salon  "})
        assert reponse.status_code == 200, reponse.text
        assert set(reponse.json()) == CHAMPS
        assert reponse.json()["name"] == "Clé du salon"
        assert nom_de(fabrique, cle) == "Clé du salon"
        assert (await liste(client, session)).json()["items"][0]["name"] == "Clé du salon"

    async def test_le_merge_patch_est_aussi_accepte_en_json_simple(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        reponse = await client.patch(
            f"{CLES}/{cle}", json={"name": "Autre"}, headers=cookie(fabrique.session(moi.id)) | en_tete()
        )
        assert reponse.status_code == 200
        assert nom_de(fabrique, cle) == "Autre"

    async def test_un_corps_vide_ne_change_rien(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id, nom="Intacte")
        reponse = await renomme(client, fabrique.session(moi.id), cle, {})
        assert reponse.status_code == 200
        assert reponse.json()["name"] == "Intacte"

    async def test_la_cle_d_une_autre_personne_est_introuvable_et_reste_intacte(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        cle = fabrique.cle(moi.id, nom="À moi")
        reponse = await renomme(client, fabrique.session(autre.id), cle, {"name": "Volée"})
        assert (reponse.status_code, reponse.json()["code"]) == (404, "cle_introuvable")
        assert nom_de(fabrique, cle) == "À moi"

    async def test_une_cle_inconnue_est_introuvable_et_un_identifiant_mal_forme_est_refuse(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        session = fabrique.session(moi.id)
        assert (await renomme(client, session, uuid4(), {"name": "x"})).status_code == 404
        assert (await renomme(client, session, "pas-un-uuid", {"name": "x"})).status_code == 422

    @pytest.mark.parametrize(
        "corps",
        [
            {"name": ""},
            {"name": "   "},
            {"name": "x" * 41},
            {"name": "ligne\nde trop"},
            {"name": "invisible​ici"},
            {"name": None},
            {"name": 12},
            {"name": "ok", "id": "pas-modifiable"},
            {"autre": "champ"},
        ],
    )
    async def test_un_corps_invalide_est_refuse_sans_rien_changer(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, corps: dict[str, Any]
    ) -> None:
        cle = fabrique.cle(moi.id, nom="Intacte")
        reponse = await renomme(client, fabrique.session(moi.id), cle, corps)
        assert reponse.status_code == 422, reponse.text
        assert nom_de(fabrique, cle) == "Intacte"

    async def test_le_nom_est_normalise_en_nfc_avant_d_etre_compte(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle, session = fabrique.cle(moi.id), fabrique.session(moi.id)
        decompose = "e\u0301" * 40  # 80 points de code, 40 caractères une fois recomposés
        reponse = await renomme(client, session, cle, {"name": decompose})
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["name"] == "é" * 40
        assert (await renomme(client, session, cle, {"name": "e\u0301" * 41})).status_code == 422

    async def test_le_rejeu_d_un_patch_rend_la_meme_reponse_sans_refaire_l_ecriture(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle, session = fabrique.cle(moi.id), fabrique.session(moi.id)
        clef = f'"{uuid4()}"'
        premier = await client.patch(
            f"{CLES}/{cle}",
            json={"name": "Une fois"},
            headers=cookie(session) | ECRITURE | {"Idempotency-Key": clef},
        )
        fabrique.admin.execute(
            "update public.webauthn_credential set name = 'Changée ailleurs' where id = %s", (cle,)
        )
        rejeu = await client.patch(
            f"{CLES}/{cle}",
            json={"name": "Une fois"},
            headers=cookie(session) | ECRITURE | {"Idempotency-Key": clef},
        )
        assert (premier.status_code, rejeu.status_code) == (200, 200)
        assert rejeu.json() == premier.json()
        assert nom_de(fabrique, cle) == "Changée ailleurs"  # le rejeu n'a pas réécrit le nom

    async def test_quarante_caracteres_passent(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        assert (await renomme(client, fabrique.session(moi.id), cle, {"name": "é" * 40})).status_code == 200

    async def test_sans_cle_d_idempotence_le_patch_est_refuse(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id, nom="Intacte")
        reponse = await client.patch(
            f"{CLES}/{cle}",
            json={"name": "Autre"},
            headers=cookie(fabrique.session(moi.id)) | ECRITURE | {"Content-Type": MERGE_PATCH},
        )
        assert reponse.status_code == 400
        assert nom_de(fabrique, cle) == "Intacte"


# ── Supprimer ───────────────────────────────────────────────────────────────


class TestSupprimer:
    async def test_la_cle_part_ses_sessions_se_ferment_les_autres_restent_et_le_journal_le_dit(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle, autre_cle = fabrique.cle(moi.id), fabrique.cle(moi.id)
        courante = fabrique.session(moi.id, ouverte_par="code")
        par_la_cle = [fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle) for _ in range(2)]
        par_l_autre_cle = fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=autre_cle)
        par_code = fabrique.session(moi.id, ouverte_par="code")
        reponse = await supprime(client, courante, cle)
        assert reponse.status_code == 204
        assert "set-cookie" not in reponse.headers
        assert nom_de(fabrique, cle) is None
        assert nom_de(fabrique, autre_cle) is not None
        assert [session_vivante(fabrique, s) for s in par_la_cle] == [False, False]
        assert all(session_vivante(fabrique, s) for s in (courante, par_l_autre_cle, par_code))
        evenements = lignes(
            fabrique,
            "select kind, session_id from public.security_event where person_id = %s order by id",
            moi.id,
        )
        assert sorted((k, str(s)) for k, s in evenements if k == "session_fermee") == sorted(
            ("session_fermee", str(s.id)) for s in par_la_cle
        )
        assert [(k, s) for k, s in evenements if k == "cle_supprimee"] == [("cle_supprimee", courante.id)]

    async def test_la_session_courante_ouverte_par_la_cle_est_fermee_et_le_cookie_vide(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        courante = fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle)
        reponse = await supprime(client, courante, cle)
        assert reponse.status_code == 204
        assert f"{NOM_DU_COOKIE}=" in reponse.headers["set-cookie"]
        assert "max-age=0" in reponse.headers["set-cookie"].lower()
        assert not session_vivante(fabrique, courante)
        assert (await client.get("/api/v1/me", headers=cookie(courante))).status_code == 401

    async def test_la_cle_d_une_autre_personne_est_introuvable_et_rien_ne_bouge(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        ouverte = fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle)
        reponse = await supprime(client, fabrique.session(autre.id), cle)
        assert (reponse.status_code, reponse.json()["code"]) == (404, "cle_introuvable")
        assert nom_de(fabrique, cle) is not None
        assert session_vivante(fabrique, ouverte)
        evenements = lignes(
            fabrique,
            "select 1 from public.security_event where kind = 'cle_supprimee' and person_id = any(%s)",
            [moi.id, autre.id],
        )
        assert evenements == []

    async def test_supprimer_deux_fois_rend_404_la_seconde(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle, session = fabrique.cle(moi.id), fabrique.session(moi.id)
        assert (await supprime(client, session, cle)).status_code == 204
        assert (await supprime(client, session, cle)).status_code == 404

    async def test_un_identifiant_mal_forme_est_refuse(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        assert (await supprime(client, fabrique.session(moi.id), "pas-un-uuid")).status_code == 422

    async def test_la_preuve_de_moins_de_5_minutes_est_exigee(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        ouverte = fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle)
        trop_vieille = fabrique.session(moi.id, preuve_il_y_a=timedelta(seconds=301))
        reponse = await supprime(client, trop_vieille, cle)
        assert (reponse.status_code, reponse.json()["code"]) == (403, "reauthentification_requise")
        assert nom_de(fabrique, cle) is not None
        assert session_vivante(fabrique, ouverte)
        assert (
            await supprime(client, fabrique.session(moi.id, preuve_il_y_a=timedelta(seconds=290)), cle)
        ).status_code == 204

    async def test_la_derniere_cle_se_supprime_et_le_code_par_mail_ouvre_encore_une_session(
        self, base: Base, fabrique: Fabrique
    ) -> None:
        banc = BancDeCode(base, fabrique, Comptes(fabrique))
        personne, email = banc.personne()
        try:
            cle = fabrique.cle(personne)
            ouverte = fabrique.session(personne, ouverte_par="cle", ouverte_avec_la_cle=cle)
            async with banc.client() as client:
                assert (await supprime(client, ouverte, cle)).status_code == 204
                assert (
                    lignes(
                        fabrique, "select 1 from public.webauthn_credential where person_id = %s", personne
                    )
                    == []
                )
                reponse = await banc.connecte_par_code(email, personne, client=client)
            assert reponse.status_code == 201
            assert lignes(
                fabrique,
                "select opened_with from public.login_session where id = %s",
                UUID(reponse.json()["id"]),
            ) == [("code",)]
        finally:
            banc.nettoie()
            fabrique.admin.execute(
                "delete from public.security_event where person_id = any(%s)", ([personne],)
            )

    async def test_les_journaux_n_ecrivent_ni_identifiant_de_cle_ni_cle_publique(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, caplog: pytest.LogCaptureFixture
    ) -> None:
        cle = fabrique.cle(moi.id)
        secret = lignes(
            fabrique,
            "select encode(credential_id, 'hex'), encode(public_key, 'hex')"
            " from public.webauthn_credential where id = %s",
            cle,
        )[0]
        session = fabrique.session(moi.id)
        with caplog.at_level(logging.DEBUG):
            await liste(client, session)
            await renomme(client, session, cle, {"name": "Autre"})
            await supprime(client, session, cle)
        for valeur in [*secret, str(cle), "Autre"]:
            assert valeur not in caplog.text


# ── Les fonctions, jouées comme l'API et avec l'horloge ─────────────────────


class TestBase:
    """`supprime_ma_cle` sous le verrou, avec l'horloge de `private` et l'empreinte du cookie."""

    @pytest.fixture
    def session_a_longue_vie(self, fabrique: Fabrique, moi: Personne) -> SessionDeTest:
        return fabrique.session(moi.id, echeance_dans=DIX_ANS, absolue_dans=DIX_ANS)

    def supprime_a(
        self, fabrique: Fabrique, personne: UUID, session: UUID, cle: UUID, maintenant: datetime
    ) -> Ligne:
        ligne = fabrique.admin.execute(SUPPRIME_A, (personne, session, cle, None, maintenant)).fetchone()
        assert ligne is not None
        return ligne

    def test_la_preuve_passe_a_300_secondes_et_refuse_a_301(
        self, fabrique: Fabrique, moi: Personne, session_a_longue_vie: SessionDeTest
    ) -> None:
        cle = fabrique.cle(moi.id)
        fabrique.admin.execute(
            "update public.login_session set reauth_at = %s where id = %s", (T0, session_a_longue_vie.id)
        )
        refusee = self.supprime_a(fabrique, moi.id, session_a_longue_vie.id, cle, T0 + timedelta(seconds=301))
        assert refusee == ("preuve_perimee", 0, False)
        assert nom_de(fabrique, cle) is not None
        passee = self.supprime_a(fabrique, moi.id, session_a_longue_vie.id, cle, T0 + timedelta(seconds=300))
        assert passee == ("supprimee", 0, False)

    def test_une_session_fermee_ou_d_une_autre_personne_est_refusee_sans_rien_supprimer(
        self, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        fermee = fabrique.session(moi.id, revoquee=True)
        d_un_autre = fabrique.session(autre.id)
        for session in (fermee.id, d_un_autre.id, uuid4()):
            assert self.supprime_a(fabrique, moi.id, session, cle, T0)[0] == "session_perimee"
        assert nom_de(fabrique, cle) is not None

    def test_l_empreinte_d_un_cookie_inconnu_ou_d_une_autre_personne_ne_supprime_rien(
        self, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        de_moi, d_un_autre = fabrique.session(moi.id), fabrique.session(autre.id)
        with en_tant_que(moi.id) as curseur:
            for jeton in (b"\x00" * 32, d_un_autre.empreinte, de_moi.id.bytes):
                curseur.execute(SUPPRIME, (jeton, cle, None))
                assert curseur.fetchone() == ("session_perimee", 0, False)
        assert nom_de(fabrique, cle) is not None

    def test_le_cookie_valide_supprime_et_rend_le_nombre_de_sessions_fermees(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        courante = fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle)
        fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle)
        with en_tant_que(moi.id) as curseur:
            curseur.execute(SUPPRIME, (courante.empreinte, cle, None))
            assert curseur.fetchone() == ("supprimee", 2, True)

    def test_une_session_deja_fermee_de_la_cle_n_est_ni_recomptee_ni_rejournalisee(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle, revoquee=True)
        courante = fabrique.session(moi.id)
        with en_tant_que(moi.id) as curseur:
            curseur.execute(SUPPRIME, (courante.empreinte, cle, None))
            assert curseur.fetchone() == ("supprimee", 0, False)
        evenements = lignes(
            fabrique,
            "select 1 from public.security_event where kind = 'session_fermee' and person_id = %s",
            moi.id,
        )
        assert evenements == []

    def test_l_identifiant_de_requete_du_journal_a_la_forme_attendue(
        self, fabrique: Fabrique, moi: Personne, session_a_longue_vie: SessionDeTest
    ) -> None:
        cle = fabrique.cle(moi.id)
        with pytest.raises(errors.InvalidParameterValue):
            fabrique.admin.execute(
                SUPPRIME_A, (moi.id, session_a_longue_vie.id, cle, "pas-un-identifiant", T0)
            )

    def test_renommer_la_cle_d_une_autre_personne_rend_faux_et_ne_change_rien_meme_sans_la_route(
        self, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        cle = fabrique.cle(moi.id, nom="À moi")
        with en_tant_que(autre.id) as curseur:
            curseur.execute("select public.renomme_ma_cle(%s, 'Volée')", (cle,))
            assert curseur.fetchone() == (False,)
        assert nom_de(fabrique, cle) == "À moi"
        with en_tant_que(moi.id) as curseur:
            curseur.execute("select public.renomme_ma_cle(%s, 'Renommée')", (cle,))
            assert curseur.fetchone() == (True,)
        assert nom_de(fabrique, cle) == "Renommée"

    def test_une_session_echue_est_refusee(self, fabrique: Fabrique, moi: Personne) -> None:
        cle = fabrique.cle(moi.id)
        vieille, un_instant = timedelta(days=2), timedelta(seconds=-1)  # échue sans précéder sa création
        echue = fabrique.session(
            moi.id, vue_il_y_a=vieille, echeance_dans=un_instant, absolue_dans=un_instant
        )
        refusee = self.supprime_a(fabrique, moi.id, echue.id, cle, datetime.now(tz=T0.tzinfo))
        assert refusee[0] == "session_perimee"
        assert nom_de(fabrique, cle) is not None

    def test_une_personne_bannie_est_refusee_meme_avec_une_session_valable(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle, valable = fabrique.cle(moi.id), fabrique.session(moi.id)
        fabrique.admin.execute(
            "update auth.users set banned_until = now() + interval '1 day' where id = %s", (moi.id,)
        )
        refusee = self.supprime_a(fabrique, moi.id, valable.id, cle, datetime.now(tz=T0.tzinfo))
        assert refusee[0] == "session_perimee"
        assert nom_de(fabrique, cle) is not None

    def test_un_identifiant_de_cle_nul_est_un_parametre_invalide(
        self, fabrique: Fabrique, moi: Personne, session_a_longue_vie: SessionDeTest
    ) -> None:
        with pytest.raises(errors.InvalidParameterValue):
            fabrique.admin.execute(SUPPRIME_A, (moi.id, session_a_longue_vie.id, None, None, T0))

    def test_l_evenement_ne_porte_ni_cle_de_compte_ni_ip_ni_identifiant_de_cle(
        self, fabrique: Fabrique, moi: Personne, session_a_longue_vie: SessionDeTest
    ) -> None:
        cle = fabrique.cle(moi.id)
        requete = uuid4().hex
        fabrique.admin.execute(
            SUPPRIME_A, (moi.id, session_a_longue_vie.id, cle, requete, datetime.now(tz=T0.tzinfo))
        )
        evenements = lignes(
            fabrique,
            "select session_id, invitation_id, account_key, ip_hash, request_id from public.security_event"
            " where kind = 'cle_supprimee' and person_id = %s",
            moi.id,
        )
        assert evenements == [(session_a_longue_vie.id, None, None, None, requete)]

    def test_deux_suppressions_paralleles_de_la_meme_cle_n_en_reussissent_qu_une(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        sessions = [fabrique.session(moi.id) for _ in range(2)]
        barriere = threading.Barrier(2)

        def appel(session: SessionDeTest) -> str:
            barriere.wait()
            with en_tant_que(moi.id) as curseur:
                curseur.execute(SUPPRIME, (session.empreinte, cle, None))
                return str(un(curseur)[0])

        with ThreadPoolExecutor(2) as pool:
            etats = sorted(f.result() for f in [pool.submit(appel, s) for s in sessions])
        assert etats == ["inconnue", "supprimee"]

    def test_la_liste_des_appareils_se_pagine_par_derniere_activite(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        sessions = [fabrique.session(moi.id, vue_il_y_a=timedelta(minutes=m)) for m in (3, 2, 1)]
        with en_tant_que(moi.id) as curseur:
            curseur.execute("select id, last_seen_at from public.mes_appareils(2, null, null)")
            premiere = curseur.fetchall()
            curseur.execute(
                "select id from public.mes_appareils(2, %s, %s)", (premiere[-1][1], premiere[-1][0])
            )
            suite = curseur.fetchall()
            with pytest.raises(errors.InvalidParameterValue):
                curseur.execute("select * from public.mes_appareils(0, null, null)")
        assert [ligne[0] for ligne in premiere] == [sessions[2].id, sessions[1].id]
        assert suite == [(sessions[0].id,)]

    def test_renommer_refuse_un_nom_blanc_ou_a_caractere_de_controle_meme_sans_la_route(
        self, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id, nom="Intacte")
        for nom in ("   ", "deux\nlignes", "x" * 41, ""):
            with pytest.raises(errors.InvalidParameterValue), en_tant_que(moi.id) as curseur:
                curseur.execute("select public.renomme_ma_cle(%s, %s)", (cle, nom))
        assert nom_de(fabrique, cle) == "Intacte"

    def test_les_roles_sans_personne_ne_peuvent_rien_appeler(self, fabrique: Fabrique) -> None:
        appels = [
            "select * from public.mes_cles()",
            "select public.renomme_ma_cle(gen_random_uuid(), 'x')",
            "select * from public.supprime_ma_cle('\\x00'::bytea, gen_random_uuid(), null)",
            "select * from public.mes_appareils(10, null, null)",
        ]
        for appel in appels:
            with pytest.raises(errors.InsufficientPrivilege), fabrique.admin.transaction():
                fabrique.admin.execute("set local role anon")
                fabrique.admin.execute(appel)  # type: ignore[call-overload]
            with pytest.raises(errors.InvalidAuthorizationSpecification), fabrique.admin.transaction():
                fabrique.admin.execute("set local role authenticated")
                fabrique.admin.execute(appel)  # type: ignore[call-overload]

    async def test_popote_api_sans_emprunt_est_refuse(self, base: Base) -> None:
        for appel in (
            "select * from public.mes_cles()",
            "select public.renomme_ma_cle(gen_random_uuid(), 'x')",
            "select * from public.supprime_ma_cle('\\x00'::bytea, gen_random_uuid(), null)",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                async with base.connexion() as curseur:
                    await curseur.execute(appel)  # type: ignore[call-overload]


# ── Comment chaque appareil est né ──────────────────────────────────────────


class TestOuvertePar:
    async def test_la_liste_des_appareils_dit_comment_chaque_session_est_nee(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        for origine in ("code", "cle", "invitation", "autre"):
            fabrique.session(
                moi.id, ouverte_par=origine, ouverte_avec_la_cle=cle if origine == "cle" else None
            )
        reponse = await client.get("/api/v1/me/sessions", headers=cookie(fabrique.session(moi.id)))
        assert reponse.status_code == 200
        assert sorted(i["opened_with"] for i in reponse.json()["items"]) == [
            "autre", "autre", "cle", "code", "invitation",
        ]  # fmt: skip

    async def test_la_liste_ne_montre_que_les_sessions_de_la_personne_et_jamais_la_cle(
        self, client: httpx.AsyncClient, fabrique: Fabrique, moi: Personne, autre: Personne
    ) -> None:
        cle = fabrique.cle(moi.id)
        fabrique.session(moi.id, ouverte_par="cle", ouverte_avec_la_cle=cle)
        chez_l_autre = fabrique.session(autre.id, ouverte_par="code")
        reponse = await client.get("/api/v1/me/sessions", headers=cookie(chez_l_autre))
        assert [i["opened_with"] for i in reponse.json()["items"]] == ["code"]
        assert str(cle) not in reponse.text
