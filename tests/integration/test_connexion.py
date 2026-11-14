"""0.4bis S7b : `POST /api/v1/sessions` par le code reçu par mail, de bout en bout, contre la base locale
(spec § 4 ; B6, B21, B22, B24).

Données inventées. Chaque test prend sa propre adresse IP (la limite est de 20) et retire ses compteurs. Les
codes sont posés en direct dans `login_code` avec leur vraie empreinte (HMAC) : la demande par mail est testée
à part (`test_demande_de_code.py`). Ce module fournit aussi `Banc` aux autres tests d'intégration.
"""

import asyncio
import logging
import random
import secrets
import statistics
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from _client import NOM_DU_COOKIE, client_de
from _fabrique import Fabrique
from test_verifie_mot_de_passe import Comptes

from popote_api.config import Settings
from popote_api.infra.db import Base
from popote_api.main import create_app
from popote_api.security import connexion as modele_connexion
from popote_api.security.empreintes import Empreintes
from popote_api.security.jeton import empreinte_du_jeton
from popote_api.security.mots_de_passe import candidats_de_connexion

pytestmark = pytest.mark.integration

POIVRE = "p" * 32
MOT_DE_PASSE = "un-mot-de-passe-assez-long"
ECRITURE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}
REFUS = {"type", "title", "status", "detail", "code"}
MESSAGE = "Code incorrect ou expiré."


class Banc:
    def __init__(self, base: Base, fabrique: Fabrique, comptes: Comptes, **reglages: Any) -> None:
        self.reglages = Settings.model_validate(
            {"env": "local", "json_logs": False, "identity_pepper": POIVRE} | reglages
        )
        self.app = create_app(self.reglages)
        self.app.state.base = base
        self.fabrique, self.comptes = fabrique, comptes
        self.empreintes = Empreintes.depuis(self.reglages)
        self.ip = f"203.0.113.{random.randint(1, 254)}"  # une IP de test par banc
        self.cles: list[bytes] = []

    def client(self, ip: str | None = None) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app, client=(ip or self.ip, 5000))
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    def compte(self, mot_de_passe: str = MOT_DE_PASSE) -> tuple[UUID, str]:
        return self.comptes.bon(mot_de_passe)

    def personne(self) -> tuple[UUID, str]:
        """Une personne avec profil et foyer ; son mot de passe ne sert à rien ici."""
        personne = self.fabrique.personne(self.fabrique.foyer())
        ligne = self.fabrique.admin.execute(
            "select email from auth.users where id = %s", (personne.id,)
        ).fetchone()
        assert ligne is not None
        return personne.id, str(ligne[0])

    def pose_un_code(self, email: str, personne: UUID | None, *, code: str | None = None) -> tuple[UUID, str]:
        """Une demande de code vivante (la précédente est révoquée) : `(code_request_id, code)`.

        `personne` nul : une ligne FACTICE, comme celle d'une adresse inconnue."""
        bon = code or f"{secrets.randbelow(10**6):06d}"
        cle = self.empreintes.cle_compte(email)
        assert cle is not None
        identifiant = uuid4()
        admin = self.fabrique.admin
        admin.execute(
            "update public.login_code set revoked_at = now()"
            " where account_key = %s and used_at is null and revoked_at is null",
            (cle,),
        )
        admin.execute(
            "insert into public.login_code (id, account_key, person_id, code_hash) values (%s, %s, %s, %s)",
            (identifiant, cle, personne, self.empreintes.empreinte_du_code(identifiant, cle, bon)),
        )
        self.cles.append(cle)
        return identifiant, bon

    async def poste(
        self,
        email: str,
        code_request_id: UUID,
        code: str,
        *,
        client: httpx.AsyncClient | None = None,
        **plus: Any,
    ) -> httpx.Response:
        """Soumet un code à `POST /sessions` ; ne pose aucune ligne."""
        cle_ip = self.empreintes.cle_ip(self.ip)
        self.cles += [c for c in (self.empreintes.cle_compte(email), cle_ip) if c]
        entetes = ECRITURE | plus.pop("headers", {})
        corps = {
            "method": "email_code",
            "email": email,
            "code_request_id": str(code_request_id),
            "code": code,
        }
        return await (client or self.client()).post("/api/v1/sessions", json=corps, headers=entetes, **plus)

    async def connecte_par_code(
        self,
        email: str,
        personne: UUID | None = None,
        *,
        faux: bool = False,
        client: httpx.AsyncClient | None = None,
        **plus: Any,
    ) -> httpx.Response:
        """Pose une demande de code puis la soumet : le bon code, ou un faux (`faux=True`)."""
        identifiant, bon = self.pose_un_code(email, personne)
        envoye = f"{(int(bon) + 1) % 10**6:06d}" if faux else bon
        return await self.poste(email, identifiant, envoye, client=client, **plus)

    async def mot_de_passe_est_bon(self, email: str, mot_de_passe: str) -> bool:
        """Le mot de passe de ce compte est-il celui-là ? (la même fonction SQL que la réauthentification)."""
        async with self.app.state.base.connexion() as curseur:
            for candidat in candidats_de_connexion(mot_de_passe):
                await curseur.execute(
                    "select public.verifie_mot_de_passe(%s, %s) as personne", (email, candidat)
                )
                ligne = await curseur.fetchone()
                if ligne is not None and ligne["personne"] is not None:
                    return True
        return False

    def lignes(self, requete: str, *args: object) -> list[tuple[Any, ...]]:
        return self.fabrique.admin.execute(requete, args).fetchall()  # type: ignore[arg-type]

    def nettoie(self) -> None:
        self.fabrique.admin.execute("delete from public.login_throttle where key = any(%s)", (self.cles,))
        self.fabrique.admin.execute(
            "delete from public.security_event where account_key = any(%s)", (self.cles,)
        )
        self.fabrique.admin.execute("delete from public.login_code where account_key = any(%s)", (self.cles,))


@pytest.fixture
async def banc_avec(base: Base, fabrique: Fabrique, comptes: Comptes) -> AsyncIterator[Callable[..., Banc]]:
    """Fabrique de bancs : leurs compteurs et événements sont retirés à la fin, même si le test échoue."""
    bancs: list[Banc] = []

    def fabrique_de_banc(**reglages: Any) -> Banc:
        bancs.append(Banc(base, fabrique, comptes, **reglages))
        return bancs[-1]

    yield fabrique_de_banc
    for banc in bancs:
        banc.nettoie()


@pytest.fixture
def banc(banc_avec: Callable[..., Banc]) -> Banc:
    return banc_avec()


@pytest.fixture
def comptes(fabrique: Fabrique) -> Comptes:
    return Comptes(fabrique)


@pytest.fixture
def verifications(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Un espion sur la vérification en base : une entrée par appel de `ouvre_une_session_par_code`."""
    appels: list[UUID] = []
    origine = modele_connexion.ouvre_une_session_par_code

    async def espion(curseur: Any, **champs: Any) -> Any:
        appels.append(champs["code_request_id"])
        return await origine(curseur, **champs)

    monkeypatch.setattr(modele_connexion, "ouvre_une_session_par_code", espion)
    return appels


def cookie_brut(reponse: httpx.Response) -> str:
    return reponse.headers["set-cookie"]


async def test_succes_cookie_aux_attributs_exacts_et_jeton_seulement_en_empreinte(banc: Banc) -> None:
    personne, email = banc.personne()
    reponse = await banc.connecte_par_code(email, personne)
    assert reponse.status_code == 201
    brut = cookie_brut(reponse)
    nom, _, reste = brut.partition("=")
    jeton, _, attributs = reste.partition(";")
    assert nom == "__Host-popote_session"
    assert len(jeton) == 43
    # Les attributs exacts, tels que l'en-tête les écrit (casse et ordre de Starlette).
    assert {a.strip().lower() for a in attributs.split(";")} == {
        "max-age=7776000",
        "path=/",
        "httponly",
        "secure",
        "samesite=lax",
    }
    assert "domain" not in brut.lower()
    assert jeton not in reponse.text
    assert reponse.headers["cache-control"] == "no-store"
    id_session = UUID(reponse.json()["id"])
    assert set(reponse.json()) == {"id"}
    (ligne,) = banc.lignes(
        "select person_id, token_hash, opened_with, row(t.*)::text from public.login_session t where id = %s",
        id_session,
    )
    assert ligne[0] == personne and ligne[2] == "code"
    assert bytes(ligne[1]) == empreinte_du_jeton(jeton)
    assert jeton not in ligne[3]  # le jeton n'est dans aucune colonne


async def test_deux_connexions_deux_jetons(banc: Banc) -> None:
    personne, email = banc.personne()
    premier = await banc.connecte_par_code(email, personne)
    second = await banc.connecte_par_code(email, personne)
    assert cookie_brut(premier).split(";")[0] != cookie_brut(second).split(";")[0]


async def test_un_cookie_fourni_par_le_client_n_est_jamais_adopte(banc: Banc) -> None:
    personne, email = banc.personne()
    impose = "A" * 43
    reponse = await banc.connecte_par_code(email, personne, headers={"Cookie": f"{NOM_DU_COOKIE}={impose}"})
    assert reponse.status_code == 201
    assert impose not in cookie_brut(reponse)
    assert (
        banc.lignes("select 1 from public.login_session where token_hash = %s", empreinte_du_jeton(impose))
        == []
    )


def _sans_instance(reponse: httpx.Response) -> tuple[int, dict[str, Any], dict[str, str]]:
    corps = reponse.json()
    corps.pop("instance")
    en_tetes = {k: v for k, v in reponse.headers.items() if k not in {"x-request-id", "date", "ratelimit"}}
    return reponse.status_code, corps, en_tetes


CAS_DE_REFUS = [
    "faux", "inconnu", "factice", "demande_inconnue", "autre_adresse", "expire", "utilise", "revoque",
    "banni", "supprime", "sans_profil",
]  # fmt: skip


async def _refus_de(banc: Banc, cas: str) -> httpx.Response:
    """La réponse de la route dans le cas voulu, sur une personne neuve (ses créneaux sont les siens)."""
    if cas == "inconnu":  # une adresse sans compte : la ligne est factice, le code est « le bon »
        return await banc.connecte_par_code(f"inconnu-{random.randint(0, 10**9)}@test.local")
    personne, email = banc.personne()
    if cas == "faux":
        return await banc.connecte_par_code(email, personne, faux=True)
    if (
        cas == "factice"
    ):  # une adresse réelle dont la ligne est factice : jamais acceptée, même avec le bon code
        return await banc.connecte_par_code(email, None)
    identifiant, code = banc.pose_un_code(email, personne)
    admin = banc.fabrique.admin
    match cas:
        case "demande_inconnue":
            return await banc.poste(email, uuid4(), code)
        case "autre_adresse":
            return await banc.poste(banc.personne()[1], identifiant, code)
        case "expire":
            admin.execute(
                "update public.login_code set created_at = now() - interval '11 minutes',"
                " expires_at = now() - interval '1 minute' where id = %s",
                (identifiant,),
            )
        case "utilise":
            assert (await banc.poste(email, identifiant, code)).status_code == 201
        case "revoque":
            banc.pose_un_code(email, personne)  # une demande plus récente révoque celle-ci
        case "banni":
            admin.execute("update auth.users set banned_until = 'infinity' where id = %s", (personne,))
        case "supprime":
            admin.execute("update auth.users set deleted_at = now() where id = %s", (personne,))
        case "sans_profil":
            admin.execute("delete from public.user_profile where id = %s", (personne,))
        case _:
            raise AssertionError(cas)
    return await banc.poste(email, identifiant, code)


@pytest.mark.parametrize("cas", CAS_DE_REFUS)
async def test_tous_les_refus_se_ressemblent_au_champ_instance_pres(banc: Banc, cas: str) -> None:
    statut, corps, en_tetes = _sans_instance(await _refus_de(banc, cas))
    assert statut == 401
    assert corps["code"] == "code_incorrect"
    assert corps["detail"] == MESSAGE
    assert "set-cookie" not in en_tetes
    # La même réponse, au caractère près, que pour un faux code sur un compte connu.
    attendue = _sans_instance(await _refus_de(banc, "faux"))
    assert (statut, corps, en_tetes) == attendue


async def test_un_refus_valide_la_transaction_l_essai_reste_compte(banc: Banc) -> None:
    personne, email = banc.personne()
    identifiant, _ = banc.pose_un_code(email, personne)
    assert (await banc.poste(email, identifiant, "000000")).status_code in (
        401,
        201,
    )  # 1 chance sur 10^6 d'être bon
    cle = banc.empreintes.cle_compte(email)
    assert banc.lignes(
        "select attempts from public.login_throttle where scope = 'account' and key = %s", cle
    ) == [(1,)]
    assert banc.lignes(
        "select attempts, used_at is null from public.login_code where id = %s", identifiant
    ) == [(1, True)]


async def test_le_temps_d_une_adresse_inconnue_est_comparable_a_celui_d_un_faux_code(
    banc_avec: Callable[..., Banc],
) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000, connexion_essais_par_ip=10000)
    personne, email = banc.personne()

    async def duree(adresse: str, titulaire: UUID | None) -> float:
        debut = time.perf_counter()
        assert (await banc.connecte_par_code(adresse, titulaire, faux=True)).status_code == 401
        return time.perf_counter() - debut

    connus = [await duree(email, personne) for _ in range(10)]
    inconnus = [await duree(f"inconnu-{i}-{random.randint(0, 10**9)}@test.local", None) for i in range(10)]
    assert 0.5 < statistics.median(inconnus) / statistics.median(connus) < 2


async def test_cinq_faux_puis_le_bon_donne_429_sans_aucune_verification(
    banc: Banc, verifications: list[UUID]
) -> None:
    personne, email = banc.personne()
    for _ in range(5):
        assert (await banc.connecte_par_code(email, personne, faux=True)).status_code == 401
    identifiant, bon = banc.pose_un_code(email, personne)
    avant = len(verifications)
    reponse = await banc.poste(email, identifiant, bon)  # le bon code, pendant le blocage
    assert reponse.status_code == 429
    assert int(reponse.headers["retry-after"]) > 0
    assert reponse.json()["code"] == "trop_de_requetes"
    assert "set-cookie" not in reponse.headers
    assert len(verifications) == avant  # aucune vérification pour un refus de créneau
    # Le code n'a pas été touché : ni essai compté, ni consommé.
    assert banc.lignes(
        "select attempts, used_at is null from public.login_code where id = %s", identifiant
    ) == [(0, True)]


async def test_le_blocage_d_un_compte_monte_jusqu_a_24_heures(banc: Banc) -> None:
    personne, email = banc.personne()
    cle = banc.empreintes.cle_compte(email)
    banc.fabrique.admin.execute(
        "insert into public.login_throttle (scope, key, window_start, strikes, last_block_at, blocked_until)"
        " values ('account', %s, now(), 7, now(), now() + interval '16 hours')",
        (cle,),
    )
    reponse = await banc.connecte_par_code(email, personne)
    assert reponse.status_code == 429
    assert 15 * 3600 < int(reponse.headers["retry-after"]) <= 16 * 3600


async def test_cinq_faux_sur_la_meme_demande_tuent_le_code_meme_pour_le_bon(
    banc_avec: Callable[..., Banc],
) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000, connexion_essais_par_ip=10000)
    personne, email = banc.personne()
    identifiant, bon = banc.pose_un_code(email, personne)
    faux = f"{(int(bon) + 1) % 10**6:06d}"
    assert [(await banc.poste(email, identifiant, faux)).status_code for _ in range(5)] == [401] * 5
    assert (await banc.poste(email, identifiant, bon)).status_code == 401
    assert banc.lignes(
        "select attempts, used_at is null from public.login_code where id = %s", identifiant
    ) == [(5, True)]


async def test_un_compte_inconnu_est_limite_comme_un_compte_connu(banc: Banc) -> None:
    email = f"inconnu-{random.randint(0, 10**9)}@test.local"
    statuts = [(await banc.connecte_par_code(email)).status_code for _ in range(6)]
    assert statuts == [401] * 5 + [429]


async def test_le_vingt_et_unieme_essai_d_une_ip_sur_des_comptes_differents_est_refuse(banc: Banc) -> None:
    statuts = [
        (await banc.connecte_par_code(f"inconnu-{i}-{random.randint(0, 10**9)}@test.local")).status_code
        for i in range(21)
    ]
    assert statuts == [401] * 20 + [429]


async def test_cinquante_tentatives_fausses_en_parallele_font_exactement_cinq_verifications(
    banc: Banc, verifications: list[UUID]
) -> None:
    personne, email = banc.personne()
    identifiant, bon = banc.pose_un_code(email, personne)
    faux = f"{(int(bon) + 1) % 10**6:06d}"
    reponses = await asyncio.gather(*(banc.poste(email, identifiant, faux) for _ in range(50)))
    assert sorted(r.status_code for r in reponses) == [401] * 5 + [429] * 45
    assert len(verifications) == 5


async def test_vingt_soumissions_du_bon_code_ouvrent_une_seule_session(
    banc_avec: Callable[..., Banc],
) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000, connexion_essais_par_ip=10000)
    personne, email = banc.personne()
    identifiant, bon = banc.pose_un_code(email, personne)
    reponses = await asyncio.gather(*(banc.poste(email, identifiant, bon) for _ in range(20)))
    assert sorted(r.status_code for r in reponses) == [201] + [401] * 19
    assert banc.lignes("select count(*) from public.login_session where person_id = %s", personne) == [(1,)]


@pytest.mark.parametrize(
    "surcharge",
    [
        {"code": "12345"}, {"code": "1234567"}, {"code": "12345a"}, {"code": "123456\n"}, {"code": " 123456"},
        {"code": "١٢٣٤٥٦"}, {"code": 123456}, {"code": None}, {"role": "admin"}, {"method": "password"},
        {"method": None}, {"code_request_id": "pas-un-uuid"}, {"code_request_id": None},
        {"email": "a" * 250 + "@x.fr"}, {"email": "a\x00@test.local"}, {"email": None},
    ],
)  # fmt: skip
async def test_un_corps_invalide_donne_422_sans_rien_recopier(banc: Banc, surcharge: dict[str, Any]) -> None:
    corps = {
        "method": "email_code",
        "email": "a@test.local",
        "code_request_id": str(uuid4()),
        "code": "123456",
    }
    corps.update(surcharge)
    reponse = await banc.client().post("/api/v1/sessions", json=corps, headers=ECRITURE)
    assert reponse.status_code == 422
    assert "123456" not in reponse.text and "1234567" not in reponse.text
    assert "set-cookie" not in reponse.headers


@pytest.mark.parametrize("champ", ["method", "email", "code_request_id", "code"])
async def test_un_champ_absent_donne_422(banc: Banc, champ: str) -> None:
    corps = {
        "method": "email_code",
        "email": "a@test.local",
        "code_request_id": str(uuid4()),
        "code": "123456",
    }
    del corps[champ]
    assert (await banc.client().post("/api/v1/sessions", json=corps, headers=ECRITURE)).status_code == 422


async def test_l_ancien_corps_a_mot_de_passe_est_refuse(banc: Banc) -> None:
    reponse = await banc.client().post(
        "/api/v1/sessions", json={"email": "a@test.local", "password": MOT_DE_PASSE}, headers=ECRITURE
    )
    assert reponse.status_code == 422
    assert MOT_DE_PASSE not in reponse.text


async def test_un_corps_non_json_est_refuse(banc: Banc) -> None:
    reponse = await banc.client().post(
        "/api/v1/sessions", content=b"pas du json", headers=ECRITURE | {"Content-Type": "application/json"}
    )
    assert reponse.status_code == 422


@pytest.mark.parametrize(
    "entetes",
    [
        {"Origin": "https://evil.example", "X-Popote-Client": "web"},
        {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "cross-site", "X-Popote-Client": "web"},
        {"Origin": "http://localhost:5173"},
    ],
)
async def test_une_origine_refusee_ne_consomme_aucun_creneau(banc: Banc, entetes: dict[str, str]) -> None:
    personne, email = banc.personne()
    identifiant, bon = banc.pose_un_code(email, personne)
    corps = {"method": "email_code", "email": email, "code_request_id": str(identifiant), "code": bon}
    reponse = await banc.client().post("/api/v1/sessions", json=corps, headers=entetes)
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "origine_refusee"
    assert (
        banc.lignes("select 1 from public.login_throttle where key = %s", banc.empreintes.cle_compte(email))
        == []
    )
    assert banc.lignes("select attempts from public.login_code where id = %s", identifiant) == [(0,)]


async def test_la_onzieme_session_ferme_la_plus_ancienne(banc: Banc) -> None:
    personne, email = banc.personne()
    ids = []
    for _ in range(11):
        banc.fabrique.admin.execute(
            "delete from public.login_throttle where key = %s", (banc.empreintes.cle_compte(email),)
        )  # cinq essais par compte : on ne teste ici que la limite de dix sessions
        ids.append((await banc.connecte_par_code(email, personne)).json()["id"])
    actives = {
        str(r[0])
        for r in banc.lignes(
            "select id from public.login_session where person_id = %s and revoked_at is null", personne
        )
    }
    assert len(actives) == 10
    assert ids[0] not in actives


async def test_le_succes_remet_le_compte_a_zero_mais_pas_l_ip(banc: Banc) -> None:
    personne, email = banc.personne()
    for _ in range(3):
        assert (await banc.connecte_par_code(email, personne, faux=True)).status_code == 401
    assert (await banc.connecte_par_code(email, personne)).status_code == 201
    cle_compte, cle_ip = banc.empreintes.cle_compte(email), banc.empreintes.cle_ip(banc.ip)
    assert banc.lignes(
        "select attempts from public.login_throttle where scope = 'account' and key = %s", cle_compte
    ) == [(0,)]
    assert banc.lignes(
        "select attempts from public.login_throttle where scope = 'ip' and key = %s", cle_ip
    ) == [(4,)]


async def test_les_evenements_de_connexion(banc_avec: Callable[..., Banc]) -> None:
    banc = banc_avec(connexion_essais_par_ip=10000)  # l'IP ne bloque pas ici
    personne, email = banc.personne()
    cle = banc.empreintes.cle_compte(email)
    reponse = await banc.connecte_par_code(email, personne)
    (reussie,) = banc.lignes(
        "select person_id, session_id, account_key, ip_hash from public.security_event "
        "where kind = 'connexion_par_code' and person_id = %s",
        personne,
    )
    assert reussie[0] == personne and str(reussie[1]) == reponse.json()["id"]
    assert bytes(reussie[2]) == cle and reussie[3] is None
    for _ in range(100):
        await banc.connecte_par_code(email, personne, faux=True)
    ratees = banc.lignes(
        "select ip_hash, person_id from public.security_event"
        " where kind = 'connexion_ratee' and account_key = %s",
        cle,
    )
    bloquees = banc.lignes(
        "select ip_hash, person_id from public.security_event "
        "where kind = 'connexion_bloquee' and account_key = %s",
        cle,
    )
    assert len(ratees) == 5  # le succès a remis le compte à zéro : cinq faux comptés, les autres refusés
    assert len(bloquees) == 1  # B21 : un événement par fenêtre de blocage, pas un par essai refusé
    assert all(ligne == (None, None) for ligne in ratees + bloquees)  # clé de compte seule


async def test_un_cookie_valide_present_est_revoque_par_la_nouvelle_connexion(
    banc_avec: Callable[..., Banc],
) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000)
    personne, email = banc.personne()
    premiere = await banc.connecte_par_code(email, personne)
    ancien = {"Cookie": cookie_brut(premiere).split(";")[0]}
    assert (await banc.client().get("/api/v1/me", headers=ancien)).status_code == 200
    seconde = await banc.connecte_par_code(email, personne, headers=ancien)
    assert seconde.status_code == 201
    assert (await banc.client().get("/api/v1/me", headers=ancien)).status_code == 401
    nouveau = {"Cookie": cookie_brut(seconde).split(";")[0]}
    assert (await banc.client().get("/api/v1/me", headers=nouveau)).status_code == 200
    fermees = banc.lignes(
        "select session_id from public.security_event where kind = 'session_fermee' and person_id = %s",
        personne,
    )
    assert [str(f[0]) for f in fermees] == [premiere.json()["id"]]


async def test_un_refus_ne_ferme_pas_la_session_presentee(banc: Banc) -> None:
    personne, email = banc.personne()
    presentee = banc.fabrique.session(personne)
    reponse = await banc.connecte_par_code(
        email, personne, faux=True, headers={"Cookie": f"{NOM_DU_COOKIE}={presentee.jeton}"}
    )
    assert reponse.status_code == 401
    assert banc.lignes("select revoked_at is null from public.login_session where id = %s", presentee.id) == [
        (True,)
    ]


async def test_un_cookie_invalide_present_est_ignore(banc_avec: Callable[..., Banc]) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000)
    personne, email = banc.personne()
    for mauvais in ("n'importe quoi", "A" * 43):
        reponse = await banc.connecte_par_code(
            email, personne, headers={"Cookie": f"{NOM_DU_COOKIE}={mauvais}"}
        )
        assert reponse.status_code == 201


async def test_aucune_donnee_personnelle_dans_les_journaux(
    banc_avec: Callable[..., Banc], caplog: pytest.LogCaptureFixture
) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000, connexion_essais_par_ip=10000)
    personne, email = banc.personne()
    secrets_vus: list[str] = []
    with caplog.at_level(logging.DEBUG):
        for faux in (True, False, True, True, True, True, True):
            identifiant, bon = banc.pose_un_code(email, personne)
            envoye = f"{(int(bon) + 1) % 10**6:06d}" if faux else bon
            secrets_vus += [str(identifiant), bon, envoye]
            reponse = await banc.poste(email, identifiant, envoye)
    jeton = cookie_brut(await banc.connecte_par_code(email, personne)).split("=")[1].split(";")[0]
    assert reponse.status_code in (401, 429)
    texte = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in (email, jeton, banc.ip, *secrets_vus):
        assert secret not in texte


async def test_la_connexion_n_exige_pas_idempotency_key(banc: Banc) -> None:
    personne, email = banc.personne()
    reponse = await banc.connecte_par_code(email, personne)
    assert reponse.status_code == 201
    assert "idempotency" not in " ".join(reponse.headers).lower()


async def test_sans_poivre_la_connexion_refuse_plutot_que_de_compter(banc_avec: Callable[..., Banc]) -> None:
    banc = banc_avec()
    sans = create_app(Settings.model_validate({"env": "local", "json_logs": False}))
    sans.state.base = banc.app.state.base
    sans.state.empreintes = Empreintes(None)  # en local, le poivre est tiré au hasard : on le retire ici
    reponse = await client_de(sans).post(
        "/api/v1/sessions",
        json={
            "method": "email_code",
            "email": "a@test.local",
            "code_request_id": str(uuid4()),
            "code": "123456",
        },
        headers=ECRITURE,
    )
    assert reponse.status_code == 503
    assert "set-cookie" not in reponse.headers


async def test_un_blocage_d_ip_marque_l_ip_et_pas_le_compte_vise(banc_avec: Callable[..., Banc]) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000)  # seule l'IP bloque
    personne, email = banc.personne()
    for _ in range(25):
        await banc.connecte_par_code(email, personne, faux=True)
    cle_ip = banc.empreintes.cle_ip(banc.ip)
    lignes = banc.lignes("select account_key, ip_hash from public.security_event where ip_hash = %s", cle_ip)
    assert [(ligne[0], bytes(ligne[1])) for ligne in lignes] == [(None, cle_ip)]
    cle_compte = banc.empreintes.cle_compte(email)
    assert (
        banc.lignes(
            "select 1 from public.security_event where kind = 'connexion_bloquee' and account_key = %s",
            cle_compte,
        )
        == []
    )
    banc.fabrique.admin.execute("delete from public.security_event where ip_hash = %s", (cle_ip,))


async def test_un_substitut_isole_dans_l_adresse_donne_422_et_non_500(banc: Banc) -> None:
    corps = (
        b'{"method": "email_code", "email": "a\\ud800@test.local",'
        b' "code_request_id": "00000000-0000-4000-8000-000000000001", "code": "123456"}'
    )  # échappement JSON
    reponse = await banc.client().post(
        "/api/v1/sessions", content=corps, headers=ECRITURE | {"Content-Type": "application/json"}
    )
    assert reponse.status_code == 422


# ── Le journal d'un refus ne peut pas annuler l'essai ; une erreur de la base annule tout ──────────────────


async def test_un_journal_qui_leve_ne_change_ni_la_reponse_ni_l_essai_compte(
    banc: Banc, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def journal_en_panne(curseur: Any, *_: Any, **__: Any) -> None:
        await curseur.execute("select 1 / 0")

    monkeypatch.setattr("popote_api.security.journal_securite.journalise", journal_en_panne)
    personne, email = banc.personne()
    identifiant, bon = banc.pose_un_code(email, personne)
    faux = f"{(int(bon) + 1) % 10**6:06d}"
    with caplog.at_level(logging.ERROR):
        reponse = await banc.poste(email, identifiant, faux)
    assert (reponse.status_code, reponse.json()["code"]) == (401, "code_incorrect")
    assert banc.lignes("select attempts from public.login_code where id = %s", identifiant) == [(1,)]
    assert banc.lignes(
        "select attempts from public.login_throttle where scope = 'account' and key = %s",
        banc.empreintes.cle_compte(email),
    ) == [(1,)]
    assert (
        banc.lignes(
            "select 1 from public.security_event where account_key = %s", banc.empreintes.cle_compte(email)
        )
        == []
    )
    assert "DivisionByZero" in caplog.text and faux not in caplog.text and email not in caplog.text


async def test_une_erreur_de_la_base_rend_503_et_laisse_le_code_valable(banc: Banc) -> None:
    """Leçon 3 : un déclencheur lève sur `login_session` : `503` réessayable, code intact, aucun cookie."""
    personne, email = banc.personne()
    identifiant, bon = banc.pose_un_code(email, personne)
    nom = f"s7b_leve_{uuid4().hex[:8]}"
    admin = banc.fabrique.admin
    admin.execute(
        f"create function public.{nom}() returns trigger language plpgsql as $$ begin"
        f" if new.person_id = '{personne}' then raise exception 'erreur injectee' using errcode = '40001';"
        f" end if; return new; end $$"
    )
    admin.execute(
        f"create trigger {nom} before insert on public.login_session"
        f" for each row execute function public.{nom}()"
    )
    try:
        reponse = await banc.poste(email, identifiant, bon)
    finally:
        admin.execute(f"drop trigger {nom} on public.login_session")
        admin.execute(f"drop function public.{nom}()")
    assert (reponse.status_code, reponse.json()["code"]) == (503, "reessayer")
    assert reponse.headers["retry-after"] == "1" and "set-cookie" not in reponse.headers
    assert banc.lignes(
        "select attempts, used_at is null from public.login_code where id = %s", identifiant
    ) == [(0, True)]
    assert banc.lignes("select 1 from public.login_session where person_id = %s", personne) == []
    assert (
        await banc.poste(email, identifiant, bon)
    ).status_code == 201  # le même code, la nouvelle tentative réussit
