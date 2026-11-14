"""T10 : `POST /api/v1/me/reauthentication` et la garde `exige_reauth` (spec § 4 ; B6, B21), en base locale.

Données inventées. Chaque test prend sa propre adresse IP et retire ses compteurs et ses événements.
"""

import unicodedata
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from _client import application_de_test, client_de, cookie
from _fabrique import Fabrique, SessionDeTest
from fastapi import APIRouter
from test_connexion import ECRITURE, MOT_DE_PASSE, Banc
from test_verifie_mot_de_passe import Comptes

from popote_api.infra.db import Base
from popote_api.security import connexion as modele_connexion
from popote_api.security.reauth import EXIGE_UNE_REAUTHENTIFICATION

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/me/reauthentication"
FAUX = "mauvais-mot-de-passe-long"


class Personne:
    """Un compte au mot de passe connu, avec une session posée, sur un banc."""

    def __init__(self, banc: Banc, mot_de_passe: str = MOT_DE_PASSE) -> None:
        self.banc = banc
        self.id, self.email = banc.compte(mot_de_passe)
        self.session = banc.fabrique.session(self.id)
        self.cle = banc.empreintes.cle_compte(self.email)
        banc.cles += [c for c in (self.cle, banc.empreintes.cle_ip(banc.ip)) if c]

    async def reauthentifie(
        self, corps: dict[str, Any] | None = None, *, session: SessionDeTest | None = None
    ) -> httpx.Response:
        envoi = {"password": MOT_DE_PASSE} if corps is None else corps
        return await self.banc.client().post(
            ROUTE, json=envoi, headers=cookie(session or self.session) | ECRITURE
        )

    def reauth_at(self, session: UUID | None = None) -> datetime:
        (ligne,) = self.banc.lignes(
            "select reauth_at from public.login_session where id = %s", session or self.session.id
        )
        return ligne[0]  # type: ignore[no-any-return]

    def vieillit(self, session: UUID | None = None, *, de: timedelta = timedelta(hours=1)) -> None:
        self.banc.fabrique.admin.execute(
            "update public.login_session set reauth_at = now() - %s where id = %s",
            (de, session or self.session.id),
        )

    def essais(self) -> int:
        (ligne,) = self.banc.lignes(
            "select coalesce(sum(attempts), 0) from public.login_throttle "
            "where scope = 'account' and key = %s",
            self.cle,
        )
        return int(ligne[0])

    def evenements(self, genre: str) -> list[tuple[Any, ...]]:
        return self.banc.lignes(
            "select session_id, account_key, ip_hash from public.security_event "
            "where kind = %s and person_id = %s",
            genre,
            self.id,
        )


@pytest.fixture
async def fabrique_de_banc(base: Base, fabrique: Fabrique) -> AsyncIterator[Callable[..., Personne]]:
    """Une personne sur un banc neuf ; compteurs et événements retirés à la fin, même si le test échoue."""
    faites: list[Personne] = []

    def cree(**reglages: Any) -> Personne:
        # Par défaut l'IP ne bloque pas : seul le compte compte.
        banc = Banc(base, fabrique, Comptes(fabrique), **({"connexion_essais_par_ip": 10000} | reglages))
        faites.append(Personne(banc))
        return faites[-1]

    yield cree
    for personne in faites:
        personne.banc.nettoie()
        personne.banc.fabrique.admin.execute(
            "delete from public.security_event where person_id = %s", (personne.id,)
        )


@pytest.fixture
def moi(fabrique_de_banc: Callable[..., Personne]) -> Personne:
    return fabrique_de_banc()


@pytest.fixture
def verifications(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Un espion sur la vérification : une entrée par appel à `verifie_mot_de_passe_de` (un `crypt()`)."""
    appels: list[UUID] = []
    origine = modele_connexion.verifie_un_candidat_de

    async def espion(curseur: Any, personne: UUID, candidat: str) -> bool:
        appels.append(personne)
        return await origine(curseur, personne, candidat)

    monkeypatch.setattr(modele_connexion, "verifie_un_candidat_de", espion)
    return appels


class TestReauthentification:
    async def test_le_bon_mot_de_passe_donne_204_et_pose_reauth_at(self, moi: Personne) -> None:
        moi.vieillit()
        avant = moi.reauth_at()
        reponse = await moi.reauthentifie()
        assert reponse.status_code == 204
        assert reponse.content == b""
        assert reponse.headers["cache-control"] == "no-store"
        assert moi.reauth_at() - avant > timedelta(minutes=59)

    async def test_un_faux_mot_de_passe_donne_403_et_le_compteur_du_compte_avance(
        self, moi: Personne
    ) -> None:
        moi.vieillit()
        avant = moi.reauth_at()
        reponse = await moi.reauthentifie({"password": FAUX})
        assert reponse.status_code == 403
        assert reponse.json()["code"] == "mot_de_passe_incorrect"
        assert moi.essais() == 1
        assert moi.reauth_at() == avant  # rien n'est posé

    async def test_cinq_faux_puis_le_bon_donne_429_sans_aucun_crypt_et_bloque_la_connexion(
        self, moi: Personne, verifications: list[UUID]
    ) -> None:
        for _ in range(5):
            assert (await moi.reauthentifie({"password": FAUX})).status_code == 403
        avant = len(verifications)
        reponse = await moi.reauthentifie()  # le bon, pendant le blocage
        assert reponse.status_code == 429
        assert int(reponse.headers["retry-after"]) > 0
        assert reponse.json()["code"] == "trop_de_requetes"
        assert len(verifications) == avant  # aucun crypt() pour un refus de créneau
        connexion = await moi.banc.connecte_par_code(moi.email, moi.id)  # même compteur : bloquée aussi
        assert connexion.status_code == 429

    async def test_cinq_faux_a_la_connexion_bloquent_aussi_la_reauthentification(self, moi: Personne) -> None:
        for _ in range(5):
            assert (await moi.banc.connecte_par_code(moi.email, moi.id, faux=True)).status_code == 401
        assert (await moi.reauthentifie()).status_code == 429

    async def test_le_succes_remet_le_compteur_a_zero(self, moi: Personne) -> None:
        for _ in range(3):
            await moi.reauthentifie({"password": FAUX})
        assert moi.essais() == 3
        assert (await moi.reauthentifie()).status_code == 204
        assert moi.essais() == 0

    async def test_une_ip_bloquee_ne_consomme_pas_les_creneaux_du_compte(
        self, fabrique_de_banc: Callable[..., Personne]
    ) -> None:
        moi = fabrique_de_banc(connexion_essais_par_ip=2)
        for _ in range(2):
            await moi.reauthentifie({"password": FAUX})
        compte = moi.essais()
        for _ in range(10):
            assert (await moi.reauthentifie({"password": FAUX})).status_code == 429
        assert moi.essais() == compte  # B6 : une IP bloquée n'épuise pas le compte

    async def test_un_seul_evenement_de_blocage_par_fenetre(self, moi: Personne) -> None:
        for _ in range(30):
            await moi.reauthentifie({"password": FAUX})
        bloquees = moi.banc.lignes(
            "select 1 from public.security_event where kind = 'connexion_bloquee' and account_key = %s",
            moi.cle,
        )
        assert len(bloquees) == 1  # B21

    async def test_sans_session_401_et_aucun_creneau_pris(self, moi: Personne) -> None:
        reponse = await moi.banc.client().post(ROUTE, json={"password": MOT_DE_PASSE}, headers=ECRITURE)
        assert reponse.status_code == 401
        assert reponse.json()["code"] == "pas_de_session"
        assert moi.essais() == 0

    async def test_seule_la_session_presentee_est_marquee(
        self, fabrique_de_banc: Callable[..., Personne]
    ) -> None:
        moi, autre = fabrique_de_banc(), fabrique_de_banc()
        deuxieme = moi.banc.fabrique.session(moi.id)  # une autre session de la MÊME personne
        for personne, session in ((moi, moi.session.id), (moi, deuxieme.id), (autre, autre.session.id)):
            personne.vieillit(session)
        avant = [moi.reauth_at(moi.session.id), moi.reauth_at(deuxieme.id), autre.reauth_at()]
        assert (await moi.reauthentifie()).status_code == 204
        assert moi.reauth_at(moi.session.id) > avant[0]
        assert moi.reauth_at(deuxieme.id) == avant[1]
        assert autre.reauth_at() == avant[2]

    async def test_le_mot_de_passe_d_un_autre_compte_ne_passe_pas(
        self, fabrique_de_banc: Callable[..., Personne]
    ) -> None:
        moi = fabrique_de_banc()
        autre_mot_de_passe = "le-mot-de-passe-de-l-autre-1"
        autre_id, _ = moi.banc.compte(autre_mot_de_passe)
        reponse = await moi.reauthentifie({"password": autre_mot_de_passe})
        assert reponse.status_code == 403
        assert autre_id != moi.id

    @pytest.mark.parametrize(
        "corps",
        [
            {},
            {"password": "x", "email": "a@b.fr"},
            {"password": "x" * 257},
            {"password": None},
            {"password": 1},
        ],
        ids=["manquant", "en_trop", "plus_de_256", "nul", "pas_un_texte"],
    )
    async def test_un_corps_invalide_donne_422_sans_creneau_ni_recopie(
        self, moi: Personne, corps: dict[str, Any]
    ) -> None:
        reponse = await moi.reauthentifie(corps)
        assert reponse.status_code == 422
        assert "x" * 20 not in reponse.text
        assert moi.essais() == 0

    async def test_un_mot_de_passe_de_256_caracteres_est_accepte_par_le_modele(self, moi: Personne) -> None:
        assert (await moi.reauthentifie({"password": "x" * 256})).status_code == 403  # faux, mais lu

    async def test_un_ancien_mot_de_passe_non_normalise_est_accepte(
        self, base: Base, fabrique: Fabrique
    ) -> None:
        # Mêmes candidats que la connexion : la forme brute, hachée telle quelle autrefois, passe aussi.
        brut = unicodedata.normalize("NFKD", "écureuil-très-sûr-pleine") + "\uff21\uff22\uff23"
        banc = Banc(base, fabrique, Comptes(fabrique), connexion_essais_par_ip=10000)
        moi = Personne(banc, brut)
        try:
            assert (await moi.reauthentifie({"password": brut})).status_code == 204
        finally:
            banc.nettoie()

    async def test_les_evenements(self, moi: Personne) -> None:
        await moi.reauthentifie({"password": FAUX})
        await moi.reauthentifie()
        (reussie,) = moi.evenements("reauthentification_reussie")
        (ratee,) = moi.evenements("reauthentification_ratee")
        assert reussie[0] == moi.session.id and ratee[0] == moi.session.id
        assert reussie[2] is None and ratee[2] is None  # jamais l'IP ni son empreinte avec la personne
        assert ratee[1] == moi.cle  # la clé de compte, qui fait avancer le compteur
        assert FAUX not in str(reussie) + str(ratee)

    async def test_l_effet_est_idempotent_sans_idempotency_key(self, moi: Personne) -> None:
        premiere = await moi.reauthentifie()
        seconde = await moi.reauthentifie()
        assert premiere.status_code == seconde.status_code == 204
        assert "idempotency-key" not in {k.lower() for k in seconde.request.headers}

    async def test_sans_origine_la_garde_d_origine_refuse_et_rien_ne_compte(self, moi: Personne) -> None:
        reponse = await moi.banc.client().post(
            ROUTE, json={"password": MOT_DE_PASSE}, headers=cookie(moi.session)
        )
        assert reponse.status_code == 403
        assert moi.essais() == 0
        assert moi.evenements("reauthentification_reussie") == []


class TestGarde:
    """`exige_reauth` sur une route de test : `reauth_at` + 299 s passe, + 301 s refuse (horloge injectée)."""

    @pytest.fixture
    def client(self, base: Base, monkeypatch: pytest.MonkeyPatch) -> tuple[httpx.AsyncClient, Any]:
        sensible = APIRouter()

        @sensible.get("/essai/sensible", dependencies=[EXIGE_UNE_REAUTHENTIFICATION])
        async def sensible_get() -> dict[str, bool]:
            return {"ok": True}

        app = application_de_test(base, monkeypatch, sensible)
        return client_de(app), app

    async def _appel(self, client: Any, moi: Personne) -> httpx.Response:
        return await client[0].get("/api/v1/essai/sensible", headers=cookie(moi.session))

    @pytest.mark.parametrize(
        ("secondes", "statut"), [(0, 200), (299, 200), (300, 200), (301, 403), (3000, 403)]
    )
    async def test_la_fenetre_est_de_300_secondes(
        self, client: Any, moi: Personne, secondes: int, statut: int
    ) -> None:
        pose = moi.reauth_at()
        client[1].state.horloge = lambda: pose + timedelta(seconds=secondes)
        reponse = await self._appel(client, moi)
        assert reponse.status_code == statut
        if statut == 403:
            assert reponse.json()["code"] == "reauthentification_requise"
            assert "www-authenticate" not in reponse.headers  # 403, pas 401 : la session reste valide

    async def test_juste_apres_la_connexion_la_garde_passe(self, client: Any, moi: Personne) -> None:
        connexion = await moi.banc.connecte_par_code(moi.email, moi.id)  # la vraie connexion pose `reauth_at`
        assert connexion.status_code == 201
        jeton = connexion.cookies["__Host-popote_session"]
        reponse = await client[0].get(
            "/api/v1/essai/sensible", headers={"Cookie": f"__Host-popote_session={jeton}"}
        )
        assert reponse.status_code == 200

    async def test_une_session_vieille_est_refusee_puis_reauthentifiee_passe(
        self,
        moi: Personne,
        client: Any,  # `moi` d'abord : son application monte la vraie route
    ) -> None:
        moi.vieillit()
        assert (await self._appel(client, moi)).status_code == 403
        assert (await moi.reauthentifie()).status_code == 204
        assert (await self._appel(client, moi)).status_code == 200

    async def test_sans_session_401(self, client: Any) -> None:
        reponse = await client[0].get("/api/v1/essai/sensible")
        assert reponse.status_code == 401
