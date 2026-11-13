"""T15a : `POST /api/v1/password-resets` (spec § 4, § 3.6 ; B3, B5, B24), en base locale.

Données inventées. Un banc par test (une IP de test à lui) ; la boîte de test garde les messages en mémoire :
aucun mail ne part. L'usage du lien est T15b.
"""

# ruff: noqa: F811, F401

import asyncio
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _client import cookie
from test_connexion import ECRITURE
from test_reauthentification import Personne, fabrique_de_banc

from popote_api.infra.mails import BoiteDeTest, MailAbsent, MailIndisponible, MessageReinitialisation
from popote_api.security.jeton import FORME_DU_JETON, empreinte_du_jeton

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/password-resets"
ORIGINE = "http://localhost:5173"
INCONNUE = "personne-n-existe-ici@test.local"


@pytest.fixture
def moi(fabrique_de_banc: Callable[..., Personne]) -> Personne:
    banc_personne = fabrique_de_banc(public_base_url=ORIGINE, mail_provider="local")
    return banc_personne


def boite(moi: Personne) -> BoiteDeTest:
    mails = moi.banc.app.state.mails
    assert isinstance(mails, BoiteDeTest)
    return mails


async def demande(
    moi: Personne, email: str, *, origine: bool = True, ip: str | None = None
) -> httpx.Response:
    moi.banc.cles += [
        c
        for c in (
            moi.banc.empreintes.cle_reinitialisation(email, ip or moi.banc.ip),
            moi.banc.empreintes.cle_compte(email),
        )
        if c
    ]
    return await moi.banc.client(ip).post(ROUTE, json={"email": email}, headers=ECRITURE if origine else {})


def liens(moi: Personne, personne: Any = None) -> list[tuple[Any, ...]]:
    return moi.banc.lignes(
        "select token_hash, created_at, expires_at, used_at, revoked_at from public.password_reset "
        "where person_id = %s order by created_at, id",
        personne or moi.id,
    )


def actifs(moi: Personne) -> int:
    return sum(1 for ligne in liens(moi) if ligne[3] is None and ligne[4] is None)


def jeton_du(message: MessageReinitialisation) -> str:
    return message.lien.split("#", 1)[1]


def entetes_stables(reponse: httpx.Response) -> dict[str, str]:
    # `ratelimit` : le compteur des requêtes de l'appelant, pas une information sur le compte.
    ignores = {"x-request-id", "date", "server-timing", "ratelimit"}
    return {k: v for k, v in reponse.headers.items() if k not in ignores}


class TestReponseUniforme:
    async def test_compte_connu_et_inconnu_donnent_meme_statut_meme_corps_memes_entetes(
        self, moi: Personne
    ) -> None:
        connu = await demande(moi, moi.email)
        inconnu = await demande(moi, INCONNUE)
        assert connu.status_code == inconnu.status_code == 202
        assert connu.json() == inconnu.json() and set(connu.json()) == {"message"}
        assert entetes_stables(connu) == entetes_stables(inconnu)
        assert "set-cookie" not in connu.headers

    async def test_le_temps_est_comparable(self, moi: Personne) -> None:
        async def mediane(email: str, debut_ip: int) -> float:
            durees = []
            for i in range(5):  # une IP à chaque appel : jamais de 429
                avant = time.perf_counter()
                await demande(moi, email, ip=f"198.51.100.{debut_ip + i}")
                durees.append(time.perf_counter() - avant)
            return sorted(durees)[2]

        connu = await mediane(moi.email, 100)
        inconnu = await mediane(INCONNUE, 150)
        assert abs(connu - inconnu) < 0.25

    async def test_une_adresse_mal_formee_ou_en_trop_est_refusee_sans_creneau(self, moi: Personne) -> None:
        client = moi.banc.client()
        assert (await client.post(ROUTE, json={"email": "a" * 300}, headers=ECRITURE)).status_code == 422
        assert (await client.post(ROUTE, json={"email": "a\u0000@x.fr"}, headers=ECRITURE)).status_code == 422
        assert (
            await client.post(ROUTE, json={"email": "a@x.fr", "extra": 1}, headers=ECRITURE)
        ).status_code == 422
        assert boite(moi).messages == []

    async def test_sans_origine_403_et_rien_ne_compte(self, moi: Personne) -> None:
        reponse = await demande(moi, moi.email, origine=False)
        assert reponse.status_code == 403
        assert boite(moi).messages == [] and liens(moi) == []
        assert (await demande(moi, moi.email)).status_code == 202  # aucun créneau n'avait été pris


class TestQuiRecoitUnLien:
    async def test_un_compte_connu_recoit_un_lien_de_la_configuration_jeton_apres_le_diese(
        self, moi: Personne
    ) -> None:
        assert (await demande(moi, moi.email)).status_code == 202
        (message,) = boite(moi).messages
        assert message.destinataire == moi.email
        assert re.fullmatch(re.escape(ORIGINE) + r"/reinitialisation#[A-Za-z0-9_-]{43}", message.lien)
        jeton = jeton_du(message)
        assert FORME_DU_JETON.fullmatch(jeton)
        (ligne,) = liens(moi)
        assert bytes(ligne[0]) == empreinte_du_jeton(jeton)  # seule l'empreinte est écrite
        assert (ligne[2] - ligne[1]).total_seconds() == 30 * 60
        assert ligne[3] is None and ligne[4] is None

    async def test_l_adresse_se_normalise_comme_ailleurs(self, moi: Personne) -> None:
        pleine_largeur = "".join(
            chr(ord(c) + 0xFEE0) if c.isalnum() and c.isascii() else c for c in moi.email
        )
        assert (await demande(moi, f" {moi.email.upper()} ")).status_code == 202
        assert (await demande(moi, pleine_largeur)).status_code == 202
        assert len(boite(moi).messages) == 2
        assert actifs(moi) == 1  # le second a révoqué le premier : un seul compte, une seule personne

    @pytest.mark.parametrize("etat", ["banni", "supprime", "sans_profil"])
    async def test_jamais_pour_banni_supprime_ou_sans_profil(self, moi: Personne, etat: str) -> None:
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
        assert boite(moi).messages == [] and liens(moi) == []

    async def test_un_bannissement_echu_ne_compte_plus(self, moi: Personne) -> None:
        moi.banc.fabrique.admin.execute(
            "update auth.users set banned_until = now() - interval '1 minute' where id = %s", (moi.id,)
        )
        await demande(moi, moi.email)
        assert len(boite(moi).messages) == 1

    async def test_jamais_pour_une_adresse_inconnue(self, moi: Personne) -> None:
        assert (await demande(moi, INCONNUE)).status_code == 202
        assert boite(moi).messages == []


class TestLimite:
    async def test_la_quatrieme_demande_de_l_heure_donne_429_pour_connu_et_inconnu(
        self, moi: Personne
    ) -> None:
        for adresse in (moi.email, INCONNUE):
            for _ in range(3):
                assert (await demande(moi, adresse)).status_code == 202
            refus = await demande(moi, adresse)
            assert refus.status_code == 429
            assert refus.json()["code"] == "trop_de_requetes"
            assert 0 < int(refus.headers["retry-after"]) <= 3600
        assert len(boite(moi).messages) == 3  # aucun mail à la 4e

    async def test_une_autre_ip_n_use_pas_les_creneaux_de_la_personne(self, moi: Personne) -> None:
        for _ in range(3):
            await demande(moi, moi.email, ip="198.51.100.10")
        assert (await demande(moi, moi.email, ip="198.51.100.10")).status_code == 429
        assert (await demande(moi, moi.email)).status_code == 202  # l'IP de la personne : ses 3 sont intacts

    async def test_sans_poivre_503_et_rien_ne_part(self, fabrique_de_banc: Callable[..., Personne]) -> None:
        sans = fabrique_de_banc(public_base_url=ORIGINE, mail_provider="local")
        sans.banc.app.state.empreintes = type(sans.banc.empreintes)(None)
        reponse = await sans.banc.client().post(ROUTE, json={"email": sans.email}, headers=ECRITURE)
        assert reponse.status_code == 503
        assert boite(sans).messages == []


class TestRenouvellement:
    async def test_une_nouvelle_demande_revoque_le_lien_precedent(self, moi: Personne) -> None:
        await demande(moi, moi.email)
        await demande(moi, moi.email)
        premier, second = liens(moi)
        assert premier[4] is not None and second[4] is None  # le premier est révoqué, le second actif
        assert actifs(moi) == 1
        anciens, recents = boite(moi).messages
        assert bytes(premier[0]) == empreinte_du_jeton(jeton_du(anciens))
        assert bytes(second[0]) == empreinte_du_jeton(jeton_du(recents))

    async def test_deux_demandes_simultanees_ne_laissent_qu_un_lien_actif(self, moi: Personne) -> None:
        reponses = await asyncio.wait_for(
            asyncio.gather(
                demande(moi, moi.email, ip="198.51.100.20"), demande(moi, moi.email, ip="198.51.100.21")
            ),
            timeout=20,
        )
        assert [r.status_code for r in reponses] == [202, 202]
        assert actifs(moi) == 1 and len(liens(moi)) == 2

    async def test_un_lien_deja_utilise_n_est_pas_touche_par_la_revocation(self, moi: Personne) -> None:
        await demande(moi, moi.email)
        moi.banc.fabrique.admin.execute(
            "update public.password_reset set used_at = now() where person_id = %s", (moi.id,)
        )
        await demande(moi, moi.email)
        utilise, neuf = liens(moi)
        assert utilise[3] is not None and utilise[4] is None and neuf[4] is None


class TestEnvoiEtJournaux:
    async def test_un_envoi_qui_echoue_ne_change_pas_la_reponse_et_se_journalise_sans_adresse_ni_lien(
        self, moi: Personne, caplog: pytest.LogCaptureFixture
    ) -> None:
        temoin = await demande(moi, INCONNUE)
        moi.banc.app.state.mails = MailAbsent()
        caplog.set_level(logging.DEBUG)
        reponse = await demande(moi, moi.email)
        assert reponse.status_code == temoin.status_code == 202
        assert reponse.json() == temoin.json()
        erreurs = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("non envoyé" in r.getMessage() for r in erreurs)
        assert len(liens(moi)) == 1
        assert moi.email not in caplog.text and "reinitialisation#" not in caplog.text
        assert "MailIndisponible" in caplog.text

    async def test_un_envoi_qui_plante_autrement_ne_change_rien(self, moi: Personne) -> None:
        class Casse:
            async def envoie_la_reinitialisation(self, message: MessageReinitialisation) -> None:
                raise RuntimeError("boum")

        moi.banc.app.state.mails = Casse()
        assert (await demande(moi, moi.email)).status_code == 202

    async def test_sans_public_base_url_rien_ne_part_et_l_erreur_est_journalisee(
        self, fabrique_de_banc: Callable[..., Personne], caplog: pytest.LogCaptureFixture
    ) -> None:
        sans = fabrique_de_banc(mail_provider="local")
        caplog.set_level(logging.DEBUG)
        assert (await demande(sans, sans.email)).status_code == 202
        assert boite(sans).messages == []
        assert "POPOTE_PUBLIC_BASE_URL absente" in caplog.text

    async def test_ni_jeton_ni_lien_dans_les_journaux_les_evenements_ni_l_idempotence(
        self, moi: Personne, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        await demande(moi, moi.email)
        await demande(moi, INCONNUE)
        jeton = jeton_du(boite(moi).messages[0])
        assert jeton not in caplog.text and moi.email not in caplog.text and INCONNUE not in caplog.text
        evenements = moi.banc.lignes(
            "select to_jsonb(e)::text from public.security_event e where kind = 'reinitialisation_demandee' "
            "and (person_id = %s or account_key = %s)",
            moi.id,
            moi.banc.empreintes.cle_compte(INCONNUE),
        )
        assert len(evenements) == 1
        assert all(jeton not in e[0] and moi.email not in e[0] and INCONNUE not in e[0] for e in evenements)
        (idem,) = moi.banc.lignes(
            "select count(*) from public.idempotency_key where body::text like %s", f"%{jeton}%"
        )
        assert idem[0] == 0
        assert (
            moi.banc.lignes("select 1 from public.password_reset where token_hash = %s", jeton.encode()) == []
        )

    async def test_l_evenement_n_est_ecrit_que_pour_un_compte_qui_recoit_un_lien(self, moi: Personne) -> None:
        await demande(moi, moi.email)
        await demande(moi, INCONNUE)
        (connu,) = moi.evenements("reinitialisation_demandee")
        assert connu[1] == moi.banc.empreintes.cle_compte(moi.email)
        assert (
            moi.banc.lignes(
                "select 1 from public.security_event "
                "where kind = 'reinitialisation_demandee' and account_key = %s",
                moi.banc.empreintes.cle_compte(INCONNUE),
            )
            == []
        )  # une adresse inconnue ne remplit pas le journal (90 jours)

    async def test_un_envoi_annule_par_le_delai_se_journalise_puis_propage_l_annulation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from types import SimpleNamespace

        from pydantic import AnyHttpUrl

        from popote_api.api.reinitialisation import envoie_le_courrier
        from popote_api.security.reinitialisation import Courrier

        class Lent:
            async def envoie_la_reinitialisation(self, message: MessageReinitialisation) -> None:
                await asyncio.sleep(60)

        etat = SimpleNamespace(settings=SimpleNamespace(public_base_url=AnyHttpUrl(ORIGINE)), mails=Lent())
        caplog.set_level(logging.DEBUG)
        tache = asyncio.create_task(envoie_le_courrier(etat, Courrier("a@x.fr", "j" * 43)))  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache
        assert (
            "annulé (délai dépassé)" in caplog.text
            and "a@x.fr" not in caplog.text
            and "j" * 43 not in caplog.text
        )


class TestTable:
    async def test_la_base_refuse_une_echeance_de_plus_de_30_minutes(self, moi: Personne) -> None:
        import psycopg

        admin = moi.banc.fabrique.admin
        with pytest.raises(psycopg.errors.CheckViolation):
            admin.execute(
                "insert into public.password_reset (person_id, token_hash, expires_at) "
                "values (%s, %s, now() + interval '31 minutes')",
                (moi.id, b"\x01" * 32),
            )

    async def test_la_purge_efface_ce_qui_a_plus_de_7_jours_de_fin_de_vie(self, moi: Personne) -> None:
        admin = moi.banc.fabrique.admin
        admin.execute(
            "insert into public.password_reset (person_id, token_hash, created_at, expires_at, revoked_at) "
            "values "
            "(%s, %s, now() - interval '9 days', now() - interval '9 days' + interval '30 minutes', now()), "
            "(%s, %s, now() - interval '3 days', now() - interval '3 days' + interval '30 minutes', now())",
            (moi.id, b"\x02" * 32, moi.id, b"\x03" * 32),
        )
        (ligne,) = admin.execute("select private.purge_password_reset()").fetchall()
        assert ligne[0] >= 1
        restants = {bytes(ligne[0]) for ligne in liens(moi)}
        assert b"\x02" * 32 not in restants and b"\x03" * 32 in restants

    async def test_supprimer_le_compte_emporte_ses_liens(self, moi: Personne) -> None:
        await demande(moi, moi.email)
        assert len(liens(moi)) == 1
        moi.banc.fabrique.admin.execute("select 1")  # la cascade se joue à la suppression de `auth.users`
        moi.banc.fabrique.admin.execute("delete from public.user_profile where id = %s", (moi.id,))
        moi.banc.fabrique.admin.execute("delete from auth.users where id = %s", (moi.id,))
        assert liens(moi) == []
