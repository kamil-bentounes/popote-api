import pytest
from _commun import DSN, SECRET
from pydantic import ValidationError

import popote_api.main
from popote_api.config import BreachCheck, Env, Settings
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


def test_le_cookie_de_session_porte_son_nom_de_prefixe_host_par_defaut() -> None:
    reglages = Settings.model_validate({"env": "local"})
    assert reglages.nom_du_cookie_de_session == "__Host-popote_session"


def test_en_local_le_nom_du_cookie_de_session_se_configure() -> None:
    reglages = Settings.model_validate({"env": "local", "session_cookie_name": "popote_session"})
    assert reglages.nom_du_cookie_de_session == "popote_session"


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_un_autre_nom_de_cookie_de_session_echoue(env: str) -> None:
    with pytest.raises(ValidationError, match="session_cookie_name"):
        Settings.model_validate(
            {"env": env, "relay_secret": SECRET, "database_url": DSN, "session_cookie_name": "popote_session"}
        )


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_le_nom_du_cookie_de_session_peut_etre_redit(env: str) -> None:
    reglages = Settings.model_validate(
        {
            "env": env,
            "relay_secret": SECRET,
            "database_url": DSN,
            "session_cookie_name": "__Host-popote_session",
        }
    )
    assert reglages.nom_du_cookie_de_session == "__Host-popote_session"


@pytest.mark.parametrize("nom", ["", "a b", "a=b", "a;b", "é", "a" * 65, "a\r\nSet-Cookie"])
def test_un_nom_de_cookie_de_session_illegal_echoue(nom: str) -> None:
    with pytest.raises(ValidationError, match="session_cookie_name"):
        Settings.model_validate({"env": "local", "session_cookie_name": nom})


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_desactiver_la_liste_de_fuites_echoue(env: str) -> None:
    with pytest.raises(ValidationError, match="breach_check"):
        Settings.model_validate(
            {"env": env, "relay_secret": SECRET, "database_url": DSN, "breach_check": "off"}
        )


def test_en_local_la_liste_de_fuites_peut_etre_desactivee_par_l_environnement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POPOTE_ENV", "local")
    monkeypatch.setenv("POPOTE_BREACH_CHECK", "off")
    assert Settings().breach_check is BreachCheck.off


def test_une_valeur_inconnue_de_breach_check_echoue() -> None:
    with pytest.raises(ValidationError, match="breach_check"):
        Settings.model_validate({"env": "local", "breach_check": "hibp2"})


def test_la_version_est_lue_dans_l_environnement_de_l_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPOTE_ENV", "local")
    monkeypatch.setenv("POPOTE_VERSION", "a" * 40)
    assert Settings().version == "a" * 40


@pytest.mark.parametrize("valeur", ["", "a b", "x" * 65, '"; drop', "é"])
def test_une_version_mal_formee_echoue(valeur: str) -> None:
    with pytest.raises(ValidationError, match="version"):
        Settings.model_validate({"env": "local", "version": valeur})
