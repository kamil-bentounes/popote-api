"""Spec § 3.10, § 4 : la session lue en base, de bout en bout par l'application (HTTP, pool, RLS).

Base locale par défaut ; `POPOTE_TEST_DSN_API` et `POPOTE_TEST_DSN_ADMIN` les rejouent sur un autre serveur.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from _client import application_de_test, client_de, cookie
from _connexions import DSN_API, DSN_API_DISTANT
from _fabrique import Fabrique, jeton_et_empreinte
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from popote_api.infra.db import Base, Pool, cree_pool
from popote_api.security.session import DEFI_D_AUTHENTIFICATION, PersonneDeLaSession

pytestmark = pytest.mark.integration

URL = "/api/v1/essai/qui"
CINQ_MINUTES = timedelta(minutes=5)

routeur = APIRouter()


@routeur.get("/essai/qui")
async def qui(personne: PersonneDeLaSession) -> dict[str, Any]:
    await personne.curseur.execute(
        "select current_user as role, session_user as connexion, auth.uid() as uid, "
        "(select array_agg(id) from public.user_profile) as profils, "
        "(select array_agg(id) from public.household) as foyers"
    )
    ligne = await personne.curseur.fetchone()
    assert ligne is not None
    return {"personne": str(personne.id), **{k: _texte(v) for k, v in ligne.items()}}


def _texte(valeur: object) -> object:
    if isinstance(valeur, list):
        return sorted(str(v) for v in valeur)
    return str(valeur)


async def test_une_session_valide_donne_le_contexte_de_sa_personne(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    session = fabrique.session(personne.id)
    async with client_de(application_de_test(base, monkeypatch, routeur)) as client:
        reponse = await client.get(URL, headers=cookie(session))
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["personne"] == str(personne.id)
    # La lecture de la session s'est faite sous `popote_api`, puis `authenticated` a été emprunté, dans la
    # même transaction : le rôle et l'identité sont ceux de la personne.
    assert (corps["role"], corps["connexion"], corps["uid"]) == (
        "authenticated",
        "popote_api",
        str(personne.id),
    )


async def test_deux_foyers_ne_voient_que_le_leur(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    moi = fabrique.personne(fabrique.foyer())
    autre = fabrique.personne(fabrique.foyer())
    sessions = {"moi": fabrique.session(moi.id), "autre": fabrique.session(autre.id)}
    async with client_de(application_de_test(base, monkeypatch, routeur)) as client:
        vus = {nom: (await client.get(URL, headers=cookie(s))).json() for nom, s in sessions.items()}
    assert vus["moi"]["profils"] == [str(moi.id)]
    assert vus["moi"]["foyers"] == [str(moi.foyer_id)]
    assert vus["autre"]["profils"] == [str(autre.id)]
    assert vus["autre"]["foyers"] == [str(autre.foyer_id)]


async def test_une_requete_n_emprunte_qu_une_connexion_au_pool(
    base: Base, pools: tuple[Pool, Pool], monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    api, _ = pools
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    async with client_de(application_de_test(base, monkeypatch, routeur)) as client:
        avant = api.get_stats().get("requests_num", 0)
        await client.get(URL, headers=cookie(session))
        apres = api.get_stats().get("requests_num", 0)
    assert apres - avant == 1


def _vue_il_y_a_une_heure() -> dict[str, Any]:
    return {"vue_il_y_a": timedelta(hours=1)}


@pytest.mark.parametrize(
    "refus",
    [
        {"echeance_dans": -timedelta(minutes=1)},
        {"revoquee": True},
        {"echeance_dans": -timedelta(days=1), "absolue_dans": -timedelta(seconds=1)},
    ],
    ids=["echue", "revoquee", "au_bout_des_90_jours"],
)
async def test_une_session_refusee_rend_401(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique, refus: dict[str, Any]
) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id, **refus)
    async with client_de(application_de_test(base, monkeypatch, routeur)) as client:
        reponse = await client.get(URL, headers=cookie(session))
    assert reponse.status_code == 401
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.headers["www-authenticate"] == DEFI_D_AUTHENTIFICATION
    assert reponse.json()["code"] == "pas_de_session"


async def test_un_jeton_inconnu_rend_401(base: Base, monkeypatch: pytest.MonkeyPatch) -> None:
    jeton, _ = jeton_et_empreinte()
    async with client_de(application_de_test(base, monkeypatch, routeur)) as client:
        reponse = await client.get(URL, headers={"Cookie": f"__Host-popote_session={jeton}"})
    assert reponse.status_code == 401
    assert reponse.json()["code"] == "pas_de_session"


@pytest.mark.parametrize(
    "bascule",
    [
        "update auth.users set banned_until = now() + interval '1 hour' where id = %s",
        "update auth.users set deleted_at = now() where id = %s",
    ],
    ids=["bannie", "supprimee"],
)
async def test_une_personne_bannie_ou_supprimee_rend_401(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique, bascule: str
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    session = fabrique.session(personne.id)
    fabrique.admin.execute(bascule, (personne.id,))  # type: ignore[call-overload]  # texte constant du test
    async with client_de(application_de_test(base, monkeypatch, routeur)) as client:
        reponse = await client.get(URL, headers=cookie(session))
    assert reponse.status_code == 401


def derniere_activite(fabrique: Fabrique, session_id: object) -> object:
    ligne = fabrique.admin.execute(
        "select last_seen_at from public.login_session where id = %s", (session_id,)
    ).fetchone()
    assert ligne is not None
    return ligne[0]


async def test_last_seen_at_n_est_pas_reecrit_a_chaque_requete(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id, vue_il_y_a=CINQ_MINUTES * 2)
    ancienne = derniere_activite(fabrique, session.id)
    async with client_de(application_de_test(base, monkeypatch, routeur)) as client:
        await client.get(URL, headers=cookie(session))
        apres_la_premiere = derniere_activite(fabrique, session.id)
        await client.get(URL, headers=cookie(session))
        apres_la_seconde = derniere_activite(fabrique, session.id)
    assert apres_la_premiere != ancienne  # vue depuis plus de 5 minutes : repoussée
    assert apres_la_seconde == apres_la_premiere  # vue à l'instant : laissée telle quelle


async def test_une_route_qui_echoue_n_ecrit_rien_et_rend_son_erreur(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    from popote_api.errors import Probleme

    echec = APIRouter()

    @echec.get("/essai/echec")
    async def echoue(personne: PersonneDeLaSession) -> None:
        raise Probleme(409, "conflit", "Essai.")

    session = fabrique.session(fabrique.personne(fabrique.foyer()).id, vue_il_y_a=CINQ_MINUTES * 2)
    ancienne = derniere_activite(fabrique, session.id)
    async with client_de(application_de_test(base, monkeypatch, echec)) as client:
        reponse = await client.get("/api/v1/essai/echec", headers=cookie(session))
    assert reponse.status_code == 409
    assert derniere_activite(fabrique, session.id) == ancienne


async def test_la_connexion_est_rendue_au_pool_avant_que_la_reponse_parte(
    base: Base, pools: tuple[Pool, Pool], monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    api, _ = pools
    disponibles_pendant_l_envoi: list[int] = []
    flux = APIRouter()

    @flux.get("/essai/flux")
    async def envoie(personne: PersonneDeLaSession) -> StreamingResponse:
        async def corps() -> AsyncIterator[bytes]:
            # Le corps part après la route : la transaction doit être finie, sa connexion de retour au pool.
            disponibles_pendant_l_envoi.append(api.get_stats().get("pool_available", 0))
            yield b"ok"

        return StreamingResponse(corps())

    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    async with client_de(application_de_test(base, monkeypatch, flux)) as client:
        reponse = await client.get("/api/v1/essai/flux", headers=cookie(session))
    assert reponse.status_code == 200
    assert disponibles_pendant_l_envoi == [1]


@pytest.mark.skipif(DSN_API_DISTANT is not None, reason="les options de connexion passent mal un pooler")
async def test_les_delais_de_l_api_bornent_la_transaction_de_la_session(
    monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    # La connexion arrive sans borne (les options du client priment sur `alter role`) : seuls les `set local`
    # de `Base.session` peuvent poser les délais que la route lit ensuite.
    delais = APIRouter()

    @delais.get("/essai/delais")
    async def lit(personne: PersonneDeLaSession) -> dict[str, str]:
        await personne.curseur.execute(
            "select current_setting('statement_timeout') as s, current_setting('lock_timeout') as l"
        )
        ligne = await personne.curseur.fetchone()
        assert ligne is not None
        return {"statement_timeout": ligne["s"], "lock_timeout": ligne["l"]}

    pool = cree_pool(f"{DSN_API}?options=-c%20statement_timeout%3D0%20-c%20lock_timeout%3D0", 1)
    await pool.open(wait=False)
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    try:
        async with client_de(application_de_test(Base(pool, None), monkeypatch, delais)) as client:
            reponse = await client.get("/api/v1/essai/delais", headers=cookie(session))
    finally:
        await pool.close()
    assert reponse.json() == {"statement_timeout": "8s", "lock_timeout": "5s"}


async def test_la_limite_par_personne_compte_par_session_et_arrete_la_cent_vingt_et_unieme_lecture(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    autre = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    app = application_de_test(base, monkeypatch, routeur)
    async with client_de(app) as client:
        statuts = [(await client.get(URL, headers=cookie(session))).status_code for _ in range(121)]
        arretee = await client.get(URL, headers=cookie(session))
        intacte = await client.get(URL, headers=cookie(autre))
    assert statuts == [200] * 120 + [429]
    assert arretee.headers["retry-after"]
    assert intacte.status_code == 200


async def test_la_limite_par_personne_compte_toutes_les_sessions_de_la_meme_personne(
    base: Base, monkeypatch: pytest.MonkeyPatch, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    premiere, seconde = fabrique.session(personne.id), fabrique.session(personne.id)
    app = application_de_test(base, monkeypatch, routeur)
    async with client_de(app) as client:
        for _ in range(120):
            await client.get(URL, headers=cookie(premiere))
        autre_session = await client.get(URL, headers=cookie(seconde))
    assert autre_session.status_code == 429


async def test_un_cookie_invente_n_ouvre_aucun_compteur_par_personne(
    base: Base, monkeypatch: pytest.MonkeyPatch
) -> None:
    jeton, _ = jeton_et_empreinte()
    app = application_de_test(base, monkeypatch, routeur)
    async with client_de(app) as client:
        reponse = await client.get(URL, headers={"Cookie": f"__Host-popote_session={jeton}"})
    assert reponse.status_code == 401
    assert app.state.debit.personne._fenetres == {}
