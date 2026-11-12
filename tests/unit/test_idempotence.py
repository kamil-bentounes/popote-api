"""La lecture de `Idempotency-Key` (RFC 9651, sf-string) et l'empreinte d'une requête."""

import pytest

from popote_api.errors import Probleme
from popote_api.security.idempotence import empreinte_de_la_requete, lit_la_cle


@pytest.mark.parametrize(
    ("valeur", "cle"),
    [
        ('"a"', "a"),
        ('"8e03978e-40d5-43e8-bc93-6894a57f9324"', "8e03978e-40d5-43e8-bc93-6894a57f9324"),
        ('"avec des espaces"', "avec des espaces"),
        ('" "', " "),
        ('"a,b;c=d"', "a,b;c=d"),
        ('"un \\"guillemet\\""', 'un "guillemet"'),
        ('"une barre \\\\ inverse"', "une barre \\ inverse"),
        ('"!#[]~"', "!#[]~"),
        ('"' + "x" * 255 + '"', "x" * 255),
        ('"' + '\\"' * 255 + '"', '"' * 255),  # 510 signes écrits, 255 une fois les échappements retirés
    ],
)
def test_lit_la_cle_rend_le_contenu_de_la_chaine(valeur: str, cle: str) -> None:
    assert lit_la_cle([valeur]) == cle


def test_lit_la_cle_sans_en_tete_leve_cle_idempotence_manquante() -> None:
    with pytest.raises(Probleme) as erreur:
        lit_la_cle([])
    assert (erreur.value.status, erreur.value.code) == (400, "cle_idempotence_manquante")


@pytest.mark.parametrize(
    "valeurs",
    [
        ["abc"],  # pas de guillemets : c'est un jeton, pas une chaîne
        ["'abc'"],
        ['""'],  # vide
        ['"x' + "x" * 255 + '"'],  # 256 signes
        ['"' + '\\"' * 256 + '"'],  # 256 une fois les échappements retirés
        ['"abc'],  # guillemet fermant manquant
        ['abc"'],
        ['"a"b"'],  # guillemet nu au milieu
        ['"a\\b"'],  # échappement hors de `"` et `\`
        ['"a\\"'],  # le guillemet fermant est échappé : la chaîne n'est pas fermée
        ['"é"'],  # hors ASCII
        ['"a\tb"'],  # tabulation
        ['"a\x7fb"'],  # DEL
        ['"a"; b=1'],  # paramètre : l'en-tête est une chaîne seule
        ['"a", "b"'],  # liste
        ['"a"', '"b"'],  # deux lignes d'en-tête
        ['"a"', '"a"'],
        [""],
        [" "],
        ['"' + "x" * 5000 + '"'],
    ],
    ids=lambda valeurs: repr(valeurs)[:40],
)
def test_lit_la_cle_mal_formee_leve_cle_idempotence_invalide(valeurs: list[str]) -> None:
    with pytest.raises(Probleme) as erreur:
        lit_la_cle(valeurs)
    assert (erreur.value.status, erreur.value.code) == (400, "cle_idempotence_invalide")


def test_l_empreinte_est_un_sha256_hexadecimal_stable() -> None:
    empreinte = empreinte_de_la_requete("POST", b"/api/v1/x", b"", b"{}")
    assert empreinte == empreinte_de_la_requete("POST", b"/api/v1/x", b"", b"{}")
    assert len(empreinte) == 64
    assert set(empreinte) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    "autre",
    [
        ("PATCH", b"/api/v1/x", b"", b"{}"),
        ("POST", b"/api/v1/y", b"", b"{}"),
        ("POST", b"/api/v1/x", b"a=1", b"{}"),
        ("POST", b"/api/v1/x", b"", b'{"a":1}'),
        ("POST", b"/api/v1/x", b"", b""),
    ],
    ids=["methode", "chemin", "requete", "corps", "corps-vide"],
)
def test_l_empreinte_change_avec_chaque_partie(autre: tuple[str, bytes, bytes, bytes]) -> None:
    assert empreinte_de_la_requete("POST", b"/api/v1/x", b"", b"{}") != empreinte_de_la_requete(*autre)


def test_l_empreinte_ne_confond_pas_le_chemin_et_la_requete() -> None:
    assert empreinte_de_la_requete("POST", b"/a", b"b", b"") != empreinte_de_la_requete(
        "POST", b"/ab", b"", b""
    )
