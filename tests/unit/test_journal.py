import json
import logging
import logging.config
import re
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
import pytest
import uvicorn.config
from _commun import appeler, reglages
from fastapi import FastAPI
from psycopg import errors
from psycopg.pq import DiagnosticField
from pydantic import BaseModel, ValidationError

from popote_api import journal, trace
from popote_api.identifiant import request_id_courant
from popote_api.main import create_app

NOMS_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")
# Une valeur qui ne doit jamais atteindre le journal. Construite à l'exécution : le texte d'une pile
# recopie les lignes de code, pas les valeurs.
DONNEE = "-".join(["valeur", "personnelle"])
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"
HORODATAGE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z")


@pytest.fixture
def etat_du_journal() -> Iterator[None]:
    """Rend la configuration du journal telle qu'elle était : un test de `configure` la remplace."""
    racine = logging.getLogger()
    avant_racine = (list(racine.handlers), racine.level)
    avant = {
        n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate, logging.getLogger(n).level)
        for n in NOMS_UVICORN
    }
    desactive = logging.getLogger("uvicorn.access").disabled
    yield
    racine.handlers[:], racine.level = avant_racine[0], avant_racine[1]
    for nom, (gestionnaires, propage, niveau) in avant.items():
        logger = logging.getLogger(nom)
        logger.handlers[:], logger.propagate = gestionnaires, propage
        logger.setLevel(niveau)
    logging.getLogger("uvicorn.access").disabled = desactive


def lignes(sortie: str) -> list[dict[str, Any]]:
    """Chaque ligne de la sortie doit être, à elle seule, un objet JSON."""
    return [json.loads(ligne) for ligne in sortie.splitlines()]


def enregistrement(message: str = "msg", **extra: Any) -> logging.LogRecord:
    enr = logging.LogRecord("popote_api.test", logging.WARNING, __file__, 1, message, None, None)
    enr.created = datetime(2026, 11, 12, 10, 30, 5, 123456, tzinfo=UTC).timestamp()
    enr.__dict__.update(extra)
    return enr


def formate(enr: logging.LogRecord) -> dict[str, Any]:
    ligne = journal.Formateur().format(enr)
    assert "\n" not in ligne
    return json.loads(ligne)  # type: ignore[no-any-return]


# --- le formateur ---------------------------------------------------------------------------------


def test_une_ligne_porte_l_heure_le_niveau_le_logger_et_le_message() -> None:
    assert formate(enregistrement("bonjour")) == {
        "ts": "2026-11-12T10:30:05.123Z",
        "level": "WARNING",
        "logger": "popote_api.test",
        "msg": "bonjour",
    }


def test_les_champs_extra_autorises_passent_et_les_autres_sont_ecartes() -> None:
    ligne = formate(
        enregistrement(method="GET", route="/api/x/{id}", status=200, duration_ms=1.5, email=DONNEE)
    )
    assert (ligne["method"], ligne["route"], ligne["status"], ligne["duration_ms"]) == (
        "GET",
        "/api/x/{id}",
        200,
        1.5,
    )
    assert "email" not in ligne
    assert DONNEE not in json.dumps(ligne)


def test_un_saut_de_ligne_dans_le_message_ne_fait_pas_une_seconde_ligne() -> None:
    faux = '{"level":"INFO","msg":"forgé"}'
    assert formate(enregistrement(f"avant\n{faux}"))["msg"] == f"avant\n{faux}"


def test_les_accents_restent_lisibles_dans_la_ligne() -> None:
    assert "café" in journal.Formateur().format(enregistrement("café"))


def test_les_identifiants_viennent_de_l_enregistrement_puis_du_contexte() -> None:
    jetons = (
        request_id_courant.set("ctx-req"),
        trace.trace_id_courant.set("ctx-trace"),
        trace.span_id_courant.set("ctx-span"),
    )
    try:
        implicite = formate(enregistrement())
        assert (implicite["request_id"], implicite["trace_id"], implicite["span_id"]) == (
            "ctx-req",
            "ctx-trace",
            "ctx-span",
        )
        explicite = formate(enregistrement(request_id="enr-req", trace_id="enr-trace", span_id=None))
        assert (explicite["request_id"], explicite["trace_id"], explicite["span_id"]) == (
            "enr-req",
            "enr-trace",
            "ctx-span",
        )
    finally:
        request_id_courant.reset(jetons[0])
        trace.trace_id_courant.reset(jetons[1])
        trace.span_id_courant.reset(jetons[2])


def test_sans_contexte_les_identifiants_sont_absents_plutot_que_nuls() -> None:
    assert not {"request_id", "trace_id", "span_id"} & formate(enregistrement()).keys()


# --- les exceptions -------------------------------------------------------------------------------


def avec_exception(exc: BaseException) -> logging.LogRecord:
    try:
        raise exc
    except BaseException:
        enr = enregistrement()
        enr.exc_info = sys.exc_info()
        return enr


def test_une_exception_se_journalise_avec_son_type_et_sa_pile_sans_son_message() -> None:
    sortie = journal.Formateur().format(avec_exception(RuntimeError(DONNEE)))
    (entree,) = json.loads(sortie)["exception"]
    assert entree["type"] == "builtins.RuntimeError"
    assert "message" not in entree
    assert any(cadre.endswith(" avec_exception") for cadre in entree["stack"])
    assert re.fullmatch(r".+test_journal\.py:\d+ avec_exception", entree["stack"][-1])
    assert DONNEE not in sortie


def erreur_de_base() -> errors.UniqueViolation:
    info = {DiagnosticField.CONSTRAINT_NAME: b"membres_courriel_cle", DiagnosticField.TABLE_NAME: b"membres"}
    return errors.UniqueViolation(f"Key (courriel)=({DONNEE}) already exists.", info=info)


def test_une_erreur_psycopg_ajoute_sqlstate_contrainte_et_table() -> None:
    sortie = journal.Formateur().format(avec_exception(erreur_de_base()))
    (entree,) = json.loads(sortie)["exception"]
    assert entree["type"] == "psycopg.errors.UniqueViolation"
    assert (entree["sqlstate"], entree["constraint_name"], entree["table_name"]) == (
        "23505",
        "membres_courriel_cle",
        "membres",
    )
    for interdit in (DONNEE, "already exists", "Key ("):
        assert interdit not in sortie


def test_une_erreur_psycopg_sans_diagnostic_n_a_que_son_sqlstate() -> None:
    (entree,) = formate(avec_exception(errors.UniqueViolation(DONNEE)))["exception"]
    assert entree["sqlstate"] == "23505"
    assert not {"constraint_name", "table_name"} & entree.keys()


def test_une_erreur_psycopg_sans_sqlstate_ni_diagnostic_se_journalise_encore() -> None:
    (entree,) = formate(avec_exception(psycopg.OperationalError(DONNEE)))["exception"]
    assert entree["type"] == "psycopg.OperationalError"
    assert not {"sqlstate", "constraint_name", "table_name"} & entree.keys()


class Modele(BaseModel):
    nombre: int


def erreur_de_validation() -> ValidationError:
    try:
        Modele.model_validate({"nombre": DONNEE})
    except ValidationError as exc:
        return exc
    raise AssertionError("la validation aurait dû échouer")  # pragma: no cover


def erreur_http() -> httpx.HTTPError:
    return httpx.ConnectError(f"https://exemple.invalid/api?jeton={DONNEE}")


# Pour chaque type d'exception, la valeur qu'elle recopie dans son message n'atteint jamais la sortie.
@pytest.mark.parametrize(
    ("fabrique", "type_attendu"),
    [
        pytest.param(lambda: RuntimeError(DONNEE), "builtins.RuntimeError", id="exception-simple"),
        pytest.param(lambda: KeyError(DONNEE), "builtins.KeyError", id="cle-absente"),
        pytest.param(erreur_de_base, "psycopg.errors.UniqueViolation", id="psycopg-avec-detail"),
        pytest.param(
            erreur_de_validation, "pydantic_core._pydantic_core.ValidationError", id="validation-pydantic"
        ),
        pytest.param(erreur_http, "httpx.ConnectError", id="httpx-avec-url"),
    ],
)
def test_la_valeur_recopiee_par_un_message_n_atteint_jamais_la_sortie(
    fabrique: Callable[[], BaseException], type_attendu: str
) -> None:
    sortie = journal.Formateur().format(avec_exception(fabrique()))
    assert json.loads(sortie)["exception"][0]["type"] == type_attendu
    assert DONNEE not in sortie


def chaine(par_cause: bool) -> logging.LogRecord:
    try:
        try:
            raise erreur_de_base()
        except errors.UniqueViolation as cause:
            if par_cause:
                raise RuntimeError(DONNEE) from cause
            raise RuntimeError(DONNEE)  # noqa: B904 - le contexte implicite est ce qu'on teste
    except RuntimeError:
        enr = enregistrement()
        enr.exc_info = sys.exc_info()
        return enr


@pytest.mark.parametrize("par_cause", [True, False], ids=["cause", "contexte"])
def test_les_exceptions_chainees_se_journalisent_sans_leur_message(par_cause: bool) -> None:
    sortie = journal.Formateur().format(chaine(par_cause))
    entrees = json.loads(sortie)["exception"]
    assert [e["type"] for e in entrees] == ["builtins.RuntimeError", "psycopg.errors.UniqueViolation"]
    assert entrees[1]["sqlstate"] == "23505"
    assert DONNEE not in sortie


def test_un_contexte_explicitement_coupe_n_est_pas_suivi() -> None:
    try:
        try:
            raise erreur_de_base()
        except errors.UniqueViolation:
            raise RuntimeError("enveloppe") from None
    except RuntimeError:
        enr = enregistrement()
        enr.exc_info = sys.exc_info()
    assert [e["type"] for e in formate(enr)["exception"]] == ["builtins.RuntimeError"]


def test_une_exception_qui_se_cite_elle_meme_ne_boucle_pas() -> None:
    exc = RuntimeError("a")
    exc.__cause__ = exc
    assert len(formate(avec_exception(exc))["exception"]) == 1


# --- configure ------------------------------------------------------------------------------------


def gestionnaires_du_journal(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if isinstance(h.formatter, journal.Formateur)]


def test_configure_est_idempotente(etat_du_journal: None, capsys: pytest.CaptureFixture[str]) -> None:
    for _ in range(3):
        journal.configure()
    assert len(gestionnaires_du_journal(logging.getLogger())) == 1
    logging.getLogger("popote_api.test").warning("une fois")
    assert [ligne["msg"] for ligne in lignes(capsys.readouterr().out)] == ["une fois"]


def test_configure_remplace_la_configuration_d_uvicorn(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)  # l'état où uvicorn laisse le processus
    journal.configure()
    logging.getLogger("uvicorn.error").error("erreur d'uvicorn")
    logging.getLogger("uvicorn").info("démarrage")
    logging.getLogger("uvicorn.access").info("127.0.0.1 - GET /secret/jeton")
    sortie = capsys.readouterr()
    assert [(ligne["logger"], ligne["msg"]) for ligne in lignes(sortie.out)] == [
        ("uvicorn.error", "erreur d'uvicorn"),
        ("uvicorn", "démarrage"),
    ]
    assert sortie.err == ""
    for nom in ("uvicorn", "uvicorn.error"):
        assert logging.getLogger(nom).handlers == []
        assert logging.getLogger(nom).propagate is True


def test_configure_garde_les_filtres_d_uvicorn_error(etat_du_journal: None) -> None:
    from popote_api.errors import FILTRE_UVICORN

    logger = logging.getLogger("uvicorn.error")
    logger.addFilter(FILTRE_UVICORN)
    journal.configure()
    assert FILTRE_UVICORN in logger.filters
    logger.removeFilter(FILTRE_UVICORN)


def test_le_filtre_anti_doublon_d_uvicorn_survit_a_create_app(etat_du_journal: None) -> None:
    from popote_api.errors import FILTRE_UVICORN

    logger = logging.getLogger("uvicorn.error")
    avant = list(logger.filters)
    try:
        create_app(reglages("local", json_logs=True))
        assert FILTRE_UVICORN in logger.filters
    finally:
        logger.filters[:] = avant


def test_create_app_configure_le_journal_si_le_reglage_est_actif(etat_du_journal: None) -> None:
    create_app(reglages("local", json_logs=True))
    assert len(gestionnaires_du_journal(logging.getLogger())) == 1


def test_create_app_ne_touche_pas_au_journal_si_le_reglage_est_coupe(etat_du_journal: None) -> None:
    create_app(reglages("local", json_logs=False))
    assert gestionnaires_du_journal(logging.getLogger()) == []


# --- le journal d'accès et les erreurs, de bout en bout --------------------------------------------


def app_journalisee(env: str = "local") -> FastAPI:
    app = create_app(reglages(env, json_logs=True))

    @app.get("/api/x/{identifiant}")
    async def lire(identifiant: str) -> dict[str, str]:
        logging.getLogger("popote_api.test").info("dans la route")
        return {"ok": "oui"}

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("texte-du-message")

    return app


async def test_la_ligne_d_acces_ne_porte_que_le_gabarit_de_la_route(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    app = app_journalisee()
    retour = await appeler(
        app,
        "GET",
        f"/api/x/{DONNEE}",
        {"User-Agent": "agent-" + DONNEE, "traceparent": TRACEPARENT},
        requete=f"jeton={DONNEE}",
    )
    sortie = capsys.readouterr().out
    assert retour.status == 200
    for interdit in (DONNEE, "jeton=", "127.0.0.1", "agent-"):
        assert interdit not in sortie
    acces = [ligne for ligne in lignes(sortie) if ligne["logger"] == "popote_api.acces"]
    assert len(acces) == 1
    ligne = acces[0]
    assert (ligne["method"], ligne["route"], ligne["status"], ligne["level"]) == (
        "GET",
        "/api/x/{identifiant}",
        200,
        "INFO",
    )
    assert isinstance(ligne["duration_ms"], float)
    assert ligne["request_id"] == retour.en_tetes["x-request-id"]
    assert ligne["trace_id"] == TRACE_ID
    assert re.fullmatch(r"[0-9a-f]{16}", ligne["span_id"])
    assert HORODATAGE.fullmatch(ligne["ts"])


async def test_un_chemin_sans_route_s_ecrit_aucune_et_jamais_en_clair(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    retour = await appeler(app_journalisee(), "GET", f"/api/inconnu/{DONNEE}")
    sortie = capsys.readouterr().out
    assert retour.status == 404
    assert DONNEE not in sortie
    assert [(ligne["route"], ligne["status"]) for ligne in lignes(sortie)] == [("(aucune)", 404)]


async def test_une_methode_refusee_porte_encore_le_gabarit(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    retour = await appeler(app_journalisee(), "DELETE", f"/api/x/{DONNEE}")
    sortie = capsys.readouterr().out
    assert retour.status == 405
    assert DONNEE not in sortie
    assert lignes(sortie)[0]["route"] == "/api/x/{identifiant}"


async def test_un_journal_ecrit_dans_une_route_porte_les_identifiants_de_la_requete(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    retour = await appeler(app_journalisee(), "GET", "/api/x/1", {"traceparent": TRACEPARENT})
    dans_la_route = next(
        ligne for ligne in lignes(capsys.readouterr().out) if ligne["msg"] == "dans la route"
    )
    assert dans_la_route["request_id"] == retour.en_tetes["x-request-id"]
    assert dans_la_route["trace_id"] == TRACE_ID


async def test_le_refus_de_la_garde_a_une_ligne_d_acces_avec_ses_identifiants(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    retour = await appeler(app_journalisee("essai"), "GET", f"/api/x/{DONNEE}", {"traceparent": TRACEPARENT})
    sortie = capsys.readouterr().out
    assert retour.status == 404
    assert DONNEE not in sortie
    (ligne,) = lignes(sortie)
    assert (ligne["status"], ligne["route"]) == (404, "(aucune)")
    assert ligne["request_id"] == retour.en_tetes["x-request-id"]
    assert ligne["trace_id"] == TRACE_ID


async def test_une_500_produit_une_ligne_d_erreur_et_une_ligne_d_acces_avec_les_memes_identifiants(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = httpx.ASGITransport(app=app_journalisee(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/api/_test/boom", headers={"traceparent": TRACEPARENT})
    assert reponse.status_code == 500
    toutes = lignes(capsys.readouterr().out)
    erreurs = [ligne for ligne in toutes if ligne["level"] == "ERROR"]
    assert len(erreurs) == 1
    assert erreurs[0]["request_id"] == reponse.json()["instance"] == reponse.headers["x-request-id"]
    assert erreurs[0]["trace_id"] == TRACE_ID
    assert re.fullmatch(r"[0-9a-f]{16}", erreurs[0]["span_id"])
    assert erreurs[0]["exception"][0]["type"] == "builtins.RuntimeError"
    assert "texte-du-message" not in json.dumps(erreurs[0])
    (acces,) = [ligne for ligne in toutes if ligne["logger"] == "popote_api.acces"]
    assert (acces["status"], acces["route"]) == (500, "/api/_test/boom")
    assert acces["request_id"] == erreurs[0]["request_id"]
    assert acces["trace_id"] == TRACE_ID


async def test_une_erreur_de_base_dans_une_route_est_journalisee_sans_son_message(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    app = app_journalisee()

    @app.get("/api/_test/base")
    async def base() -> None:
        # 23502 : sans traduction en Problem Details (23505 serait rendu 409), donc une 500 journalisée.
        info = {
            DiagnosticField.CONSTRAINT_NAME: b"membres_courriel_cle",
            DiagnosticField.TABLE_NAME: b"membres",
        }
        raise errors.NotNullViolation(f"null value in column (courriel)=({DONNEE})", info=info)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/api/_test/base")
    sortie = capsys.readouterr().out
    assert reponse.status_code == 500
    assert DONNEE not in sortie
    assert DONNEE not in reponse.text
    erreur = next(ligne for ligne in lignes(sortie) if ligne["level"] == "ERROR")
    assert erreur["exception"][0]["sqlstate"] == "23502"


# --- la durée -------------------------------------------------------------------------------------


async def test_la_duree_est_l_ecart_de_l_horloge_en_millisecondes(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    journal.configure()
    horloge = iter([10.0, 10.25])

    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def envoie(_message: Any) -> None: ...

    async def recoit() -> dict[str, Any]:
        return {"type": "http.request"}

    await journal.Acces(app, horloge=lambda: next(horloge))({"type": "http", "method": "GET"}, recoit, envoie)
    (ligne,) = lignes(capsys.readouterr().out)
    assert ligne["duration_ms"] == 250.0
    assert ligne["status"] == 204


async def test_les_scopes_qui_ne_sont_pas_http_ne_font_pas_de_ligne_d_acces(
    etat_du_journal: None, capsys: pytest.CaptureFixture[str]
) -> None:
    journal.configure()
    appels: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        appels.append(scope["type"])

    await journal.Acces(app)({"type": "websocket"}, None, None)  # type: ignore[arg-type]
    assert appels == ["websocket"]
    assert capsys.readouterr().out == ""


async def test_l_identifiant_courant_est_rendu_apres_la_requete(etat_du_journal: None) -> None:
    await appeler(app_journalisee(), "GET", "/api/x/1")
    assert request_id_courant.get() is None
    assert trace.trace_id_courant.get() is None
