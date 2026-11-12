import pytest
from _commun import RELAIS, appeler, reglages

from popote_api.main import create_app


@pytest.mark.parametrize("env", ["local", "essai"])
async def test_le_contrat_openapi_est_servi_en_local_et_en_essai(env: str) -> None:
    en_tetes = RELAIS if env == "essai" else None
    retour = await appeler(create_app(reglages(env)), "GET", "/api/openapi.json", en_tetes)
    assert retour.status == 200


async def test_le_contrat_openapi_n_est_pas_servi_en_prod() -> None:
    retour = await appeler(create_app(reglages("prod")), "GET", "/api/openapi.json", RELAIS)
    assert retour.status == 404


async def test_une_barre_finale_en_trop_ne_redirige_pas() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/ressource")
    async def ressource() -> dict[str, bool]:
        return {"ok": True}

    retour = await appeler(app, "GET", "/api/_test/ressource/")
    assert retour.status == 404
    assert "location" not in retour.en_tetes


async def test_une_barre_finale_manquante_ne_redirige_pas() -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/dossier/")
    async def dossier() -> dict[str, bool]:
        return {"ok": True}

    retour = await appeler(app, "GET", "/api/_test/dossier")
    assert retour.status == 404
    assert "location" not in retour.en_tetes
