"""`GET /api/v1/me` de bout en bout : session, RLS, e-mail par fonction `security definer`, ETag, 304.

Données inventées seulement (la fabrique). Base locale par défaut ; `POPOTE_TEST_DSN_API` et
`POPOTE_TEST_DSN_ADMIN` les rejouent sur un autre serveur.
"""

import json
from datetime import timedelta
from uuid import uuid4

import httpx
import psycopg
import pytest
from _client import application_de_test, client_de, cookie
from _connexions import DSN_API, connecte
from _fabrique import Fabrique
from psycopg import sql

from popote_api.conditionnel import etag_de_contenu
from popote_api.infra.db import Base
from popote_api.security.session import DEFI_D_AUTHENTIFICATION

pytestmark = pytest.mark.integration

URL = "/api/v1/me"


@pytest.fixture
def application(base: Base, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    return client_de(application_de_test(base, monkeypatch))


def adresse_de(fabrique: Fabrique, personne_id: object) -> str:
    ligne = fabrique.admin.execute("select email from auth.users where id = %s", (personne_id,)).fetchone()
    assert ligne is not None
    return str(ligne[0])


def prenom_et_foyer(fabrique: Fabrique, personne_id: object) -> tuple[str, str]:
    ligne = fabrique.admin.execute(
        "select p.display_name, h.name from public.user_profile p join public.household h"
        " on h.id = p.household_id where p.id = %s",
        (personne_id,),
    ).fetchone()
    assert ligne is not None
    return str(ligne[0]), str(ligne[1])


async def test_me_rend_sa_personne_son_adresse_et_son_foyer(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    prenom, foyer = prenom_et_foyer(fabrique, personne.id)
    reponse = await application.get(URL, headers=cookie(fabrique.session(personne.id)))
    assert reponse.status_code == 200
    assert reponse.json() == {
        "id": str(personne.id),
        "email": adresse_de(fabrique, personne.id),
        "display_name": prenom,
        "household": {"id": str(personne.foyer_id), "name": foyer},
    }


async def test_me_ne_rend_que_les_champs_listes(application: httpx.AsyncClient, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    corps = (await application.get(URL, headers=cookie(fabrique.session(personne.id)))).json()
    assert set(corps) == {"id", "email", "display_name", "household"}
    assert set(corps["household"]) == {"id", "name"}


async def test_deux_personnes_de_deux_foyers_ne_voient_que_le_leur(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    moi = fabrique.personne(fabrique.foyer())
    autre = fabrique.personne(fabrique.foyer())
    chez_moi = (await application.get(URL, headers=cookie(fabrique.session(moi.id)))).json()
    chez_l_autre = (await application.get(URL, headers=cookie(fabrique.session(autre.id)))).json()
    assert (chez_moi["id"], chez_moi["household"]["id"]) == (str(moi.id), str(moi.foyer_id))
    assert (chez_l_autre["id"], chez_l_autre["household"]["id"]) == (str(autre.id), str(autre.foyer_id))
    assert chez_moi["email"] != chez_l_autre["email"]


async def test_deux_personnes_du_meme_foyer_ont_chacune_leur_adresse(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    foyer = fabrique.foyer()
    premiere, seconde = fabrique.personne(foyer), fabrique.personne(foyer)
    corps = [
        (await application.get(URL, headers=cookie(fabrique.session(p.id)))).json()
        for p in (premiere, seconde)
    ]
    assert [c["email"] for c in corps] == [
        adresse_de(fabrique, premiere.id),
        adresse_de(fabrique, seconde.id),
    ]
    assert corps[0]["household"] == corps[1]["household"]


async def test_une_personne_sans_profil_n_a_ni_foyer_ni_prenom(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    fabrique.admin.execute("delete from public.user_profile where id = %s", (personne.id,))
    reponse = await application.get(URL, headers=cookie(fabrique.session(personne.id)))
    assert reponse.status_code == 200
    assert reponse.json() == {
        "id": str(personne.id),
        "email": adresse_de(fabrique, personne.id),
        "display_name": None,
        "household": None,
    }


async def test_me_n_est_jamais_mis_en_cache_et_porte_un_etag_fort(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    reponse = await application.get(
        URL, headers=cookie(fabrique.session(fabrique.personne(fabrique.foyer()).id))
    )
    assert reponse.headers["cache-control"] == "no-store"
    assert reponse.headers["etag"] == etag_de_contenu(reponse.content)  # fort : pas de `W/`


async def test_l_etag_suit_le_contenu(application: httpx.AsyncClient, fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    session = fabrique.session(personne.id)
    avant = (await application.get(URL, headers=cookie(session))).headers["etag"]
    fabrique.admin.execute(
        "update public.user_profile set display_name = 'Autre prénom' where id = %s", (personne.id,)
    )
    apres = (await application.get(URL, headers=cookie(session))).headers["etag"]
    assert avant != apres


async def test_if_none_match_egal_rend_304_sans_corps(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    premiere = await application.get(URL, headers=cookie(session))
    reponse = await application.get(
        URL, headers={**cookie(session), "If-None-Match": premiere.headers["etag"]}
    )
    assert reponse.status_code == 304
    assert reponse.content == b""
    assert reponse.headers["etag"] == premiere.headers["etag"]
    assert reponse.headers["cache-control"] == "no-store"


async def test_if_none_match_d_une_autre_version_rend_200(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    reponse = await application.get(URL, headers={**cookie(session), "If-None-Match": '"autre"'})
    assert reponse.status_code == 200


async def test_l_etag_d_une_personne_ne_donne_pas_de_304_a_une_autre(
    application: httpx.AsyncClient, fabrique: Fabrique
) -> None:
    moi = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    autre = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    mon_etag = (await application.get(URL, headers=cookie(moi))).headers["etag"]
    reponse = await application.get(URL, headers={**cookie(autre), "If-None-Match": mon_etag})
    assert reponse.status_code == 200


async def test_if_none_match_mal_forme_rend_400(application: httpx.AsyncClient, fabrique: Fabrique) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    reponse = await application.get(URL, headers={**cookie(session), "If-None-Match": "pas-une-etiquette"})
    assert reponse.status_code == 400


async def test_un_304_exige_encore_une_session(application: httpx.AsyncClient, fabrique: Fabrique) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id)
    etag = (await application.get(URL, headers=cookie(session))).headers["etag"]
    reponse = await application.get(URL, headers={"If-None-Match": etag})
    assert reponse.status_code == 401


@pytest.mark.parametrize(
    "refus",
    [
        {"echeance_dans": -timedelta(minutes=1)},
        {"revoquee": True},
        {"echeance_dans": -timedelta(days=1), "absolue_dans": -timedelta(seconds=1)},
    ],
    ids=["echue", "revoquee", "au_bout_des_90_jours"],
)
async def test_me_sans_session_valide_rend_401(
    application: httpx.AsyncClient, fabrique: Fabrique, refus: dict[str, object]
) -> None:
    session = fabrique.session(fabrique.personne(fabrique.foyer()).id, **refus)  # type: ignore[arg-type]
    reponse = await application.get(URL, headers=cookie(session))
    assert reponse.status_code == 401
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.headers["www-authenticate"] == DEFI_D_AUTHENTIFICATION


async def test_me_sans_cookie_rend_401(application: httpx.AsyncClient) -> None:
    reponse = await application.get(URL)
    assert reponse.status_code == 401
    assert reponse.json()["code"] == "pas_de_session"


async def test_me_ne_journalise_ni_l_adresse_ni_le_prenom(
    application: httpx.AsyncClient, fabrique: Fabrique, caplog: pytest.LogCaptureFixture
) -> None:
    personne = fabrique.personne(fabrique.foyer())
    prenom, _ = prenom_et_foyer(fabrique, personne.id)
    with caplog.at_level(0):
        await application.get(URL, headers=cookie(fabrique.session(personne.id)))
    assert adresse_de(fabrique, personne.id) not in caplog.text
    assert prenom not in caplog.text


# --- la fonction de l'adresse, éprouvée sous les rôles de la base ---


def adresse_sous(role: str, personne_id: object) -> object:
    with connecte(DSN_API) as cx, cx.transaction(force_rollback=True):
        cx.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
        if personne_id is not None:
            cx.execute(
                "select set_config('request.jwt.claims', %s, true)",
                (json.dumps({"role": "authenticated", "sub": str(personne_id)}),),
            )
        ligne = cx.execute("select public.mon_email()").fetchone()
    assert ligne is not None
    return ligne[0]


def test_mon_email_rend_celui_de_la_personne_du_contexte(fabrique: Fabrique) -> None:
    foyer = fabrique.foyer()
    moi, voisine = fabrique.personne(foyer), fabrique.personne(foyer)
    assert adresse_sous("authenticated", moi.id) == adresse_de(fabrique, moi.id)
    assert adresse_sous("authenticated", voisine.id) == adresse_de(fabrique, voisine.id)


def test_mon_email_ne_rend_rien_sans_identite() -> None:
    assert adresse_sous("authenticated", None) is None


def test_mon_email_ne_rend_rien_pour_une_personne_inconnue() -> None:
    assert adresse_sous("authenticated", uuid4()) is None


def test_mon_email_ne_rend_rien_pour_une_personne_supprimee(fabrique: Fabrique) -> None:
    personne = fabrique.personne(fabrique.foyer())
    fabrique.admin.execute("update auth.users set deleted_at = now() where id = %s", (personne.id,))
    assert adresse_sous("authenticated", personne.id) is None


@pytest.mark.parametrize("role", ["anon", "service_role"])
def test_mon_email_n_est_pas_executable_par(role: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        adresse_sous(role, None)


def test_les_droits_sur_mon_email_se_lisent_dans_le_catalogue(fabrique: Fabrique) -> None:
    ouverts = {
        role: fabrique.admin.execute(
            "select has_function_privilege(%s, 'public.mon_email()', 'execute')", (role,)
        ).fetchone()
        for role in ("authenticated", "anon", "service_role", "popote_api", "popote_internal")
    }
    assert ouverts == {
        "authenticated": (True,),
        "anon": (False,),
        "service_role": (False,),
        "popote_api": (False,),
        "popote_internal": (False,),
    }
    public = fabrique.admin.execute(
        "select exists (select 1 from pg_proc p, aclexplode(p.proacl) a"
        " where p.oid = 'public.mon_email()'::regprocedure and a.grantee = 0)"
    ).fetchone()
    assert public == (False,)
    definer = fabrique.admin.execute(
        "select prosecdef, proconfig from pg_proc where oid = 'public.mon_email()'::regprocedure"
    ).fetchone()
    assert definer == (True, ['search_path=""'])
