"""Les routes `/internal/*` : signées, ou `404` (spec § 3.10). Aucune route interne réelle n'existe encore :
les tests montent les leurs sur un routeur de `nouveau_routeur()`."""

import json
import logging
from collections.abc import Iterator, Sequence

import pytest
from _commun import RELAIS, Retour, appeler, reglages
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from pydantic import BaseModel, ConfigDict
from starlette.routing import BaseRoute
from starlette.types import Message, Receive, Scope, Send

from popote_api import relais
from popote_api.api import internes
from popote_api.main import create_app
from popote_api.security import signature

SECRET = "i" * 32
PRECEDENT = "p" * 32
T0 = 1_700_000_000
CORPS = b'{"n":1}'


class Charge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int


def app_interne(env: str = "essai", **autres: str) -> FastAPI:
    """L'application, l'horloge figée à `T0`, et trois routes internes de test (écho, lecture, corps typé)."""
    app = create_app(reglages(env, internal_secret=SECRET, **autres))
    app.state.horloge = lambda: float(T0)
    routeur = internes.nouveau_routeur()

    @routeur.post("/echo")
    async def echo(request: Request) -> dict[str, str]:
        return {"corps": (await request.body()).decode()}

    @routeur.get("/lecture")
    async def lecture() -> dict[str, bool]:
        return {"ok": True}

    @routeur.post("/charge")
    async def charge(donnees: Charge) -> dict[str, int]:
        return {"n": donnees.n}

    app.include_router(routeur)
    return app


def signee(
    methode: str, chemin: str, corps: bytes = b"", *, secret: str = SECRET, instant: int = T0
) -> dict[str, str]:
    brut = chemin.encode()
    return {signature.EN_TETE: signature.signe(secret.encode(), methode, brut, corps, instant)}


async def appel(
    app: FastAPI,
    methode: str,
    chemin: str,
    corps: bytes = b"",
    en_tetes: dict[str, str] | None = None,
    requete: str = "",
) -> Retour:
    """Appelle la route signée par défaut ; `en_tetes` le remplace en entier."""
    envoyes = signee(methode, chemin, corps) if en_tetes is None else en_tetes
    if corps:
        envoyes = {**envoyes, "Content-Length": str(len(corps))}
    return await appeler(app, methode, chemin, envoyes, requete, corps)


def introuvable(retour: Retour) -> bool:
    return (
        retour.status == 404
        and retour.en_tetes["content-type"].startswith("application/problem+json")
        and json.loads(retour.corps)["code"] == "introuvable"
    )


# --- la signature juste passe -----------------------------------------------------------------------------


async def test_une_signature_juste_passe_et_le_corps_arrive_a_la_route() -> None:
    retour = await appel(app_interne(), "POST", "/internal/echo", CORPS)
    assert retour.status == 200
    assert json.loads(retour.corps) == {"corps": CORPS.decode()}


async def test_une_signature_juste_passe_en_get_sans_corps() -> None:
    assert (await appel(app_interne(), "GET", "/internal/lecture")).status == 200


async def test_une_signature_juste_passe_en_local_aussi() -> None:
    assert (await appel(app_interne("local"), "GET", "/internal/lecture")).status == 200


async def test_la_signature_porte_sur_les_octets_bruts_du_chemin() -> None:
    app = app_interne()
    chemin_brut = "/internal/ec%68o"  # `%68` = `h` : le chemin décodé est `/internal/echo`
    juste = await appeler(app, "POST", chemin_brut, signee("POST", chemin_brut))
    sur_le_chemin_decode = await appeler(app, "POST", chemin_brut, signee("POST", "/internal/echo"))
    assert juste.status == 200
    assert introuvable(sur_le_chemin_decode)


# --- tout ce qui change la requête signée -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("methode", "chemin", "corps"),
    [
        ("POST", "/internal/echo", b'{"n":2}'),  # corps changé
        ("POST", "/internal/echo", b""),  # corps retiré
        ("GET", "/internal/echo", CORPS),  # méthode changée (la route POST répondrait 405 si elle était lue)
        ("POST", "/internal/lecture", CORPS),  # chemin changé, vers une route qui existe
    ],
)
async def test_une_requete_differente_de_celle_signee_rend_404(
    methode: str, chemin: str, corps: bytes
) -> None:
    en_tetes = signee("POST", "/internal/echo", CORPS)
    retour = await appel(app_interne(), methode, chemin, corps, en_tetes)
    assert introuvable(retour)


async def test_un_horodatage_change_sans_refaire_la_signature_rend_404() -> None:
    en_tete = signee("POST", "/internal/echo", CORPS)[signature.EN_TETE]
    _, v1 = en_tete.split(",")
    truque = {signature.EN_TETE: f"t={T0 + 1},{v1}"}
    assert introuvable(await appel(app_interne(), "POST", "/internal/echo", CORPS, truque))


@pytest.mark.parametrize("ecart", [-301, 301, -3600, 10**9])
async def test_un_horodatage_hors_de_la_fenetre_rend_404(ecart: int) -> None:
    en_tetes = signee("GET", "/internal/lecture", instant=T0 + ecart)
    assert introuvable(await appel(app_interne(), "GET", "/internal/lecture", en_tetes=en_tetes))


@pytest.mark.parametrize("ecart", [-300, 0, 300])
async def test_un_horodatage_au_bord_de_la_fenetre_passe(ecart: int) -> None:
    en_tetes = signee("GET", "/internal/lecture", instant=T0 + ecart)
    assert (await appel(app_interne(), "GET", "/internal/lecture", en_tetes=en_tetes)).status == 200


async def test_une_chaine_de_requete_est_refusee_meme_signee() -> None:
    app = app_interne()
    for requete in ("a=1", "a"):
        retour = await appel(app, "GET", "/internal/lecture", requete=requete)
        assert introuvable(retour)


# --- ce qui n'est pas une signature ---------------------------------------------------------------------


async def test_sans_en_tete_de_signature_rend_404() -> None:
    assert introuvable(await appel(app_interne(), "GET", "/internal/lecture", en_tetes={}))


async def test_l_en_tete_du_relais_seul_ne_suffit_pas() -> None:
    assert introuvable(await appel(app_interne(), "GET", "/internal/lecture", en_tetes=RELAIS))


async def test_un_cookie_ne_suffit_pas_et_ne_remplace_pas_la_signature() -> None:
    en_tetes = {**RELAIS, "Cookie": "sb-session=abc; __Host-popote_session=def"}
    assert introuvable(await appel(app_interne(), "GET", "/internal/lecture", en_tetes=en_tetes))


async def test_un_bearer_ne_suffit_pas() -> None:
    en_tetes = {"Authorization": "Bearer abc.def.ghi"}
    assert introuvable(await appel(app_interne(), "GET", "/internal/lecture", en_tetes=en_tetes))


async def test_un_secret_inconnu_rend_404() -> None:
    en_tetes = signee("GET", "/internal/lecture", secret="x" * 32)
    assert introuvable(await appel(app_interne(), "GET", "/internal/lecture", en_tetes=en_tetes))


async def test_deux_en_tetes_de_signature_sont_refuses() -> None:
    juste = signee("GET", "/internal/lecture")[signature.EN_TETE]
    en_tetes = [(signature.EN_TETE, juste), (signature.EN_TETE, juste)]
    retour = await appeler(app_interne(), "GET", "/internal/lecture", en_tetes)
    assert introuvable(retour)


async def test_un_corps_declare_trop_gros_est_refuse_sans_etre_lu() -> None:
    en_tetes = {**signee("POST", "/internal/echo"), "Content-Length": str(signature.CORPS_MAX_OCTETS + 1)}
    assert introuvable(await appeler(app_interne(), "POST", "/internal/echo", en_tetes))


@pytest.mark.parametrize("longueur", ["abc", "-1", "9" * 5000, "\u0661", ""])
async def test_une_longueur_declaree_mal_formee_est_refusee_sans_planter(longueur: str) -> None:
    en_tetes = {**signee("POST", "/internal/echo"), "Content-Length": longueur}
    assert introuvable(await appeler(app_interne(), "POST", "/internal/echo", en_tetes))


async def test_sans_chemin_brut_la_requete_est_refusee() -> None:
    app = app_interne()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/internal/lecture",
        "query_string": b"",
        "headers": [
            (
                signature.EN_TETE.lower().encode(),
                signee("GET", "/internal/lecture")[signature.EN_TETE].encode(),
            )
        ],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
    }
    envoyes: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        envoyes.append(message)

    await app(scope, receive, send)  # type: ignore[arg-type]
    assert envoyes[0]["status"] == 404


# --- la rotation : le secret précédent -----------------------------------------------------------------


async def test_le_secret_precedent_est_accepte_pendant_la_rotation() -> None:
    app = app_interne(internal_secret_precedent=PRECEDENT)
    ancienne = signee("GET", "/internal/lecture", secret=PRECEDENT)
    assert (await appel(app, "GET", "/internal/lecture", en_tetes=ancienne)).status == 200


async def test_le_secret_precedent_est_refuse_une_fois_retire() -> None:
    ancienne = signee("GET", "/internal/lecture", secret=PRECEDENT)
    assert introuvable(await appel(app_interne(), "GET", "/internal/lecture", en_tetes=ancienne))


async def test_le_secret_courant_reste_accepte_pendant_la_rotation() -> None:
    app = app_interne(internal_secret_precedent=PRECEDENT)
    assert (await appel(app, "GET", "/internal/lecture")).status == 200


@pytest.mark.parametrize("ordre", [("faux", "juste"), ("juste", "faux")])
async def test_plusieurs_v1_sont_admis_si_l_un_est_bon(ordre: tuple[str, str]) -> None:
    juste = signee("GET", "/internal/lecture")[signature.EN_TETE].split(",v1=")[1]
    faux = "0" * 64
    candidats = {"faux": faux, "juste": juste}
    valeur = f"t={T0}," + ",".join(f"v1={candidats[o]}" for o in ordre)
    retour = await appel(app_interne(), "GET", "/internal/lecture", en_tetes={signature.EN_TETE: valeur})
    assert retour.status == 200


# --- un en-tête mal formé ------------------------------------------------------------------------------


def _v1() -> str:
    return signee("GET", "/internal/lecture")[signature.EN_TETE].split(",v1=")[1]


@pytest.mark.parametrize(
    "valeur",
    [
        "",
        "t=,v1=" + "0" * 64,
        f"t={T0}",
        f"t={T0},v1=",
        f"t={T0},v1={'0' * 63}",
        f"t={T0},v1={'0' * 65}",
        f"t={T0},v1={'G' * 64}",
        f"t={T0},v1={'A' * 64}",  # majuscules : nous signons en minuscules
        f"t=-{T0},v1={'0' * 64}",
        f"t=+{T0},v1={'0' * 64}",
        f"t={T0}.0,v1={'0' * 64}",
        f"t={'\u0661' * 10},v1={'0' * 64}",  # chiffres arabes-indiens
        f"t={T0},t={T0},v1={'0' * 64}",
        f"t={T0},v1={'0' * 64},autre=1",
        f"t={T0},v1={'0' * 64},v1",
        f"t={T0}, v1={'0' * 64}",
        "t=" + "9" * 13 + ",v1=" + "0" * 64,
        f"t={T0}," + ",".join(["v1=" + "0" * 64] * (signature.NOMBRE_MAX_DE_V1 + 1)),
        f"t={T0},v1={'0' * 64}," + "v2=" + "x" * 600,
    ],
)
async def test_un_en_tete_mal_forme_rend_404(valeur: str) -> None:
    retour = await appel(app_interne(), "GET", "/internal/lecture", en_tetes={signature.EN_TETE: valeur})
    assert introuvable(retour)


async def test_une_version_inconnue_est_ignoree_si_v1_est_bon() -> None:
    valeur = f"t={T0},v2=abc,v1={_v1()}"
    retour = await appel(app_interne(), "GET", "/internal/lecture", en_tetes={signature.EN_TETE: valeur})
    assert retour.status == 200


# --- fermé par défaut ------------------------------------------------------------------------------------


async def test_sans_secret_toute_route_interne_rend_404_meme_bien_signee(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = app_interne()
    app.state.settings = reglages("essai")  # sans `internal_secret`
    with caplog.at_level(logging.WARNING, logger="popote_api.api.internes"):
        retour = await appel(app, "GET", "/internal/lecture")
    assert introuvable(retour)
    assert "sans_cle" in caplog.text


async def test_sans_secret_le_demarrage_avertit(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(reglages("essai"))
    with caplog.at_level(logging.WARNING, logger="popote_api.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "POPOTE_INTERNAL_SECRET" in caplog.text


async def test_avec_un_secret_le_demarrage_n_avertit_pas_du_secret(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(reglages("essai", internal_secret=SECRET))
    with caplog.at_level(logging.WARNING, logger="popote_api.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "POPOTE_INTERNAL_SECRET" not in caplog.text


async def test_le_refus_est_journalise_par_sa_raison_jamais_par_une_valeur(
    caplog: pytest.LogCaptureFixture,
) -> None:
    faux = signee("GET", "/internal/lecture", secret="x" * 32)
    with caplog.at_level(logging.WARNING, logger="popote_api.api.internes"):
        await appel(app_interne(), "GET", "/internal/lecture", en_tetes=faux)
    assert "signature_fausse" in caplog.text
    assert faux[signature.EN_TETE] not in caplog.text
    assert "/internal/lecture" not in caplog.text
    assert SECRET not in caplog.text


# --- le refus ne révèle pas la route ---------------------------------------------------------------------


async def test_une_mauvaise_methode_sans_signature_rend_404_pas_405() -> None:
    assert introuvable(await appel(app_interne(), "DELETE", "/internal/echo", en_tetes={}))


async def test_un_corps_mal_forme_sans_signature_rend_404_pas_422() -> None:
    en_tetes = {
        "Content-Type": "application/json"
    }  # sans lui, FastAPI ne lit pas le corps avant la dépendance
    retour = await appel(app_interne(), "POST", "/internal/charge", b"{pas du json", en_tetes=en_tetes)
    assert introuvable(retour)


async def test_un_json_invalide_rend_404_meme_signe() -> None:
    # FastAPI lit le JSON avant d'appeler les dépendances : la signature n'est pas encore vérifiée, et la
    # route ne se révèle pas. Contrepartie acceptée : l'appelant signé ne voit pas de `422` pour ce cas.
    corps = b"{pas du json"
    en_tetes = {**signee("POST", "/internal/charge", corps), "Content-Type": "application/json"}
    assert introuvable(await appel(app_interne(), "POST", "/internal/charge", corps, en_tetes))


async def test_un_corps_de_mauvais_type_signe_rend_422() -> None:
    retour = await appel(app_interne(), "POST", "/internal/charge", b'{"n":"x"}')
    assert retour.status == 422


async def test_une_mauvaise_methode_signee_rend_404() -> None:
    en_tetes = signee("DELETE", "/internal/echo")
    assert introuvable(await appel(app_interne(), "DELETE", "/internal/echo", en_tetes=en_tetes))


async def test_une_route_inconnue_sous_internal_rend_404_signee_ou_non() -> None:
    app = app_interne()
    assert introuvable(await appel(app, "GET", "/internal/nexiste-pas"))
    assert introuvable(await appel(app, "GET", "/internal/nexiste-pas", en_tetes={}))


# --- le relais : `/internal/` seul est exempté --------------------------------------------------------------


def test_les_exemptions_du_relais_sont_le_seul_prefixe_interne() -> None:
    assert relais.EXEMPTIONS == ("/internal/",)


def app_avec_pieges() -> FastAPI:
    """Des routes `/internal` et `/internalx` ouvertes : `200` si la garde les laissait passer."""
    app = app_interne()

    @app.get("/internalx")
    async def piege_x() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/internalx/y")
    async def piege_xy() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/internal")
    async def piege_nu() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.mark.parametrize(
    "chemin", ["/internalx", "/internalx/y", "/internal", "/INTERNAL/lecture", "//internal/lecture"]
)
async def test_ce_qui_n_est_pas_le_prefixe_interne_exige_le_relais(chemin: str) -> None:
    app = app_avec_pieges()
    sans_relais = await appeler(app, "GET", chemin)
    avec_relais = await appeler(app, "GET", chemin, RELAIS)
    assert sans_relais.status == 404
    assert json.loads(sans_relais.corps)["code"] == "introuvable"
    assert avec_relais.status in (200, 404)
    if chemin in ("/internalx", "/internalx/y", "/internal"):
        assert avec_relais.status == 200  # le piège existe : seul le relais manquant l'a fermé


async def test_une_route_interne_signee_passe_sans_le_relais() -> None:
    assert (await appel(app_avec_pieges(), "GET", "/internal/lecture")).status == 200


# --- aucune route interne n'échappe à la signature ------------------------------------------------------


def _appels(dependant: Dependant) -> Iterator[object]:
    yield dependant.call
    for sous in dependant.dependencies:
        yield from _appels(sous)


def routes_effectives(
    routes: Sequence[BaseRoute], prefixe: str = "", appels: tuple[object, ...] = ()
) -> Iterator[tuple[str, BaseRoute, tuple[object, ...]]]:
    """Les routes de l'application, routeurs inclus compris, avec leur adresse complète et les dépendances
    de leur inclusion. FastAPI 0.162 range un routeur inclus dans un `_IncludedRouter`, qui n'a ni `path` ni
    `dependant` : sans cette descente, une route montée par `include_router` serait invisible."""
    for route in routes:
        if hasattr(route, "original_router"):
            inclusion = route.include_context
            yield from routes_effectives(
                route.original_router.routes,
                prefixe + inclusion.prefix,
                appels + tuple(d.dependency for d in inclusion.dependencies),
            )
        else:
            yield prefixe + getattr(route, "path", ""), route, appels


def routes_internes_sans_signature(app: FastAPI) -> list[str]:
    """Les routes dont l'adresse peut tomber sous `/internal` et qui n'ont pas `exige_la_signature`."""
    fautes = []
    for chemin, route, appels_de_l_inclusion in routes_effectives(app.routes):
        regex = getattr(route, "path_regex", None)
        if not (chemin.startswith("/internal") or (regex and regex.match("/internal/sonde"))):
            continue
        dependant = getattr(route, "dependant", None)  # `Mount` et routes brutes n'en ont pas
        appels = {*appels_de_l_inclusion, *(_appels(dependant) if dependant else ())}
        if dependant is None or internes.exige_la_signature not in appels:
            fautes.append(chemin)
    return fautes


def test_l_enumeration_voit_les_routes_internes_de_l_application() -> None:
    chemins = [c for c, _, _ in routes_effectives(app_interne().routes) if c.startswith("/internal/")]
    assert sorted(chemins) == ["/internal/charge", "/internal/echo", "/internal/lecture"]


def test_toute_route_interne_de_l_application_exige_la_signature() -> None:
    assert routes_internes_sans_signature(app_interne()) == []


def test_l_enumeration_attrape_une_route_interne_sans_signature() -> None:
    app = app_interne()

    @app.get("/internal/oubli")
    async def oubli() -> dict[str, bool]:
        return {"ok": True}

    app.mount("/internal/statique", FastAPI())
    app.add_api_route("/{reste:path}", oubli)  # une route qui capte aussi `/internal/...`
    assert routes_internes_sans_signature(app) == ["/internal/oubli", "/internal/statique", "/{reste:path}"]


def test_l_enumeration_attrape_un_routeur_ordinaire_inclus_sous_internal() -> None:
    app = app_interne()
    ordinaire = APIRouter(prefix="/internal")

    @ordinaire.get("/oubli")
    async def oubli() -> dict[str, bool]:
        return {"ok": True}

    sans_prefixe = APIRouter()

    @sans_prefixe.get("/autre")
    async def autre() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(ordinaire)
    app.include_router(sans_prefixe, prefix="/internal")
    assert routes_internes_sans_signature(app) == ["/internal/oubli", "/internal/autre"]


def test_l_enumeration_accepte_la_dependance_posee_a_l_inclusion() -> None:
    app = app_interne()
    sans_dependance = APIRouter()

    @sans_dependance.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(
        sans_dependance, prefix="/internal/via", dependencies=[Depends(internes.exige_la_signature)]
    )
    assert routes_internes_sans_signature(app) == []


async def test_aucune_route_interne_ne_repond_sans_signature() -> None:
    app = app_interne()
    vues = 0
    for chemin, route, _ in routes_effectives(app.routes):
        if not chemin.startswith("/internal/"):
            continue
        for methode in sorted(getattr(route, "methods", None) or []):
            assert introuvable(await appel(app, methode, chemin, en_tetes={})), (methode, chemin)
            vues += 1
    assert vues == 3


# --- le corps est borné avant toute lecture ---------------------------------------------------------------


def _morceau(octets: int, *, suite: bool = True) -> dict[str, object]:
    return {"type": "http.request", "body": b"x" * octets, "more_body": suite}


async def test_un_corps_par_morceaux_qui_depasse_la_borne_est_coupe_sans_lire_le_reste() -> None:
    en_tetes = signee("POST", "/internal/echo")
    quart = signature.CORPS_MAX_OCTETS // 4
    morceaux = [_morceau(quart) for _ in range(5)] + [_morceau(1, suite=False)]
    retour = await appeler(app_interne(), "POST", "/internal/echo", en_tetes, receptions=morceaux)
    assert introuvable(retour)
    assert len(morceaux) == 1  # coupé au cinquième morceau : le dernier n'a jamais été lu


async def test_un_corps_par_morceaux_dans_la_borne_passe() -> None:
    corps = b"x" * 1000
    en_tetes = signee("POST", "/internal/echo", corps)
    recus = [_morceau(400), _morceau(600, suite=False)]
    retour = await appeler(app_interne(), "POST", "/internal/echo", en_tetes, receptions=recus)
    assert retour.status == 200


async def test_un_corps_declare_trop_gros_sur_une_route_a_corps_typé_est_refuse_sans_etre_lu() -> None:
    # FastAPI lit le corps de cette route avant ses dépendances : seule la borne d'amont l'arrête.
    en_tetes = {"Content-Type": "application/json", "Content-Length": str(signature.CORPS_MAX_OCTETS + 1)}
    retour = await appeler(app_interne(), "POST", "/internal/charge", en_tetes, receptions=[])
    assert introuvable(retour)


async def test_un_corps_par_morceaux_trop_gros_sur_une_route_a_corps_type_rend_404() -> None:
    en_tetes = {"Content-Type": "application/json"}
    recus = [_morceau(signature.CORPS_MAX_OCTETS), _morceau(1)]
    retour = await appeler(app_interne(), "POST", "/internal/charge", en_tetes, receptions=recus)
    assert introuvable(retour)


async def test_la_borne_ne_s_applique_pas_hors_de_l_interne() -> None:
    app = app_interne()

    @app.post("/api/_test/gros")
    async def gros(request: Request) -> dict[str, int]:
        return {"octets": len(await request.body())}

    corps = [_morceau(signature.CORPS_MAX_OCTETS), _morceau(10, suite=False)]
    retour = await appeler(app, "POST", "/api/_test/gros", RELAIS, receptions=corps)
    assert json.loads(retour.corps) == {"octets": signature.CORPS_MAX_OCTETS + 10}


async def test_une_deconnexion_pendant_la_lecture_du_corps_rend_404_sans_erreur(
    caplog: pytest.LogCaptureFixture,
) -> None:
    en_tetes = {**signee("POST", "/internal/echo"), "Content-Length": "10"}
    with caplog.at_level(logging.INFO):
        retour = await appeler(app_interne(), "POST", "/internal/echo", en_tetes, receptions=[])
    assert introuvable(retour)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert "corps_incomplet" in caplog.text


# --- le niveau du journal -------------------------------------------------------------------------------


async def test_un_en_tete_absent_est_journalise_en_info_une_signature_fausse_en_avertissement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = app_interne()
    with caplog.at_level(logging.INFO, logger="popote_api.api.internes"):
        await appel(app, "GET", "/internal/lecture", en_tetes={})
        await appel(
            app, "GET", "/internal/lecture", en_tetes=signee("GET", "/internal/lecture", secret="x" * 32)
        )
    niveaux = {r.getMessage().split(": ")[1]: r.levelno for r in caplog.records}
    assert niveaux == {"en_tete_absent.": logging.INFO, "signature_fausse.": logging.WARNING}


def test_les_routes_internes_sont_hors_du_contrat() -> None:
    chemins = app_interne("local").openapi()["paths"]
    assert [c for c in chemins if c.startswith("/internal")] == []


async def test_une_reponse_deja_commencee_n_en_recoit_pas_un_404_de_plus() -> None:
    async def route_qui_lit_apres_avoir_repondu(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while True:
            await receive()

    scope = {"type": "http", "path": "/internal/x", "headers": [], "query_string": b""}
    envoyes: list[Message] = []

    async def receive() -> Message:
        return _morceau(signature.CORPS_MAX_OCTETS + 1)  # type: ignore[return-value]

    async def send(message: Message) -> None:
        envoyes.append(message)

    with pytest.raises(internes.CorpsTropGros):
        await internes.CorpsBorne(route_qui_lit_apres_avoir_repondu)(scope, receive, send)
    assert [m["type"] for m in envoyes] == ["http.response.start"]
