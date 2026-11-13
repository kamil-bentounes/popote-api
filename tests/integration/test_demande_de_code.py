"""0.4bis S5b : `POST /api/v1/login-codes` (spec § 3.6, § 4 ; D3, B6, B24), en base locale.

Données inventées. Un banc par test (une IP de test à lui) ; la boîte de test garde les messages en mémoire :
aucun mail ne part. La base (migration 0147) a ses propres tests : `test_demande_de_code_base.py`.
"""

# ruff: noqa: F811, F401

import asyncio
import logging
import re
import statistics
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import httpx
import psycopg
import pytest
from test_connexion import ECRITURE
from test_reauthentification import Personne, fabrique_de_banc

from popote_api.infra.mails import BoiteDeTest, MailAbsent, MessageCode
from popote_api.security import code_de_connexion
from popote_api.security.empreintes import Empreintes

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/login-codes"
INCONNUE = "personne-n-existe-ici@test.local"
CLE_GLOBALE = bytes(32)


@pytest.fixture
def sans_coupe_circuit(fabrique_de_banc: Callable[..., Personne]) -> Iterator[None]:
    """La ligne du coupe-circuit est unique et partagée : vidée avant et après chaque test."""
    admin = fabrique_de_banc(mail_provider="local").banc.fabrique.admin
    admin.execute("delete from public.login_throttle where scope = 'mail_global'")
    yield
    admin.execute("delete from public.login_throttle where scope = 'mail_global'")


@pytest.fixture
def moi(fabrique_de_banc: Callable[..., Personne], sans_coupe_circuit: None) -> Personne:
    return fabrique_de_banc(mail_provider="local")


def boite(moi: Personne) -> BoiteDeTest:
    mails = moi.banc.app.state.mails
    assert isinstance(mails, BoiteDeTest)
    return mails


async def demande(
    moi: Personne, email: str, *, origine: bool = True, ip: str | None = None
) -> httpx.Response:
    ip_de_la_demande = ip or moi.banc.ip
    empreintes = moi.banc.empreintes
    moi.banc.cles += [
        cle
        for cle in (
            empreintes.cle_compte(email),
            empreintes.cle_ip(ip_de_la_demande),
            empreintes.cle_paire_de_code(email, ip_de_la_demande),
        )
        if cle
    ]
    return await moi.banc.client(ip).post(ROUTE, json={"email": email}, headers=ECRITURE if origine else {})


def lignes(moi: Personne, email: str) -> list[tuple[Any, ...]]:
    return moi.banc.lignes(
        "select id, person_id, code_hash, attempts, created_at, expires_at, used_at, revoked_at"
        " from public.login_code where account_key = %s order by created_at, id",
        moi.banc.empreintes.cle_compte(email),
    )


def actifs(moi: Personne, email: str) -> int:
    return sum(1 for ligne in lignes(moi, email) if ligne[6] is None and ligne[7] is None)


def vieillit(moi: Personne, email: str, de: str = "61 seconds") -> None:
    moi.banc.fabrique.admin.execute(
        "update public.login_code set created_at = created_at - %s::interval,"
        " expires_at = expires_at - %s::interval where account_key = %s",
        (de, de, moi.banc.empreintes.cle_compte(email)),
    )


def entetes_stables(reponse: httpx.Response) -> dict[str, str]:
    # `ratelimit` : le compteur des requêtes de l'appelant, pas une information sur le compte.
    ignores = {"x-request-id", "date", "server-timing", "ratelimit"}
    return {k: v for k, v in reponse.headers.items() if k not in ignores}


def sans_identifiant(corps: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in corps.items() if k != "code_request_id"}


def creneaux(moi: Personne, portee: str, cle: bytes | None) -> list[tuple[Any, ...]]:
    return moi.banc.lignes(
        "select attempts from public.login_throttle where scope = %s and key = %s", portee, cle
    )


class TestReponseUniforme:
    async def test_compte_connu_et_inconnu_donnent_meme_statut_meme_corps_memes_entetes(
        self, moi: Personne
    ) -> None:
        connu = await demande(moi, moi.email)
        inconnu = await demande(moi, INCONNUE)
        assert connu.status_code == inconnu.status_code == 202
        assert set(connu.json()) == {"code_request_id", "expires_in_s", "resend_after_s", "message"}
        assert sans_identifiant(connu.json()) == sans_identifiant(inconnu.json())
        assert (connu.json()["expires_in_s"], connu.json()["resend_after_s"]) == (600, 60)
        UUID(connu.json()["code_request_id"])
        UUID(inconnu.json()["code_request_id"])
        assert entetes_stables(connu) == entetes_stables(inconnu)
        assert "set-cookie" not in connu.headers

    async def test_le_temps_est_comparable(self, moi: Personne) -> None:
        async def mediane(email: str, debut_ip: int) -> float:
            durees = []
            for i in range(30):  # une IP à chaque appel : jamais de 429
                avant = time.perf_counter()
                await demande(moi, email, ip=f"198.51.{debut_ip}.{i + 1}")
                durees.append(time.perf_counter() - avant)
            return statistics.median(durees)

        # Le compte connu est limité à 6 par heure : on lève cette limite, elle n'est pas ce qu'on mesure.
        moi.banc.app.state.settings.code_demandes_par_compte = 10_000
        connu = await mediane(moi.email, 100)
        inconnu = await mediane(INCONNUE, 101)
        assert abs(connu - inconnu) < 0.1

    async def test_une_adresse_mal_formee_ou_en_trop_est_refusee_sans_creneau(self, moi: Personne) -> None:
        client = moi.banc.client()
        assert (await client.post(ROUTE, json={"email": "a" * 300}, headers=ECRITURE)).status_code == 422
        assert (await client.post(ROUTE, json={"email": "a\u0000@x.fr"}, headers=ECRITURE)).status_code == 422
        assert (
            await client.post(ROUTE, json={"email": "a@x.fr", "extra": 1}, headers=ECRITURE)
        ).status_code == 422
        assert (await client.post(ROUTE, json={}, headers=ECRITURE)).status_code == 422
        assert boite(moi).codes == []
        assert creneaux(moi, "code_ip", moi.banc.empreintes.cle_ip(moi.banc.ip)) == []

    async def test_sans_origine_403_et_rien_ne_compte(self, moi: Personne) -> None:
        reponse = await demande(moi, moi.email, origine=False)
        assert reponse.status_code == 403
        assert boite(moi).codes == [] and lignes(moi, moi.email) == []
        assert creneaux(moi, "code_ip", moi.banc.empreintes.cle_ip(moi.banc.ip)) == []
        assert (await demande(moi, moi.email)).status_code == 202  # aucun créneau n'avait été pris

    async def test_sans_poivre_503_et_rien_ne_part_ni_ne_s_ecrit(
        self, fabrique_de_banc: Callable[..., Personne], sans_coupe_circuit: None
    ) -> None:
        sans = fabrique_de_banc(mail_provider="local")
        sans.banc.app.state.empreintes = Empreintes(None)
        reponse = await sans.banc.client().post(ROUTE, json={"email": sans.email}, headers=ECRITURE)
        assert reponse.status_code == 503
        assert boite(sans).codes == [] and lignes(sans, sans.email) == []

    async def test_une_erreur_de_la_base_rend_503_jamais_500(
        self, moi: Personne, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def casse(*_: object) -> int:
            raise psycopg.OperationalError("boum")

        monkeypatch.setattr(code_de_connexion, "prendre_les_creneaux_de_demande", casse)
        reponse = await demande(moi, moi.email)
        assert reponse.status_code == 503
        assert boite(moi).codes == []


class TestQuiRecoitUnCode:
    async def test_un_compte_connu_recoit_un_code_dont_seule_l_empreinte_est_ecrite(
        self, moi: Personne
    ) -> None:
        reponse = await demande(moi, moi.email)
        (message,) = boite(moi).codes
        assert message.destinataire == moi.email and message.validite_min == 10
        assert re.fullmatch(r"[0-9]{6}", message.code)
        (ligne,) = lignes(moi, moi.email)
        identifiant = UUID(reponse.json()["code_request_id"])
        assert ligne[0] == identifiant and ligne[1] == moi.id
        cle = moi.banc.empreintes.cle_compte(moi.email)
        assert cle is not None
        assert bytes(ligne[2]) == moi.banc.empreintes.empreinte_du_code(identifiant, cle, message.code)
        assert ligne[3] == 0 and ligne[6] is None and ligne[7] is None
        assert (ligne[5] - ligne[4]).total_seconds() == 600

    async def test_l_adresse_se_normalise_comme_ailleurs(self, moi: Personne) -> None:
        pleine_largeur = "".join(
            chr(ord(c) + 0xFEE0) if c.isalnum() and c.isascii() else c for c in moi.email
        )
        assert (await demande(moi, f" {moi.email.upper()} ")).status_code == 202
        assert (await demande(moi, pleine_largeur)).status_code == 202
        assert (
            len(boite(moi).codes) == 1
        )  # le second est dans les 60 s du premier : même compte, rien de neuf
        assert len(lignes(moi, moi.email)) == 1

    @pytest.mark.parametrize("etat", ["banni", "supprime", "sans_profil"])
    async def test_jamais_de_mail_pour_banni_supprime_ou_sans_profil(self, moi: Personne, etat: str) -> None:
        admin = moi.banc.fabrique.admin
        if etat == "banni":
            admin.execute(
                "update auth.users set banned_until = now() + interval '1 day' where id = %s", (moi.id,)
            )
        elif etat == "supprime":
            admin.execute("update auth.users set deleted_at = now() where id = %s", (moi.id,))
        else:
            admin.execute("delete from public.user_profile where id = %s", (moi.id,))
        reponse = await demande(moi, moi.email)
        assert reponse.status_code == 202
        assert boite(moi).codes == []
        assert [ligne[1] for ligne in lignes(moi, moi.email)] == [None]  # une ligne factice, sans personne

    async def test_un_bannissement_echu_ne_compte_plus(self, moi: Personne) -> None:
        moi.banc.fabrique.admin.execute(
            "update auth.users set banned_until = now() - interval '1 minute' where id = %s", (moi.id,)
        )
        await demande(moi, moi.email)
        assert len(boite(moi).codes) == 1

    async def test_jamais_de_mail_pour_une_adresse_inconnue(self, moi: Personne) -> None:
        assert (await demande(moi, INCONNUE)).status_code == 202
        assert boite(moi).codes == []
        assert [ligne[1] for ligne in lignes(moi, INCONNUE)] == [None]

    async def test_l_evenement_n_est_ecrit_que_pour_un_compte_reel_et_porte_la_requete(
        self, moi: Personne
    ) -> None:
        reponse = await demande(moi, moi.email)
        await demande(moi, INCONNUE)
        (evenement,) = moi.evenements("code_demande")
        assert evenement[1] == moi.banc.empreintes.cle_compte(moi.email)
        assert (
            moi.banc.lignes(
                "select 1 from public.security_event where kind = 'code_demande' and account_key = %s",
                moi.banc.empreintes.cle_compte(INCONNUE),
            )
            == []
        )
        (requete,) = moi.banc.lignes(
            "select request_id from public.security_event where kind = 'code_demande' and person_id = %s",
            moi.id,
        )
        assert requete[0] == reponse.headers["x-request-id"]


class TestLimites:
    async def test_la_quatrieme_demande_de_la_meme_paire_donne_429_pour_connu_et_inconnu(
        self, moi: Personne
    ) -> None:
        for adresse in (moi.email, INCONNUE):
            for _ in range(3):
                assert (await demande(moi, adresse)).status_code == 202
            refus = await demande(moi, adresse)
            assert refus.status_code == 429
            assert refus.json()["code"] == "trop_de_requetes"
            assert 0 < int(refus.headers["retry-after"]) <= 900
        assert len(boite(moi).codes) == 1  # les 2e et 3e étaient dans les 60 s du premier

    async def test_la_onzieme_demande_d_une_ip_donne_429_meme_pour_dix_adresses_differentes(
        self, moi: Personne
    ) -> None:
        for i in range(10):
            assert (await demande(moi, f"inconnue{i}@test.local")).status_code == 202
        refus = await demande(moi, "autre@test.local")
        assert refus.status_code == 429 and 0 < int(refus.headers["retry-after"]) <= 900

    async def test_la_septieme_demande_d_une_adresse_donne_429_depuis_sept_ip_pour_connu_et_inconnu(
        self, moi: Personne
    ) -> None:
        for adresse, debut in ((moi.email, 10), (INCONNUE, 20)):
            for i in range(6):
                assert (await demande(moi, adresse, ip=f"198.51.100.{debut + i}")).status_code == 202
            refus = await demande(moi, adresse, ip=f"198.51.100.{debut + 6}")
            assert refus.status_code == 429 and 0 < int(refus.headers["retry-after"]) <= 3600

    async def test_dix_adresses_d_une_ip_ne_privent_personne_d_un_code(self, moi: Personne) -> None:
        for i in range(10):
            await demande(moi, f"inconnue{i}@test.local", ip="198.51.100.30")
        assert (await demande(moi, "encore@test.local", ip="198.51.100.30")).status_code == 429
        assert (
            await demande(moi, moi.email)
        ).status_code == 202  # l'IP de la personne : ses créneaux sont intacts
        assert len(boite(moi).codes) == 1

    async def test_une_ip_bloquee_n_use_ni_la_paire_ni_l_adresse(self, moi: Personne) -> None:
        for i in range(10):
            await demande(moi, f"inconnue{i}@test.local", ip="198.51.100.31")
        assert (await demande(moi, moi.email, ip="198.51.100.31")).status_code == 429
        empreintes = moi.banc.empreintes
        assert creneaux(moi, "code_paire", empreintes.cle_paire_de_code(moi.email, "198.51.100.31")) == []
        assert creneaux(moi, "code_compte", empreintes.cle_compte(moi.email)) == []

    async def test_un_refus_de_demande_ne_touche_pas_aux_limites_de_connexion(self, moi: Personne) -> None:
        for _ in range(4):
            await demande(moi, moi.email)
        assert moi.essais() == 0  # le compteur `account` de la connexion n'a pas bougé


class TestCoupeCircuitGlobal:
    def ferme(self, moi: Personne) -> None:
        moi.banc.fabrique.admin.execute(
            "insert into public.login_throttle (scope, key, window_start, attempts)"
            " values ('mail_global', %s, now(), 60)",
            (CLE_GLOBALE,),
        )

    def envois(self, moi: Personne) -> int:
        lignes = moi.banc.lignes(
            "select attempts from public.login_throttle where scope = 'mail_global' and key = %s", CLE_GLOBALE
        )
        return int(lignes[0][0]) if lignes else 0

    async def test_un_coupe_circuit_ouvert_jette_le_mail_sans_changer_la_reponse(
        self, moi: Personne, caplog: pytest.LogCaptureFixture
    ) -> None:
        temoin = await demande(moi, INCONNUE)
        self.ferme(moi)
        caplog.set_level(logging.DEBUG)
        reponse = await demande(moi, moi.email)
        assert reponse.status_code == temoin.status_code == 202
        assert sans_identifiant(reponse.json()) == sans_identifiant(temoin.json())
        assert boite(moi).codes == []
        assert (
            len(lignes(moi, moi.email)) == 1
        )  # le code existe : la clé d'accès, ou une autre demande, restent
        assert "coupe-circuit global ouvert" in caplog.text and moi.email not in caplog.text

    async def test_seul_un_envoi_reel_compte_pour_le_coupe_circuit(self, moi: Personne) -> None:
        for i in range(5):
            await demande(moi, f"inconnue{i}@test.local")
        assert self.envois(moi) == 0  # une adresse inventée n'envoie rien : elle n'use rien
        await demande(moi, moi.email)
        assert self.envois(moi) == 1
        await demande(moi, moi.email)  # dans les 60 s : aucun mail
        assert self.envois(moi) == 1


class TestRenouvellement:
    async def test_une_demande_dans_les_60_secondes_rend_le_meme_identifiant_et_n_envoie_rien(
        self, moi: Personne
    ) -> None:
        premiere = await demande(moi, moi.email)
        seconde = await demande(moi, moi.email)
        assert seconde.json()["code_request_id"] == premiere.json()["code_request_id"]
        assert len(boite(moi).codes) == 1 and len(lignes(moi, moi.email)) == 1

    async def test_au_dela_de_60_secondes_un_code_neuf_revoque_le_precedent(
        self, moi: Personne, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(code_de_connexion, "code_neuf", lambda: "123456")  # le même code deux fois
        premiere = await demande(moi, moi.email)
        vieillit(moi, moi.email)
        seconde = await demande(moi, moi.email)
        assert seconde.json()["code_request_id"] != premiere.json()["code_request_id"]
        ancien, neuf = lignes(moi, moi.email)
        assert ancien[7] is not None and neuf[7] is None and actifs(moi, moi.email) == 1
        assert bytes(ancien[2]) != bytes(neuf[2])  # le même code, deux demandes : deux empreintes
        assert [m.code for m in boite(moi).codes] == ["123456", "123456"]

    @pytest.mark.parametrize("reelle", [True, False], ids=["connue", "inconnue"])
    async def test_cinquante_demandes_simultanees_ne_laissent_qu_une_ligne_active_et_un_mail(
        self, reelle: bool, moi: Personne
    ) -> None:
        email = moi.email if reelle else INCONNUE
        reglages = moi.banc.app.state.settings
        reglages.code_demandes_par_ip = reglages.code_demandes_par_paire = 10_000
        reglages.code_demandes_par_compte = 10_000
        reponses = await asyncio.wait_for(
            asyncio.gather(*(demande(moi, email, ip=f"198.51.101.{i + 1}") for i in range(50))), timeout=60
        )
        assert {r.status_code for r in reponses} == {202}
        assert actifs(moi, email) == 1 and len(lignes(moi, email)) == 1
        assert len({r.json()["code_request_id"] for r in reponses}) == 1
        assert len(boite(moi).codes) == (1 if reelle else 0)


class TestEnvoiEtJournaux:
    async def test_un_envoi_qui_echoue_ne_change_pas_la_reponse_et_se_journalise_sans_adresse_ni_code(
        self, moi: Personne, caplog: pytest.LogCaptureFixture
    ) -> None:
        temoin = await demande(moi, INCONNUE)
        moi.banc.app.state.mails = MailAbsent()
        caplog.set_level(logging.DEBUG)
        reponse = await demande(moi, moi.email)
        assert reponse.status_code == temoin.status_code == 202
        assert sans_identifiant(reponse.json()) == sans_identifiant(temoin.json())
        assert any("non envoyé" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
        assert "MailIndisponible" in caplog.text and moi.email not in caplog.text
        assert len(lignes(moi, moi.email)) == 1

    async def test_un_envoi_qui_plante_autrement_ne_change_rien(self, moi: Personne) -> None:
        class Casse:
            async def envoie_le_code(self, message: MessageCode) -> None:
                raise RuntimeError("boum")

        moi.banc.app.state.mails = Casse()
        assert (await demande(moi, moi.email)).status_code == 202

    async def test_le_code_n_est_ni_dans_les_journaux_ni_les_evenements_ni_les_colonnes_ni_l_idempotence(
        self, moi: Personne, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        reponses = [await demande(moi, moi.email), await demande(moi, INCONNUE)]
        (message,) = boite(moi).codes
        code = message.code
        assert code not in caplog.text and moi.email not in caplog.text and INCONNUE not in caplog.text
        assert all(code not in r.text and moi.email not in r.text for r in reponses)
        tables = {
            "public.login_code": "account_key = %s",
            "public.security_event": "account_key = %s",
        }
        for table, filtre in tables.items():
            for adresse in (moi.email, INCONNUE):
                texte = moi.banc.lignes(
                    f"select coalesce(string_agg(to_jsonb(t)::text, ' '), '') from {table} t where {filtre}",  # noqa: S608  # noms écrits ici
                    moi.banc.empreintes.cle_compte(adresse),
                )[0][0]
                assert code not in texte and moi.email not in texte and INCONNUE not in texte
        (idem,) = moi.banc.lignes(
            "select count(*) from public.idempotency_key t where to_jsonb(t)::text like %s", f"%{code}%"
        )
        assert idem[0] == 0
        (ligne,) = lignes(moi, moi.email)
        assert code.encode() not in bytes(ligne[2])
