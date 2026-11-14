"""0.4bis S8b : l'enregistrement d'une clé d'accès, de bout en bout, avec l'authentificateur logiciel de test.

`POST /api/v1/me/passkey-challenges` puis `POST /api/v1/me/passkeys` (migration 0153), sur la base locale,
données inventées. Le navigateur est joué par `tests/unit/_authentificateur.py`. Les courses passent par
`_course.py` : jamais un `sleep` comme preuve.
"""

import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from _authentificateur import Algorithme, Authentificateur
from _client import application_de_test, client_de, cookie
from _connexions import DSN_API, connecte
from _course import attend_un_verrou
from _fabrique import Fabrique, Personne, SessionDeTest
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from popote_api.infra.db import Base

pytestmark = pytest.mark.integration

ORIGINE = "http://localhost:5173"
ECRITURE = {"Origin": ORIGINE, "X-Popote-Client": "web"}
DEFIS = "/api/v1/me/passkey-challenges"
CLES = "/api/v1/me/passkeys"
Ligne = tuple[Any, ...]


def authentificateur(**reglages: Any) -> Authentificateur:
    return Authentificateur(rp_id="localhost", origine=ORIGINE, **reglages)


class Banc:
    """Une application, une personne connectée, et de quoi demander un défi puis enregistrer une clé."""

    def __init__(
        self, base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch, **reglages: Any
    ) -> None:
        self.fabrique = fabrique
        self.app = application_de_test(base, monkeypatch, **reglages)
        self.client = client_de(self.app)
        self.moi: Personne = fabrique.personne(fabrique.foyer())
        self.session: SessionDeTest = fabrique.session(self.moi.id)

    def entetes(self, session: SessionDeTest | None = None, cle: str | None = None) -> dict[str, str]:
        return cookie(session or self.session) | ECRITURE | {"Idempotency-Key": f'"{cle or uuid4()}"'}

    async def defi(
        self,
        session: SessionDeTest | None = None,
        *,
        entetes: dict[str, str] | None = None,
        corps: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self.client.post(
            DEFIS,
            json={"purpose": "registration"} if corps is None else corps,
            headers=entetes if entetes is not None else cookie(session or self.session) | ECRITURE,
        )

    async def options(self, session: SessionDeTest | None = None) -> dict[str, Any]:
        reponse = await self.defi(session)
        assert reponse.status_code == 200, reponse.text
        options: dict[str, Any] = reponse.json()["options"]
        return options

    async def enregistre(
        self,
        credential: dict[str, Any],
        *,
        session: SessionDeTest | None = None,
        nom: str | None = None,
        cle: str | None = None,
        entetes: dict[str, str] | None = None,
    ) -> httpx.Response:
        corps: dict[str, Any] = {"credential": credential}
        if nom is not None:
            corps["name"] = nom
        return await self.client.post(
            CLES,
            json=corps,
            headers=entetes if entetes is not None else self.entetes(session, cle),
        )

    async def cle(
        self, *, session: SessionDeTest | None = None, nom: str | None = None, **reglages: Any
    ) -> tuple[Authentificateur, httpx.Response]:
        """Un défi, une clé neuve qui y répond, l'envoi : la réponse de `POST /me/passkeys`."""
        options = await self.options(session)
        cle = authentificateur(**{k: v for k, v in reglages.items() if k in {"algorithme", "transports"}})
        credential = cle.cree(
            options, **{k: v for k, v in reglages.items() if k not in {"algorithme", "transports"}}
        )
        return cle, await self.enregistre(credential, session=session, nom=nom)

    def lignes(self, requete: str, *valeurs: object) -> list[Ligne]:
        return self.fabrique.admin.execute(requete, valeurs).fetchall()

    def cles(self, personne: UUID | None = None) -> list[Ligne]:
        return self.lignes(
            "select credential_id, name, aaguid, transports, backup_eligible, backup_state, uv_initialized,"
            " sign_count from public.webauthn_credential where person_id = %s order by created_at, id",
            personne or self.moi.id,
        )

    def defis_vivants(self, personne: UUID | None = None) -> int:
        (ligne,) = self.lignes(
            "select count(*) from public.webauthn_challenge where person_id = %s", personne or self.moi.id
        )
        return int(ligne[0])

    def vieillit_la_preuve(self, de: timedelta, session: SessionDeTest | None = None) -> None:
        self.fabrique.admin.execute(
            "update public.login_session set reauth_at = now() - %s where id = %s",
            (de, (session or self.session).id),
        )

    def autre_personne(self) -> tuple[Personne, SessionDeTest]:
        personne = self.fabrique.personne(self.fabrique.foyer())
        return personne, self.fabrique.session(personne.id)

    def evenements(self, personne: UUID | None = None) -> list[Ligne]:
        return self.lignes(
            "select kind, session_id, request_id from public.security_event"
            " where kind = 'cle_ajoutee' and person_id = %s",
            personne or self.moi.id,
        )


@pytest.fixture
def banc(base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch) -> Iterator[Banc]:
    banc = Banc(base, fabrique, monkeypatch)
    yield banc
    fabrique.admin.execute("delete from public.security_event where kind = 'cle_ajoutee'")


# ── Les options ─────────────────────────────────────────────────────────────


class TestOptions:
    async def test_les_options_portent_le_rp_id_un_defi_de_32_octets_et_exigent_la_verification(
        self, banc: Banc
    ) -> None:
        options = await banc.options()
        assert options["rp"]["id"] == "localhost"
        assert len(_octets(options["challenge"])) == 32
        assert options["authenticatorSelection"]["userVerification"] == "required"
        assert options["authenticatorSelection"]["residentKey"] == "required"
        assert options["attestation"] == "none"
        assert options["excludeCredentials"] == []

    async def test_l_identifiant_d_utilisateur_fait_64_octets_et_reste_stable_pour_la_personne(
        self, banc: Banc
    ) -> None:
        premier, second = await banc.options(), await banc.options()
        assert len(_octets(premier["user"]["id"])) == 64
        assert premier["user"]["id"] == second["user"]["id"]
        assert premier["challenge"] != second["challenge"]
        (ligne,) = banc.lignes(
            "select user_handle from public.webauthn_user where person_id = %s", banc.moi.id
        )
        assert bytes(ligne[0]) == _octets(premier["user"]["id"])

    async def test_l_identifiant_d_utilisateur_n_a_aucun_lien_avec_la_personne_ni_avec_une_autre(
        self, banc: Banc
    ) -> None:
        autre, session = banc.autre_personne()
        a_moi, a_l_autre = await banc.options(), await banc.options(session)
        identifiant = a_moi["user"]["id"]
        assert identifiant != a_l_autre["user"]["id"]
        brut = _octets(identifiant)
        assert banc.moi.id.bytes not in brut
        assert banc.moi.id.hex.encode() not in brut
        assert str(banc.moi.id).encode() not in brut
        assert autre.id.bytes not in _octets(a_l_autre["user"]["id"])

    async def test_les_cles_deja_enregistrees_sont_exclues(self, banc: Banc) -> None:
        cle, reponse = await banc.cle(transports=("internal", "hybrid"))
        assert reponse.status_code == 201
        exclues = (await banc.options())["excludeCredentials"]
        assert [e["id"] for e in exclues] == [bytes_to_base64url(cle.identifiant)]
        assert sorted(exclues[0]["transports"]) == ["hybrid", "internal"]

    async def test_les_cles_d_une_autre_personne_ne_sont_pas_exclues(self, banc: Banc) -> None:
        _, session = banc.autre_personne()
        _, reponse = await banc.cle(session=session)
        assert reponse.status_code == 201
        assert (await banc.options())["excludeCredentials"] == []

    async def test_le_nom_et_l_adresse_viennent_de_la_personne_elle_meme(self, banc: Banc) -> None:
        options = await banc.options()
        (ligne,) = banc.lignes("select email from auth.users where id = %s", banc.moi.id)
        assert options["user"]["name"] == ligne[0]
        assert options["user"]["displayName"].startswith("personne-")

    async def test_un_defi_est_garde_pour_la_personne_et_la_session(self, banc: Banc) -> None:
        options = await banc.options()
        (ligne,) = banc.lignes(
            "select challenge, purpose, person_id, session_id, expires_at - created_at"
            " from public.webauthn_challenge where person_id = %s",
            banc.moi.id,
        )
        assert bytes(ligne[0]) == _octets(options["challenge"])
        assert ligne[1:4] == ("registration", banc.moi.id, banc.session.id)
        assert ligne[4] == timedelta(minutes=10)

    async def test_une_origine_qui_n_admet_pas_les_cles_donne_403_et_ne_garde_aucun_defi(
        self, base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        banc = Banc(base, fabrique, monkeypatch, webauthn_origins="http://localhost:4173")
        reponse = await banc.defi()
        assert (reponse.status_code, reponse.json()["code"]) == (403, "cle_origine_non_admise")
        assert banc.lignes("select 1 from public.webauthn_user where person_id = %s", banc.moi.id) == []

    async def test_sans_preuve_recente_403_et_aucun_defi(self, banc: Banc) -> None:
        banc.vieillit_la_preuve(timedelta(seconds=301))
        reponse = await banc.defi()
        assert (reponse.status_code, reponse.json()["code"]) == (403, "reauthentification_requise")
        assert banc.defis_vivants() == 0

    async def test_la_preuve_de_299_secondes_passe(self, banc: Banc) -> None:
        banc.vieillit_la_preuve(timedelta(seconds=299))
        assert (await banc.defi()).status_code == 200

    async def test_le_but_est_obligatoire_et_connu(self, banc: Banc) -> None:
        for corps in ({}, {"purpose": "reauthentication"}, {"purpose": "registration", "autre": 1}):
            assert (await banc.defi(corps=corps)).status_code == 422

    async def test_onze_cles_donnent_409_des_la_demande_du_defi(self, banc: Banc) -> None:
        for _ in range(10):
            assert (await banc.cle())[1].status_code == 201
        reponse = await banc.defi()
        assert (reponse.status_code, reponse.json()["code"]) == (409, "trop_de_cles")
        assert banc.defis_vivants() == 0


# ── L'enregistrement ────────────────────────────────────────────────────────


class TestEnregistrement:
    async def test_une_clef_valide_s_enregistre_avec_ses_indicateurs_son_aaguid_et_ses_transports(
        self, banc: Banc
    ) -> None:
        cle, reponse = await banc.cle(
            nom="iPhone de Camille", transports=("internal", "hybrid"), be=True, bs=True
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert set(corps) == {"id", "name", "created_at"}
        assert corps["name"] == "iPhone de Camille"
        ((identifiant, nom, aaguid, transports, be, bs, uv, compteur),) = banc.cles()
        assert bytes(identifiant) == cle.identifiant
        assert (nom, aaguid, sorted(transports)) == (
            "iPhone de Camille",
            UUID(bytes=cle.aaguid),
            ["hybrid", "internal"],
        )
        assert (be, bs, uv, compteur) == (True, True, True, 0)
        (id_en_base,) = banc.lignes(
            "select id from public.webauthn_credential where person_id = %s", banc.moi.id
        )
        assert str(id_en_base[0]) == corps["id"]

    @pytest.mark.parametrize("algorithme", list(Algorithme), ids=lambda a: a.name)
    async def test_les_trois_algorithmes_s_enregistrent(self, banc: Banc, algorithme: Algorithme) -> None:
        _, reponse = await banc.cle(algorithme=algorithme)
        assert reponse.status_code == 201

    async def test_la_clef_enregistree_ecrit_un_evenement_avec_la_session_et_la_requete(
        self, banc: Banc
    ) -> None:
        _, reponse = await banc.cle()
        assert reponse.status_code == 201
        ((genre, session, requete),) = banc.evenements()
        assert genre == "cle_ajoutee"
        assert session == banc.session.id
        assert requete == reponse.headers["x-request-id"]

    async def test_sans_nom_la_clef_s_appelle_cle_du_jour_a_paris(self, banc: Banc) -> None:
        # 23 h 30 UTC le 31/12 : il est déjà le 1er janvier à Paris. La preuve est posée à cet instant (futur
        # pour la base : elle ne la juge pas périmée).
        maintenant = datetime(2026, 12, 31, 23, 30, tzinfo=UTC)
        banc.app.state.horloge = lambda: maintenant
        banc.fabrique.admin.execute(
            "update public.login_session set reauth_at = %s where id = %s", (maintenant, banc.session.id)
        )
        reponse = (await banc.cle())[1]
        assert (reponse.status_code, reponse.json()["name"]) == (201, "Clé du 01/01/2027")

    async def test_le_nom_est_nettoye(self, banc: Banc) -> None:
        reponse = (await banc.cle(nom="  Clé de l'e\u0301cole  "))[1]
        assert (reponse.status_code, reponse.json()["name"]) == (201, "Clé de l'école")

    @pytest.mark.parametrize(
        "nom",
        ["", "   ", "x" * 41, "deux\nlignes", "invisible\u200bici", "tab\there", "sep\u2028ici", "\x00"],
        ids=[
            "vide",
            "espaces",
            "trop-long",
            "retour-ligne",
            "largeur-nulle",
            "tabulation",
            "separateur",
            "nul",
        ],
    )
    async def test_un_nom_refuse_donne_422_et_n_ecrit_rien(self, banc: Banc, nom: str) -> None:
        options = await banc.options()
        reponse = await banc.enregistre(authentificateur().cree(options), nom=nom)
        assert reponse.status_code == 422
        assert reponse.json()["errors"][0]["pointer"] == "/name"
        assert banc.cles() == []

    async def test_un_nom_de_40_caracteres_passe(self, banc: Banc) -> None:
        assert (await banc.cle(nom="x" * 40))[1].status_code == 201

    @pytest.mark.parametrize(
        "reglage",
        [
            {"origine": "https://notre-popote.fr"},
            {"rp_id": "notre-popote.fr"},
            {"uv": False},
            {"up": False},
            {"defi": b"\x01" * 32},
            {"type_de_donnees": "webauthn.get"},
            {"cross_origin": True},
            {"top_origin": ORIGINE},
            {"format_d_attestation": "packed", "declaration": {"alg": -7}},
            {"bs": True, "be": False},
        ],
        ids=[
            "mauvaise-origine",
            "mauvais-rp-id",
            "uv-absent",
            "up-absent",
            "mauvais-defi",
            "mauvais-type",
            "cadre-etranger",
            "top-origin",
            "attestation-packed",
            "bs-sans-be",
        ],
    )
    async def test_une_reponse_refusee_donne_422_cle_refusee_et_n_ecrit_rien(
        self, banc: Banc, reglage: dict[str, Any]
    ) -> None:
        _, reponse = await banc.cle(**reglage)
        assert (reponse.status_code, reponse.json()["code"]) == (422, "cle_refusee")
        assert banc.cles() == []
        assert banc.evenements() == []

    async def test_une_reponse_refusee_laisse_le_defi_valable_pour_un_second_essai(self, banc: Banc) -> None:
        options = await banc.options()
        refusee = await banc.enregistre(authentificateur().cree(options, uv=False))
        assert refusee.status_code == 422
        assert banc.defis_vivants() == 1  # rien n'a été consommé : la transaction s'est annulée
        bonne = await banc.enregistre(authentificateur().cree(options))
        assert bonne.status_code == 201

    async def test_un_defi_ne_sert_qu_une_fois(self, banc: Banc) -> None:
        options = await banc.options()
        premiere = await banc.enregistre(authentificateur().cree(options))
        seconde = await banc.enregistre(authentificateur().cree(options))
        assert premiere.status_code == 201
        assert (seconde.status_code, seconde.json()["code"]) == (422, "cle_refusee")
        assert len(banc.cles()) == 1
        assert banc.defis_vivants() == 0

    async def test_un_defi_inconnu_donne_422(self, banc: Banc) -> None:
        options = await banc.options()
        banc.fabrique.admin.execute(
            "delete from public.webauthn_challenge where person_id = %s", (banc.moi.id,)
        )
        assert (await banc.enregistre(authentificateur().cree(options))).status_code == 422

    async def test_un_defi_echu_donne_422(self, banc: Banc) -> None:
        options = await banc.options()
        banc.fabrique.admin.execute(
            "update public.webauthn_challenge set created_at = now() - interval '11 minutes',"
            " expires_at = now() - interval '1 minute' where person_id = %s",
            (banc.moi.id,),
        )
        reponse = await banc.enregistre(authentificateur().cree(options))
        assert (reponse.status_code, reponse.json()["code"]) == (422, "cle_refusee")
        assert banc.cles() == []

    async def test_le_defi_d_une_autre_personne_est_refuse_et_pas_brule(self, banc: Banc) -> None:
        autre, session = banc.autre_personne()
        options = await banc.options()
        # La personne `autre` a elle aussi un identifiant d'utilisateur : seule la liaison du défi la refuse.
        await banc.options(session)
        volee = await banc.enregistre(authentificateur().cree(options), session=session)
        assert (volee.status_code, volee.json()["code"]) == (422, "cle_refusee")
        assert banc.cles(autre.id) == []
        assert banc.defis_vivants() == 1
        assert (await banc.enregistre(authentificateur().cree(options))).status_code == 201

    async def test_le_defi_d_une_autre_session_de_la_meme_personne_est_refuse_et_pas_brule(
        self, banc: Banc
    ) -> None:
        seconde = banc.fabrique.session(banc.moi.id)
        options = await banc.options()
        refusee = await banc.enregistre(authentificateur().cree(options), session=seconde)
        assert (refusee.status_code, refusee.json()["code"]) == (422, "cle_refusee")
        assert banc.defis_vivants() == 1
        assert (await banc.enregistre(authentificateur().cree(options))).status_code == 201

    async def test_un_identifiant_de_cle_deja_pris_donne_409_meme_par_une_autre_personne(
        self, banc: Banc
    ) -> None:
        cle, premiere = await banc.cle()
        assert premiere.status_code == 201
        _, session = banc.autre_personne()
        options = await banc.options(session)
        # La même clé (même identifiant), jouée par la personne `autre` avec son propre défi.
        credential = cle.cree(options)
        reponse = await banc.enregistre(credential, session=session)
        assert (reponse.status_code, reponse.json()["code"]) == (409, "cle_deja_enregistree")
        assert len(banc.cles()) == 1

    async def test_la_meme_clef_deux_fois_pour_la_meme_personne_donne_409(self, banc: Banc) -> None:
        cle, premiere = await banc.cle()
        assert premiere.status_code == 201
        options = await banc.options()
        reponse = await banc.enregistre(cle.cree(options))
        assert (reponse.status_code, reponse.json()["code"]) == (409, "cle_deja_enregistree")
        assert len(banc.cles()) == 1

    async def test_la_onzieme_clef_donne_409_trop_de_cles(self, banc: Banc) -> None:
        options = await banc.options()  # un défi pris AVANT la dixième clé : seule la base ferme la porte
        for _ in range(10):
            assert (await banc.cle())[1].status_code == 201
        reponse = await banc.enregistre(authentificateur().cree(options))
        assert (reponse.status_code, reponse.json()["code"]) == (409, "trop_de_cles")
        assert len(banc.cles()) == 10

    async def test_douze_enregistrements_en_parallele_en_laissent_exactement_dix(self, banc: Banc) -> None:
        defis = [await banc.options() for _ in range(12)]
        reponses = await asyncio.gather(
            *(banc.enregistre(authentificateur().cree(options)) for options in defis)
        )
        statuts = sorted(r.status_code for r in reponses)
        assert statuts == [201] * 10 + [409] * 2
        assert {r.json()["code"] for r in reponses if r.status_code == 409} == {"trop_de_cles"}
        assert len(banc.cles()) == 10

    async def test_deux_premieres_demandes_en_parallele_partagent_un_seul_identifiant_d_utilisateur(
        self, banc: Banc
    ) -> None:
        a, b = await asyncio.gather(banc.options(), banc.options())
        assert a["user"]["id"] == b["user"]["id"]
        assert len(banc.lignes("select 1 from public.webauthn_user where person_id = %s", banc.moi.id)) == 1
        reponses = await asyncio.gather(
            banc.enregistre(authentificateur().cree(a)), banc.enregistre(authentificateur().cree(b))
        )
        assert [r.status_code for r in reponses] == [201, 201]

    async def test_la_preuve_de_299_secondes_passe_a_l_enregistrement(self, banc: Banc) -> None:
        options = await banc.options()
        banc.vieillit_la_preuve(timedelta(seconds=299))
        assert (await banc.enregistre(authentificateur().cree(options))).status_code == 201

    async def test_la_preuve_de_301_secondes_donne_403_a_l_enregistrement_et_rien_n_est_ecrit(
        self, banc: Banc
    ) -> None:
        options = await banc.options()
        banc.vieillit_la_preuve(timedelta(seconds=301))
        reponse = await banc.enregistre(authentificateur().cree(options))
        assert (reponse.status_code, reponse.json()["code"]) == (403, "reauthentification_requise")
        assert banc.cles() == []
        assert banc.defis_vivants() == 1

    async def test_la_garde_de_l_api_refuse_sans_attendre_la_base(self, banc: Banc) -> None:
        """L'horloge de l'API avance : sa garde refuse une preuve que la base jugerait fraîche."""
        options = await banc.options()
        maintenant = datetime.now(UTC)
        banc.app.state.horloge = lambda: maintenant + timedelta(seconds=400)
        reponse = await banc.enregistre(authentificateur().cree(options))
        assert (reponse.status_code, reponse.json()["code"]) == (403, "reauthentification_requise")
        assert banc.cles() == []
        assert (await banc.defi()).status_code == 403  # la même garde, à la demande du défi

    async def test_la_base_refuse_a_son_tour_une_preuve_que_l_api_croyait_bonne(self, banc: Banc) -> None:
        """L'horloge de l'API retarde : la garde Python passe, la base (son horloge à elle) refuse."""
        options = await banc.options()
        banc.vieillit_la_preuve(timedelta(seconds=400))
        maintenant = datetime.now(UTC)
        banc.app.state.horloge = lambda: maintenant - timedelta(seconds=200)
        reponse = await banc.enregistre(authentificateur().cree(options))
        assert (reponse.status_code, reponse.json()["code"]) == (403, "reauthentification_requise")
        assert banc.cles() == []

    async def test_une_session_fermee_donne_401_et_rien_n_est_ecrit(self, banc: Banc) -> None:
        options = await banc.options()
        banc.fabrique.admin.execute(
            "update public.login_session set revoked_at = now() where id = %s", (banc.session.id,)
        )
        reponse = await banc.enregistre(authentificateur().cree(options))
        assert reponse.status_code == 401
        assert banc.cles() == []

    async def test_sans_session_401(self, banc: Banc) -> None:
        for chemin in (DEFIS, CLES):
            reponse = await banc.client.post(
                chemin,
                json={"purpose": "registration", "credential": {}},
                headers=ECRITURE | {"Idempotency-Key": '"k"'},
            )
            assert reponse.status_code == 401

    async def test_sans_idempotency_key_400(self, banc: Banc) -> None:
        options = await banc.options()
        reponse = await banc.enregistre(
            authentificateur().cree(options), entetes=cookie(banc.session) | ECRITURE
        )
        assert (reponse.status_code, reponse.json()["code"]) == (400, "cle_idempotence_manquante")

    async def test_un_rejeu_de_la_meme_cle_rend_la_meme_reponse_sans_refaire_l_effet(
        self, banc: Banc
    ) -> None:
        options = await banc.options()
        credential = authentificateur().cree(options)
        premiere = await banc.enregistre(credential, cle="envoi-1")
        rejeu = await banc.enregistre(credential, cle="envoi-1")
        assert (premiere.status_code, rejeu.status_code) == (201, 201)
        assert rejeu.json() == premiere.json()
        assert len(banc.cles()) == 1
        assert len(banc.evenements()) == 1

    @pytest.mark.parametrize(
        "corps",
        [{}, {"credential": "x"}, {"credential": {}, "autre": 1}, {"credential": {"id": 1}}],
        ids=["vide", "chaine", "champ-inconnu", "credential-mal-forme"],
    )
    async def test_un_corps_mal_forme_donne_422_sans_rien_ecrire(
        self, banc: Banc, corps: dict[str, Any]
    ) -> None:
        await banc.options()
        reponse = await banc.client.post(CLES, json=corps, headers=banc.entetes())
        assert reponse.status_code == 422
        assert banc.cles() == []

    async def test_la_cle_d_une_autre_personne_n_apparait_jamais_dans_mes_cles_exclues(
        self, banc: Banc
    ) -> None:
        autre, session = banc.autre_personne()
        assert (await banc.cle(session=session))[1].status_code == 201
        assert banc.cles(autre.id) != []
        assert banc.cles() == []

    async def test_ni_cle_ni_identifiant_ni_defi_dans_les_journaux(
        self, banc: Banc, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        options = await banc.options()
        cle = authentificateur()
        credential = cle.cree(options)
        refusee = authentificateur().cree(options, uv=False)
        assert (await banc.enregistre(refusee)).status_code == 422
        assert (await banc.enregistre(credential)).status_code == 201
        assert (await banc.enregistre(credential)).status_code == 422  # le défi est servi
        secrets_a_cacher = [
            bytes_to_base64url(cle.identifiant),
            bytes_to_base64url(cle.cle_publique_cose()),
            options["challenge"],
            options["user"]["id"],
            credential["response"]["attestationObject"],
            credential["response"]["clientDataJSON"],
            cle.cle_publique_cose().hex(),
            cle.identifiant.hex(),
        ]
        journaux = "\n".join([r.getMessage() + str(r.args) + (r.exc_text or "") for r in caplog.records])
        for secret in secrets_a_cacher:
            assert secret not in journaux


# ── Les courses (verrou de personne) ────────────────────────────────────────


class TestCourses:
    async def test_une_fermeture_de_toutes_les_sessions_qui_precede_l_enregistrement_le_fait_refuser(
        self, banc: Banc
    ) -> None:
        """A ferme les autres sessions sous son verrou ; B (la route) attend, puis est refusé."""
        gardee = banc.fabrique.session(banc.moi.id)
        options = await banc.options()
        credential = authentificateur().cree(options)
        admin: psycopg.Connection[Ligne] = banc.fabrique.admin
        with connecte(DSN_API) as a:
            a.execute(
                "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (banc.moi.id, gardee.id)
            )
            tache = asyncio.create_task(banc.enregistre(credential))
            try:
                await attend_un_verrou(admin, "consomme_un_defi", a.info.backend_pid)
            except BaseException:
                tache.cancel()
                a.rollback()
                await asyncio.gather(tache, return_exceptions=True)
                raise
            a.commit()
            reponse = await tache
        assert reponse.status_code == 401
        assert banc.cles() == []
        assert banc.evenements() == []

    async def test_l_enregistrement_attend_le_verrou_puis_reussit_quand_rien_n_a_ete_revoque(
        self, banc: Banc
    ) -> None:
        options = await banc.options()
        credential = authentificateur().cree(options)
        admin: psycopg.Connection[Ligne] = banc.fabrique.admin
        with connecte(DSN_API) as a:
            a.execute("select public.verrouille_la_personne(%s)", (banc.moi.id,))
            tache = asyncio.create_task(banc.enregistre(credential))
            try:
                await attend_un_verrou(admin, "consomme_un_defi", a.info.backend_pid)
            except BaseException:
                tache.cancel()
                a.rollback()
                await asyncio.gather(tache, return_exceptions=True)
                raise
            a.commit()
            reponse = await tache
        assert reponse.status_code == 201
        assert len(banc.cles()) == 1


def _octets(texte: str) -> bytes:
    return base64url_to_bytes(texte)
