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


@pytest.mark.parametrize("env", ["essai", "prod"])
@pytest.mark.parametrize("secret", ["é" * 32, "s" * 31 + "é", "s" * 31 + "\u200b"])
def test_un_secret_non_ascii_echoue_au_demarrage(env: str, secret: str) -> None:
    with pytest.raises(ValidationError, match="ASCII"):
        Settings.model_validate({"env": env, "relay_secret": secret, "database_url": DSN})


@pytest.mark.parametrize("nom", ["internal_secret", "internal_secret_precedent"])
@pytest.mark.parametrize("secret", ["é" * 32, "s" * 31 + "é", "s" * 31 + "​"])
def test_un_secret_interne_non_ascii_echoue_au_demarrage(nom: str, secret: str) -> None:
    valeurs = {"env": "local", "internal_secret": SECRET, nom: secret}
    with pytest.raises(ValidationError, match=f"{nom} : caractères ASCII"):
        Settings.model_validate(valeurs)


@pytest.mark.parametrize("nom", ["internal_secret", "internal_secret_precedent"])
def test_un_secret_interne_trop_court_echoue_dans_tout_environnement(nom: str) -> None:
    valeurs = {"env": "local", "internal_secret": SECRET, nom: "s" * 31}
    with pytest.raises(ValidationError, match=f"{nom} : 32 caractères"):
        Settings.model_validate(valeurs)


def test_sans_secret_interne_le_demarrage_reussit_et_les_routes_restent_fermees() -> None:
    reglages = Settings.model_validate({"env": "local"})
    assert reglages.secrets_internes == ()


@pytest.mark.parametrize("vide", ["", None])
def test_un_secret_interne_vide_vaut_absent(vide: str | None) -> None:
    reglages = Settings.model_validate({"env": "local", "internal_secret": vide})
    assert reglages.secrets_internes == ()


def test_la_rotation_garde_le_courant_d_abord() -> None:
    reglages = Settings.model_validate(
        {"env": "local", "internal_secret": SECRET, "internal_secret_precedent": "p" * 32}
    )
    assert reglages.secrets_internes == (SECRET.encode(), b"p" * 32)


@pytest.mark.parametrize("courant", [None, ""])
def test_un_secret_precedent_sans_secret_courant_echoue(courant: str | None) -> None:
    with pytest.raises(ValidationError, match="internal_secret_precedent sans internal_secret"):
        Settings.model_validate(
            {"env": "local", "internal_secret": courant, "internal_secret_precedent": "p" * 32}
        )


def test_l_erreur_sur_un_secret_interne_ne_recopie_pas_le_secret() -> None:
    with pytest.raises(ValidationError) as erreur:
        Settings.model_validate({"env": "local", "internal_secret": "court-mais-secret"})
    assert "court-mais-secret" not in str(erreur.value)


def test_le_secret_interne_est_lu_dans_l_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPOTE_ENV", "local")
    monkeypatch.setenv("POPOTE_INTERNAL_SECRET", SECRET)
    monkeypatch.setenv("POPOTE_INTERNAL_SECRET_PRECEDENT", "p" * 32)
    assert Settings().secrets_internes == (SECRET.encode(), b"p" * 32)
