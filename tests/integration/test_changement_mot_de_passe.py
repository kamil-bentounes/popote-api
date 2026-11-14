"""T11 : `PUT /api/v1/me/password` (spec § 4 ; B3, B4, B9, B23), en base locale et contre l'Auth local.

Données inventées. Le succès passe par le vrai Auth de la pile locale (le hachage écrit est celui que la
connexion vérifie) ; une panne d'Auth est simulée. La liste de fuites est toujours un faux : aucun réseau.
"""

# ruff: noqa: F811, F401

import asyncio
import json
import logging
import unicodedata
from typing import Any
from uuid import UUID

import httpx
import pytest
from _client import cookie
from _fabrique import SessionDeTest
from pydantic import SecretStr
from test_auth_admin_local import ENV_LOCAL
from test_connexion import ECRITURE, MOT_DE_PASSE
from test_reauthentification import Personne, fabrique_de_banc, moi

from popote_api.api import moi as moi_api
from popote_api.infra.auth_admin import AuthAdmin, AuthIndisponible
from popote_api.infra.fuites import CauseIndisponibilite, ResultatFuite
from popote_api.security.jeton import empreinte_du_jeton

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/me/password"
# « é » en une seule lettre (NFC) ; la personne le tape décomposé (NFD) : la forme écrite est la NFC.
NOUVEAU_NFC = unicodedata.normalize("NFC", "un nouveau mot de passe très élaboré")
NOUVEAU_NFD = unicodedata.normalize("NFD", NOUVEAU_NFC)
assert NOUVEAU_NFC != NOUVEAU_NFD


class FauxFuites:
    def __init__(self, verdict: ResultatFuite) -> None:
        self.verdict, self.appels = verdict, 0

    async def verifie(self, mot_de_passe: str) -> ResultatFuite:
        self.appels += 1
        return self.verdict


class EspionAuth(AuthAdmin):
    """Le vrai client, qui se souvient de ce qu'on lui a demandé."""

    def __init__(self) -> None:
        url, cle = ENV_LOCAL.get("POPOTE_SUPABASE_URL"), ENV_LOCAL.get("POPOTE_SUPABASE_SECRET_KEY")
        if not url or not cle:
            pytest.fail("Pas de .env local : lancer `bash ops/env-local.sh` (pile Supabase locale démarrée).")
        super().__init__(url, SecretStr(cle))
        self.appels: list[tuple[UUID, str]] = []

    async def change_mot_de_passe(self, identifiant: UUID, mot_de_passe: str) -> None:
        self.appels.append((identifiant, mot_de_passe))
        await super().change_mot_de_passe(identifiant, mot_de_passe)


class AuthEnPanne(AuthAdmin):
    def __init__(self) -> None:
        super().__init__(None, None)
        self.appels = 0

    async def change_mot_de_passe(self, identifiant: UUID, mot_de_passe: str) -> None:
        self.appels += 1
        raise AuthIndisponible("panne simulée")


@pytest.fixture
def fuites(moi: Personne) -> FauxFuites:
    faux = FauxFuites(ResultatFuite.sain())
    moi.banc.app.state.fuites = faux
    return faux


@pytest.fixture
def auth(moi: Personne) -> EspionAuth:
    espion = EspionAuth()
    # GoTrue ne sait pas lire une ligne insérée à la main dont les jetons sont NULL (`unexpected_failure`).
    moi.banc.fabrique.admin.execute(
        "update auth.users set confirmation_token = '', recovery_token = '', email_change_token_new = '', "
        "email_change = '', email_change_token_current = '', phone_change = '', phone_change_token = '', "
        "reauthentication_token = '' where id = %s",
        (moi.id,),
    )
    moi.banc.app.state.auth_admin = espion
    return espion


def change(
    moi: Personne,
    mot_de_passe: str = NOUVEAU_NFD,
    *,
    session: SessionDeTest | None = None,
    jeton: str | None = None,
    corps: dict[str, Any] | None = None,
) -> Any:
    entetes = {"Cookie": f"{moi.banc.reglages.nom_du_cookie_de_session}={jeton}"} if jeton else {}
    envoi: dict[str, Any] = (
        # `ensure_ascii` : un substitut isolé voyage en `\\ud800`, que httpx ne saurait pas encoder en UTF-8.
        {
            "content": json.dumps({"new_password": mot_de_passe}).encode(),
            "headers": {"Content-Type": "application/json"},
        }
        if corps is None
        else {"json": corps}
    )
    entetes_complets = (entetes or cookie(session or moi.session)) | ECRITURE | envoi.pop("headers", {})
    return moi.banc.client().put(ROUTE, headers=entetes_complets, **envoi)


def jeton_pose(reponse: httpx.Response) -> str:
    entete = reponse.headers["set-cookie"]
    return entete.split(";")[0].split("=", 1)[1]


async def lit_moi(moi: Personne, jeton: str) -> int:
    cookie_ = {"Cookie": f"{moi.banc.reglages.nom_du_cookie_de_session}={jeton}"}
    return (await moi.banc.client().get("/api/v1/me", headers=cookie_)).status_code


def password_set(moi: Personne) -> bool:
    (ligne,) = moi.banc.lignes("select password_set from public.user_profile where id = %s", moi.id)
    return bool(ligne[0])


def lignes_auth(moi: Personne) -> int:
    (ligne,) = moi.banc.lignes("select count(*) from auth.sessions where user_id = %s", moi.id)
    return int(ligne[0])


def pose_des_sessions_auth(moi: Personne) -> None:
    moi.banc.fabrique.admin.execute(
        "insert into auth.sessions (id, user_id, created_at, updated_at) "
        "values (gen_random_uuid(), %s, now(), now())",
        (moi.id,),
    )
    moi.banc.fabrique.admin.execute(
        "insert into auth.refresh_tokens (instance_id, token, user_id, session_id) "
        "select '00000000-0000-0000-0000-000000000000', gen_random_uuid()::text, user_id::text, id "
        "from auth.sessions where user_id = %s",
        (moi.id,),
    )
    assert lignes_auth(moi) >= 1


class TestGarde:
    async def test_sans_reauthentification_recente_403_et_rien_ne_change(
        self,
        moi: Personne,
        fuites: FauxFuites,
        auth: EspionAuth,
    ) -> None:
        moi.vieillit()
        reponse = await change(moi)
        assert reponse.status_code == 403
        assert reponse.json()["code"] == "reauthentification_requise"
        assert "set-cookie" not in reponse.headers
        assert (fuites.appels, auth.appels) == (0, [])
        assert await lit_moi(moi, moi.session.jeton) == 200  # la session n'a pas tourné


@pytest.mark.parametrize(
    "invalide",
    [
        "a" * 14,
        "a" * 65,
        "é" * 36 + "a",  # 37 caractères, 73 octets
        "a" * 15 + "\u0000",
        "a" * 15 + "\ud800",  # un substitut isolé
        "a" * 300,  # au-delà de la borne du modèle
    ],
    ids=["14", "65", "73-octets", "nul", "substitut", "300"],
)
async def test_un_mot_de_passe_invalide_donne_422_sans_rien_changer(
    moi: Personne,
    fuites: FauxFuites,
    auth: EspionAuth,
    invalide: str,
) -> None:
    reponse = await change(moi, invalide)
    assert reponse.status_code == 422
    assert {e["pointer"] for e in reponse.json()["errors"]} == {"/new_password"}
    assert "set-cookie" not in reponse.headers
    assert (fuites.appels, auth.appels) == (0, [])
    assert await lit_moi(moi, moi.session.jeton) == 200
    assert moi.evenements("mot_de_passe_change") == []


async def test_un_champ_inconnu_ou_absent_donne_422(
    moi: Personne, fuites: FauxFuites, auth: EspionAuth
) -> None:
    assert (await change(moi, corps={"new_password": NOUVEAU_NFC, "extra": 1})).status_code == 422
    assert (await change(moi, corps={})).status_code == 422
    assert auth.appels == []


async def test_un_mot_de_passe_fuite_donne_422_sans_appel_a_auth_ni_etat_change(
    moi: Personne,
    fuites: FauxFuites,
    auth: EspionAuth,
) -> None:
    fuites.verdict = ResultatFuite.fuite()
    reponse = await change(moi)
    assert reponse.status_code == 422
    assert reponse.json()["errors"][0]["pointer"] == "/new_password"
    assert fuites.appels == 1
    assert auth.appels == []
    assert "set-cookie" not in reponse.headers
    assert await lit_moi(moi, moi.session.jeton) == 200
    assert not password_set(moi)
    assert moi.evenements("mot_de_passe_change") == []


async def test_liste_hors_service_le_mot_de_passe_est_accepte_et_l_evenement_ecrit_sans_valeur(
    moi: Personne,
    fuites: FauxFuites,
    auth: EspionAuth,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fuites.verdict = ResultatFuite.indisponible(CauseIndisponibilite.delai)
    caplog.set_level(logging.DEBUG)
    reponse = await change(moi)
    assert reponse.status_code == 204
    assert len(moi.evenements("verification_fuites_indisponible")) == 1
    assert len(moi.evenements("mot_de_passe_change")) == 1
    (colonnes,) = moi.banc.lignes(
        "select row_to_json(e)::text from public.security_event e "
        "where kind = 'verification_fuites_indisponible' and person_id = %s",
        moi.id,
    )
    assert NOUVEAU_NFC not in colonnes[0]
    assert "indisponible" in caplog.text
    assert NOUVEAU_NFC not in caplog.text and NOUVEAU_NFD not in caplog.text


class TestSucces:
    async def test_le_changement_complet(
        self,
        moi: Personne,
        fuites: FauxFuites,
        auth: EspionAuth,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        autre = moi.banc.fabrique.session(moi.id)
        pose_des_sessions_auth(moi)
        caplog.set_level(logging.DEBUG)
        reponse = await change(moi)
        assert reponse.status_code == 204
        assert reponse.content == b""
        assert reponse.headers["cache-control"] == "no-store"
        nouveau = jeton_pose(reponse)
        assert nouveau != moi.session.jeton
        assert "HttpOnly" in reponse.headers["set-cookie"] and "Secure" in reponse.headers["set-cookie"]
        # L'ancien cookie et les autres sessions sont morts ; le nouveau vit, c'est la MÊME session.
        assert await lit_moi(moi, moi.session.jeton) == 401
        assert await lit_moi(moi, autre.jeton) == 401
        assert await lit_moi(moi, nouveau) == 200
        (ligne,) = moi.banc.lignes(
            "select token_hash from public.login_session where id = %s", moi.session.id
        )
        assert bytes(ligne[0]) == empreinte_du_jeton(nouveau)  # la même session, sous le nouveau jeton
        # Auth appelé une fois, avec la forme NFKC (la forme composée), jamais celle qui a été tapée.
        assert auth.appels == [(moi.id, unicodedata.normalize("NFKC", NOUVEAU_NFD))]
        assert fuites.appels == 1
        # Le nouveau mot de passe, tapé décomposé, ouvre une session ; l'ancien est refusé.
        assert await moi.banc.mot_de_passe_est_bon(moi.email, NOUVEAU_NFD)
        assert not await moi.banc.mot_de_passe_est_bon(moi.email, MOT_DE_PASSE)
        assert password_set(moi)
        assert lignes_auth(moi) == 0  # B9 : plus de ligne `auth.sessions`
        (jetons,) = moi.banc.lignes(
            "select count(*) from auth.refresh_tokens where user_id = %s", str(moi.id)
        )
        assert jetons[0] == 0
        assert len(moi.evenements("mot_de_passe_change")) == 1
        # Le mot de passe n'est dans aucune réponse ni aucun journal.
        for forme in (NOUVEAU_NFC, NOUVEAU_NFD):
            assert forme not in reponse.text and forme not in caplog.text

    async def test_le_meme_mot_de_passe_renvoye_donne_204(
        self,
        moi: Personne,
        fuites: FauxFuites,
        auth: EspionAuth,
    ) -> None:
        reponse = await change(moi, MOT_DE_PASSE)
        assert reponse.status_code == 204
        assert await moi.banc.mot_de_passe_est_bon(moi.email, MOT_DE_PASSE)

    async def test_deux_changements_simultanes_donnent_un_204_et_un_401_sans_cookie(
        self,
        moi: Personne,
        fuites: FauxFuites,
        auth: EspionAuth,
    ) -> None:
        reponses = await asyncio.gather(change(moi, NOUVEAU_NFC), change(moi, NOUVEAU_NFC + " bis"))
        assert sorted(r.status_code for r in reponses) == [204, 401]
        perdante = next(r for r in reponses if r.status_code == 401)
        assert "set-cookie" not in perdante.headers
        assert len(auth.appels) == 1  # le perdant n'a jamais atteint Auth
        assert len(moi.evenements("mot_de_passe_change")) == 1


async def test_auth_en_panne_donne_503_avec_le_nouveau_cookie_et_le_mot_de_passe_inchange(
    moi: Personne,
    fuites: FauxFuites,
) -> None:
    panne = AuthEnPanne()
    moi.banc.app.state.auth_admin = panne
    autre = moi.banc.fabrique.session(moi.id)
    pose_des_sessions_auth(moi)
    reponse = await change(moi)
    assert reponse.status_code == 503
    assert reponse.json()["code"] == "auth_indisponible"
    nouveau = jeton_pose(reponse)
    assert panne.appels == 1
    assert await lit_moi(moi, nouveau) == 200  # la session survit, sous son nouveau jeton
    assert await lit_moi(moi, moi.session.jeton) == 401
    assert await lit_moi(moi, autre.jeton) == 401  # les autres sont fermées par précaution
    assert await moi.banc.mot_de_passe_est_bon(moi.email, MOT_DE_PASSE)  # l'ancien est encore le bon
    assert not password_set(moi)
    # B9 : fermées par la base à l'étape 2, avant Auth (au succès, Auth les ferme aussi de son côté).
    assert lignes_auth(moi) == 0
    assert moi.evenements("mot_de_passe_change") == []  # l'événement n'existe qu'au succès


async def test_une_session_ouverte_pendant_l_appel_a_auth_est_fermee_au_succes(
    moi: Personne, fuites: FauxFuites, auth: EspionAuth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une connexion faite avec l'ancien mot de passe pendant l'appel à Auth ne survit pas au changement."""
    espion = auth
    origine = espion.change_mot_de_passe
    ouvertes: list[SessionDeTest] = []

    async def avec_une_connexion_en_route(identifiant: UUID, mot_de_passe: str) -> None:
        # La rotation est déjà validée : cette session naît après elle (connexion à l'ancien mot de passe).
        ouvertes.append(moi.banc.fabrique.session(moi.id))
        assert await lit_moi(moi, ouvertes[0].jeton) == 200
        await origine(identifiant, mot_de_passe)

    monkeypatch.setattr(espion, "change_mot_de_passe", avec_une_connexion_en_route)
    reponse = await change(moi)
    assert reponse.status_code == 204
    assert len(ouvertes) == 1
    assert await lit_moi(moi, ouvertes[0].jeton) == 401
    assert await lit_moi(moi, jeton_pose(reponse)) == 200


async def test_un_echec_de_la_base_apres_auth_rend_quand_meme_204_et_le_cookie(
    moi: Personne,
    fuites: FauxFuites,
    auth: EspionAuth,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def casse(*_: object) -> None:
        raise RuntimeError("base en panne")

    monkeypatch.setattr(moi_api, "confirme_le_mot_de_passe_change", casse)
    reponse = await change(moi)
    assert reponse.status_code == 204  # le mot de passe EST changé
    assert await lit_moi(moi, jeton_pose(reponse)) == 200
    assert "confirmation en base a échoué" in caplog.text
    assert NOUVEAU_NFC not in caplog.text and NOUVEAU_NFD not in caplog.text


async def test_une_erreur_imprevue_a_l_etape_auth_rend_503_avec_le_cookie(
    moi: Personne, fuites: FauxFuites
) -> None:
    class Casse(AuthEnPanne):
        async def change_mot_de_passe(self, identifiant: UUID, mot_de_passe: str) -> None:
            raise RuntimeError("imprévu")

    moi.banc.app.state.auth_admin = Casse()
    reponse = await change(moi)
    assert reponse.status_code == 503
    assert await lit_moi(moi, jeton_pose(reponse)) == 200
