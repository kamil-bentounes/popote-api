import pytest

from popote_api.security import signature
from popote_api.security.signature import RaisonDeRefus, SignatureRefusee

SECRET = b"i" * 32
T0 = 1_700_000_000
CORPS = b'{"a":1}'
# Calculé par pgcrypto (`extensions.hmac`, la base de `pg_cron`), pas par ce module : si l'un des deux
# change de format, ce vecteur le dit. Voir `docs/exploitation.md`.
T0_ARABE = "".join(chr(0x660 + int(chiffre)) for chiffre in str(T0))
VECTEUR_PGCRYPTO = "871a79ea98b4b7a55b8a6552756c12adaa3cb39d34fd35d426f4fe8b5aee1684"


def test_la_signature_suit_le_format_documente() -> None:
    assert signature.signe(SECRET, "POST", b"/internal/purges", CORPS, T0) == f"t={T0},v1={VECTEUR_PGCRYPTO}"


def test_la_methode_est_signee_en_majuscules() -> None:
    assert signature.signe(SECRET, "post", b"/internal/purges", CORPS, T0).endswith(VECTEUR_PGCRYPTO)


def test_l_en_tete_signe_est_relu_et_verifie() -> None:
    en_tete = signature.lit_l_en_tete(signature.signe(SECRET, "POST", b"/internal/purges", CORPS, T0), T0)
    signature.verifie([SECRET], en_tete, "POST", b"/internal/purges", CORPS)
    assert en_tete.instant == T0


@pytest.mark.parametrize(
    ("methode", "chemin", "corps"),
    [
        ("GET", b"/internal/purges", CORPS),
        ("POST", b"/internal/purge", CORPS),
        ("POST", b"/internal/purges", b""),
    ],
)
def test_une_requete_differente_n_est_pas_reconnue(methode: str, chemin: bytes, corps: bytes) -> None:
    en_tete = signature.lit_l_en_tete(signature.signe(SECRET, "POST", b"/internal/purges", CORPS, T0), T0)
    with pytest.raises(SignatureRefusee) as refus:
        signature.verifie([SECRET], en_tete, methode, chemin, corps)
    assert refus.value.raison is RaisonDeRefus.SIGNATURE_FAUSSE


def test_sans_secret_rien_n_est_reconnu() -> None:
    en_tete = signature.lit_l_en_tete(signature.signe(SECRET, "GET", b"/internal/x", b"", T0), T0)
    with pytest.raises(SignatureRefusee):
        signature.verifie([], en_tete, "GET", b"/internal/x", b"")


def test_la_fenetre_est_de_300_secondes_dans_les_deux_sens() -> None:
    valeur = signature.signe(SECRET, "GET", b"/internal/x", b"", T0)
    for maintenant in (T0 - 300, T0 + 300, T0 + 0.5):
        signature.lit_l_en_tete(valeur, maintenant)
    for maintenant in (T0 - 301, T0 + 300.5, T0 + 301):
        with pytest.raises(SignatureRefusee) as refus:
            signature.lit_l_en_tete(valeur, maintenant)
        assert refus.value.raison is RaisonDeRefus.HORS_FENETRE


def test_la_raison_du_refus_ne_porte_aucune_valeur_recue() -> None:
    with pytest.raises(SignatureRefusee) as refus:
        signature.lit_l_en_tete("t=1,v1=secret-recu", T0)
    assert str(refus.value) == "en_tete_mal_forme"


def _v1() -> str:
    return signature.signe(SECRET, "GET", b"/internal/x", b"", T0).split("v1=")[1]


@pytest.mark.parametrize(
    "valeur",
    [
        f"t={T0},t={T0},v1={'0' * 64}",
        f"t={T0_ARABE},v1={'0' * 64}",  # 1700000000 en chiffres arabes-indiens
        f"t={T0},v1={'0' * 64}," * (signature.NOMBRE_MAX_DE_V1 + 1),
        f"t={T0},v1={'0' * 64},v1={'0' * 64},v1={'0' * 64},v1={'0' * 64},v1={'0' * 64}",
        f"t={T0},v1={_v1()},inconnu=1",
        f"t={T0},v1={_v1().upper()}",
        f"t={T0} ,v1={_v1()}",
        f"t={T0},v1={_v1()}" + " " * 600,
    ],
)
def test_un_en_tete_mal_forme_est_refuse_pour_sa_forme(valeur: str) -> None:
    with pytest.raises(SignatureRefusee) as refus:
        signature.lit_l_en_tete(valeur, T0)
    assert refus.value.raison is RaisonDeRefus.EN_TETE_MAL_FORME
