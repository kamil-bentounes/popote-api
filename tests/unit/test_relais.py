import httpx
from fastapi import Request

from popote_api.config import Settings
from popote_api.main import create_app
from popote_api.relais import ip_de

SECRET = "s" * 32


def client(env: str, secret: str | None = SECRET) -> httpx.AsyncClient:
    app = create_app(Settings(env=env, relay_secret=secret))  # type: ignore[arg-type]

    @app.get("/api/_test/ip")
    async def ip(request: Request) -> dict[str, str]:
        return {"ip": ip_de(request)}

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_hors_local_sans_en_tete_rend_404() -> None:
    assert (await client("essai").get("/api/healthz")).status_code == 404


async def test_hors_local_mauvais_en_tete_rend_404() -> None:
    r = await client("essai").get("/api/healthz", headers={"X-Popote-Relais": "faux"})
    assert r.status_code == 404


async def test_hors_local_bon_en_tete_passe() -> None:
    r = await client("essai").get("/api/healthz", headers={"X-Popote-Relais": SECRET})
    assert r.status_code == 200


async def test_en_local_le_relais_nest_pas_exige() -> None:
    assert (await client("local").get("/api/healthz")).status_code == 200


async def test_hors_local_sans_secret_configure_tout_est_refuse() -> None:
    r = await client("prod", secret=None).get("/api/healthz", headers={"X-Popote-Relais": SECRET})
    assert r.status_code == 404


async def test_le_refus_est_un_probleme_qui_porte_son_identifiant() -> None:
    r = await client("essai").get("/api/healthz")
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.headers["x-request-id"] == r.json()["instance"]
    assert r.json()["code"] == "introuvable"


async def test_lip_annoncee_est_crue_avec_le_bon_relais() -> None:
    r = await client("essai").get(
        "/api/_test/ip", headers={"X-Popote-Relais": SECRET, "X-Popote-IP": "203.0.113.7"}
    )
    assert r.json() == {"ip": "203.0.113.7"}


async def test_lip_annoncee_est_ignoree_sans_relais_authentique() -> None:
    r = await client("local").get("/api/_test/ip", headers={"X-Popote-IP": "203.0.113.7"})
    assert r.json() == {"ip": "127.0.0.1"}
