"""La lecture de `Idempotency-Key` (RFC 9651, sf-string) et l'empreinte d'une requête."""

import json

import pytest

from popote_api.errors import Probleme
from popote_api.security.idempotence import (
    RouteIdempotente,
    empreinte_de_la_requete,
    lit_la_cle,
    sans_les_champs_secrets,
)


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


def test_les_champs_secrets_sont_remis_a_null_et_le_reste_ne_bouge_pas() -> None:
    corps = json.dumps({"id": "i", "token": "SECRET", "n": 1, "z": "é"}).encode()
    rendu = sans_les_champs_secrets(corps, ("token",))
    assert b"SECRET" not in rendu
    assert json.loads(rendu) == {"id": "i", "token": None, "n": 1, "z": "é"}


@pytest.mark.parametrize("corps", [b"pas du json", b"[1]", b'{"autre": 1}', b'"token"'])
def test_une_route_a_champs_secrets_qui_ne_rend_pas_le_champ_est_une_faute(corps: bytes) -> None:
    with pytest.raises(RuntimeError):
        sans_les_champs_secrets(corps, ("token",))


def test_avec_construit_une_classe_qui_porte_les_champs_et_la_classe_de_base_n_en_a_pas() -> None:
    classe = RouteIdempotente.avec(champs_secrets=("token", "code"))
    assert issubclass(classe, RouteIdempotente)
    assert classe.champs_secrets == ("token", "code")
    assert RouteIdempotente.champs_secrets == ()


def test_avec_sans_champ_est_refuse() -> None:
    with pytest.raises(ValueError, match="champ secret"):
        RouteIdempotente.avec(champs_secrets=())
