"""Les erreurs de la base deviennent des Problem Details ; le journal ne reçoit jamais leur message."""

import logging
from uuid import uuid4

import httpx
import psycopg
import pytest
from _commun import reglages
from fastapi import FastAPI
from psycopg_pool import PoolClosed, PoolTimeout

from popote_api import erreurs_base, errors
from popote_api.erreurs_base import refus_vaut_introuvable, traduit
from popote_api.errors import Probleme
from popote_api.infra.db import BaseError, BaseIndisponibleError
from popote_api.main import create_app

# Une valeur que le serveur recopierait dans le DETAIL d'une erreur : elle ne doit sortir nulle part.
VALEUR_SECRETE = "montant-4217-prenom-Zoe"


def erreur_sql(sqlstate: str) -> psycopg.Error:
    return psycopg.errors.lookup(sqlstate)(
        f"duplicate key value\nDETAIL: Key (nom)=({VALEUR_SECRETE}) exists."
    )


async def appeler_une_route_qui_leve(erreur: Exception) -> httpx.Response:
    app = FastAPI()
    app.state.settings = reglages("local")
    errors.installe(app)
    erreurs_base.installe(app)

    @app.get("/boom")
    async def boom() -> None:
        raise erreur

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/boom")


@pytest.mark.parametrize(
    ("sqlstate", "status", "code"),
    [
        ("23505", 409, "conflit"),
        ("23503", 422, "donnees_invalides"),
        ("23514", 422, "donnees_invalides"),
        ("22P02", 422, "donnees_invalides"),
        ("40001", 503, "reessayer"),
        ("40P01", 503, "reessayer"),
        ("55P03", 503, "reessayer"),
        ("57014", 503, "delai_depasse"),
        ("08006", 503, "base_indisponible"),
        ("08001", 503, "base_indisponible"),
        ("53300", 503, "base_indisponible"),
        ("57P01", 503, "base_indisponible"),
    ],
)
async def test_un_sqlstate_connu_est_rendu_avec_son_statut_et_son_code(
    sqlstate: str, status: int, code: str
) -> None:
    reponse = await appeler_une_route_qui_leve(erreur_sql(sqlstate))
    assert (reponse.status_code, reponse.json()["code"]) == (status, code)
    assert reponse.headers["content-type"] == "application/problem+json"
    assert VALEUR_SECRETE not in reponse.text


@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "55P03"])
async def test_une_erreur_transitoire_demande_de_reessayer_apres_une_seconde(sqlstate: str) -> None:
    reponse = await appeler_une_route_qui_leve(erreur_sql(sqlstate))
    assert reponse.headers["retry-after"] == "1"


async def test_une_erreur_de_donnees_n_indique_aucun_champ() -> None:
    reponse = await appeler_une_route_qui_leve(erreur_sql("23514"))
    assert "errors" not in reponse.json()


@pytest.mark.parametrize(
    "erreur",
    [
        PoolTimeout("attente"),
        PoolClosed("fermé"),
        psycopg.OperationalError("coupée"),
        psycopg.InterfaceError("close"),
    ],
)
async def test_une_erreur_de_connexion_sans_sqlstate_est_base_indisponible(erreur: Exception) -> None:
    reponse = await appeler_une_route_qui_leve(erreur)
    assert (reponse.status_code, reponse.json()["code"]) == (503, "base_indisponible")


async def test_un_sqlstate_inconnu_reste_une_500_generique() -> None:
    reponse = await appeler_une_route_qui_leve(erreur_sql("22012"))
    assert (reponse.status_code, reponse.json()["code"]) == (500, "erreur_interne")
    assert VALEUR_SECRETE not in reponse.text


async def test_un_droit_refuse_hors_lecture_ciblee_est_une_500_journalisee_en_avertissement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="popote_api.erreurs_base"):
        reponse = await appeler_une_route_qui_leve(erreur_sql("42501"))
    assert (reponse.status_code, reponse.json()["code"]) == (500, "erreur_interne")
    assert "Droit refusé par la base" in caplog.text
    assert "rendu=500" in caplog.text


async def test_la_pile_et_le_message_de_la_base_ne_sont_pas_journalises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="popote_api.erreurs_base"):
        await appeler_une_route_qui_leve(erreur_sql("23505"))
    assert "sqlstate=23505" in caplog.text
    assert VALEUR_SECRETE not in caplog.text
    assert all(enregistrement.exc_info is None for enregistrement in caplog.records)


def test_refus_vaut_introuvable_rend_404_et_garde_la_cause() -> None:
    refus = psycopg.errors.InsufficientPrivilege("permission denied")
    with pytest.raises(Probleme) as erreur, refus_vaut_introuvable():
        raise refus
    assert (erreur.value.status, erreur.value.code) == (404, "introuvable")
    assert erreur.value.__cause__ is refus


@pytest.mark.parametrize("autre", [psycopg.errors.UniqueViolation("x"), ValueError("x")])
def test_refus_vaut_introuvable_laisse_passer_toute_autre_erreur(autre: Exception) -> None:
    with pytest.raises(type(autre)), refus_vaut_introuvable():
        raise autre


def test_une_erreur_de_la_base_hors_de_la_liste_n_a_pas_de_traduction() -> None:
    assert traduit(erreur_sql("22012")) is None
    assert traduit(BaseError()) is None
    assert traduit(BaseIndisponibleError()) is not None


async def test_sans_pool_interne_la_route_de_service_rend_503_service_indisponible() -> None:
    app = create_app(reglages("local"))

    @app.get("/service")
    async def service() -> None:
        async with app.state.base.service():
            pass

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        reponse = await client.get("/service")
    assert (reponse.status_code, reponse.json()["code"]) == (503, "service_indisponible")


async def test_sans_pool_api_la_route_de_personne_rend_503_base_indisponible() -> None:
    app = create_app(reglages("local"))

    @app.get("/personne")
    async def personne() -> None:
        async with app.state.base.personne(uuid4()):
            pass

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        reponse = await client.get("/personne")
    assert (reponse.status_code, reponse.json()["code"]) == (503, "base_indisponible")
