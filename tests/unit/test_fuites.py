import asyncio
import logging
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from _commun import reglages

from popote_api.config import BreachCheck
from popote_api.infra import fuites
from popote_api.infra.fuites import (
    CauseIndisponibilite,
    EtatFuite,
    FuitesDesactivees,
    PwnedPasswords,
    ResultatFuite,
    fuites_pour,
)

# SHA-1 de « password » : référence publique, pas un secret.
MOT_DE_PASSE = "password"
EMPREINTE = "5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8"
PLAGE, SUFFIXE = EMPREINTE[:5], EMPREINTE[5:]
AUTRE_SUFFIXE = "0" * 35
SUFFIXE_DE_BOURRAGE = "F" * 35


def corps_de(*lignes: str) -> bytes:
    return ("\r\n".join(lignes) + "\r\n").encode("ascii")


def repond(corps: bytes, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda requete: httpx.Response(status, content=corps)


class Espion:
    """Un transport factice qui garde les requêtes reçues."""

    def __init__(self, reponse: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requetes: list[httpx.Request] = []
        self._reponse = reponse

    def transport(self) -> httpx.MockTransport:
        def gestionnaire(requete: httpx.Request) -> httpx.Response:
            self.requetes.append(requete)
            return self._reponse(requete)

        return httpx.MockTransport(gestionnaire)


async def verdict(reponse: Callable[[httpx.Request], httpx.Response], mot_de_passe: str = MOT_DE_PASSE):
    return await PwnedPasswords(Espion(reponse).transport()).verifie(mot_de_passe)


# --- ce qui part ------------------------------------------------------------------------------------


async def test_seule_la_plage_de_cinq_caracteres_part(caplog: pytest.LogCaptureFixture) -> None:
    # Un mot de passe qui n'apparaît dans aucun nom d'hôte ni d'en-tête ; sa plage et son suffixe viennent
    # de `sha1`, calculés hors du code testé.
    mot_de_passe, plage, suffixe = "cheval-agrafe-42", "70F01", "829679B569C978AAFC00323F6FAD69EC309"
    espion = Espion(repond(corps_de(f"{AUTRE_SUFFIXE}:3")))
    with caplog.at_level(logging.DEBUG):
        await PwnedPasswords(espion.transport()).verifie(mot_de_passe)
    (requete,) = espion.requetes
    assert str(requete.url) == f"https://api.pwnedpasswords.com/range/{plage}"
    assert requete.method == "GET"
    assert requete.url.query == b""
    assert requete.content == b""
    tout_ce_qui_part = f"{requete.url} {dict(requete.headers)} {requete.content!r}".lower()
    assert mot_de_passe not in tout_ce_qui_part
    assert suffixe.lower() not in tout_ce_qui_part
    assert (plage + suffixe).lower() not in tout_ce_qui_part
    journal = caplog.text.lower()
    assert mot_de_passe not in journal
    assert suffixe.lower() not in journal
    assert plage.lower() not in journal  # httpx écrit l'adresse à INFO : le module le fait taire
    assert caplog.records == []


async def test_la_requete_demande_le_bourrage_et_porte_un_agent_generique() -> None:
    espion = Espion(repond(corps_de(f"{AUTRE_SUFFIXE}:3")))
    await PwnedPasswords(espion.transport()).verifie(MOT_DE_PASSE)
    en_tetes = espion.requetes[0].headers
    assert en_tetes["add-padding"] == "true"
    assert en_tetes["user-agent"] == "popote"


async def test_l_empreinte_se_calcule_sur_les_octets_utf8() -> None:
    espion = Espion(repond(corps_de(f"{AUTRE_SUFFIXE}:3")))
    await PwnedPasswords(espion.transport()).verifie("é" * 20)
    # SHA-1 de « é » x 20 en UTF-8, calculé hors du code testé.
    assert espion.requetes[0].url.path == "/range/A495C"


# --- verdicts ---------------------------------------------------------------------------------------


async def test_un_suffixe_present_donne_fuite() -> None:
    assert (
        await verdict(repond(corps_de(f"{AUTRE_SUFFIXE}:1", f"{SUFFIXE}:9545824"))) == ResultatFuite.fuite()
    )


async def test_la_correspondance_de_suffixe_ignore_la_casse() -> None:
    assert (await verdict(repond(corps_de(f"{SUFFIXE.lower()}:12")))).etat is EtatFuite.fuite


async def test_aucune_correspondance_donne_sain() -> None:
    corps = corps_de(f"{AUTRE_SUFFIXE}:4", f"{SUFFIXE_DE_BOURRAGE}:0")
    assert await verdict(repond(corps)) == ResultatFuite.sain()


async def test_une_ligne_a_compte_zero_est_du_bourrage_et_est_ignoree() -> None:
    assert (await verdict(repond(corps_de(f"{SUFFIXE}:0", f"{AUTRE_SUFFIXE}:5")))).etat is EtatFuite.sain


async def test_un_compte_de_zeros_multiples_est_aussi_du_bourrage() -> None:
    assert (await verdict(repond(corps_de(f"{SUFFIXE}:000")))).etat is EtatFuite.sain


async def test_un_compte_enorme_ne_leve_pas() -> None:
    assert (await verdict(repond(corps_de(f"{SUFFIXE}:{'9' * 100_000}")))).etat is EtatFuite.fuite


async def test_les_fins_de_ligne_lf_seules_sont_acceptees_sans_ligne_finale() -> None:
    corps = f"{AUTRE_SUFFIXE}:1\n{SUFFIXE}:2".encode("ascii")
    assert (await verdict(repond(corps))).etat is EtatFuite.fuite


async def test_un_mot_de_passe_notoire_est_sain_quand_sa_plage_ne_le_contient_pas() -> None:
    # Le suffixe d'un autre mot de passe de la même plage ne suffit pas.
    assert (await verdict(repond(corps_de(f"{SUFFIXE[:-1]}0:7")))).etat is EtatFuite.sain


# --- pannes : résultat explicite, pas d'exception ---------------------------------------------------


@pytest.mark.parametrize("status", [403, 404, 429, 500, 502, 503, 504, 204])
async def test_un_statut_autre_que_200_rend_indisponible(status: int) -> None:
    resultat = await verdict(repond(corps_de(f"{SUFFIXE}:5"), status))
    assert resultat == ResultatFuite.indisponible(CauseIndisponibilite.statut)


async def test_une_redirection_est_refusee_et_non_suivie() -> None:
    espion = Espion(lambda r: httpx.Response(301, headers={"Location": "https://exemple.invalide/x"}))
    resultat = await PwnedPasswords(espion.transport()).verifie(MOT_DE_PASSE)
    assert resultat == ResultatFuite.indisponible(CauseIndisponibilite.redirection)
    assert len(espion.requetes) == 1


async def test_une_panne_reseau_rend_indisponible() -> None:
    def echoue(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée vers 5BAA6")

    assert await verdict(echoue) == ResultatFuite.indisponible(CauseIndisponibilite.reseau)


async def test_un_delai_de_httpx_rend_indisponible_avec_la_cause_delai() -> None:
    def lent(requete: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("trop lent")

    assert await verdict(lent) == ResultatFuite.indisponible(CauseIndisponibilite.delai)


async def test_le_delai_total_est_tenu_meme_si_le_serveur_ne_repond_jamais(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fuites, "DELAI_TOTAL_S", 0.01)

    async def silence(requete: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()  # ne se termine jamais : seule l'échéance l'interrompt
        raise AssertionError("inatteignable")

    async with asyncio.timeout(2):  # filet : sans échéance dans le code, le test échoue au lieu de pendre
        resultat = await PwnedPasswords(httpx.MockTransport(silence)).verifie(MOT_DE_PASSE)
    assert resultat == ResultatFuite.indisponible(CauseIndisponibilite.delai)


async def test_le_delai_total_couvre_aussi_la_lecture_du_corps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fuites, "DELAI_TOTAL_S", 0.01)

    async def goutte_a_goutte() -> AsyncIterator[bytes]:
        yield b"0" * 35 + b":1\r\n"
        await asyncio.Event().wait()

    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=goutte_a_goutte()))
    async with asyncio.timeout(2):
        resultat = await PwnedPasswords(transport).verifie(MOT_DE_PASSE)
    assert resultat == ResultatFuite.indisponible(CauseIndisponibilite.delai)


async def test_un_corps_de_plus_de_un_mio_rend_indisponible() -> None:
    corps = b"A" * (fuites.TAILLE_MAXIMALE_OCTETS + 1)
    assert await verdict(repond(corps)) == ResultatFuite.indisponible(CauseIndisponibilite.trop_gros)


async def test_un_corps_d_exactement_un_mio_n_est_pas_trop_gros() -> None:
    ligne = f"{AUTRE_SUFFIXE}:1\r\n".encode("ascii")
    corps = ligne * (fuites.TAILLE_MAXIMALE_OCTETS // len(ligne))
    corps += b"0" * (
        fuites.TAILLE_MAXIMALE_OCTETS - len(corps)
    )  # complète : ligne mal formée, pas « trop gros »
    resultat = await verdict(repond(corps))
    assert resultat == ResultatFuite.indisponible(CauseIndisponibilite.mal_forme)


async def test_la_lecture_s_arrete_des_que_la_limite_est_depassee() -> None:
    lus: list[int] = []

    async def flot() -> AsyncIterator[bytes]:
        for _ in range(1000):  # 64 Mio promis
            lus.append(1)
            yield b"A" * 65536

    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=flot()))
    resultat = await PwnedPasswords(transport).verifie(MOT_DE_PASSE)
    assert resultat == ResultatFuite.indisponible(CauseIndisponibilite.trop_gros)
    assert len(lus) <= fuites.TAILLE_MAXIMALE_OCTETS // 65536 + 1


@pytest.mark.parametrize(
    "corps",
    [
        b"",
        b"\r\n",
        b"pas une ligne\r\n",
        f"{SUFFIXE}\r\n".encode(),  # sans compte
        f"{SUFFIXE}:\r\n".encode(),
        f"{SUFFIXE}:abc\r\n".encode(),
        f"{SUFFIXE}:-1\r\n".encode(),
        f"{SUFFIXE[:-1]}:1\r\n".encode(),  # suffixe trop court
        f"{SUFFIXE}0:1\r\n".encode(),  # suffixe trop long
        ("Z" * 35 + ":1\r\n").encode(),  # pas hexadécimal
        f"{SUFFIXE}:1\r\n\r\n{AUTRE_SUFFIXE}:1\r\n".encode(),  # ligne vide au milieu
        f"{AUTRE_SUFFIXE}:1\r\n{SUFFIXE}:1\r\ngarbage\r\n".encode(),  # une ligne mal formée après un succès
        f"{SUFFIXE}:1\r\n".encode() + b"\xff\xfe",
        "é".encode(),
        b"<html>Captive portal</html>",
    ],
)
async def test_une_reponse_mal_formee_rend_indisponible_meme_si_une_ligne_correspond(corps: bytes) -> None:
    assert await verdict(repond(corps)) == ResultatFuite.indisponible(CauseIndisponibilite.mal_forme)


async def test_aucune_panne_ne_leve_et_aucune_ne_journalise(caplog: pytest.LogCaptureFixture) -> None:
    def echoue(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refus pour {requete.url}")

    with caplog.at_level(logging.DEBUG):
        resultat = await verdict(echoue)
    assert resultat.etat is EtatFuite.indisponible
    assert caplog.records == []
    assert PLAGE not in repr(resultat)
    assert MOT_DE_PASSE not in repr(resultat)


# --- l'objet résultat -------------------------------------------------------------------------------


def test_une_cause_n_existe_que_pour_indisponible() -> None:
    with pytest.raises(ValueError, match="cause"):
        ResultatFuite(EtatFuite.indisponible)
    with pytest.raises(ValueError, match="cause"):
        ResultatFuite(EtatFuite.sain, CauseIndisponibilite.delai)


# --- la réalisation à brancher ----------------------------------------------------------------------


async def test_local_peut_desactiver_la_liste() -> None:
    liste = fuites_pour(reglages("local", breach_check="off"))
    assert isinstance(liste, FuitesDesactivees)
    assert (await liste.verifie(MOT_DE_PASSE)).etat is EtatFuite.sain


@pytest.mark.parametrize("env", ["local", "essai", "prod"])
def test_par_defaut_la_liste_est_pwned_passwords(env: str) -> None:
    liste = fuites_pour(reglages(env))
    assert isinstance(liste, PwnedPasswords)
    assert reglages(env).breach_check is BreachCheck.hibp
