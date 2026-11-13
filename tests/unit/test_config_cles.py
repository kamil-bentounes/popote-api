"""Le RP ID et les origines des clés d'accès : un défaut par environnement, des refus au démarrage."""

from typing import Any

import pytest
from _commun import reglages
from pydantic import ValidationError

from popote_api.config import Env, Settings, hote_de_l_origine_de_cle


@pytest.mark.parametrize(
    ("env", "rp_id", "origines"),
    [
        ("prod", "notre-popote.fr", {"https://notre-popote.fr"}),
        ("essai", "essai.notre-popote.fr", {"https://essai.notre-popote.fr"}),
        ("local", "localhost", {"http://localhost:5173"}),
    ],
)
def test_chaque_environnement_a_son_rp_id_et_ses_origines(env: str, rp_id: str, origines: set[str]) -> None:
    configuration = reglages(env)
    assert configuration.rp_id_webauthn == rp_id
    assert configuration.origines_webauthn == origines


def test_l_adresse_ip_de_boucle_n_est_pas_une_origine_de_cle_en_local() -> None:
    # Une adresse IP n'est pas un RP ID valide : `127.0.0.1` ne sert pas, même si l'API l'admet ailleurs.
    assert "http://127.0.0.1:5173" not in reglages("local").origines_webauthn


def test_le_nom_de_l_application_a_un_defaut_et_se_borne() -> None:
    assert reglages("local").webauthn_rp_name == "Popote"
    for nom in ("", "x" * 65):
        with pytest.raises(ValidationError, match="webauthn_rp_name"):
            reglages("local", webauthn_rp_name=nom)


def test_les_apercus_de_fusion_n_ont_pas_de_cle() -> None:
    # Le RP ID de l'essai ne peut pas être celui d'un `*.workers.dev` : `apercu_compte` n'ajoute rien ici.
    configuration = reglages("essai", apercu_compte="moncompte")
    assert not any("workers.dev" in origine for origine in configuration.origines_webauthn)


def test_un_rp_id_et_des_origines_se_posent_ensemble_dans_l_environnement() -> None:
    configuration = reglages(
        "essai",
        webauthn_rp_id="notre-popote.fr",
        webauthn_origins="https://essai.notre-popote.fr, https://notre-popote.fr",
    )
    assert configuration.rp_id_webauthn == "notre-popote.fr"
    assert configuration.origines_webauthn == {"https://essai.notre-popote.fr", "https://notre-popote.fr"}


@pytest.mark.parametrize("env", ["essai", "prod"])
@pytest.mark.parametrize(
    "origine",
    [
        "http://notre-popote.fr",  # pas https
        "https://notre-popote.fr:8443",  # un port hors local
        "https://localhost",  # localhost hors local
        "https://sub.localhost",
        "https://127.0.0.1",
        "https://[::1]",
    ],
)
def test_hors_local_une_origine_non_https_ou_locale_echoue(env: str, origine: str) -> None:
    with pytest.raises(ValidationError, match="webauthn_origins"):
        reglages(env, webauthn_rp_id="notre-popote.fr", webauthn_origins=origine)


@pytest.mark.parametrize("env", ["essai", "prod"])
@pytest.mark.parametrize("rp_id", ["localhost", "127.0.0.1", "fr", "*.notre-popote.fr", "Notre-Popote.fr"])
def test_hors_local_un_rp_id_local_ou_mal_forme_echoue(env: str, rp_id: str) -> None:
    with pytest.raises(ValidationError, match="webauthn_rp_id"):
        reglages(env, webauthn_rp_id=rp_id, webauthn_origins="https://notre-popote.fr")


@pytest.mark.parametrize(
    ("rp_id", "origine"),
    [
        ("notre-popote.fr", "https://autre.fr"),  # autre domaine
        ("notre-popote.fr", "https://evilnotre-popote.fr"),  # suffixe sans frontière de point
        ("essai.notre-popote.fr", "https://notre-popote.fr"),  # le RP ID est plus précis que l'origine
        ("notre-popote.fr", "https://popote-web-essai.moncompte.workers.dev"),  # un aperçu
    ],
)
def test_le_rp_id_est_le_suffixe_de_chaque_origine_sinon_le_demarrage_echoue(
    rp_id: str, origine: str
) -> None:
    with pytest.raises(ValidationError, match="webauthn_rp_id"):
        reglages("essai", webauthn_rp_id=rp_id, webauthn_origins=origine)


@pytest.mark.parametrize(
    "origine",
    [
        "https://notre-popote.fr/",  # le navigateur n'écrit pas la barre finale
        "https://notre-popote.fr/chemin",
        "https://notre-popote.fr?a=1",
        "https://notre-popote.fr#f",
        "https://u:p@notre-popote.fr",
        "https://Notre-Popote.fr",
        "https://notre-popote.fr:443",  # le port par défaut n'est jamais écrit
        "ftp://notre-popote.fr",
        "notre-popote.fr",
    ],
)
def test_une_origine_qui_n_est_pas_celle_que_le_navigateur_ecrit_echoue(origine: str) -> None:
    with pytest.raises(ValidationError, match="webauthn_origins"):
        reglages("prod", webauthn_rp_id="notre-popote.fr", webauthn_origins=origine)


def test_en_local_http_ne_passe_que_pour_localhost() -> None:
    assert reglages("local", webauthn_origins="http://localhost:3000").origines_webauthn == {
        "http://localhost:3000"
    }
    for origine in ("http://127.0.0.1:5173", "http://popote.example", "http://localhost.evil.example"):
        with pytest.raises(ValidationError, match="webauthn_origins"):
            reglages("local", webauthn_origins=origine)


def test_en_local_un_rp_id_adresse_ip_echoue() -> None:
    with pytest.raises(ValidationError, match="webauthn_rp_id"):
        reglages("local", webauthn_rp_id="127.0.0.1")


def test_l_erreur_de_configuration_ne_depend_pas_de_la_forme_de_la_liste() -> None:
    # Les blancs autour d'une virgule sont ignorés ; une liste vide ou à trou est une erreur.
    configuration = reglages("local", webauthn_origins=" http://localhost:5173 ,http://localhost:3000 ")
    assert configuration.origines_webauthn == {"http://localhost:5173", "http://localhost:3000"}
    for liste in (",", "http://localhost:5173,,http://localhost:3000"):
        with pytest.raises(ValidationError, match="webauthn_origins"):
            reglages("local", webauthn_origins=liste)


def test_une_valeur_vide_vaut_absente_comme_les_autres_reglages() -> None:
    valeurs: dict[str, Any] = {"webauthn_rp_id": "", "webauthn_origins": ""}
    configuration = Settings.model_validate({"env": "local"} | valeurs)
    assert configuration.rp_id_webauthn == "localhost"
    assert configuration.origines_webauthn == {"http://localhost:5173"}


@pytest.mark.parametrize("env", ["essai", "prod"])
@pytest.mark.parametrize(
    "domaine",
    [
        "workers.dev",  # un suffixe public : le RP ID d'un aperçu de fusion
        "co.uk",  # un suffixe public d'un autre pays
        "popote-web-essai.moncompte.workers.dev",  # l'aperçu lui-même, en toutes lettres
        "autre.example",
        "evilnotre-popote.fr",
        "notre-popote.fr.evil.example",
        "fr",
    ],
)
def test_hors_local_le_rp_id_est_le_domaine_de_popote_ou_l_un_de_ses_sous_domaines(
    env: str, domaine: str
) -> None:
    with pytest.raises(ValidationError, match="webauthn_rp_id"):
        reglages(
            env, webauthn_rp_id=domaine, webauthn_origins=f"https://popote-web-essai.moncompte.{domaine}"
        )
    with pytest.raises(ValidationError, match="webauthn_rp_id"):
        reglages(env, webauthn_rp_id=domaine, webauthn_origins=f"https://{domaine}")


def test_hors_local_un_sous_domaine_de_popote_passe() -> None:
    configuration = reglages(
        "essai", webauthn_rp_id="essai.notre-popote.fr", webauthn_origins="https://app.essai.notre-popote.fr"
    )
    assert configuration.origines_webauthn == {"https://app.essai.notre-popote.fr"}


@pytest.mark.parametrize(
    ("env", "origine"),
    [
        ("local", "http://localhost:0"),  # le port 0 n'existe pas
        ("local", "http://evillocalhost:5173"),  # `localhost` à la frontière d'un point seulement
        ("local", "http://notlocalhost"),
        ("prod", "https://a_b.notre-popote.fr"),  # `_` n'est pas une lettre d'un nom d'hôte
        ("prod", "https://-a.notre-popote.fr"),
        ("prod", "https://notre-popote.fr."),
    ],
)
def test_le_controle_d_une_origine_de_cle_refuse_ces_formes(env: str, origine: str) -> None:
    with pytest.raises(ValueError):
        hote_de_l_origine_de_cle(origine, Env(env))


def test_un_sous_domaine_de_localhost_passe_en_local() -> None:
    assert hote_de_l_origine_de_cle("http://app.localhost:5173", Env.local) == "app.localhost"


def test_en_local_le_port_par_defaut_ne_s_ecrit_pas_et_un_rp_id_sans_point_echoue() -> None:
    with pytest.raises(ValidationError, match="webauthn_origins"):
        reglages("local", webauthn_origins="http://localhost:80")
    with pytest.raises(ValidationError, match="webauthn_origins"):
        reglages("local", webauthn_rp_id="localhost", webauthn_origins="https://localhost:443")
    with pytest.raises(ValidationError, match="webauthn_rp_id"):
        reglages("local", webauthn_rp_id="fr", webauthn_origins="https://notre-popote.fr")
