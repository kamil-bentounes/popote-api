import logging

import httpx
import pytest
from _commun import RELAIS, SECRET, reglages
from fastapi import Request

from popote_api.main import create_app
from popote_api.relais import ip_de


def client(env: str) -> httpx.AsyncClient:
    app = create_app(reglages(env))

    @app.get("/api/_test/ip")
    async def ip(request: Request) -> dict[str, str | None]:
        return {"ip": ip_de(request)}

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def ip_vue(ip_annoncee: str | None, env: str = "essai") -> str | None:
    en_tetes = dict(RELAIS) if env != "local" else {}
    if ip_annoncee is not None:
        en_tetes["X-Popote-IP"] = ip_annoncee
    r = await client(env).get("/api/_test/ip", headers=en_tetes)
    assert r.status_code == 200
    valeur: str | None = r.json()["ip"]
    return valeur


@pytest.mark.parametrize(
    ("annoncee", "attendue"),
    [
        ("203.0.113.7", "203.0.113.7"),
        (" 203.0.113.7 ", "203.0.113.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("2001:DB8:0:0:0:0:0:1", "2001:db8::1"),
    ],
)
async def test_une_ip_valide_annoncee_par_le_relais_authentique_est_rendue(
    annoncee: str, attendue: str
) -> None:
    assert await ip_vue(annoncee) == attendue


@pytest.mark.parametrize("annoncee", [None, "", "   ", "pas-une-ip", "203.0.113.7, 10.0.0.1", "999.1.1.1"])
async def test_une_ip_absente_ou_invalide_rend_none_et_jamais_l_adresse_du_relais(
    annoncee: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="popote_api.relais"):
        assert await ip_vue(annoncee) is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert all("127.0.0.1" not in r.getMessage() for r in caplog.records)


async def test_l_avertissement_ne_recopie_pas_l_en_tete_recu(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="popote_api.relais"):
        await ip_vue("pas-une-ip")
    assert all("pas-une-ip" not in r.getMessage() for r in caplog.records)


async def test_en_local_l_ip_est_celle_de_la_connexion() -> None:
    assert await ip_vue(None, env="local") == "127.0.0.1"


async def test_en_local_une_ip_annoncee_est_ignoree() -> None:
    assert await ip_vue("203.0.113.7", env="local") == "127.0.0.1"


async def test_un_faux_relais_est_refuse_avant_que_l_ip_annoncee_compte() -> None:
    faux = {"X-Popote-Relais": "x" * len(SECRET), "X-Popote-IP": "203.0.113.7"}
    r = await client("essai").get("/api/_test/ip", headers=faux)
    assert r.status_code == 404
    assert "203.0.113.7" not in r.text
