import pytest
from _commun import DSN, SECRET
from pydantic import ValidationError

import popote_api.main
from popote_api.config import Env, Settings
from popote_api.main import create_app


def test_sans_popote_env_le_demarrage_echoue() -> None:
    with pytest.raises(ValidationError, match="env"):
        Settings()


def test_une_faute_dans_le_nom_de_la_variable_fait_echouer_le_demarrage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POPOTE_ENVIRONMENT", "prod")
    with pytest.raises(ValidationError, match="env"):
        Settings()


@pytest.mark.parametrize("valeur", ["production", "Prod", "prod ", ""])
def test_un_environnement_inconnu_echoue(monkeypatch: pytest.MonkeyPatch, valeur: str) -> None:
    monkeypatch.setenv("POPOTE_ENV", valeur)
    with pytest.raises(ValidationError):
        Settings()


def test_popote_env_est_lu_dans_l_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPOTE_ENV", "local")
    assert Settings().env is Env.local


def test_local_n_exige_ni_secret_ni_base() -> None:
    reglages = Settings.model_validate({"env": "local"})
    assert reglages.relais_exige is False


@pytest.mark.parametrize("env", ["essai", "prod"])
@pytest.mark.parametrize("secret", [None, "", "s" * 31])
def test_hors_local_un_secret_absent_vide_ou_court_echoue(env: str, secret: str | None) -> None:
    with pytest.raises(ValidationError, match="relay_secret"):
        Settings.model_validate({"env": env, "relay_secret": secret, "database_url": DSN})


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_sans_base_echoue(env: str) -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings.model_validate({"env": env, "relay_secret": SECRET})


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_un_secret_de_32_caracteres_et_une_base_passent(env: str) -> None:
    reglages = Settings.model_validate({"env": env, "relay_secret": SECRET, "database_url": DSN})
    assert reglages.relais_exige is True


def test_l_erreur_de_configuration_ne_recopie_pas_le_secret() -> None:
    with pytest.raises(ValidationError) as erreur:
        Settings.model_validate({"env": "prod", "relay_secret": "court-mais-secret", "database_url": DSN})
    assert "court-mais-secret" not in str(erreur.value)


def test_create_app_sans_popote_env_echoue() -> None:
    with pytest.raises(ValidationError):
        create_app()


def test_le_module_ne_cree_pas_d_application_a_l_import() -> None:
    assert not hasattr(popote_api.main, "app")
