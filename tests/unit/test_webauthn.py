"""L'enveloppe WebAuthn : les options, l'enregistrement et la connexion, et tous les refus.

Pas de navigateur : `_authentificateur.py` fabrique les réponses. Le défi à usage unique (le rejeu) est tenu
par la base (S8b) ; ici, une réponse n'est valable que pour le défi qu'on donne à la vérification.
"""

import copy
import random
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import cbor2
import pytest
from _authentificateur import Algorithme, Authentificateur
from _commun import reglages
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from popote_api.infra.webauthn import (
    TAILLE_DU_DEFI,
    CleDeConnexion,
    CleEnregistree,
    CleExistante,
    CleStockeeIllisible,
    CompteurDeCleRegresse,
    OptionsDeCeremonie,
    PartieDeConfiance,
    ReponseDeCleRefusee,
    defi_de_la_reponse,
    identifiant_de_la_cle,
    options_d_enregistrement,
    options_de_connexion,
    verifie_l_enregistrement,
    verifie_la_connexion,
)

PARTIE = PartieDeConfiance("notre-popote.fr", "Popote", frozenset({"https://notre-popote.fr"}))
ORIGINE = "https://notre-popote.fr"
PERSONNE = bytes(range(64))
AUTRE_PERSONNE = bytes(range(64, 128))

ORIGINES_ETRANGERES = [
    "https://evil.example",
    "https://notre-popote.fr.evil.example",
    "https://evil.example/https://notre-popote.fr",
    "http://notre-popote.fr",  # le schéma compte
    "https://notre-popote.fr:8443",  # le port compte
    "https://essai.notre-popote.fr",  # une autre origine du même domaine
    "https://sub.notre-popote.fr",
    "https://NOTRE-POPOTE.FR",
    "http://localhost:5173",
    "null",
    "",
]


CADRES_ETRANGERS: list[dict[str, Any]] = [
    {"cross_origin": True},
    {"cross_origin": "false"},  # la bibliothèque lirait une chaîne non vide comme vraie
    {"cross_origin": 0},
    {"top_origin": "https://notre-popote.fr"},
    {"top_origin": "https://x.example"},
]


@contextmanager
def refuse(motif: str) -> Iterator[None]:
    """Un refus, et pour CE motif : le texte de l'erreur de la bibliothèque (la cause) le dit."""
    with pytest.raises(ReponseDeCleRefusee) as erreur:
        yield
    cause = erreur.value.__cause__
    assert motif in (str(cause) if cause else str(erreur.value))


def nouvelle_cle(**champs: Any) -> Authentificateur:
    return Authentificateur(rp_id="notre-popote.fr", origine=ORIGINE, **champs)


def options_de_creation(partie: PartieDeConfiance = PARTIE, **champs: Any) -> OptionsDeCeremonie:
    valeurs: dict[str, Any] = {
        "identifiant_utilisateur": PERSONNE,
        "nom_d_utilisateur": "personne",
        "nom_affiche": "Personne",
    }
    return options_d_enregistrement(partie, **(valeurs | champs))


def enregistre(
    authentificateur: Authentificateur, partie: PartieDeConfiance = PARTIE, **surcharges: Any
) -> CleEnregistree:
    options = options_de_creation(partie)
    reponse = authentificateur.cree(options.options, **surcharges)
    return verifie_l_enregistrement(partie, reponse=reponse, defi=options.defi)


def cle_de_connexion(enregistree: CleEnregistree, **champs: Any) -> CleDeConnexion:
    valeurs: dict[str, Any] = {
        "identifiant": enregistree.identifiant,
        "cle_publique": enregistree.cle_publique,
        "compteur": enregistree.compteur,
        "peut_etre_sauvegardee": enregistree.peut_etre_sauvegardee,
        "identifiant_utilisateur": PERSONNE,
    }
    return CleDeConnexion(**(valeurs | champs))


def connecte(
    authentificateur: Authentificateur,
    cle: CleDeConnexion,
    partie: PartieDeConfiance = PARTIE,
    **surcharges: Any,
) -> Any:
    options = options_de_connexion(partie)
    reponse = authentificateur.signe(options.options, **surcharges)
    return verifie_la_connexion(partie, reponse=reponse, defi=options.defi, cle=cle)


# ---------------------------------------------------------------------------------------------------------
# Les options : ce que le navigateur reçoit
# ---------------------------------------------------------------------------------------------------------


def test_les_options_d_enregistrement_exigent_une_cle_decouvrable_verifiee_sans_attestation() -> None:
    options = options_de_creation().options
    assert options["rp"] == {"name": "Popote", "id": "notre-popote.fr"}
    assert options["authenticatorSelection"] == {
        "residentKey": "required",
        "requireResidentKey": True,
        "userVerification": "required",
    }
    assert options["attestation"] == "none"
    assert options["timeout"] == 300_000
    assert [parametre["alg"] for parametre in options["pubKeyCredParams"]] == [-8, -7, -257]


def test_le_defi_fait_32_octets_et_change_a_chaque_demande() -> None:
    premieres = [options_de_creation(), options_de_connexion(PARTIE)]
    secondes = [options_de_creation(), options_de_connexion(PARTIE)]
    for options in premieres + secondes:
        assert len(options.defi) == TAILLE_DU_DEFI == 32
        assert base64url_to_bytes(options.options["challenge"]) == options.defi
    assert len({options.defi for options in premieres + secondes}) == 4


def test_l_identifiant_d_utilisateur_est_celui_qu_on_donne_et_sans_lien_avec_le_nom() -> None:
    options = options_de_creation(
        identifiant_utilisateur=PERSONNE, nom_d_utilisateur="nom@exemple.fr"
    ).options
    assert base64url_to_bytes(options["user"]["id"]) == PERSONNE
    assert options["user"]["name"] == "nom@exemple.fr"
    assert options["user"]["displayName"] == "Personne"


@pytest.mark.parametrize("identifiant", [b"", bytes(65)])
def test_un_identifiant_d_utilisateur_hors_de_1_a_64_octets_est_une_erreur(identifiant: bytes) -> None:
    with pytest.raises(ValueError, match="identifiant"):
        options_de_creation(identifiant_utilisateur=identifiant)


def test_les_cles_existantes_sont_exclues_avec_leurs_transports_connus() -> None:
    existantes = [CleExistante(b"a" * 32, ("internal", "hybrid", "inconnu")), CleExistante(b"b" * 32)]
    exclues = options_de_creation(cles_existantes=existantes).options["excludeCredentials"]
    assert [base64url_to_bytes(cle["id"]) for cle in exclues] == [b"a" * 32, b"b" * 32]
    assert exclues[0]["transports"] == ["internal", "hybrid"]
    assert "transports" not in exclues[1]


def test_sans_cle_existante_rien_n_est_exclu() -> None:
    assert options_de_creation().options["excludeCredentials"] == []


def test_les_options_de_connexion_ne_nomment_aucune_cle_et_exigent_la_verification() -> None:
    options = options_de_connexion(PARTIE).options
    assert options["rpId"] == "notre-popote.fr"
    assert options["allowCredentials"] == []
    assert options["userVerification"] == "required"
    assert options["timeout"] == 300_000


def test_la_partie_de_confiance_vient_des_reglages_de_l_environnement() -> None:
    prod = PartieDeConfiance.des_reglages(reglages("prod"))
    assert (prod.identifiant, prod.nom, prod.origines) == ("notre-popote.fr", "Popote", {ORIGINE})
    assert "http://localhost:5173" not in prod.origines


# ---------------------------------------------------------------------------------------------------------
# L'enregistrement
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("algorithme", list(Algorithme))
def test_un_enregistrement_valide_rend_la_cle_a_ecrire(algorithme: Algorithme) -> None:
    authentificateur = nouvelle_cle(algorithme=algorithme, transports=("hybrid", "internal"))
    cle = enregistre(authentificateur)
    assert cle.identifiant == authentificateur.identifiant
    assert cle.cle_publique == authentificateur.cle_publique_cose()
    assert cle.compteur == 0
    assert cle.verification_initialisee is True
    assert cle.aaguid == "00010203-0405-0607-0809-0a0b0c0d0e0f"
    assert cle.transports == ("hybrid", "internal")
    assert (cle.peut_etre_sauvegardee, cle.est_sauvegardee) == (False, False)


def test_l_enregistrement_garde_les_indicateurs_de_sauvegarde_et_le_compteur() -> None:
    cle = enregistre(nouvelle_cle(peut_etre_sauvegardee=True, est_sauvegardee=True, compteur=7))
    assert (cle.peut_etre_sauvegardee, cle.est_sauvegardee, cle.compteur) == (True, True, 7)


def test_l_enregistrement_ne_garde_que_les_transports_connus_sans_doublon() -> None:
    cle = enregistre(nouvelle_cle(transports=("usb", "usb", "nfc", "quantique")))
    assert cle.transports == ("nfc", "usb")


@pytest.mark.parametrize("origine", ORIGINES_ETRANGERES)
def test_l_enregistrement_refuse_une_origine_etrangere(origine: str) -> None:
    with refuse("origin"):
        enregistre(nouvelle_cle(), origine=origine)


@pytest.mark.parametrize("rp_id", ["evil.example", "essai.notre-popote.fr", "popote.fr", "localhost"])
def test_l_enregistrement_refuse_un_autre_rp_id(rp_id: str) -> None:
    with refuse("RP ID"):
        enregistre(nouvelle_cle(), rp_id=rp_id)


def test_l_enregistrement_refuse_un_defi_qui_n_est_pas_celui_des_options() -> None:
    options = options_de_creation()
    reponse = nouvelle_cle().cree(options.options, defi=secrets.token_bytes(32))
    with refuse("challenge"):
        verifie_l_enregistrement(PARTIE, reponse=reponse, defi=options.defi)
    # Le défi d'une autre cérémonie, valide en soi, ne vaut pas non plus.
    autres_options = options_de_creation()
    reponse_valide = nouvelle_cle().cree(options.options)
    with refuse("challenge"):
        verifie_l_enregistrement(PARTIE, reponse=reponse_valide, defi=autres_options.defi)


@pytest.mark.parametrize("defi", [b"", b"a" * 31])
def test_un_defi_trop_court_donne_a_la_verification_est_une_erreur_du_code_appelant(defi: bytes) -> None:
    reponse = nouvelle_cle().cree(options_de_creation().options)
    with pytest.raises(ValueError, match="défi"):
        verifie_l_enregistrement(PARTIE, reponse=reponse, defi=defi)


@pytest.mark.parametrize(("indicateur", "motif"), [("uv", "verification"), ("up", "presence")])
def test_l_enregistrement_exige_la_presence_et_la_verification_de_la_personne(
    indicateur: str, motif: str
) -> None:
    with refuse(motif):
        enregistre(nouvelle_cle(), **{indicateur: False})


def test_l_enregistrement_refuse_une_cle_sauvegardee_sans_etre_eligible() -> None:
    with refuse("backed up"):
        enregistre(nouvelle_cle(), be=False, bs=True)


def test_l_enregistrement_refuse_le_type_d_une_assertion() -> None:
    with refuse("client data type"):
        enregistre(nouvelle_cle(), type_de_donnees="webauthn.get")


@pytest.mark.parametrize("cadre", CADRES_ETRANGERS)
def test_l_enregistrement_refuse_un_cadre_d_une_autre_origine(cadre: dict[str, Any]) -> None:
    with pytest.raises(ReponseDeCleRefusee, match="cadre"):
        enregistre(nouvelle_cle(), **cadre)


def test_l_enregistrement_admet_une_reponse_sans_cross_origin() -> None:
    # Le champ est facultatif dans les données du client (W3C § 5.8.1) : l'absence vaut « faux ».
    assert enregistre(nouvelle_cle(), cross_origin=None).compteur == 0


@pytest.mark.parametrize(
    "format_d_attestation", ["packed", "fido-u2f", "tpm", "apple", "android-key", "inconnu"]
)
def test_l_enregistrement_refuse_toute_attestation_autre_que_none(format_d_attestation: str) -> None:
    with pytest.raises(ReponseDeCleRefusee, match="attestation"):
        enregistre(nouvelle_cle(), format_d_attestation=format_d_attestation)


def test_l_enregistrement_refuse_une_attestation_none_qui_porte_un_contenu() -> None:
    with pytest.raises(ReponseDeCleRefusee):
        enregistre(nouvelle_cle(), declaration={"sig": b"x"})


def test_l_enregistrement_refuse_un_identifiant_brut_qui_differe_de_l_identifiant() -> None:
    with pytest.raises(ReponseDeCleRefusee):
        enregistre(nouvelle_cle(), identifiant_brut_different=True)


def test_l_enregistrement_refuse_un_identifiant_d_attestation_qui_differe_de_celui_du_navigateur() -> None:
    authentificateur = nouvelle_cle()
    with pytest.raises(ReponseDeCleRefusee, match="incohérent"):
        enregistre(authentificateur, identifiant_de_l_attestation=secrets.token_bytes(32))


@pytest.mark.parametrize(
    "cle_cose",
    [
        b"\x00",  # un entier, pas une clé
        b"\xa0",  # une clé vide
        bytes.fromhex("a1010a"),  # un type de clé inconnu
        bytes.fromhex("a50102032720012158200000"),  # coordonnées tronquées
        bytes.fromhex("a301020326"),  # sans coordonnées
        b"\x04" + b"\x00" * 10,  # un point non comprimé trop court
    ],
)
def test_l_enregistrement_refuse_une_cle_publique_illisible(cle_cose: bytes) -> None:
    with pytest.raises(ReponseDeCleRefusee):
        enregistre(nouvelle_cle(), cle_cose=cle_cose)


@pytest.mark.parametrize(("taille", "admis"), [(15, False), (16, True), (1023, True), (1024, False)])
def test_la_taille_de_l_identifiant_de_cle_est_bornee(taille: int, admis: bool) -> None:
    authentificateur = nouvelle_cle(identifiant=secrets.token_bytes(taille))
    if admis:
        assert enregistre(authentificateur).identifiant == authentificateur.identifiant
    else:
        with pytest.raises(ReponseDeCleRefusee, match="taille"):
            enregistre(authentificateur)


# ---------------------------------------------------------------------------------------------------------
# La connexion
# ---------------------------------------------------------------------------------------------------------


def une_cle_enregistree(**champs: Any) -> tuple[Authentificateur, CleEnregistree]:
    authentificateur = nouvelle_cle(**champs)
    return authentificateur, enregistre(authentificateur)


@pytest.mark.parametrize("algorithme", list(Algorithme))
def test_une_assertion_valide_rend_le_nouveau_compteur(algorithme: Algorithme) -> None:
    authentificateur, enregistree = une_cle_enregistree(algorithme=algorithme)
    resultat = connecte(authentificateur, cle_de_connexion(enregistree))
    assert (resultat.compteur, resultat.est_sauvegardee, resultat.verification_utilisateur) == (
        1,
        False,
        True,
    )


def test_une_assertion_rend_l_etat_de_sauvegarde_courant() -> None:
    authentificateur, enregistree = une_cle_enregistree(peut_etre_sauvegardee=True)
    resultat = connecte(authentificateur, cle_de_connexion(enregistree), bs=True)
    assert resultat.est_sauvegardee is True  # l'état (BS) change au fil du temps ; l'éligibilité (BE) jamais


@pytest.mark.parametrize("origine", ORIGINES_ETRANGERES)
def test_la_connexion_refuse_une_origine_etrangere(origine: str) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with refuse("origin"):
        connecte(authentificateur, cle_de_connexion(enregistree), origine=origine)


@pytest.mark.parametrize("rp_id", ["evil.example", "essai.notre-popote.fr", "localhost"])
def test_la_connexion_refuse_un_autre_rp_id(rp_id: str) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with refuse("RP ID"):
        connecte(authentificateur, cle_de_connexion(enregistree), rp_id=rp_id)


def test_la_connexion_refuse_un_defi_qui_n_est_pas_celui_des_options() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    options, autres_options = options_de_connexion(PARTIE), options_de_connexion(PARTIE)
    reponse = authentificateur.signe(options.options)
    with refuse("challenge"):
        verifie_la_connexion(
            PARTIE, reponse=reponse, defi=autres_options.defi, cle=cle_de_connexion(enregistree)
        )
    reponse_changee = authentificateur.signe(options.options, defi=secrets.token_bytes(32))
    with refuse("challenge"):
        verifie_la_connexion(
            PARTIE, reponse=reponse_changee, defi=options.defi, cle=cle_de_connexion(enregistree)
        )


def test_la_connexion_refuse_une_signature_fausse() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with refuse("signature"):
        connecte(authentificateur, cle_de_connexion(enregistree), signature_fausse=True)


def test_la_connexion_refuse_la_signature_d_une_autre_cle_sous_le_meme_identifiant() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    imitation = nouvelle_cle(identifiant=authentificateur.identifiant)
    imitation.identifiant_utilisateur = PERSONNE
    with refuse("signature"):
        connecte(imitation, cle_de_connexion(enregistree))


def test_la_connexion_refuse_la_reponse_d_une_autre_cle_que_celle_lue_en_base() -> None:
    _, enregistree = une_cle_enregistree()
    autre, _ = une_cle_enregistree()
    with pytest.raises(ReponseDeCleRefusee, match="pas la clé attendue"):
        connecte(autre, cle_de_connexion(enregistree))


def test_la_connexion_refuse_un_identifiant_brut_qui_differe_de_l_identifiant() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with pytest.raises(ReponseDeCleRefusee):
        connecte(authentificateur, cle_de_connexion(enregistree), identifiant_brut_different=True)


@pytest.mark.parametrize(("indicateur", "motif"), [("uv", "verification"), ("up", "not present")])
def test_la_connexion_exige_la_presence_et_la_verification_de_la_personne(
    indicateur: str, motif: str
) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with refuse(motif):
        connecte(authentificateur, cle_de_connexion(enregistree), **{indicateur: False})


def test_la_connexion_refuse_le_type_d_un_enregistrement() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with refuse("client data type"):
        connecte(authentificateur, cle_de_connexion(enregistree), type_de_donnees="webauthn.create")


@pytest.mark.parametrize("cadre", CADRES_ETRANGERS)
def test_la_connexion_refuse_un_cadre_d_une_autre_origine(cadre: dict[str, Any]) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with pytest.raises(ReponseDeCleRefusee, match="cadre"):
        connecte(authentificateur, cle_de_connexion(enregistree), **cadre)


@pytest.mark.parametrize("poignee", [None, AUTRE_PERSONNE, PERSONNE[:-1], PERSONNE + b"x", b""])
def test_la_connexion_exige_le_user_handle_de_la_personne(poignee: bytes | None) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with pytest.raises(ReponseDeCleRefusee, match="userHandle"):
        connecte(authentificateur, cle_de_connexion(enregistree), identifiant_utilisateur=poignee)


def test_la_connexion_lie_la_cle_a_la_personne_de_la_base_pas_a_celle_de_la_reponse() -> None:
    # L'authentificateur a mémorisé `PERSONNE` ; la base dit que la clé est à `AUTRE_PERSONNE`.
    authentificateur, enregistree = une_cle_enregistree()
    with pytest.raises(ReponseDeCleRefusee, match="userHandle"):
        connecte(authentificateur, cle_de_connexion(enregistree, identifiant_utilisateur=AUTRE_PERSONNE))


@pytest.mark.parametrize(
    ("eligible_en_base", "be_de_la_reponse"),
    [(False, True), (True, False)],
)
def test_l_eligibilite_a_la_sauvegarde_ne_change_jamais(
    eligible_en_base: bool, be_de_la_reponse: bool
) -> None:
    authentificateur, enregistree = une_cle_enregistree(peut_etre_sauvegardee=eligible_en_base)
    with pytest.raises(ReponseDeCleRefusee, match="éligibilité"):
        connecte(authentificateur, cle_de_connexion(enregistree), be=be_de_la_reponse, bs=False)


def test_la_connexion_refuse_une_cle_sauvegardee_sans_etre_eligible() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with refuse("backed up"):
        connecte(authentificateur, cle_de_connexion(enregistree), be=False, bs=True)


# ---- le compteur de signature (W3C § 7.2, § 6.1.1) ----


@pytest.mark.parametrize(
    ("compteur_en_base", "compteur_de_la_reponse"),
    [(0, 1), (0, 0), (5, 6), (5, 1000)],  # une clé synchronisée reste à 0 ; une autre croît
)
def test_un_compteur_qui_croit_ou_une_cle_qui_reste_a_zero_passe(
    compteur_en_base: int, compteur_de_la_reponse: int
) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    cle = cle_de_connexion(enregistree, compteur=compteur_en_base)
    assert connecte(authentificateur, cle, compteur=compteur_de_la_reponse).compteur == compteur_de_la_reponse


@pytest.mark.parametrize(
    ("compteur_en_base", "compteur_de_la_reponse"),
    [(5, 5), (5, 4), (5, 0), (1, 1), (1, 0)],
)
def test_un_compteur_qui_ne_croit_pas_est_refuse_comme_signal_de_clonage(
    compteur_en_base: int, compteur_de_la_reponse: int
) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    cle = cle_de_connexion(enregistree, compteur=compteur_en_base)
    with pytest.raises(CompteurDeCleRegresse):
        connecte(authentificateur, cle, compteur=compteur_de_la_reponse)


def test_un_compteur_en_recul_sous_une_signature_fausse_n_est_pas_un_signal() -> None:
    # Sans signature valide, le recul ne dit rien de la clé : refus ordinaire, jamais `CompteurDeCleRegresse`
    # (S9 n'écrit `cle_suspecte` que sur ce dernier, et un inconnu ne doit pas pouvoir en provoquer).
    authentificateur, enregistree = une_cle_enregistree()
    cle = cle_de_connexion(enregistree, compteur=5)
    with pytest.raises(ReponseDeCleRefusee) as erreur:
        connecte(authentificateur, cle, compteur=2, signature_fausse=True)
    assert not isinstance(erreur.value, CompteurDeCleRegresse)


@pytest.mark.parametrize(
    "refus",
    [
        {"origine": "https://evil.example"},
        {"uv": False},
        {"identifiant_utilisateur": AUTRE_PERSONNE},
        {"be": True},
    ],
)
def test_un_compteur_en_recul_sous_un_autre_defaut_n_est_pas_un_signal(refus: dict[str, Any]) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    cle = cle_de_connexion(enregistree, compteur=5)
    with pytest.raises(ReponseDeCleRefusee) as erreur:
        connecte(authentificateur, cle, compteur=2, **refus)
    assert not isinstance(erreur.value, CompteurDeCleRegresse)


# ---- le message d'un refus ne porte rien de la réponse ----


def _formes(secret: bytes) -> list[str]:
    """Toutes les écritures sous lesquelles un octet secret pourrait finir dans un message."""
    return [bytes_to_base64url(secret), repr(secret), str(secret), secret.hex(), secret.decode("latin-1")]


@pytest.mark.parametrize(
    "refus",
    [
        {"signature_fausse": True},
        {"origine": "https://evil.example"},
        {"uv": False},
        {"identifiant_utilisateur": AUTRE_PERSONNE},
        {"compteur": 0, "be": True},
        {"cross_origin": True},
    ],
)
def test_un_refus_ne_recopie_ni_identifiant_ni_signature_ni_defi_ni_poignee(refus: dict[str, Any]) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    options = options_de_connexion(PARTIE)
    reponse = authentificateur.signe(options.options, **refus)
    with pytest.raises(ReponseDeCleRefusee) as erreur:
        verifie_la_connexion(PARTIE, reponse=reponse, defi=options.defi, cle=cle_de_connexion(enregistree))
    secrets_a_cacher = [
        authentificateur.identifiant,
        base64url_to_bytes(reponse["response"]["signature"]),
        options.defi,
        PERSONNE,
        AUTRE_PERSONNE,
        enregistree.cle_publique,
    ]
    ecritures = [str(erreur.value), repr(erreur.value), str(erreur.value.args)]
    for secret in secrets_a_cacher:
        for forme in _formes(secret):
            assert all(forme not in ecriture for ecriture in ecritures)


# ---- les réponses mal formées : toujours un refus, jamais une autre exception ----


def _sans(champ: str) -> Any:
    def retire(reponse: dict[str, Any]) -> Any:
        reponse = copy.deepcopy(reponse)
        reponse.pop(champ, None)
        if isinstance(reponse.get("response"), dict):
            reponse["response"].pop(champ, None)
        return reponse

    return retire


def _remplace(chemin: tuple[str, ...], valeur: Any) -> Any:
    def remplace(reponse: dict[str, Any]) -> Any:
        reponse = copy.deepcopy(reponse)
        cible = reponse
        for etape in chemin[:-1]:
            cible = cible[etape]
        cible[chemin[-1]] = valeur
        return reponse

    return remplace


DEFORMATIONS_COMMUNES: list[Any] = [
    lambda _: None,
    lambda _: [],
    lambda _: "pas du json",
    lambda _: {},
    lambda _: {"id": 1, "rawId": 2, "type": "public-key", "response": 3},
    _sans("id"),
    _sans("rawId"),
    _sans("response"),
    _remplace(("type",), "password"),
    _remplace(("type",), None),
    _remplace(("id",), None),
    _remplace(("rawId",), "***"),
    _remplace(("rawId",), "a"),
    _remplace(("response", "clientDataJSON"), "***"),
    _remplace(("response", "clientDataJSON"), ""),
    _remplace(("response", "clientDataJSON"), "bnVsbA"),  # `null`
    _remplace(("response", "clientDataJSON"), "e30"),  # `{}`
    _remplace(("response", "clientDataJSON"), "W10"),  # `[]`
    _remplace(("response", "clientDataJSON"), 12),
]
DEFORMATIONS_D_ENREGISTREMENT: list[Any] = [
    _remplace(("response", "attestationObject"), "AAAA"),
    _remplace(("response", "attestationObject"), ""),
    _remplace(("response", "attestationObject"), "oA"),  # un dictionnaire CBOR vide
    _remplace(("response", "attestationObject"), "gA"),  # un tableau CBOR vide
    _sans("attestationObject"),
]
DEFORMATIONS_DE_CONNEXION: list[Any] = [
    _remplace(("response", "authenticatorData"), "AAAA"),
    _remplace(("response", "authenticatorData"), ""),
    _remplace(("response", "authenticatorData"), None),
    _remplace(("response", "signature"), ""),
    _remplace(("response", "signature"), "AAAA"),
    _remplace(("response", "signature"), 7),
    _remplace(("response", "userHandle"), 7),
    _remplace(("response", "userHandle"), "***"),
    _sans("authenticatorData"),
    _sans("signature"),
]


@pytest.mark.parametrize("deforme", DEFORMATIONS_COMMUNES + DEFORMATIONS_D_ENREGISTREMENT)
def test_une_reponse_d_enregistrement_mal_formee_est_un_refus_et_rien_d_autre(deforme: Any) -> None:
    options = options_de_creation()
    valide = nouvelle_cle().cree(options.options)
    with pytest.raises(ReponseDeCleRefusee):
        verifie_l_enregistrement(PARTIE, reponse=deforme(valide), defi=options.defi)


@pytest.mark.parametrize("deforme", DEFORMATIONS_COMMUNES + DEFORMATIONS_DE_CONNEXION)
def test_une_assertion_mal_formee_est_un_refus_et_rien_d_autre(deforme: Any) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    options = options_de_connexion(PARTIE)
    valide = authentificateur.signe(options.options)
    with pytest.raises(ReponseDeCleRefusee):
        verifie_la_connexion(
            PARTIE, reponse=deforme(valide), defi=options.defi, cle=cle_de_connexion(enregistree)
        )


@pytest.mark.parametrize("illisible", [b"\x00", b"\xa0", b"\x04" + b"\x00" * 10, b"", b"\xff"])
def test_une_cle_publique_illisible_en_base_n_est_pas_un_refus_mais_une_donnee_abimee(
    illisible: bytes,
) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    with pytest.raises(CleStockeeIllisible) as erreur:
        connecte(authentificateur, cle_de_connexion(enregistree, cle_publique=illisible))
    assert not isinstance(erreur.value, ReponseDeCleRefusee)


def test_une_cle_publique_incoherente_en_base_est_une_donnee_abimee() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    incoherente = cbor2.dumps({1: 3, 3: -7, -1: b"\x01" * 256, -2: b"\x01\x00\x01"})  # du RSA annoncé ES256
    with pytest.raises(CleStockeeIllisible):
        connecte(authentificateur, cle_de_connexion(enregistree, cle_publique=incoherente))


@pytest.mark.parametrize("reponse", [None, [], {}, {"rawId": 1}, {"id": "a", "rawId": "***"}])
def test_l_identifiant_d_une_reponse_mal_formee_est_un_refus(reponse: Any) -> None:
    with pytest.raises(ReponseDeCleRefusee):
        identifiant_de_la_cle(reponse)


def test_l_identifiant_d_une_reponse_est_celui_de_la_cle() -> None:
    authentificateur, enregistree = une_cle_enregistree()
    reponse = authentificateur.signe(options_de_connexion(PARTIE).options)
    assert identifiant_de_la_cle(reponse) == enregistree.identifiant


# ---- une partie de confiance : rien d'autre que ses origines ----


def test_hors_local_une_reponse_de_localhost_est_refusee_de_bout_en_bout() -> None:
    prod = PartieDeConfiance.des_reglages(reglages("prod"))
    authentificateur = Authentificateur(rp_id="notre-popote.fr", origine="http://localhost:5173")
    options = options_d_enregistrement(
        prod, identifiant_utilisateur=PERSONNE, nom_d_utilisateur="p", nom_affiche="P"
    )
    with pytest.raises(ReponseDeCleRefusee):
        verifie_l_enregistrement(prod, reponse=authentificateur.cree(options.options), defi=options.defi)


def test_une_partie_a_plusieurs_origines_les_admet_toutes_et_elles_seules() -> None:
    partie = PartieDeConfiance(
        "notre-popote.fr", "Popote", frozenset({"https://notre-popote.fr", "https://essai.notre-popote.fr"})
    )
    for origine in ("https://notre-popote.fr", "https://essai.notre-popote.fr"):
        assert enregistre(nouvelle_cle(), partie=partie, origine=origine).compteur == 0
    with pytest.raises(ReponseDeCleRefusee):
        enregistre(nouvelle_cle(), partie=partie, origine="https://sub.notre-popote.fr")


# ---- des octets quelconques dans la réponse : toujours un refus, jamais une autre exception ----


def _abime(reponse: dict[str, Any], champ: str, graine: int) -> dict[str, Any]:
    """Change, ajoute ou retire un octet du champ (en base64url), au hasard mais de façon reproductible."""
    hasard = random.Random(graine)
    octets = bytearray(base64url_to_bytes(reponse["response"][champ]))
    match hasard.randrange(3):
        case 0:
            octets[hasard.randrange(len(octets))] ^= 1 << hasard.randrange(8)
        case 1:
            del octets[hasard.randrange(len(octets)) :]
        case _:
            octets.insert(hasard.randrange(len(octets)), hasard.randrange(256))
    abimee = copy.deepcopy(reponse)
    abimee["response"][champ] = bytes_to_base64url(bytes(octets))
    return abimee


@pytest.mark.parametrize("champ", ["attestationObject", "clientDataJSON"])
@pytest.mark.parametrize("graine", range(150))
def test_un_enregistrement_aux_octets_abimes_est_un_refus_ou_reste_valide(champ: str, graine: int) -> None:
    options = options_de_creation()
    valide = nouvelle_cle().cree(options.options)
    try:
        cle = verifie_l_enregistrement(PARTIE, reponse=_abime(valide, champ, graine), defi=options.defi)
    except ReponseDeCleRefusee:
        return
    assert cle.identifiant == base64url_to_bytes(valide["id"])  # un octet sans effet (un blanc du JSON)


@pytest.mark.parametrize("champ", ["authenticatorData", "clientDataJSON", "signature"])
@pytest.mark.parametrize("graine", range(150))
def test_une_assertion_aux_octets_abimes_est_un_refus_ou_reste_valide(champ: str, graine: int) -> None:
    authentificateur, enregistree = une_cle_enregistree()
    options = options_de_connexion(PARTIE)
    valide = authentificateur.signe(options.options)
    try:
        verifie_la_connexion(
            PARTIE,
            reponse=_abime(valide, champ, graine),
            defi=options.defi,
            cle=cle_de_connexion(enregistree),
        )
    except ReponseDeCleRefusee:
        return
    assert champ == "clientDataJSON"  # seul un octet sans effet passe (un blanc du JSON)


# ---- des entrées démesurées : un refus, jamais une exception qui finirait en 500 ----

IMBRICATIONS = [b"[" * 20_000, b'{"a":' * 20_000]


@pytest.mark.parametrize("donnees", IMBRICATIONS)
def test_un_json_imbrique_a_l_exces_dans_les_donnees_du_client_est_un_refus(donnees: bytes) -> None:
    options = options_de_creation()
    valide = nouvelle_cle().cree(options.options)
    valide["response"]["clientDataJSON"] = bytes_to_base64url(donnees)
    with pytest.raises(ReponseDeCleRefusee):
        verifie_l_enregistrement(PARTIE, reponse=valide, defi=options.defi)
    authentificateur, enregistree = une_cle_enregistree()
    options_connexion = options_de_connexion(PARTIE)
    assertion = authentificateur.signe(options_connexion.options)
    assertion["response"]["clientDataJSON"] = bytes_to_base64url(donnees)
    with pytest.raises(ReponseDeCleRefusee):
        verifie_la_connexion(
            PARTIE, reponse=assertion, defi=options_connexion.defi, cle=cle_de_connexion(enregistree)
        )
    with pytest.raises(ReponseDeCleRefusee):
        defi_de_la_reponse(assertion)


@pytest.mark.parametrize(
    "auth_data", [2**70, 2**40, -(2**70), 1.5, True, None, "texte", [1, 2], {"a": 1}, b"", b"\x00" * 36]
)
def test_un_auth_data_qui_n_est_pas_une_chaine_d_octets_valide_est_un_refus(auth_data: Any) -> None:
    # `bytes(2**40)` alloue un téraoctet : le type se contrôle avant la bibliothèque.
    options = options_de_creation()
    attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
    reponse = nouvelle_cle().cree(options.options, attestation_brute=attestation)
    with pytest.raises(ReponseDeCleRefusee):
        verifie_l_enregistrement(PARTIE, reponse=reponse, defi=options.defi)


@pytest.mark.parametrize("contenu", [None, 12, [1], "none", {"fmt": "none"}, {"authData": b"x"}])
def test_une_attestation_qui_n_est_pas_un_objet_complet_est_un_refus(contenu: Any) -> None:
    options = options_de_creation()
    reponse = nouvelle_cle().cree(options.options, attestation_brute=cbor2.dumps(contenu))
    with pytest.raises(ReponseDeCleRefusee, match="attestation"):
        verifie_l_enregistrement(PARTIE, reponse=reponse, defi=options.defi)


@pytest.mark.parametrize("declaration", [[1], "x", 0, {"sig": b"x"}])
def test_une_attestation_none_dont_la_declaration_n_est_pas_vide_est_un_refus(declaration: Any) -> None:
    with pytest.raises(ReponseDeCleRefusee, match="attestation"):
        enregistre(nouvelle_cle(), declaration=declaration)


# ---- la clé publique d'un enregistrement : chargeable et cohérente avec son algorithme ----


def _cose_ec2(alg: int, crv: int = 1, x: bytes | None = None, y: bytes | None = None) -> bytes:
    nombres = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
    return cbor2.dumps(
        {
            1: 2,
            3: alg,
            -1: crv,
            -2: nombres.x.to_bytes(32, "big") if x is None else x,
            -3: nombres.y.to_bytes(32, "big") if y is None else y,
        }
    )


def _cose_rsa(alg: int, bits: int, e: int = 65537) -> bytes:
    n = rsa.generate_private_key(public_exponent=e, key_size=bits).public_key().public_numbers().n
    return cbor2.dumps({1: 3, 3: alg, -1: n.to_bytes((bits + 7) // 8, "big"), -2: e.to_bytes(3, "big")})


def _cose_okp(alg: int, crv: int = 6) -> bytes:
    brute = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    return cbor2.dumps({1: 1, 3: alg, -1: crv, -2: brute})


CLES_INCOHERENTES = {
    "P-256 annoncée EdDSA": _cose_ec2(-8),
    "P-256 annoncée RS256": _cose_ec2(-257),
    "P-384 annoncée ES256": _cose_ec2(-7, crv=2),
    "point hors de la courbe": _cose_ec2(-7, x=b"\x01" * 32, y=b"\x02" * 32),
    "coordonnées courtes": _cose_ec2(-7, x=b"\x01" * 8, y=b"\x02" * 8),
    "Ed25519 annoncée ES256": _cose_okp(-7),
    "Ed25519 annoncée RS256": _cose_okp(-257),
    "Ed448 annoncée EdDSA": _cose_okp(-8, crv=7),
    "RSA annoncée ES256": _cose_rsa(-7, 2048),
    "RSA annoncée EdDSA": _cose_rsa(-8, 2048),
    "RSA de 1024 bits": _cose_rsa(-257, 1024),
    "RSA d'exposant 3": _cose_rsa(-257, 2048, e=3),
}


@pytest.mark.parametrize("cle_cose", CLES_INCOHERENTES.values(), ids=CLES_INCOHERENTES.keys())
def test_l_enregistrement_refuse_une_cle_publique_incoherente_ou_inutilisable(cle_cose: bytes) -> None:
    # La bibliothèque admet ces clés à l'enregistrement et les refuse ensuite à chaque connexion.
    with pytest.raises(ReponseDeCleRefusee):
        enregistre(nouvelle_cle(), cle_cose=cle_cose)


# ---- lire le défi annoncé, l'identifiant : bornes et refus ----


def test_le_defi_de_la_reponse_est_celui_du_client_pour_les_deux_ceremonies() -> None:
    options = options_de_creation()
    assert defi_de_la_reponse(nouvelle_cle().cree(options.options)) == options.defi
    authentificateur, _ = une_cle_enregistree()
    connexion = options_de_connexion(PARTIE)
    assert defi_de_la_reponse(authentificateur.signe(connexion.options)) == connexion.defi


@pytest.mark.parametrize("reponse", [None, [], {}, {"response": None}, {"response": {}}])
def test_le_defi_d_une_reponse_mal_formee_est_un_refus(reponse: Any) -> None:
    with pytest.raises(ReponseDeCleRefusee):
        defi_de_la_reponse(reponse)


@pytest.mark.parametrize("taille", [0, 15, 1024, 5000])
def test_l_identifiant_d_une_reponse_hors_des_bornes_est_un_refus(taille: int) -> None:
    reponse = nouvelle_cle().signe(options_de_connexion(PARTIE).options)
    reponse["rawId"] = reponse["id"] = bytes_to_base64url(bytes(taille))
    with pytest.raises(ReponseDeCleRefusee, match="taille"):
        identifiant_de_la_cle(reponse)


def test_un_defi_qui_n_est_pas_des_octets_est_une_erreur_du_code_appelant() -> None:
    reponse = nouvelle_cle().cree(options_de_creation().options)
    with pytest.raises(TypeError, match="défi"):
        verifie_l_enregistrement(PARTIE, reponse=reponse, defi="a" * 32)  # type: ignore[arg-type]


# ---- ce qui sort d'un refus ou d'un objet ne porte rien de secret ----


def test_un_refus_dit_le_type_de_sa_cause_sans_en_recopier_le_message() -> None:
    options = options_de_creation()
    reponse = nouvelle_cle().cree(options.options, origine="https://evil.example/" + "x" * 5000)
    with pytest.raises(ReponseDeCleRefusee) as erreur:
        verifie_l_enregistrement(PARTIE, reponse=reponse, defi=options.defi)
    assert erreur.value.type_de_la_cause == "InvalidRegistrationResponse"
    assert "evil.example" not in str(erreur.value)
    assert "evil.example" in str(erreur.value.__cause__)  # c'est bien ce qu'un journal ne doit pas écrire


def test_aucun_repr_ne_montre_un_identifiant_une_cle_ou_un_defi() -> None:
    authentificateur = nouvelle_cle()
    options = options_de_creation()
    enregistree = verifie_l_enregistrement(
        PARTIE, reponse=authentificateur.cree(options.options), defi=options.defi
    )
    existante = CleExistante(authentificateur.identifiant)
    de_connexion = cle_de_connexion(enregistree)
    secrets_a_cacher = [
        authentificateur.identifiant,
        enregistree.cle_publique,
        PERSONNE,
        options.defi,
    ]
    for objet in (options, enregistree, existante, de_connexion):
        texte = repr(objet)
        for secret in secrets_a_cacher:
            assert repr(secret) not in texte
            assert bytes_to_base64url(secret) not in texte
    assert enregistree.aaguid not in repr(enregistree)


# ---- la connexion admet chaque origine de la liste, et elles seules ----


def test_la_connexion_admet_chaque_origine_de_la_liste_et_elles_seules() -> None:
    partie = PartieDeConfiance(
        "notre-popote.fr", "Popote", frozenset({"https://notre-popote.fr", "https://essai.notre-popote.fr"})
    )
    for origine in sorted(partie.origines):
        authentificateur = nouvelle_cle()
        cle = cle_de_connexion(enregistre(authentificateur, partie=partie, origine=origine))
        assert connecte(authentificateur, cle, partie=partie, origine=origine).compteur == 1
    authentificateur = nouvelle_cle()
    cle = cle_de_connexion(enregistre(authentificateur, partie=partie))
    with refuse("origin"):
        connecte(authentificateur, cle, partie=partie, origine="https://sub.notre-popote.fr")
