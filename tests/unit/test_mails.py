"""L'interface d'envoi (0.4bis S3) : messages, textes, prénom affiché, boîte de test, route retirée."""

import asyncio
import json
from datetime import UTC, datetime, tzinfo
from pathlib import Path

import pytest
from _commun import reglages

from popote_api.infra import mails_textes as textes
from popote_api.infra.mails import (
    BoiteDeTest,
    MailAbsent,
    MailIndisponible,
    MessageCode,
    MessageInvitation,
    TypeDeMail,
    cree_envoi_mail,
    envoie_sans_remonter,
)
from popote_api.main import create_app

ADRESSE = "claire@example.org"
LIEN = "https://essai.notre-popote.fr/invitation#jeton-secret"
EXPIRE_LE = datetime(2026, 11, 20, 10, 30, tzinfo=UTC)


def code(valeur: str = "123456") -> MessageCode:
    return MessageCode(ADRESSE, valeur, 10, EXPIRE_LE)


def invitation(prenom_invite: str = "Claire", prenom_hote: str = "Marc") -> MessageInvitation:
    return MessageInvitation(ADRESSE, prenom_invite, prenom_hote, LIEN, EXPIRE_LE)


# --- Les textes ---------------------------------------------------------------------------------------


def test_texte_du_code_est_exact() -> None:
    assert textes.texte_du_code(code()) == (
        "Ton code Popote est 123456. Il est valable 10 minutes. Si tu n'as rien demandé, ignore ce message."
    )


def test_texte_de_l_invitation_est_exact() -> None:
    assert textes.texte_de_l_invitation(invitation()) == (
        "Bonjour Claire,\n\n"
        "Marc t'invite à rejoindre son foyer sur Popote.\n\n"
        f"Pour accepter, ouvre ce lien : {LIEN}\n\n"
        "Ce lien est valable jusqu'au 20/11/2026 à 11 h 30. Si tu en as reçu un autre avant, "
        "celui-ci le remplace. Si tu ne connais pas cette personne, ignore ce message."
    )


def test_la_date_de_l_invitation_est_celle_de_paris() -> None:
    minuit_passe = datetime(2026, 11, 20, 23, 30, tzinfo=UTC)  # 00 h 30 le 21 à Paris
    message = MessageInvitation(ADRESSE, "Claire", "Marc", LIEN, minuit_passe)
    assert "jusqu'au 21/11/2026 à 00 h 30" in textes.texte_de_l_invitation(message)


@pytest.mark.parametrize(
    "objet",
    [textes.OBJET_DU_CODE, textes.OBJET_DE_L_INVITATION_DE_REPLI, textes.objet_de_l_invitation("Marc")],
)
def test_un_objet_fait_au_moins_dix_caracteres_et_ne_porte_aucun_secret(objet: str) -> None:
    assert len(objet) >= 10
    assert "123456" not in objet
    assert LIEN not in objet


def test_le_code_n_est_jamais_dans_l_objet() -> None:
    assert not any(c.isdigit() for c in textes.OBJET_DU_CODE)


# --- Le prénom ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prenom",
    [
        "Marc<b>",
        "marc@x.fr",
        "a:b",
        "http://x",
        "Marc2",
        "Marc\nClaire",
        "Marc\tClaire",
        "",
        "   ",
        "-",
        "' '",
        "A" * 31,
    ],
)
def test_un_prenom_non_presentable_donne_le_repli(prenom: str) -> None:
    assert textes.prenom_affichable(prenom) == textes.REPLI_DU_PRENOM


PRENOMS_LATINS = [
    "Marc",
    "Élodie",
    "Jean-Pierre",
    "O'Brien",
    "D\u2019Artagnan",
    "Anne Sophie",
    "Zoë",
    "Łukasz",
    "A" * 30,
]
PRENOMS_NON_LATINS = ["किरण", "प्रिया", "அருண்", "สมศักดิ์", "مُحَمَّد"]


@pytest.mark.parametrize("prenom", PRENOMS_LATINS + PRENOMS_NON_LATINS)
def test_un_prenom_presentable_est_garde(prenom: str) -> None:
    assert textes.prenom_affichable(prenom) == prenom


@pytest.mark.parametrize(
    "prenom",
    [
        "\u3164",
        "\u115f\u1160",
        "\uffa0 ",
        "\u0301",
        "\u0301Marc",
        "Marc \u0301",
        "M" + "\u0301" * 5,
        "Marc\u200d",
    ],
)
def test_un_prenom_invisible_ou_aux_marques_abusives_donne_le_repli(prenom: str) -> None:
    assert textes.prenom_affichable(prenom) == textes.REPLI_DU_PRENOM


def test_les_blancs_de_bord_d_un_prenom_sont_retires() -> None:
    assert textes.prenom_affichable("  Marc \t") == "Marc"
    assert textes.prenom_valide("\u00a0Marc ") == "Marc"


@pytest.mark.parametrize(("marques", "attendu"), [(3, True), (4, False)])
def test_trois_marques_combinantes_de_suite_passent_la_quatrieme_non(marques: int, attendu: bool) -> None:
    prenom = "x" + "\u0301" * marques  # « x » n'a pas de forme précomposée : NFC ne retire aucune marque
    assert (textes.prenom_valide(prenom) is not None) is attendu
    assert textes.MARQUES_DE_SUITE_MAX == 3


def test_un_prenom_decompose_est_recompose() -> None:
    assert textes.prenom_affichable("E\u0301loi") == "\u00c9loi"  # « E » + accent combinant devient « É »


def test_un_prenom_non_presentable_n_entre_pas_dans_l_invitation() -> None:
    texte = textes.texte_de_l_invitation(invitation(prenom_invite="x@y.fr", prenom_hote="Marc<script>"))
    assert "<script>" not in texte and "x@y.fr" not in texte
    assert texte.startswith("Bonjour,\n\n")
    assert "Quelqu'un t'invite à rejoindre son foyer" in texte


# --- Les messages -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valeur", ["12345a", "", " 123456", "١٢٣٤٥٦", "1234\n56", "12345", "1234567", "0" * 1000, 123456, None]
)
def test_un_code_qui_n_est_pas_fait_de_six_chiffres_est_refuse(valeur: object) -> None:
    with pytest.raises(ValueError, match="six chiffres"):
        MessageCode(ADRESSE, valeur, 10, EXPIRE_LE)  # type: ignore[arg-type]


@pytest.mark.parametrize("validite", [0, -1, True, 1.5, "10"])
def test_une_validite_qui_n_est_pas_un_entier_positif_est_refusee(validite: object) -> None:
    with pytest.raises(ValueError, match="validite_min"):
        MessageCode(ADRESSE, "123456", validite, EXPIRE_LE)  # type: ignore[arg-type]


def test_une_validite_d_une_minute_s_ecrit_au_singulier() -> None:
    assert "valable 1 minute." in textes.texte_du_code(MessageCode(ADRESSE, "123456", 1, EXPIRE_LE))


@pytest.mark.parametrize("destinataire", ["", "a@b.fr\r\nBcc: x@y.fr", "a b@c.fr", 3])
def test_un_destinataire_vide_ou_avec_un_blanc_est_refuse(destinataire: object) -> None:
    with pytest.raises(ValueError, match="destinataire"):
        MessageCode(destinataire, "123456", 10, EXPIRE_LE)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="destinataire"):
        MessageInvitation(destinataire, "Claire", "Marc", LIEN, EXPIRE_LE)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "lien", ["", "https://x\n\nHello", "ftp://x", "javascript:alert(1)", "https://x y", "https://"]
)
def test_un_lien_qui_n_est_pas_un_lien_web_sans_blanc_est_refuse(lien: str) -> None:
    with pytest.raises(ValueError, match="lien web"):
        MessageInvitation(ADRESSE, "Claire", "Marc", lien, EXPIRE_LE)


class _FuseauSansDecalage(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None


@pytest.mark.parametrize(
    "quand",
    [datetime(2026, 11, 20, 10, 30), datetime(2026, 11, 20, 10, 30, tzinfo=_FuseauSansDecalage())],
    ids=["naif", "fuseau_sans_decalage"],
)
def test_une_invitation_sans_decalage_horaire_est_refusee(quand: datetime) -> None:
    with pytest.raises(ValueError, match="fuseau"):
        MessageInvitation(ADRESSE, "Claire", "Marc", LIEN, quand)


@pytest.mark.parametrize("message", [code(), invitation()])
def test_le_repr_d_un_message_ne_porte_ni_adresse_ni_code_ni_lien(message: object) -> None:
    rendu = f"{message!r} {message}"
    for secret in (ADRESSE, "123456", "jeton-secret", "Claire", "Marc"):
        assert secret not in rendu


# --- Les réalisations ---------------------------------------------------------------------------------


async def test_la_boite_de_test_garde_les_deux_listes() -> None:
    boite = BoiteDeTest()
    await boite.envoie_le_code(code())
    await boite.envoie_l_invitation(invitation())
    assert [m.code for m in boite.codes] == ["123456"]
    assert [m.lien for m in boite.invitations] == [LIEN]


async def test_la_boite_de_test_en_panne_leve_mail_indisponible() -> None:
    boite = BoiteDeTest(en_panne=True)
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(code())
    with pytest.raises(MailIndisponible):
        await boite.envoie_l_invitation(invitation())
    assert boite.codes == [] and boite.invitations == []


async def test_envoie_sans_remonter_rend_vrai_quand_le_message_part() -> None:
    boite = BoiteDeTest()
    assert await envoie_sans_remonter(boite.envoie_le_code, code(), TypeDeMail.code) is True
    assert len(boite.codes) == 1


@pytest.mark.parametrize("erreur", [MailIndisponible("x"), OverflowError("a@b.fr"), RuntimeError("123456")])
async def test_envoie_sans_remonter_journalise_le_type_seul_et_ne_remonte_pas(
    erreur: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    async def tombe(message: MessageCode) -> None:
        raise erreur

    assert await envoie_sans_remonter(tombe, code(), TypeDeMail.code) is False
    assert f"Mail (code) non envoyé : {type(erreur).__name__}" in caplog.text
    assert ADRESSE not in caplog.text and "123456" not in caplog.text and "a@b.fr" not in caplog.text


async def test_envoie_sans_remonter_journalise_l_annulation_puis_la_laisse_remonter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def annule(message: MessageInvitation) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await envoie_sans_remonter(annule, invitation(), TypeDeMail.invitation)
    assert "Mail (invitation) : annulé pendant l'envoi, issue inconnue" in caplog.text
    assert "non envoyé" not in caplog.text
    assert ADRESSE not in caplog.text and LIEN not in caplog.text


@pytest.mark.parametrize("envoi", ["code", "invitation"])
async def test_sans_fournisseur_chaque_envoi_echoue_proprement(envoi: str) -> None:
    with pytest.raises(MailIndisponible, match="POPOTE_MAIL_PROVIDER=aucun") as erreur:
        if envoi == "code":
            await MailAbsent().envoie_le_code(code())
        else:
            await MailAbsent().envoie_l_invitation(invitation())
    assert ADRESSE not in str(erreur.value) and "123456" not in str(erreur.value)


@pytest.mark.parametrize(("fournisseur", "attendu"), [("local", BoiteDeTest), ("aucun", MailAbsent)])
def test_le_fournisseur_choisit_la_realisation(fournisseur: str, attendu: type) -> None:
    assert type(cree_envoi_mail(reglages("local", mail_provider=fournisseur))) is attendu


# --- La route retirée ---------------------------------------------------------------------------------

CHEMIN_RETIRE = "/api/v1/password-resets"


def test_la_demande_de_reinitialisation_n_est_plus_dans_le_registre_des_routes() -> None:
    chemins = {getattr(route, "path", "") for route in create_app(reglages("local")).routes}
    assert not [c for c in chemins if "password-reset" in c or "reinitialisation" in c]
    assert CHEMIN_RETIRE not in chemins


def test_la_demande_de_reinitialisation_n_est_plus_dans_le_contrat() -> None:
    contrat = json.loads((Path(__file__).parents[2] / "openapi.json").read_text())
    assert CHEMIN_RETIRE not in contrat["paths"]
    assert not [c for c in contrat["paths"] if "password-reset" in c]
    assert CHEMIN_RETIRE not in create_app(reglages("local")).openapi()["paths"]
