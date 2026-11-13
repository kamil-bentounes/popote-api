"""L'interface d'envoi durcie (0.4bis S3b) : enveloppe, destinataire, lien, prénom, journal, délai."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest
from _commun import reglages

from popote_api.infra import mails_textes as textes
from popote_api.infra.mails import (
    DELAI_D_UN_ENVOI_S,
    BoiteDeTest,
    EnvoiParEnveloppe,
    MailIndisponible,
    MessageCode,
    MessageInvitation,
    TypeDeMail,
    envoie_sans_remonter,
)
from popote_api.infra.mails_textes import Enveloppe
from popote_api.main import create_app

ADRESSE = "claire@example.org"
LIEN = "https://essai.notre-popote.fr/invitation#jeton-secret"
EXPIRE_LE = datetime(2026, 11, 20, 10, 30, tzinfo=UTC)
MAINTENANT = datetime(2026, 11, 13, 9, 30, 15, tzinfo=UTC)
ORIGINES = reglages("essai").origines


def code() -> MessageCode:
    return MessageCode(ADRESSE, "123456", 10)


def invitation(lien: str = LIEN, destinataire: str = ADRESSE) -> MessageInvitation:
    return MessageInvitation(destinataire, "Claire", "Marc", lien, EXPIRE_LE)


# --- `quoi` : un type fermé --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quoi",
    [f"code {ADRESSE} 123456", "", "Code", "code ", "code\n", "mail", None, 3, ADRESSE, "invitation 123456"],
)
async def test_un_nom_de_mail_hors_de_la_liste_fermee_est_refuse_avant_tout_envoi(quoi: object) -> None:
    boite = BoiteDeTest()
    with pytest.raises((ValueError, TypeError)):
        await envoie_sans_remonter(boite.envoie_le_code, code(), quoi)  # type: ignore[arg-type]
    with pytest.raises((ValueError, TypeError)):
        await envoie_sans_remonter(boite.envoie_l_invitation, invitation(), quoi)  # type: ignore[arg-type]
    assert boite.codes == [] and boite.invitations == []


async def test_le_nom_libre_est_refuse_meme_quand_il_s_apparie_au_message() -> None:
    # Pas de repli sur l'appariement : « invitation <adresse> » n'est pas un nom de la liste fermée.
    boite = BoiteDeTest()
    with pytest.raises(ValueError, match="invitation"):
        await envoie_sans_remonter(boite.envoie_l_invitation, invitation(), f"invitation {ADRESSE}")  # type: ignore[arg-type]
    assert boite.invitations == []


async def test_un_objet_qui_n_est_pas_un_message_est_refuse_avant_tout_appel() -> None:
    appels: list[object] = []

    async def envoyer(message: object) -> None:
        appels.append(message)

    for quoi in (TypeDeMail.code, TypeDeMail.invitation):
        with pytest.raises(ValueError, match="ne correspond pas"):
            await envoie_sans_remonter(envoyer, object(), quoi)  # type: ignore[type-var]
    assert appels == []


async def test_les_deux_noms_litteraux_restent_admis_pour_les_appelants_qui_ecrivent_une_chaine() -> None:
    boite = BoiteDeTest()
    assert await envoie_sans_remonter(boite.envoie_le_code, code(), "code") is True
    assert await envoie_sans_remonter(boite.envoie_l_invitation, invitation(), "invitation") is True


async def test_les_deux_noms_de_la_liste_fermee_sont_admis_et_s_ecrivent_tels_quels() -> None:
    assert {t.value for t in TypeDeMail} == {"code", "invitation"}
    boite = BoiteDeTest()
    assert await envoie_sans_remonter(boite.envoie_le_code, code(), TypeDeMail.code) is True
    assert await envoie_sans_remonter(boite.envoie_l_invitation, invitation(), TypeDeMail.invitation) is True


async def test_un_nom_qui_ne_correspond_pas_au_message_est_refuse() -> None:
    boite = BoiteDeTest()
    with pytest.raises(ValueError, match="ne correspond pas"):
        await envoie_sans_remonter(boite.envoie_le_code, code(), TypeDeMail.invitation)
    with pytest.raises(ValueError, match="ne correspond pas"):
        await envoie_sans_remonter(boite.envoie_l_invitation, invitation(), TypeDeMail.code)  # type: ignore[arg-type]
    assert boite.codes == [] and boite.invitations == []


# --- L'enveloppe : seule chose que les réalisations transmettent -----------------------------------------


def test_l_enveloppe_du_code_expire_a_l_heure_de_l_envoi_plus_la_validite() -> None:
    enveloppe = textes.enveloppe_du_code(MessageCode(ADRESSE, "123456", 7), MAINTENANT)
    assert enveloppe.expire_le == MAINTENANT + timedelta(minutes=7)
    assert textes.enveloppe_de_l_invitation(invitation(), ORIGINES).expire_le is None


def test_une_enveloppe_refuse_une_heure_d_expiration_sans_fuseau() -> None:
    with pytest.raises(ValueError, match="fuseau"):
        textes.enveloppe_du_code(code(), datetime(2026, 11, 13, 9, 30))


def test_une_enveloppe_refuse_un_objet_qui_est_une_sous_classe_de_str_a_l_egalite_truquee() -> None:
    class Truque(str):
        __slots__ = ()

        def __hash__(self) -> int:
            return hash(textes.OBJET_DU_CODE)

        def __eq__(self, autre: object) -> bool:
            return autre == textes.OBJET_DU_CODE

    with pytest.raises(ValueError, match="objet"):
        Enveloppe(ADRESSE, Truque("Code 123456"), "texte", textes._CACHET)


class Realisation(EnvoiParEnveloppe):
    def __init__(self, origines: frozenset[str]) -> None:
        super().__init__(origines, maintenant=lambda: MAINTENANT)
        self.recues: list[object] = []

    async def _transmet(self, enveloppe: Enveloppe) -> None:
        self.recues.append(enveloppe)


async def test_une_realisation_ne_recoit_que_des_enveloppes_au_objet_constant() -> None:
    realisation = Realisation(ORIGINES)
    await realisation.envoie_le_code(code())
    await realisation.envoie_l_invitation(invitation())
    assert [type(e) for e in realisation.recues] == [Enveloppe, Enveloppe]
    assert [e.objet for e in realisation.recues] == [
        textes.OBJET_DU_CODE,
        "Marc t'a gardé une place en cuisine",
    ]  # type: ignore[attr-defined]
    assert realisation.recues[0].expire_le == MAINTENANT + timedelta(minutes=10)  # type: ignore[attr-defined]


async def test_une_realisation_refuse_un_lien_hors_des_origines_de_son_environnement() -> None:
    realisation = Realisation(reglages("prod").origines)
    with pytest.raises(ValueError, match="origine"):
        await realisation.envoie_l_invitation(invitation())  # un lien de l'essai, une réalisation de la prod
    assert realisation.recues == []


def test_une_realisation_se_derive_des_origines_de_l_environnement() -> None:
    assert Realisation(reglages("essai").origines)._origines == {"https://essai.notre-popote.fr"}


def test_le_repr_d_une_enveloppe_ne_porte_rien() -> None:
    enveloppe = textes.enveloppe_du_code(code(), MAINTENANT)
    rendu = f"{enveloppe!r} {enveloppe}"
    for secret in (ADRESSE, "123456", "Popote"):
        assert secret not in rendu


def test_l_enveloppe_du_code_porte_le_texte_et_l_objet_constants() -> None:
    enveloppe = textes.enveloppe_du_code(code(), MAINTENANT)
    assert enveloppe.destinataire == ADRESSE
    assert enveloppe.objet == textes.OBJET_DU_CODE
    assert enveloppe.texte == textes.texte_du_code(code())


def test_l_enveloppe_de_l_invitation_porte_le_texte_et_l_objet_constants() -> None:
    enveloppe = textes.enveloppe_de_l_invitation(invitation(), ORIGINES)
    assert enveloppe.objet == "Marc t'a gardé une place en cuisine"
    assert enveloppe.texte == textes.texte_de_l_invitation(invitation())


@pytest.mark.parametrize(
    "objet",
    [
        "Code Popote 123456",
        "Invitation de Claire",
        "",
        textes.OBJET_DU_CODE + " ",
        "Marc<b> t'a gardé une place en cuisine",  # prénom non présentable
        "x@y.fr t'a gardé une place en cuisine",
        " t'a gardé une place en cuisine",  # sans prénom
        "A" * 31 + " t'a gardé une place en cuisine",  # plus de 30 caractères
        "Marc t'a gardé une place en cuisine 123456",  # rien après le gabarit
        "Marc t'a gardé une place en cuisine\n",
        "Marc\u3164Support t'a gardé une place en cuisine",
        "123456 t'a gardé une place en cuisine",
    ],
)
def test_une_enveloppe_refuse_un_objet_hors_des_gabarits_autorises(objet: str) -> None:
    with pytest.raises(ValueError, match="objet"):
        textes.Enveloppe(ADRESSE, objet, "texte", textes._CACHET)


def test_une_enveloppe_ne_se_fabrique_pas_sans_le_cachet_du_module() -> None:
    with pytest.raises(TypeError, match="mails_textes"):
        textes.Enveloppe(ADRESSE, textes.OBJET_DU_CODE, "texte", object())


def test_une_enveloppe_refuse_un_destinataire_invalide_ou_un_texte_vide() -> None:
    with pytest.raises(ValueError, match="destinataire"):
        textes.Enveloppe("a@b.fr,c@d.fr", textes.OBJET_DU_CODE, "texte", textes._CACHET)
    with pytest.raises(ValueError, match="texte vide"):
        textes.Enveloppe(ADRESSE, textes.OBJET_DU_CODE, "", textes._CACHET)


@pytest.mark.parametrize(
    ("prenom_hote", "attendu"),
    [
        ("Marc", "Marc t'a gardé une place en cuisine"),
        ("  Élodie ", "Élodie t'a gardé une place en cuisine"),
        ("A" * 30, "A" * 30 + " t'a gardé une place en cuisine"),
        ("A" * 31, "Une place t'attend en cuisine"),
        ("x@y.fr", "Une place t'attend en cuisine"),
        ("Marc<script>", "Une place t'attend en cuisine"),
        ("Marc\u3164Support", "Une place t'attend en cuisine"),
        ("", "Une place t'attend en cuisine"),
        ("Marc2", "Une place t'attend en cuisine"),
    ],
)
def test_l_objet_de_l_invitation_porte_le_seul_prenom_de_l_hote_ou_le_repli(
    prenom_hote: str, attendu: str
) -> None:
    message = MessageInvitation(ADRESSE, "Claire", prenom_hote, LIEN, EXPIRE_LE)
    assert textes.enveloppe_de_l_invitation(message, ORIGINES).objet == attendu


def test_l_objet_de_l_invitation_ne_porte_ni_l_invite_ni_le_lien() -> None:
    objet = textes.enveloppe_de_l_invitation(invitation(), ORIGINES).objet
    assert "Claire" not in objet and "jeton-secret" not in objet and ADRESSE not in objet


def test_l_objet_du_code_ne_porte_pas_le_code_et_celui_de_l_invitation_ni_prenom_ni_lien() -> None:
    assert "123456" not in textes.enveloppe_du_code(code(), MAINTENANT).objet
    objet = textes.enveloppe_de_l_invitation(invitation(), ORIGINES).objet
    assert "Claire" not in objet and "jeton-secret" not in objet


# --- Le destinataire --------------------------------------------------------------------------------------

ADRESSES_REFUSEES = [
    "victime@example.org,attaquant@example.org",
    "a@b.fr;c@d.fr",
    "a@b.fr\x00",
    "a\x00@b.fr",
    "a@b.fr\x1b[31m",
    "a@b.fr‮",  # RLO
    "‮a@b.fr",
    "a‏@b.fr",
    "a@b.fr\r\nBcc: x@y.fr",
    "a b@c.fr",
    "a@@b.fr",
    "<a@b.fr>",
    '"a"@b.fr',
    "é@b.fr",
    "a@bé.fr",
    "a@.fr",
    "",
    "x" * 250 + "@b.fr",  # plus de 254 caractères
    "a@localhost",  # un domaine sans point
    "a@b",
]


@pytest.mark.parametrize("adresse", ADRESSES_REFUSEES)
def test_un_destinataire_qui_n_est_pas_une_seule_adresse_stricte_est_refuse(adresse: str) -> None:
    with pytest.raises(ValueError, match="destinataire"):
        MessageCode(adresse, "123456", 10)
    with pytest.raises(ValueError, match="destinataire"):
        invitation(destinataire=adresse)


def adresse_de(longueur: int, local: int = 64) -> str:
    """Une adresse valide de `longueur` caractères, partie locale de `local`, quatre étiquettes."""
    domaine = ".".join(["d" * 60, "e" * 60, "g" * 60, "f" * (longueur - local - 1 - 183)])
    return "x" * local + "@" + domaine


def test_un_destinataire_de_254_caracteres_passe_255_non() -> None:
    assert len(adresse_de(254)) == 254 and len(adresse_de(255)) == 255
    assert MessageCode(adresse_de(254), "123456", 10).destinataire == adresse_de(254)
    with pytest.raises(ValueError, match="destinataire"):
        MessageCode(adresse_de(255), "123456", 10)


def test_une_partie_locale_de_64_caracteres_passe_65_non() -> None:
    assert MessageCode("x" * 64 + "@example.org", "123456", 10)
    for adresse in ("x" * 65 + "@example.org", "x" * 65 + "@b.fr"):
        with pytest.raises(ValueError, match="destinataire"):
            MessageCode(adresse, "123456", 10)
    assert MessageCode("a.b+c@example.org", "123456", 10).destinataire == "a.b+c@example.org"


# --- Le lien d'invitation ---------------------------------------------------------------------------------

LIENS_ADMIS = [
    ("https://essai.notre-popote.fr/invitation#jeton-secret", "essai"),
    ("https://notre-popote.fr/invitation#abcDEF_-0123", "prod"),
    ("https://ESSAI.notre-popote.fr/invitation#jeton", "essai"),
    ("http://localhost:5173/invitation#jeton", "local"),
    ("http://127.0.0.1:5173/invitation#jeton", "local"),
    ("https://essai.notre-popote.fr/invitation#" + "j" * 128, "essai"),
]


@pytest.mark.parametrize(("lien", "env"), LIENS_ADMIS)
def test_un_lien_d_une_origine_du_front_est_admis(lien: str, env: str) -> None:
    assert textes.lien_d_invitation_admis(lien, reglages(env).origines) is True
    assert textes.enveloppe_de_l_invitation(invitation(lien), reglages(env).origines).texte.count(lien) == 1


LIENS_REFUSES = [
    ("https://notre-popote.fr@evil.example/invitation#jeton", "prod"),  # l'hôte est ce qui suit l'@
    ("https://essai.notre-popote.fr:evil@evil.example/invitation#jeton", "essai"),
    ("https://user:pass@essai.notre-popote.fr/invitation#jeton", "essai"),
    ("https://evil.example/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr.evil.example/invitation#jeton", "essai"),
    ("https://evil.example/https://essai.notre-popote.fr/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr:8443/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr:443/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr:99999/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr:abc/invitation#jeton", "essai"),
    ("http://essai.notre-popote.fr/invitation#jeton", "essai"),
    ("http://localhost:5173/invitation#jeton", "essai"),
    ("http://evil.example:5173/invitation#jeton", "local"),
    ("https://notre-popote.fr/invitation#jeton", "essai"),  # la prod n'est pas l'origine de l'essai
    ("https://essai.notre-popote.fr/autre#jeton", "essai"),
    ("https://essai.notre-popote.fr/invitation?x=1#jeton", "essai"),
    ("https://essai.notre-popote.fr/invitation", "essai"),
    ("https://essai.notre-popote.fr/invitation#", "essai"),
    ("https://essai.notre-popote.fr/invitation#jeton/../x", "essai"),
    ("https://essai.notre-popote.fr/invitation#jeton‮", "essai"),
    ("https://[::1/invitation#jeton", "essai"),
    ("ftp://essai.notre-popote.fr/invitation#jeton", "essai"),
    ("//essai.notre-popote.fr/invitation#jeton", "essai"),
    (" https://essai.notre-popote.fr/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr/invitation#jeton\n", "essai"),
    ("https://essai.notre-popote.fr/inv\titation#jeton", "essai"),
    ("https://essai.notre-popote.fr\t/invitation#jeton", "essai"),
    ("\x00https://essai.notre-popote.fr/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr/invitation?#jeton", "essai"),
    ("https://essai.notre-popote.fr\\@evil.example/invitation#jeton", "essai"),
    ("https://essai.notre-popote.fr/invitation#" + "j" * 129, "essai"),
]


@pytest.mark.parametrize(("lien", "env"), LIENS_REFUSES)
def test_un_lien_hors_des_origines_du_front_est_refuse(lien: str, env: str) -> None:
    origines = reglages(env).origines
    assert textes.lien_d_invitation_admis(lien, origines) is False
    try:
        message = invitation(lien)
    except ValueError:
        return  # déjà refusé par la forme du message
    with pytest.raises(ValueError, match="origine"):
        textes.enveloppe_de_l_invitation(message, origines)


@pytest.mark.parametrize("lien", [None, 3, b"https://essai.notre-popote.fr/invitation#jeton", ["https://x"]])
def test_un_lien_qui_n_est_pas_une_chaine_est_refuse_sans_lever(lien: object) -> None:
    assert textes.lien_d_invitation_admis(lien, ORIGINES) is False  # type: ignore[arg-type]


def test_http_n_est_admis_que_vers_l_hote_local_meme_si_l_origine_figure_dans_la_liste() -> None:
    origines = frozenset({"http://notre-popote.fr", "http://localhost:5173"})
    assert textes.lien_d_invitation_admis("http://notre-popote.fr/invitation#jeton", origines) is False
    assert textes.lien_d_invitation_admis("http://localhost:5173/invitation#jeton", origines) is True


@pytest.mark.parametrize("port", ["99999", "abc", "-1"])
def test_un_port_invalide_est_refuse_meme_si_l_origine_figure_dans_la_liste(port: str) -> None:
    origine = f"https://essai.notre-popote.fr:{port}"
    assert textes.lien_d_invitation_admis(f"{origine}/invitation#jeton", frozenset({origine})) is False


# --- Le prénom --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prenom",
    [
        "MarcㅤSupport",
        "MarcᅟSupport",
        "MarcᅠSupport",
        "MarcﾠSupport",
        "Marc⠀Support",
        *[f"Marc{chr(c)}Support" for c in range(0x200B, 0x2010)],
        *[f"Marc{chr(c)}Support" for c in range(0x2060, 0x2065)],
        "Marc﻿Support",
        "﻿Marc",
        "Marc​",
    ],
)
def test_un_prenom_avec_un_invisible_au_milieu_ou_au_bord_donne_le_repli(prenom: str) -> None:
    assert textes.prenom_affichable(prenom) == textes.REPLI_DU_PRENOM


OMICRON_GREC = "\N{GREEK SMALL LETTER OMICRON}"
A_CYRILLIQUE = "\N{CYRILLIC CAPITAL LETTER A}"
O_CYRILLIQUE = "\N{CYRILLIC SMALL LETTER O}"
ALPHA_GREC = "\N{GREEK CAPITAL LETTER ALPHA}"


@pytest.mark.parametrize(
    "prenom",
    [
        f"P{OMICRON_GREC}p{OMICRON_GREC}te",  # omicrons grecs dans un prénom latin
        f"Marc {A_CYRILLIQUE}lain",  # « A » cyrillique dans un prénom latin
        f"{A_CYRILLIQUE}lain Marc",
        f"{ALPHA_GREC}lain",  # « A » grec
        f"{ALPHA_GREC}{A_CYRILLIQUE}",  # grec et cyrillique
        f"Marc-{O_CYRILLIQUE}",  # « o » cyrillique après un tiret
        "\N{FULLWIDTH LATIN CAPITAL LETTER M}arc",
        "\N{DOUBLE-STRUCK CAPITAL P}opote",
        "Support \N{MATHEMATICAL BOLD CAPITAL P}ote",
        "Pop\N{MODIFIER LETTER SMALL O}te",
        "P\N{ARMENIAN SMALL LETTER OH}pote",
        "P\N{CHEROKEE LETTER QUV}pote",
        "P\N{COPTIC SMALL LETTER O}pote",
        "Marc\N{COMBINING CYRILLIC TITLO}Support",
        "\N{LATIN SMALL LIGATURE FI}lipe",
    ],
)
def test_un_prenom_qui_melange_latin_grec_ou_cyrillique_donne_le_repli(prenom: str) -> None:
    assert textes.prenom_affichable(prenom) == textes.REPLI_DU_PRENOM


@pytest.mark.parametrize(
    "prenom",
    ["Marc\u034fSupport", "Marc\ufe0fSupport", "Marc\u17b4Support", "Marc\u180bSupport", "Marc\ufe00"],
)
def test_un_prenom_avec_une_marque_combinante_invisible_donne_le_repli(prenom: str) -> None:
    assert textes.prenom_affichable(prenom) == textes.REPLI_DU_PRENOM


@pytest.mark.parametrize(
    "prenom",
    [
        "Marc",
        "\N{CYRILLIC CAPITAL LETTER A}\N{CYRILLIC SMALL LETTER EL}\N{CYRILLIC SMALL LETTER IE}",
        "\N{GREEK CAPITAL LETTER ALPHA}\N{GREEK SMALL LETTER LAMDA}\N{GREEK SMALL LETTER SIGMA}",
        "Zoë Łukasz",
        "किरण",
    ],
)
def test_un_prenom_d_une_seule_ecriture_est_garde(prenom: str) -> None:
    assert textes.prenom_affichable(prenom) == prenom


def test_les_homoglyphes_d_une_seule_ecriture_passent_et_c_est_dit() -> None:
    # Limite connue (docs/securite.md § 4.12) : tout en cyrillique, « Pop » imite le latin sans mélange.
    cyrillique = "\N{CYRILLIC CAPITAL LETTER ER}\N{CYRILLIC SMALL LETTER O}\N{CYRILLIC SMALL LETTER ER}"
    assert textes.prenom_valide(cyrillique) is not None


# --- L'annulation et le délai propre de l'envoi ----------------------------------------------------------


async def test_une_annulation_pendant_l_appel_dit_issue_inconnue_et_jamais_non_envoye(
    caplog: pytest.LogCaptureFixture,
) -> None:
    debut = asyncio.Event()

    async def accepte_puis_attend(message: MessageCode) -> None:
        debut.set()
        await asyncio.Event().wait()

    tache = asyncio.create_task(envoie_sans_remonter(accepte_puis_attend, code(), TypeDeMail.code))
    await debut.wait()
    tache.cancel()
    with caplog.at_level(logging.DEBUG), pytest.raises(asyncio.CancelledError):
        await tache
    assert "issue inconnue" in caplog.text
    assert "non envoyé" not in caplog.text
    assert ADRESSE not in caplog.text and "123456" not in caplog.text


async def test_une_annulation_traduite_en_erreur_par_la_realisation_repart_quand_meme(
    caplog: pytest.LogCaptureFixture,
) -> None:
    debut = asyncio.Event()

    async def traduit(message: MessageCode) -> None:
        debut.set()
        try:
            await asyncio.Event().wait()
        except BaseException as erreur:
            raise MailIndisponible("coupé") from erreur

    tache = asyncio.create_task(envoie_sans_remonter(traduit, code(), TypeDeMail.code))
    await debut.wait()
    tache.cancel()
    with caplog.at_level(logging.DEBUG), pytest.raises(asyncio.CancelledError):
        await tache
    assert "issue inconnue" in caplog.text and "non envoyé" not in caplog.text


async def test_une_panne_apres_l_envoi_de_la_requete_dit_issue_inconnue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def coupe(message: MessageCode) -> None:
        raise MailIndisponible("coupure", issue_inconnue=True)

    with caplog.at_level(logging.DEBUG):
        assert await envoie_sans_remonter(coupe, code(), TypeDeMail.code) is False
    assert "Mail (code) : MailIndisponible, issue inconnue" in caplog.text
    assert "non envoyé" not in caplog.text


async def test_un_envoi_bloque_est_borne_par_son_propre_delai(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("popote_api.infra.mails.DELAI_D_UN_ENVOI_S", 0.05)

    async def bloque(message: MessageCode) -> None:
        await asyncio.Event().wait()

    with caplog.at_level(logging.DEBUG):
        reussi = await asyncio.wait_for(envoie_sans_remonter(bloque, code(), TypeDeMail.code), timeout=5)
    assert reussi is False
    assert "délai de l'envoi dépassé, issue inconnue" in caplog.text
    assert "non envoyé" not in caplog.text


async def test_un_timeout_de_la_realisation_n_est_pas_pris_pour_le_delai_propre(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def tombe(message: MessageCode) -> None:
        raise TimeoutError

    with caplog.at_level(logging.DEBUG):
        assert await envoie_sans_remonter(tombe, code(), TypeDeMail.code) is False
    assert "Mail (code) non envoyé : TimeoutError" in caplog.text


def test_le_delai_propre_tient_entre_l_envoi_reel_et_la_requete() -> None:
    from popote_api.limites import DELAI_SECONDES

    assert 15.0 < DELAI_D_UN_ENVOI_S < DELAI_SECONDES


async def test_une_panne_du_fournisseur_reste_journalisee_par_son_type_seul(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boite = BoiteDeTest(en_panne=True)
    with caplog.at_level(logging.DEBUG):
        assert await envoie_sans_remonter(boite.envoie_le_code, code(), TypeDeMail.code) is False
    assert "Mail (code) non envoyé : MailIndisponible" in caplog.text
    assert issubclass(MailIndisponible, Exception)


async def test_une_adresse_publique_hors_des_origines_du_front_est_signalee_au_demarrage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Tous les liens d'invitation seraient refusés à l'envoi : le démarrage le dit au lieu de le taire.
    app = create_app(reglages("essai", public_base_url="https://app.notre-popote.fr"))
    with caplog.at_level(logging.WARNING, logger="popote_api.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "POPOTE_PUBLIC_BASE_URL" in caplog.text and "origines" in caplog.text


async def test_une_adresse_publique_d_une_origine_du_front_ne_dit_rien(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(reglages("essai", public_base_url="https://essai.notre-popote.fr"))
    with caplog.at_level(logging.WARNING, logger="popote_api.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "origines" not in caplog.text
