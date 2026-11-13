"""0.4bis S5b : le code de connexion (six chiffres), son empreinte, ses clés, son envoi et ses réglages."""

import asyncio
import logging
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from _commun import POIVRE, reglages
from pydantic import SecretStr, ValidationError

from popote_api.infra.mails import BoiteDeTest, MessageCode
from popote_api.security.code_de_connexion import Courrier, envoie_le_courrier
from popote_api.security.codes import (
    CHIFFRES_DU_CODE,
    RENVOI_APRES_S,
    VALIDITE_DU_CODE_MIN,
    VIE_DU_CODE_S,
    code_neuf,
)
from popote_api.security.empreintes import Empreintes, PoivreAbsentError

ADRESSE = "a@x.fr"
CLE = b"\x01" * 32
IDENTIFIANT = UUID("12345678-1234-5678-1234-567812345678")


def empreintes(poivre: str | None = POIVRE) -> Empreintes:
    return Empreintes(SecretStr(poivre) if poivre else None)


# ── Le code ─────────────────────────────────────────────────────────────────


def test_les_valeurs_du_plan() -> None:
    assert (CHIFFRES_DU_CODE, VIE_DU_CODE_S, VALIDITE_DU_CODE_MIN, RENVOI_APRES_S) == (6, 600, 10, 60)


@pytest.mark.parametrize(
    ("tire", "attendu"), [(0, "000000"), (7, "000007"), (123456, "123456"), (999999, "999999")]
)
def test_le_code_garde_ses_zeros_de_tete(tire: int, attendu: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "randbelow", lambda borne: tire)
    assert code_neuf() == attendu


def test_le_code_est_tire_sur_un_million_de_valeurs(monkeypatch: pytest.MonkeyPatch) -> None:
    bornes: list[int] = []
    monkeypatch.setattr(secrets, "randbelow", lambda borne: bornes.append(borne) or 0)
    code_neuf()
    assert bornes == [10**6]


def test_mille_codes_ont_six_chiffres_et_ne_se_repetent_pas_tous() -> None:
    codes = [code_neuf() for _ in range(1000)]
    assert all(re.fullmatch(r"[0-9]{6}", code) for code in codes)
    assert len(set(codes)) > 900


# ── L'empreinte du code ─────────────────────────────────────────────────────


def test_l_empreinte_a_32_octets_et_ne_porte_pas_le_code() -> None:
    empreinte = empreintes().empreinte_du_code(IDENTIFIANT, CLE, "123456")
    assert len(empreinte) == 32 and b"123456" not in empreinte


def test_l_empreinte_est_stable_pour_les_memes_entrees() -> None:
    assert empreintes().empreinte_du_code(IDENTIFIANT, CLE, "123456") == empreintes().empreinte_du_code(
        IDENTIFIANT, CLE, "123456"
    )


@pytest.mark.parametrize(
    "variante",
    [
        {"identifiant": uuid4()},
        {"cle": b"\x02" * 32},
        {"code": "123457"},
        {"poivre": "q" * 32},
    ],
    ids=["demande", "compte", "code", "poivre"],
)
def test_l_empreinte_depend_de_la_demande_du_compte_du_code_et_du_poivre(variante: dict[str, Any]) -> None:
    base = empreintes().empreinte_du_code(IDENTIFIANT, CLE, "123456")
    autre = empreintes(variante.get("poivre", POIVRE)).empreinte_du_code(
        variante.get("identifiant", IDENTIFIANT), variante.get("cle", CLE), variante.get("code", "123456")
    )
    assert autre != base


def test_deux_demandes_du_meme_code_ont_deux_empreintes() -> None:
    assert empreintes().empreinte_du_code(uuid4(), CLE, "123456") != empreintes().empreinte_du_code(
        uuid4(), CLE, "123456"
    )


def test_sans_poivre_l_empreinte_refuse_au_lieu_de_calculer_sans_protection() -> None:
    with pytest.raises(PoivreAbsentError):
        empreintes(None).empreinte_du_code(IDENTIFIANT, CLE, "123456")


def test_l_empreinte_n_est_aucune_des_autres_cles() -> None:
    cle = empreintes().cle_compte(ADRESSE)
    assert cle is not None
    autres = {cle, empreintes().cle_ip("1.2.3.4"), empreintes().cle_paire_de_code(ADRESSE, "1.2.3.4")}
    assert empreintes().empreinte_du_code(IDENTIFIANT, cle, "123456") not in autres


# ── La clé de la paire (adresse, IP) ────────────────────────────────────────


def test_la_paire_depend_de_l_adresse_et_de_l_ip_et_regroupe_l_ipv6_par_64() -> None:
    e = empreintes()
    base = e.cle_paire_de_code(ADRESSE, "1.2.3.4")
    assert base is not None and len(base) == 32
    assert base != e.cle_paire_de_code("b@x.fr", "1.2.3.4")
    assert base != e.cle_paire_de_code(ADRESSE, "1.2.3.5")
    assert e.cle_paire_de_code(ADRESSE, "2001:db8::1") == e.cle_paire_de_code(ADRESSE, "2001:db8::ffff")
    assert e.cle_paire_de_code(ADRESSE, "2001:db8:0:1::1") != e.cle_paire_de_code(ADRESSE, "2001:db8::1")


def test_la_paire_ne_change_pas_avec_la_forme_de_l_adresse() -> None:
    e = empreintes()
    assert e.cle_paire_de_code(" A@X.FR ", "1.2.3.4") == e.cle_paire_de_code(ADRESSE, "1.2.3.4")


def test_la_paire_n_est_pas_la_cle_de_reinitialisation() -> None:
    e = empreintes()
    assert e.cle_paire_de_code(ADRESSE, "1.2.3.4") != e.cle_reinitialisation(ADRESSE, "1.2.3.4")


def test_sans_poivre_la_paire_requise_refuse() -> None:
    assert empreintes(None).cle_paire_de_code(ADRESSE, "1.2.3.4") is None
    with pytest.raises(PoivreAbsentError):
        empreintes(None).cle_paire_de_code_requise(ADRESSE, "1.2.3.4")


# ── Les réglages ────────────────────────────────────────────────────────────


def test_les_defauts_sont_ceux_du_plan() -> None:
    r = reglages("local")
    assert (r.code_demandes_par_ip, r.code_demandes_par_paire, r.code_demandes_par_compte) == (10, 3, 6)
    assert (r.code_fenetre_s, r.code_fenetre_compte_s) == (900, 3600)
    assert (r.mail_global_par_fenetre, r.mail_global_fenetre_s) == (60, 3600)


@pytest.mark.parametrize(
    "nom",
    [
        "code_demandes_par_ip",
        "code_demandes_par_paire",
        "code_demandes_par_compte",
        "code_fenetre_s",
        "code_fenetre_compte_s",
        "mail_global_par_fenetre",
        "mail_global_fenetre_s",
    ],
)
@pytest.mark.parametrize("valeur", [0, -1, 10_000_000])
def test_un_reglage_hors_bornes_est_refuse_au_demarrage(nom: str, valeur: int) -> None:
    with pytest.raises(ValidationError):
        reglages("local", **{nom: valeur})


# ── L'envoi, après la réponse ───────────────────────────────────────────────


class CurseurFaux:
    def __init__(self, attente_s: int) -> None:
        self.attente_s = attente_s

    async def execute(self, requete: str, parametres: object = None) -> None:
        self.requete = requete

    async def fetchone(self) -> dict[str, int]:
        return {"attente_s": self.attente_s}


class BaseFausse:
    """Un `base.connexion()` qui rend un curseur répondant `attente_s`, ou qui lève dès l'ouverture."""

    def __init__(self, attente_s: int = 0, erreur: Exception | None = None) -> None:
        self.attente_s, self.erreur = attente_s, erreur

    @asynccontextmanager
    async def connexion(self) -> AsyncIterator[CurseurFaux]:
        if self.erreur is not None:
            raise self.erreur
        yield CurseurFaux(self.attente_s)


def etat(base: BaseFausse, mails: object) -> SimpleNamespace:
    return SimpleNamespace(base=base, settings=reglages("local"), mails=mails)


ECHEANCE = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
COURRIER = Courrier("destinataire@x.fr", "246810", ECHEANCE)


async def test_un_envoi_passe_par_le_coupe_circuit_puis_part_avec_dix_minutes() -> None:
    boite = BoiteDeTest()
    await envoie_le_courrier(etat(BaseFausse(0), boite), COURRIER)  # type: ignore[arg-type]
    (message,) = boite.codes
    assert (message.destinataire, message.code, message.validite_min) == ("destinataire@x.fr", "246810", 10)
    assert message.expire_le == ECHEANCE  # l'échéance fixée à la demande, pas recalculée à l'envoi


async def test_un_coupe_circuit_ouvert_jette_le_mail_et_le_dit_sans_adresse_ni_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boite = BoiteDeTest()
    caplog.set_level(logging.DEBUG)
    await envoie_le_courrier(etat(BaseFausse(1800), boite), COURRIER)  # type: ignore[arg-type]
    assert boite.codes == []
    assert "coupe-circuit global ouvert" in caplog.text
    assert "destinataire@x.fr" not in caplog.text and "246810" not in caplog.text


async def test_une_erreur_de_la_base_au_coupe_circuit_jette_le_mail_et_journalise_son_type_seul(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boite = BoiteDeTest()
    caplog.set_level(logging.DEBUG)
    erreur = psycopg.OperationalError("destinataire@x.fr 246810")
    await envoie_le_courrier(etat(BaseFausse(erreur=erreur), boite), COURRIER)  # type: ignore[arg-type]
    assert boite.codes == []
    assert "OperationalError" in caplog.text
    assert "destinataire@x.fr" not in caplog.text and "246810" not in caplog.text


async def test_une_adresse_qui_ne_fait_pas_un_message_valide_est_jetee_et_journalisee_par_son_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boite = BoiteDeTest()
    caplog.set_level(logging.DEBUG)
    await envoie_le_courrier(etat(BaseFausse(0), boite), Courrier("a b@x.fr", "246810", ECHEANCE))  # type: ignore[arg-type]
    assert boite.codes == [] and "message invalide (ValueError)" in caplog.text
    assert "a b@x.fr" not in caplog.text and "246810" not in caplog.text


async def test_un_envoi_en_panne_se_journalise_par_son_type_seul(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    await envoie_le_courrier(etat(BaseFausse(0), BoiteDeTest(en_panne=True)), COURRIER)  # type: ignore[arg-type]
    assert "MailIndisponible" in caplog.text
    assert "destinataire@x.fr" not in caplog.text and "246810" not in caplog.text


async def test_un_envoi_annule_par_le_delai_propage_l_annulation(caplog: pytest.LogCaptureFixture) -> None:
    class Lent:
        async def envoie_le_code(self, message: MessageCode) -> None:
            await asyncio.sleep(60)

    caplog.set_level(logging.DEBUG)
    tache = asyncio.create_task(envoie_le_courrier(etat(BaseFausse(0), Lent()), COURRIER))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    assert "annulé" in caplog.text and "destinataire@x.fr" not in caplog.text


def test_le_courrier_ne_montre_ni_adresse_ni_code() -> None:
    assert "destinataire" not in repr(COURRIER) and "246810" not in repr(COURRIER)
