import logging
from collections.abc import ItemsView

import httpx
import pytest
from _commun import RELAIS, reglages
from fastapi import FastAPI, Request, Response

from popote_api.main import create_app
from popote_api.security.debit import (
    ECRITURE,
    LECTURE,
    Debit,
    Fenetre,
    Limiteur,
    limite_par_personne,
)

# Ce que le front envoie dans une écriture ; sans effet tant que la garde d'origine n'est pas là.
WEB = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}


class Horloge:
    """Une horloge qu'on avance à la main : aucun test ne dépend du temps réel."""

    def __init__(self) -> None:
        self.maintenant = 1000.0

    def __call__(self) -> float:
        return self.maintenant

    def avance(self, secondes: float) -> None:
        self.maintenant += secondes


def app_de_test(horloge: Horloge, env: str = "local", max_cles: int | None = None) -> FastAPI:
    app = create_app(reglages(env), horloge=horloge)
    if max_cles is not None:
        app.state.debit = Debit(horloge, max_cles)

    @app.api_route("/api/_test/x", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
    async def x() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/_test/personne")
    async def personne(request: Request, response: Response) -> dict[str, bool]:
        await limite_par_personne(request, response, request.headers["x-test-personne"])
        return {"ok": True}

    return app


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def repete(c: httpx.AsyncClient, methode: str, fois: int, **requete: object) -> httpx.Response:
    """Envoie `fois` requêtes et rend la dernière réponse."""
    for _ in range(fois):
        r = await c.request(methode, "/api/_test/x", **requete)  # type: ignore[arg-type]
    return r


# --- Lecture et écriture --------------------------------------------------------------------------


@pytest.mark.parametrize("methode", ["GET", "HEAD"])
async def test_la_120e_lecture_passe_et_la_121e_rend_429(methode: str) -> None:
    async with client(app_de_test(Horloge())) as c:
        assert (await repete(c, methode, 120)).status_code == 200
        r = await repete(c, methode, 1)
    assert r.status_code == 429


@pytest.mark.parametrize("methode", ["POST", "PUT", "PATCH", "DELETE"])
async def test_la_30e_ecriture_passe_et_la_31e_rend_429(methode: str) -> None:
    async with client(app_de_test(Horloge())) as c:
        assert (await repete(c, methode, 30, headers=WEB)).status_code == 200
        r = await repete(c, methode, 1, headers=WEB)
    assert r.status_code == 429


async def test_les_lectures_et_les_ecritures_ont_chacune_leur_compteur() -> None:
    async with client(app_de_test(Horloge())) as c:
        await repete(c, "POST", 30, headers=WEB)
        assert (await repete(c, "POST", 1, headers=WEB)).status_code == 429
        assert (await repete(c, "GET", 1)).status_code == 200


async def test_la_429_est_un_probleme_avec_les_en_tetes_du_brouillon() -> None:
    horloge = Horloge()
    async with client(app_de_test(horloge)) as c:
        await repete(c, "GET", 120)
        horloge.avance(10.4)
        r = await repete(c, "GET", 1)
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "trop_de_requetes"
    assert r.headers["x-request-id"] == r.json()["instance"]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["retry-after"] == "50"  # 60 - 10,4 arrondi à la seconde supérieure, entier
    assert r.headers["ratelimit-policy"] == '"read";q=120;w=60'
    assert r.headers["ratelimit"] == '"read";r=0;t=50'


async def test_une_reponse_acceptee_dit_ce_qui_reste() -> None:
    async with client(app_de_test(Horloge())) as c:
        premiere = await repete(c, "GET", 1)
        seconde = await repete(c, "GET", 1)
        ecriture = await repete(c, "POST", 1, headers=WEB)
    assert premiere.headers["ratelimit"] == '"read";r=119;t=60'
    assert seconde.headers["ratelimit"] == '"read";r=118;t=60'
    assert ecriture.headers["ratelimit-policy"] == '"write";q=30;w=60'
    assert ecriture.headers["ratelimit"] == '"write";r=29;t=60'


async def test_la_fenetre_se_libere_avec_le_temps() -> None:
    horloge = Horloge()
    async with client(app_de_test(horloge)) as c:
        await repete(c, "GET", 121)
        horloge.avance(59.9)
        encore = await repete(c, "GET", 1)
        horloge.avance(0.1)
        libre = await repete(c, "GET", 1)
    assert (encore.status_code, libre.status_code) == (429, 200)
    assert libre.headers["ratelimit"] == '"read";r=119;t=60'


async def test_healthz_et_readyz_ne_sont_pas_limites() -> None:
    app = app_de_test(Horloge())
    async with client(app) as c:
        for chemin in ("/api/healthz", "/api/readyz"):
            for _ in range(LECTURE.quota + 5):
                r = await c.get(chemin)
            assert r.status_code != 429
        assert (await c.get("/api/_test/x")).status_code == 200  # et ils n'ont rien consommé


# --- La clé : l'adresse vue par le relais, jamais le cookie -----------------------------------------


def avec_relais(ip: str | None) -> dict[str, str]:
    return RELAIS | ({"X-Popote-IP": ip} if ip is not None else {})


async def test_chaque_adresse_a_son_compteur() -> None:
    async with client(app_de_test(Horloge(), "essai")) as c:
        await repete(c, "GET", 121, headers=avec_relais("203.0.113.1"))
        autre = await repete(c, "GET", 1, headers=avec_relais("203.0.113.2"))
        meme = await repete(c, "GET", 1, headers=avec_relais("203.0.113.1"))
    assert (autre.status_code, meme.status_code) == (200, 429)


async def test_un_cookie_different_a_chaque_requete_n_ouvre_pas_de_compteur_neuf() -> None:
    app = app_de_test(Horloge(), "essai")
    async with client(app) as c:
        for i in range(121):
            cookie = {"Cookie": f"__Host-popote_session=inv{i}"}
            r = await c.get("/api/_test/x", headers=avec_relais("203.0.113.1") | cookie)
    assert r.status_code == 429


async def test_sans_adresse_toutes_les_requetes_partagent_une_cle_commune() -> None:
    async with client(app_de_test(Horloge(), "essai")) as c:
        await repete(c, "GET", 120, headers=avec_relais(None))
        invalide = await repete(c, "GET", 1, headers=avec_relais("pas-une-adresse"))
        valide = await repete(c, "GET", 1, headers=avec_relais("203.0.113.9"))
    assert (invalide.status_code, valide.status_code) == (429, 200)


async def test_hors_relais_l_adresse_vient_de_la_connexion_et_non_de_l_en_tete() -> None:
    """En local, `X-Popote-IP` du client est ignoré : le changer ne donne pas de compteur neuf."""
    async with client(app_de_test(Horloge())) as c:
        for i in range(121):
            r = await c.get("/api/_test/x", headers={"X-Popote-IP": f"203.0.113.{i}"})
    assert r.status_code == 429


async def test_un_appelant_sans_le_secret_du_relais_est_renvoye_avant_le_limiteur() -> None:
    app = app_de_test(Horloge(), "essai")
    async with client(app) as c:
        r = await c.get("/api/_test/x", headers={"X-Popote-IP": "203.0.113.1"})
    assert r.status_code == 404
    assert app.state.debit.ip._fenetres == {}


# --- Le limiteur par personne ---------------------------------------------------------------------


async def test_la_cle_par_personne_arrete_la_personne_meme_quand_l_adresse_change() -> None:
    async with client(app_de_test(Horloge(), "essai")) as c:
        for i in range(120):
            await c.get(
                "/api/_test/personne", headers=avec_relais(f"203.0.113.{i}") | {"X-Test-Personne": "anne"}
            )
        anne = await c.get(
            "/api/_test/personne", headers=avec_relais("198.51.100.1") | {"X-Test-Personne": "anne"}
        )
        bruno = await c.get(
            "/api/_test/personne", headers=avec_relais("198.51.100.2") | {"X-Test-Personne": "bruno"}
        )
    assert (anne.status_code, bruno.status_code) == (429, 200)


async def test_une_personne_arretee_ne_l_est_pas_pour_une_autre() -> None:
    limiteur_personne = Limiteur(Horloge())
    for _ in range(ECRITURE.quota):
        assert limiteur_personne.consomme("anne", ECRITURE) is not None
    anne = limiteur_personne.consomme("anne", ECRITURE)
    bruno = limiteur_personne.consomme("bruno", ECRITURE)
    assert anne is not None
    assert (anne.autorise, bruno is not None and bruno.autorise) == (False, True)


# --- La mémoire bornée ----------------------------------------------------------------------------


def test_a_la_limite_de_cles_une_cle_nouvelle_est_refusee_et_les_compteurs_actifs_sont_gardes() -> None:
    horloge = Horloge()
    limiteur = Limiteur(horloge, max_cles=3)
    for cle in ("a", "b", "c"):
        limiteur.consomme(cle, LECTURE)
    limiteur.consomme("a", LECTURE)  # a a déjà compté deux requêtes
    assert limiteur.consomme("d", LECTURE) is None  # refusée, aucun compteur actif n'est oublié
    a = limiteur.consomme("a", LECTURE)
    assert a is not None
    assert a.restant == LECTURE.quota - 3  # a se souvient de ses trois requêtes


def test_les_fenetres_expirees_cedent_la_place_avant_tout_refus() -> None:
    horloge = Horloge()
    limiteur = Limiteur(horloge, max_cles=3)
    for cle in ("a", "b", "c"):
        limiteur.consomme(cle, LECTURE)
    horloge.avance(LECTURE.fenetre)
    nouvelle = limiteur.consomme("d", LECTURE)
    assert nouvelle is not None
    assert nouvelle.autorise
    assert len(limiteur._fenetres) == 1  # les trois expirées sont parties


def test_une_fenetre_encore_ouverte_n_est_pas_retiree_quand_une_autre_a_expire() -> None:
    horloge = Horloge()
    limiteur = Limiteur(horloge, max_cles=2)
    limiteur.consomme("ancien", LECTURE)
    horloge.avance(40)
    limiteur.consomme("recent", LECTURE)
    horloge.avance(20)  # « ancien » a expiré, « recent » non
    assert limiteur.consomme("nouveau", LECTURE) is not None
    recent = limiteur.consomme("recent", LECTURE)
    assert recent is not None
    assert recent.restant == LECTURE.quota - 2


def test_la_saturation_est_journalisee_une_fois_par_minute(caplog: pytest.LogCaptureFixture) -> None:
    horloge = Horloge()
    limiteur = Limiteur(horloge, max_cles=1)
    limiteur.consomme("a", LECTURE)
    with caplog.at_level(logging.WARNING, logger="popote_api.security.debit"):
        for _ in range(5):
            assert limiteur.consomme("autre", LECTURE) is None
        horloge.avance(30)
        assert limiteur.consomme("autre", LECTURE) is None
    assert caplog.text.count("saturé") == 1
    horloge.avance(31)  # plus de 60 s depuis la première alerte
    with caplog.at_level(logging.WARNING, logger="popote_api.security.debit"):
        limiteur.consomme("a", LECTURE)  # la fenêtre de « a » a expiré, il redevient actif
        assert limiteur.consomme("autre", LECTURE) is None
    assert caplog.text.count("saturé") == 2


async def test_la_saturation_rend_503_avec_retry_after_et_n_est_pas_une_429() -> None:
    horloge = Horloge()
    app = app_de_test(horloge, "essai", max_cles=1)
    async with client(app) as c:
        await c.get("/api/_test/x", headers=avec_relais("203.0.113.1"))
        horloge.avance(20)
        r = await c.get("/api/_test/x", headers=avec_relais("203.0.113.2"))
    assert r.status_code == 503
    assert r.json()["code"] == "limiteur_sature"
    assert r.headers["retry-after"] == "40"
    assert r.headers["x-request-id"] == r.json()["instance"]
    assert "ratelimit" not in r.headers


async def test_la_saturation_ne_journalise_pas_l_adresse(caplog: pytest.LogCaptureFixture) -> None:
    app = app_de_test(Horloge(), "essai", max_cles=1)
    async with client(app) as c:
        await c.get("/api/_test/x", headers=avec_relais("203.0.113.1"))
        with caplog.at_level(logging.WARNING):
            await c.get("/api/_test/x", headers=avec_relais("203.0.113.2"))
    assert "203.0.113" not in caplog.text


class FenetresComptees(dict[tuple[str, str], Fenetre]):
    """Un dictionnaire qui compte les balayages complets du limiteur."""

    balayages = 0

    def items(self) -> ItemsView[tuple[str, str], Fenetre]:
        FenetresComptees.balayages += 1
        return super().items()


def test_un_afflux_de_cles_nouvelles_ne_declenche_pas_un_balayage_par_requete() -> None:
    horloge = Horloge()
    limiteur = Limiteur(horloge, max_cles=3)
    for cle in ("a", "b", "c"):
        limiteur.consomme(cle, LECTURE)
    limiteur._fenetres = FenetresComptees(limiteur._fenetres)
    FenetresComptees.balayages = 0
    for i in range(100):
        assert limiteur.consomme(f"inconnu{i}", LECTURE) is None
    assert FenetresComptees.balayages == 1  # un seul balayage, puis rien avant la première échéance
