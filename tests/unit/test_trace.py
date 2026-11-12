import json
import re

import pytest
from _commun import appeler, reglages
from fastapi import FastAPI, Request

from popote_api import trace
from popote_api.main import create_app

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_ID = "00f067aa0ba902b7"
VALIDE = f"00-{TRACE_ID}-{PARENT_ID}-01"
HEX_32 = re.compile(r"[0-9a-f]{32}")
HEX_16 = re.compile(r"[0-9a-f]{16}")


def app_de_test() -> FastAPI:
    app = create_app(reglages("local"))

    @app.get("/api/_test/trace")
    async def lire(request: Request) -> dict[str, str | None]:
        return {
            "state_trace": request.state.trace_id,
            "state_span": request.state.span_id,
            "ctx_trace": trace.trace_id_courant.get(),
            "ctx_span": trace.span_id_courant.get(),
        }

    return app


async def vu_par_la_route(traceparent: str | None) -> dict[str, str | None]:
    en_tetes = {} if traceparent is None else {"traceparent": traceparent}
    retour = await appeler(app_de_test(), "GET", "/api/_test/trace", en_tetes)
    assert retour.status == 200
    corps: dict[str, str | None] = json.loads(retour.corps)
    assert corps["state_trace"] == corps["ctx_trace"]
    assert corps["state_span"] == corps["ctx_span"]
    return corps


async def test_un_traceparent_valide_est_repris_avec_un_nouveau_span() -> None:
    vu = await vu_par_la_route(VALIDE)
    assert vu["state_trace"] == TRACE_ID
    assert vu["state_span"] != PARENT_ID
    assert HEX_16.fullmatch(vu["state_span"] or "")


async def test_sans_traceparent_une_nouvelle_trace_commence() -> None:
    vu = await vu_par_la_route(None)
    assert HEX_32.fullmatch(vu["state_trace"] or "")
    assert HEX_16.fullmatch(vu["state_span"] or "")


async def test_deux_requetes_sans_traceparent_ont_des_traces_et_des_spans_differents() -> None:
    premiere, seconde = await vu_par_la_route(None), await vu_par_la_route(None)
    assert premiere["state_trace"] != seconde["state_trace"]
    assert premiere["state_span"] != seconde["state_span"]


async def test_deux_requetes_de_la_meme_trace_ont_chacune_leur_span() -> None:
    premiere, seconde = await vu_par_la_route(VALIDE), await vu_par_la_route(VALIDE)
    assert premiere["state_trace"] == seconde["state_trace"] == TRACE_ID
    assert premiere["state_span"] != seconde["state_span"]


# Version 00 : exactement 55 caractères. Version inconnue (01 à fe) : au moins 55, et ce qui suit les
# drapeaux est une fin de chaîne ou un tiret (W3C Trace Context niveau 1, § 3.2.4).
VALIDES = [
    pytest.param(VALIDE, id="version-00"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-00", id="drapeaux-a-zero"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-ff", id="drapeaux-inconnus-permis"),
    pytest.param(f"01-{TRACE_ID}-{PARENT_ID}-01", id="version-future"),
    pytest.param(f"fe-{TRACE_ID}-{PARENT_ID}-01", id="derniere-version-future"),
    pytest.param(f"01-{TRACE_ID}-{PARENT_ID}-01-champ-ajoute", id="version-future-plus-longue"),
    pytest.param(f"01-{TRACE_ID}-{PARENT_ID}-01-", id="version-future-tiret-final"),
]


@pytest.mark.parametrize("entete", VALIDES)
async def test_les_formes_valides_sont_reprises(entete: str) -> None:
    assert (await vu_par_la_route(entete))["state_trace"] == TRACE_ID


INVALIDES = [
    pytest.param("", id="vide"),
    pytest.param(VALIDE.upper(), id="tout-en-majuscules"),
    pytest.param(f"00-{TRACE_ID.upper()}-{PARENT_ID}-01", id="trace-id-en-majuscules"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID.upper()}-01", id="parent-id-en-majuscules"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-0A", id="drapeaux-en-majuscules"),
    pytest.param(f"0A-{TRACE_ID}-{PARENT_ID}-01", id="version-en-majuscules"),
    pytest.param(f"00-{TRACE_ID[:-1]}-{PARENT_ID}-01", id="trace-id-trop-court"),
    pytest.param(f"00-{TRACE_ID}0-{PARENT_ID}-01", id="trace-id-trop-long"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID[:-1]}-01", id="parent-id-trop-court"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}0-01", id="parent-id-trop-long"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-1", id="drapeaux-trop-courts"),
    pytest.param(f"00-{'0' * 32}-{PARENT_ID}-01", id="trace-id-tout-zero"),
    pytest.param(f"00-{TRACE_ID}-{'0' * 16}-01", id="parent-id-tout-zero"),
    pytest.param(f"ff-{TRACE_ID}-{PARENT_ID}-01", id="version-ff"),
    pytest.param(f"0g-{TRACE_ID}-{PARENT_ID}-01", id="version-pas-hexadecimale"),
    pytest.param(f"00-{'g' * 32}-{PARENT_ID}-01", id="trace-id-pas-hexadecimal"),
    pytest.param(f"00-{TRACE_ID}-{'g' * 16}-01", id="parent-id-pas-hexadecimal"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-0g", id="drapeaux-pas-hexadecimaux"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-01-champ-ajoute", id="version-00-plus-longue"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-01-", id="version-00-tiret-final"),
    pytest.param(f"01-{TRACE_ID}-{PARENT_ID}-01champ", id="version-future-sans-tiret-apres-les-drapeaux"),
    pytest.param(f"01-{TRACE_ID}-{PARENT_ID}-0", id="version-future-trop-courte"),
    pytest.param(f"01-{TRACE_ID}_{PARENT_ID}-01", id="mauvais-separateur"),
    pytest.param(f" {VALIDE}", id="espace-avant"),
    pytest.param(f"{VALIDE} ", id="espace-apres"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-01\n", id="saut-de-ligne"),
    pytest.param(f"00{TRACE_ID}{PARENT_ID}01", id="sans-tirets"),
    pytest.param(f"00-{TRACE_ID}-{PARENT_ID}-é1", id="caractere-non-ascii"),
]


def future_de_longueur(longueur: int) -> str:
    base = f"01-{TRACE_ID}-{PARENT_ID}-01-"
    return base + "x" * (longueur - len(base))


async def test_un_en_tete_de_512_caracteres_est_encore_lu() -> None:
    assert (await vu_par_la_route(future_de_longueur(trace.LONGUEUR_MAX)))["state_trace"] == TRACE_ID


async def test_un_en_tete_de_plus_de_512_caracteres_est_ignore() -> None:
    vu = await vu_par_la_route(future_de_longueur(trace.LONGUEUR_MAX + 1))
    assert vu["state_trace"] != TRACE_ID


def test_un_identifiant_tire_n_est_jamais_nul(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace.secrets, "randbelow", lambda _borne: 0)
    assert trace.identifiant_non_nul(8) == "0" * 15 + "1"
    assert trace.identifiant_non_nul(16) == "0" * 31 + "1"


@pytest.mark.parametrize("entete", INVALIDES)
async def test_une_forme_invalide_est_ignoree_et_une_nouvelle_trace_commence(entete: str) -> None:
    vu = await vu_par_la_route(entete)
    assert HEX_32.fullmatch(vu["state_trace"] or "")
    assert vu["state_trace"] != TRACE_ID
    assert vu["state_trace"] != "0" * 32
    assert vu["state_span"] != PARENT_ID


async def test_deux_lignes_traceparent_sont_ignorees() -> None:
    en_tetes = [("traceparent", VALIDE), ("traceparent", VALIDE)]
    retour = await appeler(app_de_test(), "GET", "/api/_test/trace", en_tetes)
    assert json.loads(retour.corps)["state_trace"] != TRACE_ID


async def test_tracestate_n_est_pas_interprete() -> None:
    app = app_de_test()
    retour = await appeler(app, "GET", "/api/_test/trace", {"traceparent": VALIDE, "tracestate": "a=b,c"})
    assert retour.status == 200
    assert json.loads(retour.corps)["state_trace"] == TRACE_ID


async def test_les_variables_de_contexte_sont_rendues_apres_la_requete() -> None:
    await vu_par_la_route(VALIDE)
    assert trace.trace_id_courant.get() is None
    assert trace.span_id_courant.get() is None
