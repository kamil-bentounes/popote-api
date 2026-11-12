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


# --- Administration de Supabase Auth ----------------------------------------------------------------

CLE_SUPABASE = "sb_secret_" + "k" * 30


def test_les_reglages_d_auth_sont_facultatifs() -> None:
    reglages = Settings.model_validate({"env": "local"})
    assert reglages.supabase_url is None and reglages.supabase_secret_key is None


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_les_reglages_d_auth_restent_facultatifs(env: str) -> None:
    reglages = Settings.model_validate({"env": env, "relay_secret": SECRET, "database_url": DSN})
    assert reglages.supabase_url is None


def test_les_reglages_d_auth_sont_lus_dans_l_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPOTE_ENV", "local")
    monkeypatch.setenv("POPOTE_SUPABASE_URL", "http://127.0.0.1:54321")
    monkeypatch.setenv("POPOTE_SUPABASE_SECRET_KEY", CLE_SUPABASE)
    reglages = Settings()
    assert reglages.supabase_url == "http://127.0.0.1:54321"
    assert reglages.supabase_secret_key is not None
    assert reglages.supabase_secret_key.get_secret_value() == CLE_SUPABASE


@pytest.mark.parametrize(
    "seul",
    [{"supabase_url": "https://p.supabase.co"}, {"supabase_secret_key": CLE_SUPABASE}],
)
def test_l_url_et_la_cle_d_auth_vont_ensemble(seul: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="vont ensemble") as erreur:
        Settings.model_validate({"env": "local"} | seul)
    assert CLE_SUPABASE not in str(erreur.value)


@pytest.mark.parametrize(
    ("saisie", "origine"),
    [
        ("https://p.supabase.co", "https://p.supabase.co"),
        ("https://p.supabase.co/", "https://p.supabase.co"),
        ("  https://P.supabase.co:8443  ", "https://p.supabase.co:8443"),
        ("http://127.0.0.1:54321", "http://127.0.0.1:54321"),
        ("http://localhost:54321/", "http://localhost:54321"),
        ("http://[::1]:54321", "http://[::1]:54321"),
    ],
)
def test_l_url_d_auth_est_ramenee_a_son_origine(saisie: str, origine: str) -> None:
    reglages = Settings.model_validate(
        {"env": "local", "supabase_url": saisie, "supabase_secret_key": CLE_SUPABASE}
    )
    assert reglages.supabase_url == origine


@pytest.mark.parametrize(
    "mauvaise",
    [
        "p.supabase.co",
        "ftp://p.supabase.co",
        "https://",
        "https://p.supabase.co/auth/v1",
        "https://p.supabase.co/?a=1",
        "https://p.supabase.co/#x",
        "https://nom:motdepasse@p.supabase.co",
        "https://p.supabase.co:abc",
        "https://p.supabase.co:0",
        "https://p.supabase.co:70000",
        "https://<ref>.supabase.co",
        "https://p supabase.co",
        "https://p.supabase.co\\",
        "https://evil.example\\.supabase.co",
        "https://p.supabase.co%2f",
        "https://p..supabase.co",
        "https://-p.supabase.co",
        "https://p.supabase.co\x00",
        "https://[zz::1]",
        "",
    ],
)
def test_une_url_d_auth_mal_formee_echoue_sans_etre_recopiee(mauvaise: str) -> None:
    with pytest.raises(ValidationError, match="supabase_url") as erreur:
        Settings.model_validate(
            {"env": "local", "supabase_url": mauvaise, "supabase_secret_key": CLE_SUPABASE}
        )
    assert "motdepasse" not in str(erreur.value)


@pytest.mark.parametrize(
    ("env", "url"),
    [
        ("local", "http://p.supabase.co"),
        ("local", "http://127.0.0.1.evil.example"),
        ("essai", "http://127.0.0.1:54321"),
        ("prod", "http://localhost:54321"),
    ],
)
def test_http_n_est_permis_qu_en_local_et_vers_l_hote_local(env: str, url: str) -> None:
    autres = {} if env == "local" else {"relay_secret": SECRET, "database_url": DSN}
    with pytest.raises(ValidationError, match="https obligatoire"):
        Settings.model_validate(
            {"env": env, "supabase_url": url, "supabase_secret_key": CLE_SUPABASE} | autres
        )


@pytest.mark.parametrize("cle", ["", "clé-é", "a b", "a\nb", "a\x00b", "a\tb"])
def test_une_cle_d_auth_non_transmissible_echoue_sans_etre_recopiee(cle: str) -> None:
    with pytest.raises(ValidationError, match="supabase_secret_key") as erreur:
        Settings.model_validate(
            {"env": "local", "supabase_url": "https://p.supabase.co", "supabase_secret_key": cle}
        )
    assert cle == "" or cle not in str(erreur.value)
