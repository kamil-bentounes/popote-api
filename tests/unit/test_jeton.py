import base64
import hashlib

import pytest

from popote_api.security.jeton import JetonMalFormeError, empreinte_du_jeton

OCTETS = bytes(range(32))
JETON = base64.urlsafe_b64encode(OCTETS).decode().rstrip("=")


def test_l_empreinte_est_le_sha256_des_32_octets_du_jeton() -> None:
    assert empreinte_du_jeton(JETON) == hashlib.sha256(OCTETS).digest()


def test_l_empreinte_n_est_pas_celle_du_texte_du_jeton() -> None:
    assert empreinte_du_jeton(JETON) != hashlib.sha256(JETON.encode()).digest()


@pytest.mark.parametrize(
    "jeton",
    [
        "",
        "abc",
        JETON[:-1],  # trop court
        JETON + "A",  # trop long
        JETON + "=",  # avec remplissage
        JETON[:-1] + "+",  # alphabet base64 standard
        JETON[:-1] + "/",
        JETON[:-1] + " ",
        JETON[:-1] + "é",
        "\x00" * 43,
        JETON[:-1] + "B",  # derniers bits non nuls : non canonique
    ],
    ids=[
        "vide",
        "court",
        "un_de_moins",
        "un_de_plus",
        "remplissage",
        "plus",
        "barre",
        "espace",
        "hors_ascii",
        "nul",
        "non_canonique",
    ],
)
def test_un_jeton_mal_forme_est_refuse(jeton: str) -> None:
    with pytest.raises(JetonMalFormeError):
        empreinte_du_jeton(jeton)


def test_l_erreur_ne_recopie_pas_le_jeton() -> None:
    mauvais = "secret-" + "x" * 10
    with pytest.raises(JetonMalFormeError) as erreur:
        empreinte_du_jeton(mauvais)
    assert mauvais not in str(erreur.value)
