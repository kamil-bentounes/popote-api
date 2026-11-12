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


@pytest.mark.parametrize(
    "valeurs",
    [
        {"internal_secret": "s" * 32, "relay_secret": "s" * 32},
        {"internal_secret": "s" * 32, "internal_secret_precedent": "s" * 32},
        {"internal_secret": "i" * 32, "internal_secret_precedent": "r" * 32, "relay_secret": "r" * 32},
    ],
)
def test_les_secrets_internes_et_celui_du_relais_sont_distincts(valeurs: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="trois valeurs distinctes"):
        Settings.model_validate({"env": "local", "database_url": DSN, **valeurs})


def test_trois_secrets_distincts_passent() -> None:
    reglages = Settings.model_validate(
        {
            "env": "essai",
            "database_url": DSN,
            "relay_secret": "r" * 32,
            "internal_secret": "i" * 32,
            "internal_secret_precedent": "p" * 32,
        }
    )
    assert len(reglages.secrets_internes) == 2


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


@pytest.mark.parametrize("env", ["local", "essai", "prod"])
def test_un_poivre_de_moins_de_32_caracteres_echoue_au_demarrage(env: str) -> None:
    valeurs = {"env": env, "identity_pepper": "poivre-" + "x" * 24}
    if env != "local":
        valeurs |= {"relay_secret": SECRET, "database_url": DSN}
    with pytest.raises(ValidationError, match="identity_pepper") as erreur:
        Settings.model_validate(valeurs)
    assert "poivre-xxx" not in str(erreur.value)


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_le_poivre_est_facultatif(env: str) -> None:
    reglages = Settings.model_validate(
        {"env": env, "relay_secret": SECRET, "database_url": DSN, "identity_pepper": ""}
    )
    assert reglages.identity_pepper is None


def test_un_retour_a_la_ligne_de_fin_du_poivre_est_retire() -> None:
    reglages = Settings.model_validate({"env": "local", "identity_pepper": "p" * 32 + "\n"})
    assert reglages.identity_pepper is not None
    assert reglages.identity_pepper.get_secret_value() == "p" * 32


@pytest.mark.parametrize("poivre", [" " * 40, "x" * 31 + "\n"])
def test_un_poivre_fait_de_blancs_ou_trop_court_une_fois_nettoye_echoue(poivre: str) -> None:
    with pytest.raises(ValidationError, match="identity_pepper"):
        Settings.model_validate({"env": "local", "identity_pepper": poivre})


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
    assert str(reglages.supabase_url) == "http://127.0.0.1:54321/"
    assert reglages.supabase_secret_key is not None
    assert reglages.supabase_secret_key.get_secret_value() == CLE_SUPABASE


def test_l_adresse_seule_est_valide_elle_sert_a_iss() -> None:
    reglages = Settings.model_validate({"env": "local", "supabase_url": "https://p.supabase.co"})
    assert reglages.emetteur_des_jetons == "https://p.supabase.co/auth/v1"
    assert reglages.supabase_secret_key is None


@pytest.mark.parametrize("env", ["local", "essai", "prod"])
def test_la_cle_secrete_sans_l_adresse_est_refusee_au_demarrage(env: str) -> None:
    autres = {} if env == "local" else {"relay_secret": SECRET, "database_url": DSN}
    with pytest.raises(ValidationError, match="sans supabase_url") as erreur:
        Settings.model_validate({"env": env, "supabase_secret_key": CLE_SUPABASE} | autres)
    assert CLE_SUPABASE not in str(erreur.value)


@pytest.mark.parametrize("nom", ["supabase_url", "supabase_secret_key"])
def test_une_valeur_vide_vaut_absente(nom: str) -> None:
    reglages = Settings.model_validate({"env": "local", nom: ""})
    assert getattr(reglages, nom) is None


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
    assert str(reglages.supabase_url).rstrip("/") == origine


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
        "https://evil.example\\.supabase.co",
        "https://p.supabase.co%2f",
        "https://p..supabase.co",
        "https://-p.supabase.co",
        "https://[zz::1]",
    ],
)
def test_une_url_d_auth_mal_formee_echoue_sans_etre_recopiee(mauvaise: str) -> None:
    with pytest.raises(ValidationError, match="supabase_url") as erreur:
        Settings.model_validate({"env": "local", "supabase_url": mauvaise})
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


@pytest.mark.parametrize("cle", ["clé-é", "a b", "a\nb", "a\x00b", "a\tb"])
def test_une_cle_d_auth_non_transmissible_echoue_sans_etre_recopiee(cle: str) -> None:
    with pytest.raises(ValidationError, match="supabase_secret_key") as erreur:
        Settings.model_validate(
            {"env": "local", "supabase_url": "https://p.supabase.co", "supabase_secret_key": cle}
        )
    assert cle not in str(erreur.value)
