"""T8 : `POST /api/v1/sessions` de bout en bout, contre la base locale (spec § 4 ; B6, B21, B22, B24).

Données inventées. Chaque test prend sa propre adresse IP (la limite est de 20) et retire ses compteurs.
"""

import asyncio
import logging
import random
import statistics
import time
import unicodedata
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from _client import NOM_DU_COOKIE, client_de
from _fabrique import Fabrique
from test_verifie_mot_de_passe import Comptes, hache

from popote_api.config import Settings
from popote_api.infra.db import Base
from popote_api.main import create_app
from popote_api.security import connexion as modele_connexion
from popote_api.security.empreintes import Empreintes
from popote_api.security.jeton import empreinte_du_jeton

pytestmark = pytest.mark.integration

POIVRE = "p" * 32
MOT_DE_PASSE = "un-mot-de-passe-assez-long"
ECRITURE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}
REFUS = {"type", "title", "status", "detail", "code"}
MESSAGE = "E-mail ou mot de passe incorrect."


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

    async def connecte(
        self,
        email: str,
        mot_de_passe: str = MOT_DE_PASSE,
        *,
        client: httpx.AsyncClient | None = None,
        **plus: Any,
    ) -> httpx.Response:
        self.cles += [c for c in (self.empreintes.cle_compte(email), self.empreintes.cle_ip(self.ip)) if c]
        entetes = ECRITURE | plus.pop("headers", {})
        envoi = client or self.client()
        return await envoi.post(
            "/api/v1/sessions", json={"email": email, "password": mot_de_passe}, headers=entetes, **plus
        )

    def lignes(self, requete: str, *args: object) -> list[tuple[Any, ...]]:
        return self.fabrique.admin.execute(requete, args).fetchall()  # type: ignore[arg-type]

    def nettoie(self) -> None:
        self.fabrique.admin.execute("delete from public.login_throttle where key = any(%s)", (self.cles,))
        self.fabrique.admin.execute(
            "delete from public.security_event where account_key = any(%s)", (self.cles,)
        )


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
def verifications(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Un espion sur la vérification du mot de passe : une entrée par appel à la base."""
    appels: list[str] = []
    origine = modele_connexion.verifie_un_candidat

    async def espion(curseur: Any, email: str, mot_de_passe: str) -> UUID | None:
        appels.append(email)
        return await origine(curseur, email, mot_de_passe)

    monkeypatch.setattr(modele_connexion, "verifie_un_candidat", espion)
    return appels


def cookie_brut(reponse: httpx.Response) -> str:
    return reponse.headers["set-cookie"]


async def test_succes_cookie_aux_attributs_exacts_et_jeton_seulement_en_empreinte(banc: Banc) -> None:
    personne, email = banc.compte()
    reponse = await banc.connecte(email)
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
        "select person_id, token_hash, row(t.*)::text from public.login_session t where id = %s", id_session
    )
    assert ligne[0] == personne
    assert bytes(ligne[1]) == empreinte_du_jeton(jeton)
    assert jeton not in ligne[2]  # le jeton n'est dans aucune colonne


async def test_deux_connexions_deux_jetons(banc: Banc) -> None:
    _, email = banc.compte()
    premier, second = await banc.connecte(email), await banc.connecte(email)
    assert premier.cookies != second.cookies
    assert cookie_brut(premier).split(";")[0] != cookie_brut(second).split(";")[0]


async def test_un_cookie_fourni_par_le_client_n_est_jamais_adopte(banc: Banc) -> None:
    _, email = banc.compte()
    impose = "A" * 43
    reponse = await banc.connecte(email, headers={"Cookie": f"{NOM_DU_COOKIE}={impose}"})
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


CAS_DE_REFUS = ["faux", "inconnu", "banni", "supprime", "sans_hash", "blowfish_y"]


@pytest.mark.parametrize("cas", CAS_DE_REFUS)
async def test_tous_les_refus_se_ressemblent_au_champ_instance_pres(banc: Banc, cas: str) -> None:
    modeles = {
        "faux": lambda: banc.comptes.bon(),
        "banni": lambda: banc.comptes.bon(banned_until="infinity"),
        "sans_hash": lambda: banc.comptes.cree(None),
        "blowfish_y": lambda: banc.comptes.cree("$2y$" + hache(banc.fabrique.admin, MOT_DE_PASSE)[4:]),
    }
    if cas == "inconnu":
        email = f"inconnu-{random.randint(0, 10**9)}@test.local"
    else:
        if cas == "supprime":  # `deleted_at` se pose par une date, pas par le mot « now() »
            personne, email = banc.comptes.bon()
            banc.fabrique.admin.execute("update auth.users set deleted_at = now() where id = %s", (personne,))
        else:
            _, email = modeles[cas]()
    reponse = await banc.connecte(email, MOT_DE_PASSE if cas != "faux" else "mauvais-mot-de-passe-long")
    statut, corps, en_tetes = _sans_instance(reponse)
    assert statut == 401
    assert corps["code"] == "identifiants_incorrects"
    assert corps["detail"] == MESSAGE
    assert "set-cookie" not in en_tetes
    # La même réponse, au caractère près, que pour un mot de passe faux sur un compte connu.
    _, autre = banc.compte()
    attendue = _sans_instance(await banc.connecte(autre, "mauvais-mot-de-passe-long"))
    assert (statut, corps, en_tetes) == attendue


async def test_le_temps_d_un_compte_inconnu_est_comparable_a_celui_d_un_faux_mot_de_passe(
    banc_avec: Callable[..., Banc],
) -> None:
    banc = banc_avec(connexion_essais_par_compte=1000, connexion_essais_par_ip=10000)
    if True:
        _, email = banc.compte()

        async def duree(adresse: str) -> float:
            debut = time.perf_counter()
            assert (await banc.connecte(adresse, "mauvais-mot-de-passe-long")).status_code == 401
            return time.perf_counter() - debut

        connus = [await duree(email) for _ in range(10)]
        inconnus = [await duree(f"inconnu-{i}-{random.randint(0, 10**9)}@test.local") for i in range(10)]
        rapport = statistics.median(inconnus) / statistics.median(connus)
        assert 0.5 < rapport < 2


async def test_cinq_faux_puis_le_bon_donne_429_sans_aucune_verification(
    banc: Banc, verifications: list[str]
) -> None:
    _, email = banc.compte()
    for _ in range(5):
        assert (await banc.connecte(email, "mauvais-mot-de-passe-long")).status_code == 401
    avant = len(verifications)
    reponse = await banc.connecte(email)  # le bon mot de passe, pendant le blocage
    assert reponse.status_code == 429
    assert int(reponse.headers["retry-after"]) > 0
    assert reponse.json()["code"] == "trop_de_requetes"
    assert "set-cookie" not in reponse.headers
    assert len(verifications) == avant  # aucun crypt() pour un refus de créneau


async def test_un_compte_inconnu_est_limite_comme_un_compte_connu(banc: Banc) -> None:
    email = f"inconnu-{random.randint(0, 10**9)}@test.local"
    statuts = [(await banc.connecte(email)).status_code for _ in range(6)]
    assert statuts == [401] * 5 + [429]


async def test_le_vingt_et_unieme_essai_d_une_ip_sur_des_comptes_differents_est_refuse(banc: Banc) -> None:
    statuts = [
        (await banc.connecte(f"inconnu-{i}-{random.randint(0, 10**9)}@test.local")).status_code
        for i in range(21)
    ]
    assert statuts == [401] * 20 + [429]


async def test_cinquante_tentatives_fausses_en_parallele_font_exactement_cinq_verifications(
    banc: Banc, verifications: list[str]
) -> None:
    _, email = banc.compte()
    reponses = await asyncio.gather(*(banc.connecte(email, "mauvais-mot-de-passe-long") for _ in range(50)))
    statuts = sorted(r.status_code for r in reponses)
    assert statuts == [401] * 5 + [429] * 45
    assert len(verifications) == 5


async def test_un_ancien_mot_de_passe_non_normalise_est_accepte(banc: Banc) -> None:
    brut = (
        unicodedata.normalize("NFKD", "écureuil-très-sûr-pleine") + "\uff21\uff22\uff23"
    )  # haché brut par GoTrue autrefois
    _, email = banc.compte(brut)
    assert (await banc.connecte(email, brut)).status_code == 201


async def test_un_mot_de_passe_de_73_octets_est_refuse_sans_appel_a_la_base(
    banc: Banc, verifications: list[str]
) -> None:
    _, email = banc.compte("a" * 72)
    reponse = await banc.connecte(email, "a" * 73)
    assert reponse.status_code == 401
    assert verifications == []


@pytest.mark.parametrize(
    "corps",
    [
        {"email": "a@test.local"},
        {"password": MOT_DE_PASSE},
        {"email": "a@test.local", "password": MOT_DE_PASSE, "role": "admin"},
        {"email": "a" * 250 + "@x.fr", "password": MOT_DE_PASSE},
        {"email": "a@test.local", "password": "x" * 257},
    ],
)
async def test_un_corps_invalide_donne_422_sans_rien_recopier(banc: Banc, corps: dict[str, str]) -> None:
    reponse = await banc.client().post("/api/v1/sessions", json=corps, headers=ECRITURE)
    assert reponse.status_code == 422
    assert "x" * 257 not in reponse.text
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
    _, email = banc.compte()
    reponse = await banc.client().post(
        "/api/v1/sessions", json={"email": email, "password": MOT_DE_PASSE}, headers=entetes
    )
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "origine_refusee"
    cle = banc.empreintes.cle_compte(email)
    assert banc.lignes("select 1 from public.login_throttle where key = %s", cle) == []


async def test_la_onzieme_session_ferme_la_plus_ancienne(banc: Banc) -> None:
    personne, email = banc.compte()
    ids = [(await banc.connecte(email)).json()["id"] for _ in range(11)]
    actives = {
        str(r[0])
        for r in banc.lignes(
            "select id from public.login_session where person_id = %s and revoked_at is null", personne
        )
    }
    assert len(actives) == 10
    assert ids[0] not in actives


async def test_les_evenements_de_connexion(banc_avec: Callable[..., Banc]) -> None:
    banc = banc_avec(connexion_essais_par_ip=10000)  # l'IP ne bloque pas ici
    personne, email = banc.compte()
    cle = banc.empreintes.cle_compte(email)
    reponse = await banc.connecte(email)
    (reussie,) = banc.lignes(
        "select person_id, session_id, account_key, ip_hash from public.security_event "
        "where kind = 'connexion_reussie' and person_id = %s",
        personne,
    )
    assert reussie[0] == personne and str(reussie[1]) == reponse.json()["id"]
    assert reussie[2] is None and reussie[3] is None
    for _ in range(100):
        await banc.connecte(email, "mauvais-mot-de-passe-long")
    ratees = banc.lignes(
        "select ip_hash, person_id from public.security_event "
        "where kind = 'connexion_ratee' and account_key = %s",
        cle,
    )
    bloquees = banc.lignes(
        "select ip_hash, person_id from public.security_event "
        "where kind = 'connexion_bloquee' and account_key = %s",
        cle,
    )
    assert len(ratees) == 5  # les cinq essais comptés ; les autres sont des refus de créneau
    assert len(bloquees) == 1  # B21 : un événement par fenêtre de blocage, pas un par essai refusé
    assert all(ligne == (None, None) for ligne in ratees + bloquees)  # clé de compte seule


async def test_un_cookie_valide_present_est_revoque_par_la_nouvelle_connexion(banc: Banc) -> None:
    personne, email = banc.compte()
    premiere = await banc.connecte(email)
    ancien = {"Cookie": cookie_brut(premiere).split(";")[0]}
    assert (await banc.client().get("/api/v1/me", headers=ancien)).status_code == 200
    seconde = await banc.connecte(email, headers=ancien)
    assert seconde.status_code == 201
    assert (await banc.client().get("/api/v1/me", headers=ancien)).status_code == 401
    nouveau = {"Cookie": cookie_brut(seconde).split(";")[0]}
    assert (await banc.client().get("/api/v1/me", headers=nouveau)).status_code == 200
    fermees = banc.lignes(
        "select session_id from public.security_event where kind = 'session_fermee' and person_id = %s",
        personne,
    )
    assert [str(f[0]) for f in fermees] == [premiere.json()["id"]]


async def test_un_cookie_invalide_present_est_ignore(banc: Banc) -> None:
    _, email = banc.compte()
    for mauvais in ("n'importe quoi", "A" * 43):
        reponse = await banc.connecte(email, headers={"Cookie": f"{NOM_DU_COOKIE}={mauvais}"})
        assert reponse.status_code == 201


async def test_aucune_donnee_personnelle_dans_les_journaux(
    banc: Banc, caplog: pytest.LogCaptureFixture
) -> None:
    _, email = banc.compte()
    with caplog.at_level(logging.DEBUG):
        await banc.connecte(email, "mauvais-mot-de-passe-long")
        reussie = await banc.connecte(email)
        for _ in range(6):
            await banc.connecte(email, "mauvais-mot-de-passe-long")
    jeton = cookie_brut(reussie).split("=")[1].split(";")[0]
    texte = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in (email, MOT_DE_PASSE, "mauvais-mot-de-passe-long", jeton, banc.ip):
        assert secret not in texte


async def test_la_connexion_n_exige_pas_idempotency_key(banc: Banc) -> None:
    _, email = banc.compte()
    reponse = await banc.connecte(email)
    assert reponse.status_code == 201
    assert "idempotency" not in " ".join(reponse.headers).lower()


async def test_sans_poivre_la_connexion_refuse_plutot_que_de_compter(banc_avec: Callable[..., Banc]) -> None:
    banc = banc_avec()
    base = banc.app.state.base
    sans = create_app(Settings.model_validate({"env": "local", "json_logs": False}))
    sans.state.base = base
    sans.state.empreintes = Empreintes(None)  # en local, le poivre est tiré au hasard : on le retire ici
    _, email = banc.compte()
    reponse = await client_de(sans).post(
        "/api/v1/sessions", json={"email": email, "password": MOT_DE_PASSE}, headers=ECRITURE
    )
    assert reponse.status_code == 503
    assert "set-cookie" not in reponse.headers
