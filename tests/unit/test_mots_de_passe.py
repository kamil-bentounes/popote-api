import pytest

from popote_api.security.mots_de_passe import (
    CodeDeDefaut,
    candidats_de_connexion,
    normalise,
    verifie_nouveau,
)

A_LARGE = "\N{FULLWIDTH LATIN SMALL LETTER A}"  # 3 octets en UTF-8, un « a » après NFKC


def codes(mot_de_passe: str) -> list[CodeDeDefaut]:
    return [d.code for d in verifie_nouveau(mot_de_passe)]


# --- longueur en caractères -------------------------------------------------------------------------


def test_quatorze_caracteres_sont_refuses() -> None:
    assert codes("a" * 14) == [CodeDeDefaut.trop_court]


def test_quinze_caracteres_sont_acceptes() -> None:
    assert codes("a" * 15) == []


def test_soixante_quatre_caracteres_ascii_sont_acceptes() -> None:
    assert codes("a" * 64) == []


def test_soixante_cinq_caracteres_ascii_sont_refuses_sans_double_defaut() -> None:
    assert codes("a" * 65) == [CodeDeDefaut.trop_long]


def test_la_longueur_se_compte_en_points_de_code_apres_nfkc() -> None:
    # 15 lettres pleine largeur = 15 caractères ; 14 lettres + 1 combinant composé = 15 aussi.
    assert codes(A_LARGE * 15) == []
    assert codes(A_LARGE * 14) == [CodeDeDefaut.trop_court]
    assert codes("e\N{COMBINING ACUTE ACCENT}" * 15) == []  # « é » décomposé : 2 points de code, 1 après NFKC
    assert codes("e\N{COMBINING ACUTE ACCENT}" * 14) == [CodeDeDefaut.trop_court]


# --- longueur en octets -----------------------------------------------------------------------------


def test_soixante_quatre_caracteres_de_deux_octets_sont_refuses_pour_les_octets() -> None:
    assert codes("é" * 64) == [CodeDeDefaut.trop_d_octets]


def test_soixante_douze_octets_sont_acceptes_et_soixante_treize_refuses() -> None:
    assert codes("é" * 36) == []  # 72 octets
    assert codes("é" * 35 + "abc") == [CodeDeDefaut.trop_d_octets]  # 73 octets, 38 caractères


# --- normalisation ----------------------------------------------------------------------------------


def test_pleine_largeur_est_ramenee_a_l_ascii() -> None:
    assert normalise("\N{FULLWIDTH LATIN CAPITAL LETTER A}\N{FULLWIDTH DIGIT ONE}") == "A1"


def test_e_accent_compose_et_decompose_sont_identiques() -> None:
    assert normalise("é") == normalise("e\N{COMBINING ACUTE ACCENT}")


def test_un_mot_de_passe_ascii_est_inchange() -> None:
    assert normalise("Cheval-Agrafe 42!") == "Cheval-Agrafe 42!"


# --- caractères interdits ---------------------------------------------------------------------------


def test_le_caractere_nul_est_un_defaut() -> None:
    assert codes("a" * 20 + "\x00") == [CodeDeDefaut.caractere_nul]


def test_un_substitut_isole_est_un_defaut_et_non_une_exception() -> None:
    assert codes("a" * 20 + "\ud800") == [CodeDeDefaut.non_encodable]


def test_un_substitut_isole_dans_un_mot_de_passe_court_cumule_les_defauts() -> None:
    assert codes("\ud800") == [CodeDeDefaut.trop_court, CodeDeDefaut.non_encodable]


# --- espaces et composition -------------------------------------------------------------------------


def test_quinze_espaces_sont_acceptes_et_ne_sont_pas_rognes() -> None:
    assert codes(" " * 15) == []
    assert normalise(" " * 15) == " " * 15


@pytest.mark.parametrize(
    "mot_de_passe", ["a" * 15, "1" * 15, "!" * 15, "ÉÉÉÉÉÉÉÉÉÉÉÉÉÉÉ", "motdepassecourt!!!"]
)
def test_aucune_regle_de_composition(mot_de_passe: str) -> None:
    assert codes(mot_de_passe) == []


# --- forme du défaut --------------------------------------------------------------------------------


def test_le_defaut_porte_le_pointeur_demande_et_ne_recopie_pas_le_mot_de_passe() -> None:
    secret = "Court-test"  # 10 caractères
    (defaut,) = verifie_nouveau(secret, pointeur="/new_password")
    assert defaut.pointeur == "/new_password"
    assert defaut.en_erreur_de_champ() == {"pointer": "/new_password", "message": defaut.message}
    assert secret not in defaut.message
    assert secret not in repr(defaut)


def test_le_pointeur_par_defaut_est_password() -> None:
    assert verifie_nouveau("court")[0].pointeur == "/password"


# --- candidats de connexion -------------------------------------------------------------------------


def test_un_mot_de_passe_deja_normalise_n_a_qu_un_candidat() -> None:
    assert candidats_de_connexion("Cheval-Agrafe 42!") == ("Cheval-Agrafe 42!",)


def test_les_deux_formes_sont_rendues_quand_elles_different_la_normalisee_d_abord() -> None:
    brut = A_LARGE + " de passe é"
    assert candidats_de_connexion(brut) == (normalise(brut), brut)


def test_un_candidat_de_soixante_treize_octets_est_ecarte_et_jamais_tronque() -> None:
    trop_long = "a" * 73
    assert candidats_de_connexion(trop_long) == ()
    assert candidats_de_connexion("a" * 72) == ("a" * 72,)


def test_seule_la_forme_brute_trop_longue_est_ecartee() -> None:
    # Brut : 25 caractères pleine largeur = 75 octets (écarté) ; normalisé : 25 octets.
    brut = A_LARGE * 25
    assert candidats_de_connexion(brut) == ("a" * 25,)


@pytest.mark.parametrize("mot_de_passe", ["a\x00b", "a\ud800b"])
def test_un_candidat_inutilisable_est_ecarte_sans_exception(mot_de_passe: str) -> None:
    assert candidats_de_connexion(mot_de_passe) == ()
