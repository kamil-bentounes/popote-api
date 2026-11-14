"""0.4bis S10 : la suppression d'une clé et ses voisines sous le verrou de personne (leçon 1 de T15b).

Courses déterministes (`_course.py`) : une connexion A tient le verrou sans valider, B démarre, le test
attend que `pg_stat_activity` montre B en attente, A valide, on lit le sort de B. Aucun `sleep` comme preuve.
Base locale, données inventées.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import psycopg
import pytest
from _client import cookie
from _connexions import DSN_ADMIN, DSN_API, connecte
from _course import attend_un_verrou
from _fabrique import Fabrique, jeton_et_empreinte
from test_connexion_par_cle import BancDeConnexion
from test_enregistrement_de_cle import Banc as BancDEnregistrement

from popote_api.infra.db import Base

pytestmark = pytest.mark.integration

ECRITURE = {"Origin": "http://localhost:5173", "X-Popote-Client": "web"}
POIVRE = "p" * 32
Ligne = tuple[object, ...]


@pytest.fixture
async def banc(
    base: Base, fabrique: Fabrique, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[BancDeConnexion]:
    enregistrement = BancDEnregistrement(base, fabrique, monkeypatch, identity_pepper=POIVRE)
    banc = BancDeConnexion(enregistrement)
    yield banc
    cle_ip = banc.empreintes.cle_ip_requise(banc.ip)
    admin = fabrique.admin
    admin.execute("delete from public.login_throttle where key = %s", (cle_ip,))
    admin.execute(
        "delete from public.security_event where person_id = %s or ip_hash = %s", (banc.moi.id, cle_ip)
    )
    admin.execute("delete from public.webauthn_challenge where purpose = 'authentication'")


def cle_de(banc: BancDeConnexion) -> UUID:
    (ligne,) = banc.lignes("select id from public.webauthn_credential where person_id = %s", banc.moi.id)
    return UUID(str(ligne[0]))


async def attend_puis_valide(
    admin: psycopg.Connection[Ligne],
    motif: str,
    a: psycopg.Connection[Ligne],
    tache: asyncio.Task[httpx.Response],
) -> httpx.Response:
    """Attend que B (`motif`) bloque derrière A, valide A, rend la réponse de B ; annule si B n'attend pas."""
    try:
        await attend_un_verrou(admin, motif, a.info.backend_pid)
    except BaseException:
        tache.cancel()
        a.rollback()
        await asyncio.gather(tache, return_exceptions=True)
        raise
    a.commit()
    return await tache


class TestCourse:
    async def test_une_connexion_par_la_cle_attend_la_suppression_puis_est_refusee_sans_session(
        self, banc: BancDeConnexion
    ) -> None:
        cle_d_acces = await banc.cle()
        credential = cle_d_acces.signe(await banc.options())
        cle = cle_de(banc)
        proche = banc.fabrique.session(banc.moi.id)
        admin = banc.fabrique.admin
        with connecte(DSN_API) as a:
            a.execute("set local role authenticated")
            a.execute(
                "select set_config('request.jwt.claims', %s, true)",
                (f'{{"sub": "{banc.moi.id}", "role": "authenticated"}}',),
            )
            a.execute("select * from public.supprime_ma_cle(%s, %s, null)", (proche.empreinte, cle))
            tache = asyncio.create_task(banc.poste(credential))
            reponse = await attend_puis_valide(admin, "cle_pour_connexion", a, tache)
        assert (reponse.status_code, reponse.json()["code"]) == (401, "cle_refusee")
        assert banc.sessions_de_la_cle() == []
        assert banc.lignes("select 1 from public.webauthn_credential where person_id = %s", banc.moi.id) == []

    async def test_une_session_ouverte_par_la_cle_juste_avant_est_fermee_avec_elle(
        self, banc: BancDeConnexion
    ) -> None:
        await banc.cle()
        cle = cle_de(banc)
        proche = banc.fabrique.session(banc.moi.id)
        _, empreinte = jeton_et_empreinte()
        admin = banc.fabrique.admin
        with connecte(DSN_ADMIN) as a:
            # A joue `ouvre_une_session_par_cle` : le verrou de la personne, puis la session de la clé.
            a.execute("select private.verrouille_la_personne(%s)", (banc.moi.id,))
            ligne = a.execute(
                "insert into public.login_session (token_hash, person_id, expires_at, absolute_expires_at,"
                " opened_with, opened_with_credential) values (%s, %s, now() + interval '30 days',"
                " now() + interval '90 days', 'cle', %s) returning id",
                (empreinte, banc.moi.id, cle),
            ).fetchone()
            assert ligne is not None
            en_vol = ligne[0]
            tache = asyncio.create_task(
                banc.client().delete(f"/api/v1/me/passkeys/{cle}", headers=cookie(proche) | ECRITURE)
            )
            reponse = await attend_puis_valide(admin, "supprime_ma_cle", a, tache)
        assert reponse.status_code == 204
        assert banc.lignes(
            "select revoked_at is not null from public.login_session where id = %s", en_vol
        ) == [(True,)]
        assert banc.lignes("select 1 from public.webauthn_credential where person_id = %s", banc.moi.id) == []

    async def test_une_suppression_apres_la_fermeture_de_toutes_les_sessions_est_refusee_et_garde_la_cle(
        self, banc: BancDeConnexion
    ) -> None:
        await banc.cle()
        cle = cle_de(banc)
        fermee_en_vol = banc.fabrique.session(banc.moi.id)
        admin = banc.fabrique.admin
        with connecte(DSN_ADMIN) as a:
            a.execute("select private.verrouille_la_personne(%s)", (banc.moi.id,))
            a.execute("update public.login_session set revoked_at = now() where id = %s", (fermee_en_vol.id,))
            tache = asyncio.create_task(
                banc.client().delete(f"/api/v1/me/passkeys/{cle}", headers=cookie(fermee_en_vol) | ECRITURE)
            )
            reponse = await attend_puis_valide(admin, "supprime_ma_cle", a, tache)
        assert (reponse.status_code, reponse.json()["code"]) == (401, "pas_de_session")
        assert banc.lignes("select id from public.webauthn_credential where person_id = %s", banc.moi.id) == [
            (cle,)
        ]
