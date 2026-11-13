"""`adresse_valide` : une liste fermée de caractères ASCII, jamais un motif (T13, B24)."""

import pytest

from popote_api.infra.comptes import adresse_valide
from popote_api.security.empreintes import Empreintes, email_normalise


@pytest.mark.parametrize("adresse", ["a@test.local", "lea.martin+x@mail.example.org", "victime-%@test.local"])
def test_adresses_acceptees(adresse: str) -> None:
    assert adresse_valide(adresse)


@pytest.mark.parametrize(
    "adresse",
    [
        "",
        "a",
        "a@",
        "@b.c",
        "a@@b.c",
        "a@b@c.d",
        "a b@c.d",
        "a\x00@c.d",
        "a\n@c.d",
        "é@c.d",
        "a@é.d",
        "a..b@c.d",
        "a@-b.c",
        "a@b..c",
        "a" * 250 + "@b.cd",
    ],
)
def test_adresses_refusees(adresse: str) -> None:
    assert not adresse_valide(adresse)


def test_la_forme_pleine_largeur_se_normalise_avant_le_controle() -> None:
    pleine = "".join(chr(ord(c) + 0xFEE0) if c != "@" and c != "." else c for c in "a@test.local")
    assert not adresse_valide(pleine)
    assert adresse_valide(email_normalise(pleine))


def test_la_cle_de_lien_ne_se_confond_ni_avec_l_empreinte_ni_entre_deux_liens() -> None:
    from pydantic import SecretStr

    empreintes = Empreintes(SecretStr("p" * 32))
    un, deux = b"\x01" * 32, b"\x02" * 32
    assert empreintes.cle_lien_requise(un) != un
    assert empreintes.cle_lien_requise(un) != empreintes.cle_lien_requise(deux)
    assert empreintes.cle_lien_requise(un) == empreintes.cle_lien_requise(un)
