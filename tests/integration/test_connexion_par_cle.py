"""0.4bis S9b : `POST /api/v1/passkey-challenges` puis `POST /api/v1/sessions` par clé d'accès, de bout
en bout.

Base locale, données inventées. Le navigateur est joué par `tests/unit/_authentificateur.py` ; la clé est
enregistrée par les vraies routes de S8b. Chaque banc prend sa propre IP (la limite est de 20) et retire ses
compteurs, ses défis et ses événements.
"""

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from _authentificateur import Authentificateur
from _client import NOM_DU_COOKIE
from _connexions import DSN_API, connecte
from _course import attend_un_verrou
from _fabrique import Fabrique
from test_enregistrement_de_cle import Banc as BancDEnregistrement
from test_enregistrement_de_cle import authentificateur

from popote_api.infra.db import Base
from popote_api.security.empreintes import Empreintes

pytestmark = pytest.mark.integration

ORIGINE = "http://localhost:5173"
ECRITURE = {"Origin": ORIGINE, "X-Popote-Client": "web"}
DEFIS = "/api/v1/passkey-challenges"
SESSIONS = "/api/v1/sessions"
POIVRE = "p" * 32
MESSAGE = "Clé d'accès refusée. Utilise le code reçu par mail."
Ligne = tuple[Any, ...]


class BancDeConnexion:
    """Une personne qui a une clé enregistrée, et de quoi demander un défi puis se connecter avec elle."""

    def __init__(self, enregistrement: BancDEnregistrement) -> None:
        self.enregistrement = enregistrement
        self.app = enregistrement.app
        self.fabrique = enregistrement.fabrique
        self.moi = enregistrement.moi
        self.empreintes = Empreintes.depuis(self.app.state.settings)
        self.ip = f"203.0.113.{random.randint(1, 254)}"
        self.defis: list[bytes] = []

    def client(self, ip: str | None = None) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app, client=(ip or self.ip, 5000))
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    async def cle(self, **reglages: Any) -> Authentificateur:
        cle, reponse = await self.enregistrement.cle(**reglages)
        assert reponse.status_code == 201, reponse.text
        return cle

    async def options(self, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        reponse = await (client or self.client()).post(DEFIS, headers=ECRITURE)
        assert reponse.status_code == 200, reponse.text
        options: dict[str, Any] = reponse.json()["options"]
        return options

    async def poste(
        self,
        credential: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
        entetes: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await (client or self.client()).post(
            SESSIONS, json={"method": "passkey", "credential": credential}, headers=ECRITURE | (entetes or {})
        )

    async def connecte(self, cle: Authentificateur, **reglages: Any) -> httpx.Response:
        """Un défi neuf, la clé le signe (avec `reglages` de `signe`), l'envoi."""
        return await self.poste(cle.signe(await self.options(), **reglages))

    def lignes(self, requete: str, *valeurs: object) -> list[Ligne]:
        return self.fabrique.admin.execute(requete, valeurs).fetchall()

    def sessions_de_la_cle(self) -> list[Ligne]:
        return self.lignes(
            "select opened_with, opened_with_credential is not null from public.login_session"
            " where person_id = %s and opened_with = 'cle'",
            self.moi.id,
        )

    def compteur(self) -> int:
        (ligne,) = self.lignes(
            "select sign_count from public.webauthn_credential where person_id = %s", self.moi.id
        )
        return int(ligne[0])

    def evenements(self, kind: str) -> int:
        (ligne,) = self.lignes(
            "select count(*) from public.security_event where kind = %s and person_id = %s", kind, self.moi.id
        )
        return int(ligne[0])

    def defis_vivants(self) -> int:
        (ligne,) = self.lignes(
            "select count(*) from public.webauthn_challenge where purpose = 'authentication' and "
            "expires_at > now()"
        )
        return int(ligne[0])


@pytest.fixture
async def banc(
    base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[BancDeConnexion]:
    enregistrement = BancDEnregistrement(base, fabrique, monkeypatch, identity_pepper=POIVRE)
    banc = BancDeConnexion(enregistrement)
    yield banc
    admin = fabrique.admin
    cle_ip = banc.empreintes.cle_ip_requise(banc.ip)
    admin.execute("delete from public.login_throttle where key = %s", (cle_ip,))
    admin.execute(
        "delete from public.security_event where person_id = %s or ip_hash = %s", (banc.moi.id, cle_ip)
    )
    admin.execute(
        "delete from public.webauthn_challenge where purpose = 'authentication' and expires_at < now() + "
        "interval '1 hour'"
    )


def sans_bruit(reponse: httpx.Response) -> tuple[int, dict[str, Any], dict[str, str]]:
    """Ce qui doit être identique d'un refus à l'autre : statut, corps, en-têtes (sans date ni
    identifiant)."""
    entetes = {
        nom: valeur
        for nom, valeur in reponse.headers.items()
        if nom not in {"date", "x-request-id", "content-length", "traceparent"}
        and not nom.startswith("ratelimit")  # le « restant » baisse à chaque essai, par construction
    }
    corps = {nom: valeur for nom, valeur in reponse.json().items() if nom != "instance"}
    return reponse.status_code, corps, entetes


# ── Le défi ─────────────────────────────────────────────────────────────────


class TestDefi:
    async def test_les_options_n_ont_ni_nom_ni_cle_nommee_et_exigent_la_verification(
        self, banc: BancDeConnexion
    ) -> None:
        options = await banc.options()
        assert options["rpId"] == "localhost"
        assert options["userVerification"] == "required"
        assert options.get("allowCredentials", []) == []
        assert len(_octets(options["challenge"])) == 32
        assert "user" not in options

    async def test_deux_defis_different(self, banc: BancDeConnexion) -> None:
        assert (await banc.options())["challenge"] != (await banc.options())["challenge"]

    async def test_un_defi_se_garde_sans_personne_ni_session(self, banc: BancDeConnexion) -> None:
        options = await banc.options()
        (ligne,) = banc.lignes(
            "select purpose, person_id, session_id from public.webauthn_challenge where challenge = %s",
            _octets(options["challenge"]),
        )
        assert tuple(ligne) == ("authentication", None, None)

    async def test_une_origine_non_admise_rend_403_sans_defi_ni_creneau(self, banc: BancDeConnexion) -> None:
        avant = banc.defis_vivants()
        reponse = await banc.client().post(
            DEFIS, headers={"Origin": "http://127.0.0.1:5173", "X-Popote-Client": "web"}
        )
        assert (reponse.status_code, reponse.json()["code"]) == (403, "cle_origine_non_admise")
        assert banc.defis_vivants() == avant
        assert (
            banc.lignes(
                "select 1 from public.login_throttle where key = %s", banc.empreintes.cle_ip_requise(banc.ip)
            )
            == []
        )

    async def test_les_defis_d_une_ip_sont_limites_sans_escalade(
        self, base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        enregistrement = BancDEnregistrement(
            base, fabrique, monkeypatch, identity_pepper=POIVRE, cle_defis_par_ip=2
        )
        banc = BancDeConnexion(enregistrement)
        try:
            await banc.options()
            await banc.options()
            refus = await banc.client().post(DEFIS, headers=ECRITURE)
            assert (refus.status_code, refus.json()["code"]) == (429, "trop_de_requetes")
            assert 0 < int(refus.headers["retry-after"]) <= 900
            # Une autre IP n'est pas touchée.
            assert (await banc.client("198.51.100.7").post(DEFIS, headers=ECRITURE)).status_code == 200
        finally:
            cle = banc.empreintes.cle_ip_requise(banc.ip)
            fabrique.admin.execute(
                "delete from public.login_throttle where key = any(%s)",
                ([cle, banc.empreintes.cle_ip_requise("198.51.100.7")],),
            )

    async def test_au_dela_du_plafond_de_defis_vivants_la_reponse_est_429(
        self, base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vivants = fabrique.admin.execute(
            "select count(*) from public.webauthn_challenge where purpose = 'authentication' and "
            "expires_at > now()"
        ).fetchone()
        assert vivants is not None
        enregistrement = BancDEnregistrement(
            base, fabrique, monkeypatch, identity_pepper=POIVRE, cle_defis_anonymes_max=int(vivants[0]) + 1
        )
        banc = BancDeConnexion(enregistrement)
        try:
            await banc.options()
            refus = await banc.client().post(DEFIS, headers=ECRITURE)
            assert (refus.status_code, refus.json()["code"]) == (429, "trop_de_requetes")
            assert refus.headers["retry-after"] == "60"
        finally:
            fabrique.admin.execute(
                "delete from public.login_throttle where key = %s", (banc.empreintes.cle_ip_requise(banc.ip),)
            )
            fabrique.admin.execute(
                "delete from public.webauthn_challenge where purpose = 'authentication' and expires_at < "
                "now() + interval '1 hour'"
            )


# ── La connexion ────────────────────────────────────────────────────────────


class TestConnexion:
    async def test_la_connexion_sans_taper_d_adresse_ouvre_une_session_par_cle_avec_son_cookie(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        reponse = await banc.connecte(cle)
        assert reponse.status_code == 201, reponse.text
        assert set(reponse.json()) == {"id"}
        cookie = reponse.headers["set-cookie"]
        assert cookie.startswith(f"{NOM_DU_COOKIE}=")
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        assert banc.sessions_de_la_cle() == [("cle", True)]
        assert banc.compteur() == cle.compteur
        assert banc.evenements("connexion_par_cle") == 1
        # La session sert : la personne lit ses appareils avec ce cookie.
        appareils = await banc.client().get("/api/v1/me/sessions", headers={"Cookie": cookie.split(";")[0]})
        assert appareils.status_code == 200
        assert reponse.json()["id"] in [s["id"] for s in appareils.json()["items"]]

    async def test_une_assertion_ne_sert_qu_une_fois(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        credential = cle.signe(await banc.options())
        assert (await banc.poste(credential)).status_code == 201
        rejeu = await banc.poste(credential)
        assert (rejeu.status_code, rejeu.json()["code"]) == (401, "cle_refusee")
        assert len(banc.sessions_de_la_cle()) == 1

    async def test_deux_soumissions_paralleles_de_la_meme_assertion_ouvrent_une_seule_session(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        credential = cle.signe(await banc.options())
        reponses = await asyncio.gather(*(banc.poste(credential) for _ in range(2)))
        assert sorted(r.status_code for r in reponses) == [201, 401]
        assert len(banc.sessions_de_la_cle()) == 1

    @pytest.mark.parametrize(
        "reglage",
        [
            pytest.param({"origine": "https://faux.example"}, id="mauvaise_origine"),
            pytest.param({"rp_id": "example.com"}, id="mauvais_rp_id"),
            pytest.param({"up": False}, id="presence_absente"),
            pytest.param({"uv": False}, id="verification_absente"),
            pytest.param({"signature_fausse": True}, id="signature_fausse"),
            pytest.param({"identifiant_utilisateur": None}, id="user_handle_absent"),
            pytest.param({"identifiant_utilisateur": b"\x07" * 64}, id="user_handle_d_un_autre"),
            pytest.param({"type_de_donnees": "webauthn.create"}, id="mauvais_type"),
            pytest.param({"cross_origin": True}, id="autre_cadre"),
            pytest.param({"defi": b"\x00" * 32}, id="defi_inconnu"),
        ],
    )
    async def test_tout_ce_qui_n_est_pas_une_assertion_valable_rend_le_meme_401_sans_session(
        self, banc: BancDeConnexion, reglage: dict[str, Any]
    ) -> None:
        cle = await banc.cle()
        reponse = await banc.connecte(cle, **reglage)
        assert (reponse.status_code, reponse.json()["code"], reponse.json()["detail"]) == (
            401,
            "cle_refusee",
            MESSAGE,
        )
        assert "set-cookie" not in reponse.headers
        assert banc.sessions_de_la_cle() == []
        assert banc.evenements("cle_suspecte") == 0

    async def test_une_eligibilite_de_sauvegarde_changee_est_refusee_et_journalisee_comme_suspecte(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()  # enregistrée sans BE
        reponse = await banc.connecte(cle, be=True)
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert banc.evenements("cle_suspecte") == 1
        assert banc.sessions_de_la_cle() == []
        # Sans signature valide, même changement : aucune alerte.
        assert (await banc.connecte(cle, be=True, signature_fausse=True)).status_code == 401
        assert banc.evenements("cle_suspecte") == 1

    async def test_une_erreur_de_validation_garde_le_pointeur_du_champ_de_chaque_forme_du_corps(
        self, banc: BancDeConnexion
    ) -> None:
        async def pointeurs(corps: dict[str, Any]) -> list[str | None]:
            reponse = await banc.client().post(SESSIONS, json=corps, headers=ECRITURE)
            assert reponse.status_code == 422
            return [erreur.get("pointer") for erreur in reponse.json()["errors"]]

        code = {"email": "a@example.com", "code_request_id": str(uuid4())}
        assert await pointeurs({"method": "email_code", **code, "code": "12"}) == ["/code"]
        assert await pointeurs({"method": "passkey"}) == ["/credential"]
        assert await pointeurs({**code, "code": "123456"}) == ["/method"]
        assert await pointeurs({"method": "mot_de_passe", **code, "code": "123456"}) == ["/method"]

    async def test_une_cle_inconnue_et_une_signature_fausse_rendent_la_meme_reponse(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        inconnue = authentificateur()  # jamais enregistrée
        fausse = await banc.connecte(cle, signature_fausse=True)
        pas_la_bonne = await banc.connecte(inconnue)
        assert sans_bruit(fausse) == sans_bruit(pas_la_bonne)

    async def test_un_defi_echu_est_refuse(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        options = await banc.options()
        banc.fabrique.admin.execute(
            "update public.webauthn_challenge set created_at = now() - interval '11 minutes',"
            " expires_at = now() - interval '1 minute' where challenge = %s",
            (_octets(options["challenge"]),),
        )
        reponse = await banc.poste(cle.signe(options))
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert banc.sessions_de_la_cle() == []

    async def test_un_defi_d_enregistrement_ne_sert_pas_a_se_connecter(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        options = await banc.enregistrement.options()  # un défi de la cérémonie d'enregistrement
        credential = cle.signe({"challenge": options["challenge"], "rpId": "localhost"})
        reponse = await banc.poste(credential)
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert banc.sessions_de_la_cle() == []
        assert banc.enregistrement.defis_vivants() == 1  # il n'a pas été brûlé

    async def test_le_defi_brule_reste_brule_apres_un_refus(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        options = await banc.options()
        assert (await banc.poste(cle.signe(options, signature_fausse=True))).status_code == 401
        # Le même défi, une assertion cette fois valable : refusé, le défi a servi.
        assert (await banc.poste(cle.signe(options))).status_code == 401
        assert banc.sessions_de_la_cle() == []

    @pytest.mark.parametrize("etat", ["bannie", "supprimee", "sans_profil"])
    async def test_une_personne_qui_ne_peut_pas_entrer_recoit_le_meme_401_et_non_un_503(
        self, banc: BancDeConnexion, etat: str
    ) -> None:
        cle = await banc.cle()
        admin = banc.fabrique.admin
        match etat:
            case "bannie":
                admin.execute(
                    "update auth.users set banned_until = now() + interval '1 day' where id = %s",
                    (banc.moi.id,),
                )
            case "supprimee":
                admin.execute("update auth.users set deleted_at = now() where id = %s", (banc.moi.id,))
            case "sans_profil":
                admin.execute("delete from public.user_profile where id = %s", (banc.moi.id,))
        reponse = await banc.connecte(cle)
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert (
            banc.lignes(
                "select 1 from public.login_session where person_id = %s and opened_with = 'cle'", banc.moi.id
            )
            == []
        )

    async def test_le_cookie_present_est_revoque_par_la_nouvelle_session(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        credential = cle.signe(await banc.options())
        reponse = await banc.poste(
            credential, entetes={"Cookie": f"{NOM_DU_COOKIE}={banc.enregistrement.session.jeton}"}
        )
        assert reponse.status_code == 201
        assert banc.lignes(
            "select revoked_at is not null from public.login_session where id = %s",
            banc.enregistrement.session.id,
        ) == [(True,)]

    async def test_une_origine_etrangere_est_refusee_sans_creneau(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        credential = cle.signe(await banc.options())
        reponse = await banc.poste(credential, entetes={"Origin": "https://faux.example"})
        assert reponse.status_code == 403
        assert banc.sessions_de_la_cle() == []

    async def test_un_corps_de_plus_de_16_kio_est_refuse_en_422(self, banc: BancDeConnexion) -> None:
        reponse = await banc.poste({"id": "x" * 20_000})
        assert reponse.status_code == 422
        assert (
            banc.lignes(
                "select 1 from public.login_throttle where key = %s", banc.empreintes.cle_ip_requise(banc.ip)
            )
            == []
        )

    @pytest.mark.parametrize(
        "corps", [{"method": "passkey"}, {"method": "passkey", "credential": {}, "email": "a@b.fr"}]
    )
    async def test_un_corps_incomplet_ou_avec_un_champ_en_trop_est_refuse_en_422(
        self, banc: BancDeConnexion, corps: dict[str, Any]
    ) -> None:
        reponse = await banc.client().post(SESSIONS, json=corps, headers=ECRITURE)
        assert reponse.status_code == 422

    async def test_un_credential_mal_forme_rend_401_et_pas_500(self, banc: BancDeConnexion) -> None:
        for credential in ({}, {"id": 1}, {"id": "a", "rawId": "a", "type": "public-key", "response": {}}):
            reponse = await banc.poste(credential)
            assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")


# ── Le compteur ─────────────────────────────────────────────────────────────


class TestCompteur:
    async def test_un_compteur_qui_croit_passe(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        assert (await banc.connecte(cle, compteur=5)).status_code == 201
        assert (await banc.connecte(cle, compteur=6)).status_code == 201
        assert banc.compteur() == 6

    async def test_un_compteur_egal_est_refuse_sans_alerte_ni_changement(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        assert (await banc.connecte(cle, compteur=5)).status_code == 201
        reponse = await banc.connecte(cle, compteur=5)
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert banc.compteur() == 5

    async def test_une_regression_signee_est_refusee_journalisee_et_laisse_le_compteur(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        assert (await banc.connecte(cle, compteur=9)).status_code == 201
        reponse = await banc.connecte(cle, compteur=3)
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert banc.compteur() == 9
        assert banc.evenements("cle_suspecte") == 1
        assert len(banc.sessions_de_la_cle()) == 1

    async def test_une_regression_non_signee_ne_fait_pas_naitre_d_alerte(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle()
        assert (await banc.connecte(cle, compteur=9)).status_code == 201
        assert (await banc.connecte(cle, compteur=3, signature_fausse=True)).status_code == 401
        assert banc.evenements("cle_suspecte") == 0

    async def test_une_regression_avec_un_mauvais_user_handle_ne_fait_pas_naitre_d_alerte(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        assert (await banc.connecte(cle, compteur=9)).status_code == 201
        assert (await banc.connecte(cle, compteur=3, identifiant_utilisateur=b"\x01" * 64)).status_code == 401
        assert banc.evenements("cle_suspecte") == 0

    async def test_deux_zeros_sont_acceptes_comme_une_cle_synchronisee(self, banc: BancDeConnexion) -> None:
        cle = await banc.cle(be=True, bs=True)
        assert (await banc.connecte(cle, compteur=0, be=True, bs=True)).status_code == 201
        assert (await banc.connecte(cle, compteur=0, be=True, bs=True)).status_code == 201
        assert banc.compteur() == 0

    async def test_l_etat_de_sauvegarde_se_met_a_jour_et_l_eligibilite_ne_change_pas(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle(be=True)
        assert (await banc.connecte(cle, be=True, bs=True)).status_code == 201
        assert banc.lignes(
            "select backup_state from public.webauthn_credential where person_id = %s", banc.moi.id
        ) == [(True,)]
        assert (await banc.connecte(cle, be=False)).status_code == 401


# ── Les limites ─────────────────────────────────────────────────────────────


class TestLimites:
    async def test_au_dela_de_la_limite_la_reponse_est_429_sans_verification_et_sans_brûler_le_defi(
        self, base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        enregistrement = BancDEnregistrement(
            base, fabrique, monkeypatch, identity_pepper=POIVRE, cle_essais_par_ip=2
        )
        banc = BancDeConnexion(enregistrement)
        try:
            cle = await banc.cle()
            for _ in range(2):
                assert (await banc.connecte(cle, signature_fausse=True)).status_code == 401
            options = await banc.options()
            bloque = await banc.poste(cle.signe(options))
            assert (bloque.status_code, bloque.json()["code"]) == (429, "trop_de_requetes")
            assert 0 < int(bloque.headers["retry-after"]) <= 900
            assert banc.sessions_de_la_cle() == []
            # Le défi n'a pas été consommé par le refus.
            assert (
                banc.lignes(
                    "select 1 from public.webauthn_challenge where challenge = %s",
                    _octets(options["challenge"]),
                )
                != []
            )
            assert banc.evenements("connexion_par_cle") == 0
            # Un seul événement de blocage pour tous les essais refusés.
            assert (await banc.poste(cle.signe(options))).status_code == 429
            (ligne,) = banc.lignes(
                "select count(*) from public.security_event where kind = 'connexion_bloquee' and ip_hash "
                "= %s",
                banc.empreintes.cle_ip_requise(banc.ip),
            )
            assert ligne[0] == 1
            # Une autre IP n'est pas touchée.
            assert (
                await banc.poste(cle.signe(await banc.options()), client=banc.client("198.51.100.9"))
            ).status_code == 201
        finally:
            cles = [banc.empreintes.cle_ip_requise(ip) for ip in (banc.ip, "198.51.100.9")]
            fabrique.admin.execute("delete from public.login_throttle where key = any(%s)", (cles,))
            fabrique.admin.execute(
                "delete from public.security_event where ip_hash = any(%s) or person_id = %s",
                (cles, banc.moi.id),
            )
            fabrique.admin.execute(
                "delete from public.webauthn_challenge where purpose = 'authentication' and expires_at < "
                "now() + interval '1 hour'"
            )

    async def test_le_refus_ecrit_connexion_ratee_avec_la_cle_de_l_ip_et_jamais_l_ip(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        assert (await banc.connecte(cle, signature_fausse=True)).status_code == 401
        (ligne,) = banc.lignes(
            "select ip_hash from public.security_event where kind = 'connexion_ratee' and ip_hash = %s",
            banc.empreintes.cle_ip_requise(banc.ip),
        )
        assert bytes(ligne[0]) == banc.empreintes.cle_ip_requise(banc.ip)


# ── Les pannes ──────────────────────────────────────────────────────────────


class TestPannes:
    async def test_une_erreur_de_base_a_la_creation_de_la_session_rend_503_et_laisse_le_defi_valable(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        options = await banc.options()
        credential = cle.signe(options)
        nom = f"s9b_leve_{uuid4().hex[:8]}"
        admin = banc.fabrique.admin
        admin.execute(
            f"create function public.{nom}() returns trigger language plpgsql as $$ begin"
            f" if new.person_id = '{banc.moi.id}' and new.opened_with = 'cle' then"
            f" raise exception 'erreur injectee' using errcode = '40001'; end if; return new; end $$"
        )
        admin.execute(
            f"create trigger {nom} before insert on public.login_session for each row execute function "
            f"public.{nom}()"
        )
        try:
            reponse = await banc.poste(credential)
        finally:
            admin.execute(f"drop trigger {nom} on public.login_session")
            admin.execute(f"drop function public.{nom}()")
        assert (reponse.status_code, reponse.json()["code"]) == (503, "reessayer")
        assert reponse.headers["retry-after"] == "1" and "set-cookie" not in reponse.headers
        assert banc.compteur() == 0
        assert banc.sessions_de_la_cle() == []
        assert (
            banc.lignes(
                "select 1 from public.webauthn_challenge where challenge = %s", _octets(options["challenge"])
            )
            != []
        )
        # La même assertion, la nouvelle tentative réussit : rien n'a été brûlé.
        assert (await banc.poste(credential)).status_code == 201

    async def test_une_cle_publique_illisible_en_base_rend_503_sans_bruler_le_defi(
        self, banc: BancDeConnexion, caplog: pytest.LogCaptureFixture
    ) -> None:
        cle = await banc.cle()
        banc.fabrique.admin.execute(
            "update public.webauthn_credential set public_key = %s where person_id = %s",
            (b"\x00" * 10, banc.moi.id),
        )
        options = await banc.options()
        with caplog.at_level(logging.DEBUG):
            reponse = await banc.poste(cle.signe(options))
        assert (reponse.status_code, reponse.json()["code"]) == (503, "service_indisponible")
        assert (
            banc.lignes(
                "select 1 from public.webauthn_challenge where challenge = %s", _octets(options["challenge"])
            )
            != []
        )
        assert banc.sessions_de_la_cle() == []

    async def test_les_journaux_n_ecrivent_ni_defi_ni_assertion_ni_identifiant_de_cle(
        self, banc: BancDeConnexion, caplog: pytest.LogCaptureFixture
    ) -> None:
        cle = await banc.cle()
        options = await banc.options()
        credential = cle.signe(options, signature_fausse=True)
        with caplog.at_level(logging.DEBUG):
            assert (await banc.poste(credential)).status_code == 401
            assert (await banc.connecte(cle, compteur=0)).status_code == 201
        texte = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
        for secret in (
            options["challenge"],
            credential["id"],
            credential["response"]["signature"],
            credential["response"]["clientDataJSON"],
            credential["response"]["authenticatorData"],
            credential["response"]["userHandle"],
        ):
            assert secret not in texte


# ── La course ───────────────────────────────────────────────────────────────


class TestCourse:
    async def test_une_connexion_attend_la_fermeture_des_sessions_puis_ouvre_une_session_posterieure(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        gardee = banc.fabrique.session(banc.moi.id)
        credential = cle.signe(await banc.options())
        admin = banc.fabrique.admin
        with connecte(DSN_API) as a:
            a.execute(
                "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (banc.moi.id, gardee.id)
            )
            tache = asyncio.create_task(banc.poste(credential))
            try:
                await attend_un_verrou(admin, "cle_pour_connexion", a.info.backend_pid)
            except BaseException:
                tache.cancel()
                a.rollback()
                await asyncio.gather(tache, return_exceptions=True)
                raise
            a.commit()
            reponse = await tache
        # La preuve se fait après le verrou : la session est postérieure à la fermeture, elle survit.
        assert reponse.status_code == 201
        vivantes = {
            UUID(str(ligne[0]))
            for ligne in banc.lignes(
                "select id from public.login_session where person_id = %s and revoked_at is null", banc.moi.id
            )
        }
        assert vivantes == {gardee.id, UUID(reponse.json()["id"])}

    async def test_une_connexion_attend_la_suppression_de_la_cle_puis_est_refusee(
        self, banc: BancDeConnexion
    ) -> None:
        cle = await banc.cle()
        credential = cle.signe(await banc.options())
        admin = banc.fabrique.admin
        with connecte(DSN_API) as a:
            a.execute("select public.verrouille_la_personne(%s, null)", (banc.moi.id,))
            a.execute("select set_config('popote.test', '1', true)")
            tache = asyncio.create_task(banc.poste(credential))
            try:
                await attend_un_verrou(admin, "cle_pour_connexion", a.info.backend_pid)
            except BaseException:
                tache.cancel()
                a.rollback()
                await asyncio.gather(tache, return_exceptions=True)
                raise
            # A supprime la clé sous le verrou (c'est ce que fera S10), puis valide.
            admin.execute("delete from public.webauthn_credential where person_id = %s", (banc.moi.id,))
            a.commit()
            reponse = await tache
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert banc.sessions_de_la_cle() == []


def _octets(valeur: str) -> bytes:
    from webauthn.helpers import base64url_to_bytes

    return base64url_to_bytes(valeur)
