"""Le client d'administration d'Auth, contre un faux transport : aucun réseau, un seul appel observé."""

import asyncio
import json
import logging
import traceback
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from _commun import reglages
from fastapi import FastAPI
from pydantic import SecretStr

from popote_api import errors
from popote_api.infra import auth_admin
from popote_api.infra.auth_admin import (
    AuthAdmin,
    AuthIndisponible,
    CompteDejaExistant,
    MotDePasseRefuseParAuth,
    ReponseAuthInattendue,
    cree_auth_admin,
)
from popote_api.main import create_app

URL = "https://projet.supabase.co"
CLE = "sb_secret_" + "k" * 30
EMAIL = "lea.martin@example.com"
MOT_DE_PASSE = "un mot de passe très long 42"
IDENTIFIANT = UUID("11111111-2222-3333-4444-555555555555")
# Ce qu'Auth recopie dans ses messages : il ne doit sortir nulle part.
MESSAGE_D_AUTH = f"A user with this email address {EMAIL} has already been registered"

Reponse = Callable[[httpx.Request], httpx.Response]


def erreur_d_auth(statut: int, code: str, **autres: Any) -> httpx.Response:
    return httpx.Response(statut, json={"code": statut, "error_code": code, "msg": MESSAGE_D_AUTH} | autres)


def client(reponse: Reponse) -> tuple[AuthAdmin, list[httpx.Request]]:
    """Un client branché sur un faux Auth ; la liste reçoit chaque requête vue."""
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return reponse(requete)

    config = reglages("local", supabase_url=URL, supabase_secret_key=CLE)
    return cree_auth_admin(config, transport=httpx.MockTransport(gestionnaire)), vues


def auth_admin_cle() -> Any:
    return reglages("local", supabase_url=URL, supabase_secret_key=CLE).supabase_secret_key


def utilisateur(identifiant: UUID = IDENTIFIANT) -> httpx.Response:
    return httpx.Response(200, json={"id": str(identifiant), "email": EMAIL})


# --- Succès : les requêtes exactes ---------------------------------------------------------------


async def test_cree_compte_envoie_la_requete_exacte_et_rend_l_identifiant() -> None:
    admin, vues = client(lambda _: utilisateur())

    identifiant = await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    assert identifiant == IDENTIFIANT
    (requete,) = vues
    assert (requete.method, str(requete.url)) == ("POST", f"{URL}/auth/v1/admin/users")
    assert json.loads(requete.content) == {
        "email": EMAIL,
        "password": MOT_DE_PASSE,
        "email_confirm": True,
        "app_metadata": {"cree_par": "popote-api"},
    }


async def test_la_cle_voyage_dans_apikey_seul_et_nulle_part_ailleurs() -> None:
    admin, vues = client(lambda _: utilisateur())

    await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    (requete,) = vues
    assert requete.headers["apikey"] == CLE
    assert "authorization" not in requete.headers
    assert CLE not in str(requete.url) and CLE.encode() not in requete.content
    assert requete.headers["content-type"] == "application/json"
    assert requete.headers["accept-encoding"] == "identity"


async def test_change_mot_de_passe_envoie_put_avec_le_seul_mot_de_passe() -> None:
    admin, vues = client(lambda _: utilisateur())

    assert await admin.change_mot_de_passe(IDENTIFIANT, MOT_DE_PASSE) is None

    (requete,) = vues
    assert (requete.method, str(requete.url)) == ("PUT", f"{URL}/auth/v1/admin/users/{IDENTIFIANT}")
    assert json.loads(requete.content) == {"password": MOT_DE_PASSE}
    assert requete.headers["apikey"] == CLE and "authorization" not in requete.headers


async def test_supprime_compte_envoie_delete_sans_corps() -> None:
    admin, vues = client(lambda _: httpx.Response(200, json={}))

    assert await admin.supprime_compte(IDENTIFIANT) is None

    (requete,) = vues
    assert (requete.method, str(requete.url)) == ("DELETE", f"{URL}/auth/v1/admin/users/{IDENTIFIANT}")
    assert requete.content == b""
    assert requete.headers["apikey"] == CLE and "authorization" not in requete.headers


async def test_un_mot_de_passe_de_72_octets_exacts_part() -> None:
    admin, vues = client(lambda _: utilisateur())

    await admin.cree_compte(EMAIL, "a" * 72)

    assert len(vues) == 1


# --- Erreurs d'Auth traduites ----------------------------------------------------------------------


@pytest.mark.parametrize("code", ["email_exists", "user_already_exists"])
async def test_une_adresse_deja_prise_leve_compte_deja_existant(code: str) -> None:
    admin, vues = client(lambda _: erreur_d_auth(422, code))

    with pytest.raises(CompteDejaExistant):
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    assert len(vues) == 1


async def test_un_mot_de_passe_faible_leve_mot_de_passe_refuse_par_auth_a_la_creation() -> None:
    admin, _ = client(lambda _: erreur_d_auth(422, "weak_password", weak_password={"reasons": ["length"]}))

    with pytest.raises(MotDePasseRefuseParAuth):
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)


async def test_un_mot_de_passe_faible_leve_mot_de_passe_refuse_par_auth_au_changement() -> None:
    admin, _ = client(lambda _: erreur_d_auth(422, "weak_password"))

    with pytest.raises(MotDePasseRefuseParAuth):
        await admin.change_mot_de_passe(IDENTIFIANT, MOT_DE_PASSE)


@pytest.mark.parametrize("statut", [500, 502, 503, 429, 401, 403, 400])
async def test_un_autre_statut_leve_auth_indisponible_sans_reprise(statut: int) -> None:
    admin, vues = client(lambda _: erreur_d_auth(statut, "unexpected_failure"))

    with pytest.raises(ReponseAuthInattendue) as erreur:
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    assert isinstance(erreur.value, AuthIndisponible)
    assert (erreur.value.status, erreur.value.code_auth) == (statut, "unexpected_failure")
    assert len(vues) == 1


@pytest.mark.parametrize(
    "faute",
    [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.ConnectError("c"), httpx.WriteTimeout("t")],
)
async def test_une_panne_de_transport_leve_auth_indisponible_sans_reprise_et_garde_la_cause(
    faute: httpx.HTTPError,
) -> None:
    appels = 0

    def tombe(_: httpx.Request) -> httpx.Response:
        nonlocal appels
        appels += 1
        raise faute

    admin, _ = client(tombe)

    with pytest.raises(AuthIndisponible) as erreur:
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    assert erreur.value.__cause__ is faute
    assert appels == 1


async def test_le_delai_total_borne_un_serveur_qui_goutte_a_goutte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_admin, "DELAI_TOTAL_S", 0.05)

    async def lent(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)  # le faux serveur ne répond pas ; l'échéance du client doit couper
        return utilisateur()

    admin = AuthAdmin(URL, auth_admin_cle(), transport=httpx.MockTransport(lent))

    with pytest.raises(AuthIndisponible) as erreur:
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    assert isinstance(erreur.value.__cause__, TimeoutError)


async def test_les_delais_vraiment_passes_au_client_sont_ceux_du_plan() -> None:
    vus: list[dict[str, float | None]] = []

    def releve(requete: httpx.Request) -> httpx.Response:
        vus.append(requete.extensions["timeout"])
        return utilisateur()

    admin, _ = client(releve)

    await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    assert vus == [{"connect": 3.0, "read": 10.0, "write": 10.0, "pool": 3.0}]


def test_les_delais_sont_ceux_du_plan() -> None:
    assert (auth_admin.DELAI_CONNEXION_S, auth_admin.DELAI_LECTURE_S, auth_admin.DELAI_TOTAL_S) == (
        3.0,
        10.0,
        15.0,
    )


async def test_une_redirection_n_est_pas_suivie_et_la_cle_ne_part_pas_ailleurs() -> None:
    admin, vues = client(lambda _: httpx.Response(302, headers={"Location": "https://autre.example/x"}))

    with pytest.raises(ReponseAuthInattendue):
        await admin.supprime_compte(IDENTIFIANT)

    assert [str(v.url.host) for v in vues] == ["projet.supabase.co"]


# --- supprimer : 404 ---------------------------------------------------------------------------------


async def test_supprimer_un_compte_deja_supprime_est_un_succes() -> None:
    admin, vues = client(lambda _: erreur_d_auth(404, "user_not_found"))

    assert await admin.supprime_compte(IDENTIFIANT) is None
    assert len(vues) == 1


@pytest.mark.parametrize(
    "reponse",
    [
        httpx.Response(404, text="<html>Not Found</html>"),
        httpx.Response(404, json={"error_code": "validation_failed", "msg": "x"}),
        httpx.Response(404, json=["user_not_found"]),
        httpx.Response(401, json={"error_code": "no_authorization"}),
        httpx.Response(403, json={"error_code": "not_admin"}),
        httpx.Response(500, json={"error_code": "unexpected_failure"}),
    ],
)
async def test_supprimer_ne_prend_pour_un_succes_que_le_404_d_un_compte_inconnu(
    reponse: httpx.Response,
) -> None:
    admin, _ = client(lambda _: reponse)

    with pytest.raises(ReponseAuthInattendue):
        await admin.supprime_compte(IDENTIFIANT)


async def test_changer_le_mot_de_passe_d_un_compte_inconnu_est_une_erreur() -> None:
    admin, _ = client(lambda _: erreur_d_auth(404, "user_not_found"))

    with pytest.raises(ReponseAuthInattendue) as erreur:
        await admin.change_mot_de_passe(IDENTIFIANT, MOT_DE_PASSE)

    assert erreur.value.code_auth == "user_not_found"


# --- Réponses mal formées ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reponse",
    [
        httpx.Response(200, text="<html>portail captif</html>"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"id": "99999999-2222-3333-4444-555555555555"}),
        httpx.Response(200, json=["id"]),
        httpx.Response(204),
    ],
    ids=["html", "sans-id", "autre-id", "tableau", "204-vide"],
)
async def test_un_changement_n_est_un_succes_que_si_auth_rend_le_compte_modifie(
    reponse: httpx.Response,
) -> None:
    admin, _ = client(lambda _: reponse)

    with pytest.raises(ReponseAuthInattendue):
        await admin.change_mot_de_passe(IDENTIFIANT, MOT_DE_PASSE)


@pytest.mark.parametrize("reponse", [httpx.Response(200, json={}), httpx.Response(204)], ids=["json", "vide"])
async def test_une_suppression_accepte_un_objet_json_ou_un_corps_vide(reponse: httpx.Response) -> None:
    admin, _ = client(lambda _: reponse)

    assert await admin.supprime_compte(IDENTIFIANT) is None


@pytest.mark.parametrize(
    "reponse",
    [httpx.Response(200, text="<html>portail captif</html>"), httpx.Response(200, json=["ok"])],
    ids=["html", "tableau"],
)
async def test_une_suppression_n_est_pas_un_succes_si_le_corps_n_est_pas_celui_d_auth(
    reponse: httpx.Response,
) -> None:
    admin, _ = client(lambda _: reponse)

    with pytest.raises(ReponseAuthInattendue):
        await admin.supprime_compte(IDENTIFIANT)


@pytest.mark.parametrize("statut", [200, 500])
async def test_un_corps_json_imbrique_a_l_exces_reste_une_erreur_typee(statut: int) -> None:
    profond = httpx.Response(statut, content=b"[" * 20_000 + b"]" * 20_000)
    admin, _ = client(lambda _: profond)

    with pytest.raises(ReponseAuthInattendue):
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)


async def test_une_reponse_plus_grosse_que_la_borne_est_refusee() -> None:
    enorme = httpx.Response(200, content=b'{"id": "' + b"a" * (auth_admin.OCTETS_MAX_REPONSE + 1) + b'"}')
    admin, _ = client(lambda _: enorme)

    with pytest.raises(ReponseAuthInattendue, match="trop grosse"):
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)


async def test_une_adresse_de_base_invalide_leve_auth_indisponible() -> None:
    admin = AuthAdmin("https://p.supabase.co\x00", auth_admin_cle(), transport=httpx.MockTransport(vide))

    with pytest.raises(AuthIndisponible):
        await admin.supprime_compte(IDENTIFIANT)


def vide(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


@pytest.mark.parametrize("cle", ["", "clé", "a b", "sb_secret_AAAA\nBBBB", "a\x00b"])
def test_une_cle_non_transmissible_est_refusee_des_la_construction_sans_etre_recopiee(cle: str) -> None:
    with pytest.raises(ValueError, match="non transmissible") as erreur:
        AuthAdmin(URL, SecretStr(cle))

    assert cle == "" or cle not in tout_ce_qui_sort(erreur.value)


@pytest.mark.parametrize(
    "reponse",
    [
        httpx.Response(200, text="pas du json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"id": "pas-un-uuid"}),
        httpx.Response(200, json={"id": 12}),
        httpx.Response(200, json=["id"]),
        httpx.Response(200, content=b"\xff\xfe"),
    ],
)
async def test_une_creation_dont_la_reponse_est_illisible_leve_une_erreur_typee(
    reponse: httpx.Response,
) -> None:
    admin, _ = client(lambda _: reponse)

    with pytest.raises(ReponseAuthInattendue) as erreur:
        await admin.cree_compte(EMAIL, MOT_DE_PASSE)

    assert erreur.value.status == 200


@pytest.mark.parametrize(
    ("corps", "attendu"),
    [
        (httpx.Response(500, text="<html>boom</html>"), None),
        (httpx.Response(500, json=["error_code"]), None),
        (httpx.Response(500, json={"error_code": 12}), None),
        (httpx.Response(500, json={"error_code": "Mauvais Code\nforgé"}), None),
        (httpx.Response(500, json={"error_code": "x" * 65}), None),
        (httpx.Response(500, json={"error_code": "over_request_rate_limit"}), "over_request_rate_limit"),
    ],
)
async def test_le_code_d_auth_n_est_garde_que_s_il_a_la_forme_d_un_code(
    corps: httpx.Response, attendu: str | None
) -> None:
    admin, _ = client(lambda _: corps)

    with pytest.raises(ReponseAuthInattendue) as erreur:
        await admin.supprime_compte(IDENTIFIANT)

    assert erreur.value.code_auth == attendu


# --- Rien ne fuit --------------------------------------------------------------------------------------


def tout_ce_qui_sort(erreur: BaseException) -> str:
    return "\n".join([str(erreur), repr(erreur), *traceback.format_exception(erreur)])


async def appels_en_echec(admin: AuthAdmin) -> list[BaseException]:
    echecs: list[BaseException] = []
    for operation in (
        lambda: admin.cree_compte(EMAIL, MOT_DE_PASSE),
        lambda: admin.change_mot_de_passe(IDENTIFIANT, MOT_DE_PASSE),
        lambda: admin.supprime_compte(IDENTIFIANT),
    ):
        with pytest.raises(auth_admin.AuthAdminError) as erreur:
            await operation()
        echecs.append(erreur.value)
    return echecs


@pytest.mark.parametrize(
    "reponse",
    [
        lambda: erreur_d_auth(422, "email_exists"),
        lambda: erreur_d_auth(422, "weak_password"),
        lambda: erreur_d_auth(500, "unexpected_failure"),
        lambda: erreur_d_auth(401, "no_authorization"),
    ],
)
async def test_ni_le_message_d_auth_ni_l_adresse_ni_le_mot_de_passe_ni_la_cle_ne_sortent(
    reponse: Callable[[], httpx.Response], caplog: pytest.LogCaptureFixture
) -> None:
    admin, _ = client(lambda _: reponse())

    with caplog.at_level(logging.DEBUG):
        echecs = await appels_en_echec(admin)

    sortie = "\n".join(tout_ce_qui_sort(e) for e in echecs) + caplog.text
    for secret in (EMAIL, "lea.martin", MESSAGE_D_AUTH, MOT_DE_PASSE, CLE):
        assert secret not in sortie


async def test_la_cle_n_est_ni_dans_le_repr_du_client_ni_dans_celui_des_reglages() -> None:
    config = reglages("local", supabase_url=URL, supabase_secret_key=CLE)
    admin = cree_auth_admin(config)

    for texte in (repr(admin), repr(vars(admin)), repr(config), str(config), config.model_dump_json()):
        assert CLE not in texte
    assert "k" * 30 not in repr(config.model_dump())


async def test_la_cle_n_est_pas_dans_la_trace_d_une_panne_de_transport() -> None:
    def tombe(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé")

    admin, _ = client(tombe)

    with pytest.raises(AuthIndisponible) as erreur:
        await admin.supprime_compte(IDENTIFIANT)

    assert CLE not in tout_ce_qui_sort(erreur.value)


# --- Avant tout appel ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifiant",
    ["abc", "../../x", f"{IDENTIFIANT}/../..", f"{IDENTIFIANT}?a=b", str(IDENTIFIANT), 42, None],
)
async def test_un_identifiant_qui_n_est_pas_un_uuid_n_entre_pas_dans_l_adresse(identifiant: Any) -> None:
    admin, vues = client(lambda _: utilisateur())

    with pytest.raises(TypeError):
        await admin.supprime_compte(identifiant)
    with pytest.raises(TypeError):
        await admin.change_mot_de_passe(identifiant, MOT_DE_PASSE)

    assert vues == []


@pytest.mark.parametrize(
    "mot_de_passe",
    ["a" * 73, "é" * 37, "abc\x00def", "abc\ud800def"],
    ids=["73-octets", "37-deux-octets", "nul", "substitut-isole"],
)
async def test_un_mot_de_passe_non_transmissible_est_refuse_sans_appel(mot_de_passe: str) -> None:
    admin, vues = client(lambda _: utilisateur())

    with pytest.raises(MotDePasseRefuseParAuth) as erreur:
        await admin.cree_compte(EMAIL, mot_de_passe)
    with pytest.raises(MotDePasseRefuseParAuth):
        await admin.change_mot_de_passe(IDENTIFIANT, mot_de_passe)

    assert vues == []
    assert mot_de_passe not in tout_ce_qui_sort(erreur.value)


@pytest.mark.parametrize("email", ["a\ud800@example.com", "a\x00@example.com"])
async def test_une_adresse_non_transmissible_est_refusee_sans_appel_ni_recopie(email: str) -> None:
    admin, vues = client(lambda _: utilisateur())

    with pytest.raises(ValueError, match="non transmissible") as erreur:
        await admin.cree_compte(email, MOT_DE_PASSE)

    assert vues == []
    assert email not in tout_ce_qui_sort(erreur.value)


# --- Non configuré -----------------------------------------------------------------------------------------


async def test_non_configure_chaque_operation_leve_auth_indisponible_sans_rien_envoyer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def ne_doit_pas_etre_appele(_: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun envoi attendu")

    with caplog.at_level(logging.WARNING):
        admin = cree_auth_admin(reglages("local"), transport=httpx.MockTransport(ne_doit_pas_etre_appele))

    for operation in (
        lambda: admin.cree_compte(EMAIL, MOT_DE_PASSE),
        lambda: admin.change_mot_de_passe(IDENTIFIANT, MOT_DE_PASSE),
        lambda: admin.supprime_compte(IDENTIFIANT),
    ):
        with pytest.raises(AuthIndisponible, match="pas configurée"):
            await operation()
    assert "Administration d'Auth non configurée" in caplog.text


def test_l_application_demarre_sans_la_configuration_d_auth_et_l_avertit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        app = create_app(reglages("local"))

    assert isinstance(app.state.auth_admin, AuthAdmin)
    assert caplog.text.count("Administration d'Auth non configurée") == 1


def test_l_application_configuree_n_avertit_pas(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        create_app(reglages("local", supabase_url=URL, supabase_secret_key=CLE))

    assert "non configurée" not in caplog.text


# --- À la frontière HTTP ----------------------------------------------------------------------------------


def app_qui_leve(erreur: Exception) -> FastAPI:
    app = FastAPI()
    errors.installe(app)

    @app.get("/essai")
    async def essai() -> None:
        raise erreur

    return app


async def appelle(app: FastAPI) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        return await c.get("/essai")


async def test_auth_indisponible_devient_un_503_sans_detail_d_auth(caplog: pytest.LogCaptureFixture) -> None:
    faute = ReponseAuthInattendue(500, "unexpected_failure", "Auth a refusé l'opération")

    with caplog.at_level(logging.WARNING):
        r = await appelle(app_qui_leve(faute))

    assert r.status_code == 503
    assert r.json()["code"] == "auth_indisponible"
    assert r.headers["cache-control"] == "no-store"
    assert "500" not in r.text and "unexpected_failure" not in r.text
    assert "HTTP 500, code=unexpected_failure" in caplog.text


async def test_le_503_journalise_la_cause_de_la_panne(caplog: pytest.LogCaptureFixture) -> None:
    cause = httpx.ConnectError("refusé")
    faute = AuthIndisponible("Auth est injoignable ou trop lent.")
    faute.__cause__ = cause

    with caplog.at_level(logging.WARNING):
        await appelle(app_qui_leve(faute))

    assert any(r.exc_info is not None for r in caplog.records)
    assert "ConnectError" in caplog.text


async def test_compte_deja_existant_devient_un_409_compte_existant() -> None:
    r = await appelle(app_qui_leve(CompteDejaExistant("x")))

    assert r.status_code == 409
    assert r.json()["code"] == "compte_existant"
