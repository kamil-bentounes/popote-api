"""Les clés HMAC du journal : une forme unique de l'adresse, l'IPv6 par /64, aucun poivre dans un `repr`."""

import pytest
from _commun import POIVRE, reglages
from pydantic import SecretStr

from popote_api.security.empreintes import Empreintes, email_normalise, ip_canonique

POIVRE_B = "q" * 32
# « a@x.fr » en pleine largeur (U+FF41…), en majuscules et suivi d'une espace idéographique.
PLEINE_LARGEUR = "\uff41\uff20\uff58\uff0e\uff46\uff52"
PLEINE_LARGEUR_MAJ = "\uff21\uff20\uff38\uff0e\uff26\uff32\u3000"


def empreintes(poivre: str | None = POIVRE) -> Empreintes:
    return Empreintes(SecretStr(poivre) if poivre else None)


@pytest.mark.parametrize(
    "variante",
    ["A@x.fr ", " a@x.fr", "A@X.FR", "a@x.fr\t", PLEINE_LARGEUR, PLEINE_LARGEUR_MAJ, "a@x.fr\u00a0"],
)
def test_cle_compte_est_la_meme_pour_toutes_les_formes_d_une_adresse(variante: str) -> None:
    assert empreintes().cle_compte(variante) == empreintes().cle_compte("a@x.fr")


@pytest.mark.parametrize("variante", ["A@x.fr ", PLEINE_LARGEUR, "É@x.fr", "é@x.fr", "İ@x.fr", "a@x.fr"])
def test_email_normalise_est_idempotent(variante: str) -> None:
    une_fois = email_normalise(variante)
    assert email_normalise(une_fois) == une_fois


def test_email_normalise_met_en_minuscules_et_retire_les_espaces_de_bord_seulement() -> None:
    assert email_normalise(" A@X.fr ") == "a@x.fr"
    assert email_normalise("a b@x.fr") == "a b@x.fr"


def test_e_accent_compose_et_decompose_donnent_la_meme_cle() -> None:
    assert empreintes().cle_compte("é@x.fr") == empreintes().cle_compte("é@x.fr")


def test_cle_compte_a_32_octets_et_differe_d_un_compte_a_l_autre() -> None:
    cle = empreintes().cle_compte("a@x.fr")
    assert cle is not None
    assert len(cle) == 32
    assert cle != empreintes().cle_compte("b@x.fr")


def test_cle_compte_depend_du_poivre() -> None:
    assert empreintes(POIVRE).cle_compte("a@x.fr") != empreintes(POIVRE_B).cle_compte("a@x.fr")


def test_cle_compte_accepte_un_substitut_isole_sans_lever() -> None:
    assert empreintes().cle_compte("a\ud800@x.fr") != empreintes().cle_compte("a@x.fr")


def test_une_cle_de_compte_n_est_pas_une_cle_d_ip() -> None:
    assert empreintes().cle_compte("1.2.3.4") != empreintes().cle_ip("1.2.3.4")


def test_deux_ip_equivalentes_ont_la_meme_cle() -> None:
    assert empreintes().cle_ip("::ffff:1.2.3.4") == empreintes().cle_ip("1.2.3.4")
    assert empreintes().cle_ip("2001:DB8:0:0:0:0:0:1") == empreintes().cle_ip("2001:db8::1")


def test_cle_ip_a_32_octets_et_une_ipv4_reste_entiere() -> None:
    cle = empreintes().cle_ip("1.2.3.4")
    assert cle is not None
    assert len(cle) == 32
    assert cle != empreintes().cle_ip("1.2.3.5")


def test_deux_adresses_du_meme_slash_64_ont_la_meme_cle() -> None:
    assert empreintes().cle_ip("2001:db8:aaaa:bbbb::1") == empreintes().cle_ip(
        "2001:db8:aaaa:bbbb:ffff:ffff:ffff:ffff"
    )


def test_deux_slash_64_differents_ont_des_cles_differentes() -> None:
    assert empreintes().cle_ip("2001:db8:aaaa:bbbb::1") != empreintes().cle_ip("2001:db8:aaaa:bbbc::1")


def test_un_identifiant_de_zone_ipv6_ne_change_pas_la_cle() -> None:
    assert empreintes().cle_ip("fe80::1%eth0") == empreintes().cle_ip("fe80::1")


def test_sans_adresse_la_cle_est_commune_et_distincte_de_toute_adresse() -> None:
    sans_ip = empreintes().cle_ip(None)
    assert sans_ip is not None
    assert sans_ip == empreintes().cle_ip(None)
    assert sans_ip != empreintes().cle_ip("0.0.0.0")  # noqa: S104
    assert ip_canonique(None) == "sans-ip"


@pytest.mark.parametrize("texte", ["", "pas-une-ip", "1.2.3", "1.2.3.4.5", "sans-ip"])
def test_une_ip_mal_formee_leve_valueerror(texte: str) -> None:
    with pytest.raises(ValueError, match="does not appear to be"):
        empreintes().cle_ip(texte)


def test_sans_poivre_les_deux_cles_manquent() -> None:
    sans = empreintes(None)
    assert sans.disponible is False
    assert sans.cle_compte("a@x.fr") is None
    assert sans.cle_ip("1.2.3.4") is None


def test_le_poivre_n_apparait_dans_aucun_repr() -> None:
    poivre = "tres-secret-" + "z" * 24
    fabrique = Empreintes(SecretStr(poivre))
    assert poivre not in repr(fabrique)
    assert poivre not in str(fabrique)
    assert poivre not in repr(reglages("essai", identity_pepper=poivre))
    assert poivre not in str(reglages("essai", identity_pepper=poivre).model_dump())


def test_en_local_sans_poivre_il_est_tire_au_hasard_par_processus() -> None:
    a, b = Empreintes.depuis(reglages("local")), Empreintes.depuis(reglages("local"))
    assert a.disponible is True
    assert a.cle_compte("a@x.fr") == a.cle_compte("a@x.fr")
    assert a.cle_compte("a@x.fr") != b.cle_compte("a@x.fr")


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_sans_poivre_les_cles_manquent(env: str) -> None:
    assert Empreintes.depuis(reglages(env, identity_pepper=None)).disponible is False


def test_avec_le_meme_poivre_deux_processus_calculent_la_meme_cle() -> None:
    a, b = Empreintes.depuis(reglages("prod")), Empreintes.depuis(reglages("prod"))
    assert a.cle_compte("a@x.fr") == b.cle_compte("a@x.fr")
