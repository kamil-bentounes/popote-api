"""0.4bis S7b : la route de connexion par code face aux fermetures de sessions (S6), par HTTP.

Course déterministe : A tient le verrou de la personne en fermant ses sessions et ne valide pas ; B (la route)
a déjà pris ses créneaux et attend ce verrou ; on le voit dans `pg_stat_activity` ; A valide ; B est refusé.
Les créneaux se prennent AVANT le verrou (limites, puis personne) : B a donc déjà écrit un compteur quand il
attend, ce que `_course.course` interdit pour les autres fonctions ; on emploie `attend_un_verrou` seul.
"""

# ruff: noqa: F811  # les fixtures de test_connexion sont reprises par import

import asyncio

import psycopg
import pytest
from _connexions import DSN_API, connecte
from _course import attend_un_verrou
from _fabrique import Fabrique
from test_connexion import Banc, banc, banc_avec, comptes  # noqa: F401  # fixtures reprises

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]


async def test_une_fermeture_de_toutes_les_sessions_qui_precede_fait_refuser_le_code(
    banc: Banc, fabrique: Fabrique
) -> None:
    personne, email = banc.personne()
    admin: psycopg.Connection[Ligne] = fabrique.admin
    gardee = fabrique.session(personne)
    identifiant, bon = banc.pose_un_code(email, personne)
    with connecte(DSN_API) as a:
        a.execute("select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (personne, gardee.id))
        tache = asyncio.create_task(banc.poste(email, identifiant, bon))
        try:
            await attend_un_verrou(admin, "ouvre_une_session_par_code", a.info.backend_pid)
        except BaseException:
            tache.cancel()
            a.rollback()
            await asyncio.gather(tache, return_exceptions=True)
            raise
        a.commit()
        reponse = await tache
    assert (reponse.status_code, reponse.json()["code"]) == (401, "code_incorrect")
    assert "set-cookie" not in reponse.headers
    # Le code a été révoqué par la fermeture : rien ne s'ouvre après elle, la session gardée est la seule.
    assert banc.lignes(
        "select revoked_at is not null, used_at is null from public.login_code where id = %s", identifiant
    ) == [(True, True)]
    assert [
        r[0]
        for r in banc.lignes(
            "select id from public.login_session where person_id = %s and revoked_at is null", personne
        )
    ] == [gardee.id]


async def test_la_connexion_attend_le_verrou_puis_reussit_quand_rien_n_a_ete_revoque(
    banc: Banc, fabrique: Fabrique
) -> None:
    personne, email = banc.personne()
    admin: psycopg.Connection[Ligne] = fabrique.admin
    identifiant, bon = banc.pose_un_code(email, personne)
    with connecte(DSN_API) as a:
        a.execute("select public.verrouille_la_personne(%s)", (personne,))
        tache = asyncio.create_task(banc.poste(email, identifiant, bon))
        try:
            await attend_un_verrou(admin, "ouvre_une_session_par_code", a.info.backend_pid)
        except BaseException:
            tache.cancel()
            a.rollback()
            await asyncio.gather(tache, return_exceptions=True)
            raise
        a.commit()
        reponse = await tache
    assert reponse.status_code == 201
