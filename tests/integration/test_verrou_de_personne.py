"""0.4bis S6 : le verrou de personne et la fermeture des sessions (migration 0148 ; leçon 1, A2).

En base locale, données inventées. Les courses sont déterministes (`_course.py`) : A tient un verrou sans
valider, B démarre, on attend B dans `pg_stat_activity`, A valide, on lit le sort de B. Aucun `sleep`
ne sert de preuve.
"""

# ruff: noqa: F811  # les fixtures de test_connexion sont reprises par import

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from secrets import token_bytes
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_API, connecte
from _course import attend_un_verrou, course, ne_fait_pas_attendre
from _fabrique import Fabrique, SessionDeTest
from test_connexion import MOT_DE_PASSE, Banc, banc, banc_avec, comptes  # noqa: F401  # fixtures reprises
from test_verifie_mot_de_passe import hache

from popote_api.infra import db
from popote_api.infra.db import Base, SessionRefuseeError
from popote_api.security import connexion as modele_connexion
from popote_api.security.appareil import Appareil
from popote_api.security.sessions_base import cree_session

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
MIN = timedelta(minutes=1)
PERIMEE = timedelta(minutes=10)
APPAREIL = Appareil("chrome", "linux")
VERROU = "select public.verrouille_la_personne(%s)"
FERME_LES_AUTRES = "select public.ferme_les_autres_appareils(%s)"
LIT = "select person_id, session_id, activite_perimee from private.lit_la_session(%s, %s)"
NOTE = "select private.note_l_activite_de_la_session(%s, %s)"
CREE = "select private.cree_session(%s, %s, 'chrome', 'linux', null, %s)"


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


@pytest.fixture
def personne(fabrique: Fabrique) -> UUID:
    return fabrique.personne(fabrique.foyer()).id


def active(admin: psycopg.Connection[Ligne], session: UUID) -> bool:
    ligne = admin.execute(
        "select revoked_at is null from public.login_session where id = %s", (session,)
    ).fetchone()
    assert ligne is not None
    return bool(ligne[0])


def nombre_d_actives(admin: psycopg.Connection[Ligne], personne: UUID) -> int:
    ligne = admin.execute(
        "select count(*) from public.login_session where person_id = %s and revoked_at is null", (personne,)
    ).fetchone()
    assert ligne is not None
    return int(ligne[0])  # type: ignore[call-overload]


def code_en_attente(admin: psycopg.Connection[Ligne], personne: UUID) -> bytes:
    cle = token_bytes(32)
    admin.execute(
        "insert into public.login_code (account_key, person_id, code_hash) values (%s, %s, %s)",
        (cle, personne, token_bytes(32)),
    )
    return cle


def revoque(admin: psycopg.Connection[Ligne], cle: bytes) -> bool:
    ligne = admin.execute(
        "select revoked_at is not null from public.login_code where account_key = %s", (cle,)
    ).fetchone()
    assert ligne is not None
    return bool(ligne[0])


def prend(personne: UUID) -> Callable[[psycopg.Connection[Ligne]], object]:
    return lambda a: a.execute(VERROU, (personne,))


async def ferme_les_autres_appareils(base: Base, personne: UUID, courante: UUID) -> None:
    async with base.personne(personne) as curseur:
        await curseur.execute(FERME_LES_AUTRES, (courante,))


async def confirme_le_mot_de_passe(base: Base, personne: UUID, courante: UUID) -> None:
    async with base.connexion() as curseur:
        await curseur.execute(
            "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (personne, courante)
        )


async def fait_tourner_et_ferme(base: Base, ancienne: bytes, nouvelle: bytes) -> None:
    async with base.connexion() as curseur:
        await curseur.execute("select public.fait_tourner_et_ferme_les_autres(%s, %s)", (ancienne, nouvelle))


async def cree(base: Base, personne: UUID, session_presentee: bytes | None = None) -> tuple[UUID, bytes]:
    empreinte = token_bytes(32)
    async with base.connexion() as curseur:
        identifiant = await cree_session(
            curseur, personne, empreinte, APPAREIL, session_presentee=session_presentee
        )
    return identifiant, empreinte


# ── Le verrou : celui de `cree_session`, nommé ──────────────────────────────


def test_le_verrou_est_celui_de_cree_session_et_refuse_une_personne_nulle(
    admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        admin.execute("select private.verrouille_la_personne(null)")
    with admin.transaction():
        admin.execute("select private.verrouille_la_personne(%s)", (personne,))
        cle = admin.execute("select hashtextextended(%s, 0)", (str(personne),)).fetchone()
        assert cle is not None
        tenus = admin.execute(
            "select count(*) from pg_locks where locktype = 'advisory' and pid = pg_backend_pid() and granted"
            " and ((classid::bigint << 32) | objid::bigint) = %s",
            (cle[0],),
        ).fetchone()
        assert tenus == (1,)


async def test_le_verrou_public_tient_jusqu_a_la_fin_de_la_transaction(
    base: Base, admin: psycopg.Connection[Ligne], personne: UUID
) -> None:
    # B prend le même verrou : il attend A, et passe dès que A valide.
    async def b() -> None:
        async with base.connexion() as curseur:
            await curseur.execute(VERROU, (personne,))

    await course(admin, prend(personne), b, "verrouille_la_personne")


async def test_deux_personnes_ne_se_verrouillent_pas(base: Base, fabrique: Fabrique, personne: UUID) -> None:
    autre = fabrique.personne(fabrique.foyer()).id

    async def b() -> None:
        async with base.connexion() as curseur:
            await curseur.execute(VERROU, (autre,))

    await ne_fait_pas_attendre(prend(personne), b)


# ── Tout ce qui ferme des sessions attend le verrou de la même personne ─────


class TestAttend:
    async def test_ferme_les_autres_appareils(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        courante, autre = fabrique.session(personne), fabrique.session(personne)
        await course(
            admin,
            prend(personne),
            lambda: ferme_les_autres_appareils(base, personne, courante.id),
            "ferme_les_autres_appareils",
        )
        assert active(admin, courante.id) and not active(admin, autre.id)

    async def test_ferme_les_autres_appareils_n_attend_pas_une_autre_personne(
        self, base: Base, fabrique: Fabrique, personne: UUID
    ) -> None:
        autre_personne = fabrique.personne(fabrique.foyer()).id
        courante = fabrique.session(personne)
        await ne_fait_pas_attendre(
            prend(autre_personne), lambda: ferme_les_autres_appareils(base, personne, courante.id)
        )

    async def test_ferme_les_autres_sessions_appelee_seule(
        self, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        """La fonction interne prend elle-même le verrou : ses appelants futurs n'y pensent pas."""
        courante, autre = fabrique.session(personne), fabrique.session(personne)

        def appel() -> None:
            with psycopg.connect(admin.info.dsn, password=admin.info.password) as cx:
                cx.execute("select private.ferme_les_autres_sessions(%s, %s, now())", (personne, courante.id))

        await course(admin, prend(personne), lambda: asyncio.to_thread(appel), "ferme_les_autres_sessions")
        assert active(admin, courante.id) and not active(admin, autre.id)

    async def test_le_changement_de_mot_de_passe_ferme_les_autres_sessions(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        courante, autre = fabrique.session(personne), fabrique.session(personne)
        await course(
            admin,
            prend(personne),
            lambda: confirme_le_mot_de_passe(base, personne, courante.id),
            "confirme_le_changement_de_mot_de_passe",
        )
        assert active(admin, courante.id) and not active(admin, autre.id)

    async def test_fait_tourner_et_ferme_les_autres(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        courante, autre = fabrique.session(personne), fabrique.session(personne)
        await course(
            admin,
            prend(personne),
            lambda: fait_tourner_et_ferme(base, courante.empreinte, token_bytes(32)),
            "fait_tourner_et_ferme_les_autres",
        )
        assert active(admin, courante.id) and not active(admin, autre.id)

    async def test_cree_session(self, base: Base, admin: psycopg.Connection[Ligne], personne: UUID) -> None:
        identifiant, _ = await course(admin, prend(personne), lambda: cree(base, personne), "cree_session")
        assert active(admin, identifiant)


# ── Une preuve en vol, avant ou après la fermeture ──────────────────────────


class TestPreuveEnVol:
    async def test_une_session_ouverte_avant_la_fermeture_est_fermee(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        courante = fabrique.session(personne)
        nouvelle = token_bytes(32)
        en_vol = uuid4()

        def connexion_en_vol(a: psycopg.Connection[Ligne]) -> None:
            ligne = a.execute(
                "select public.cree_session(%s, %s, 'chrome', 'linux', null)", (personne, nouvelle)
            ).fetchone()
            assert ligne is not None
            nonlocal en_vol
            en_vol = ligne[0]  # type: ignore[assignment]

        await course(
            admin,
            connexion_en_vol,
            lambda: ferme_les_autres_appareils(base, personne, courante.id),
            "ferme_les_autres_appareils",
        )
        assert active(admin, courante.id)
        assert not active(admin, en_vol)  # sa preuve précédait la fermeture : aucune session ne survit

    async def test_une_session_ouverte_apres_la_fermeture_survit(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        courante, ancienne = fabrique.session(personne), fabrique.session(personne)

        def fermeture(a: psycopg.Connection[Ligne]) -> None:
            a.execute(
                "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (personne, courante.id)
            )

        apres, _ = await course(admin, fermeture, lambda: cree(base, personne), "cree_session")
        assert active(admin, apres) and active(admin, courante.id) and not active(admin, ancienne.id)


# ── La preuve et la session : un mot de passe changé entre les deux ─────────


async def test_un_mot_de_passe_change_entre_la_verification_et_la_session_refuse_la_connexion(
    banc: Banc, admin: psycopg.Connection[Ligne], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La barrière : juste après la première vérification, Auth change le mot de passe."""
    personne, email = banc.compte()
    verifie = modele_connexion.verifie_un_candidat

    async def verifie_puis_change(curseur: object, adresse: str, mot_de_passe: str) -> UUID | None:
        trouvee = await verifie(curseur, adresse, mot_de_passe)  # type: ignore[arg-type]
        admin.execute(
            "update auth.users set encrypted_password = %s where id = %s",
            (hache(admin, "un-autre-mot-de-passe-long"), personne),
        )
        return trouvee

    monkeypatch.setattr(modele_connexion, "verifie_un_candidat", verifie_puis_change)
    reponse = await banc.connecte(email, MOT_DE_PASSE)
    assert reponse.status_code == 401  # la preuve refaite sous le verrou échoue : aucune session ne survit
    assert nombre_d_actives(admin, personne) == 0


async def test_une_connexion_dont_le_mot_de_passe_n_a_pas_change_ouvre_sa_session(
    banc: Banc, admin: psycopg.Connection[Ligne]
) -> None:
    personne, email = banc.compte()
    assert (await banc.connecte(email, MOT_DE_PASSE)).status_code == 201
    assert nombre_d_actives(admin, personne) == 1


# ── Le code déjà déployé, pendant la fenêtre de déploiement ─────────────────


async def test_l_ancien_chemin_de_lecture_ne_s_interbloque_pas_avec_les_fermetures_et_les_reconnexions(
    base: Base, fabrique: Fabrique, personne: UUID
) -> None:
    """L'ancien code lit par `session_courante` (une lecture, 0148) avant d'appeler les fermetures qui
    prennent la personne : il ne tient plus de ligne de session, donc aucun cycle avec une reconnexion."""
    vivante = fabrique.session(personne)

    async def ancienne_requete(session: SessionDeTest) -> None:
        async with base.connexion() as lecture:  # une transaction de l'ancien code : lecture puis fermeture
            await lecture.execute("select public.session_courante(%s)", (session.empreinte,))
            await lecture.execute(
                "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (personne, vivante.id)
            )

    for _ in range(40):
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)
        await asyncio.gather(
            ancienne_requete(session),
            cree(base, personne, session_presentee=session.empreinte),
            ancienne_requete(session),
        )


# ── La session présentée peut être celle d'une autre personne ───────────────


def verrou_libre(admin: psycopg.Connection[Ligne], personne: UUID) -> bool:
    """Vrai si le verrou de cette personne est libre (un essai sans attente, transaction annulée)."""
    with psycopg.connect(admin.info.dsn, password=admin.info.password) as cx:
        ligne = cx.execute(
            "select pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (str(personne),)
        ).fetchone()
    assert ligne is not None
    return bool(ligne[0])


class TestSessionPresenteeDUneAutrePersonne:
    """Deux personnes, un navigateur : présenter le cookie de l'autre ferme sa session (B22)."""

    @pytest.fixture
    def deux(self, fabrique: Fabrique) -> tuple[UUID, UUID]:
        un, autre = fabrique.personne(fabrique.foyer()).id, fabrique.personne(fabrique.foyer()).id
        bas, haut = sorted((un, autre), key=str)
        return bas, haut

    async def test_la_session_de_l_autre_est_fermee_comme_avant(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], deux: tuple[UUID, UUID]
    ) -> None:
        bas, haut = deux
        de_l_autre = fabrique.session(haut)
        await cree(base, bas, session_presentee=de_l_autre.empreinte)
        assert not active(admin, de_l_autre.id)

    async def test_l_id_le_plus_grand_prend_d_abord_le_plus_petit_sans_tenir_le_sien(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], deux: tuple[UUID, UUID]
    ) -> None:
        bas, haut = deux
        de_bas = fabrique.session(bas)
        with connecte(DSN_API) as a:
            a.execute(VERROU, (bas,))
            tache = asyncio.create_task(cree(base, haut, session_presentee=de_bas.empreinte))
            await attend_un_verrou(admin, "cree_session", a.info.backend_pid)
            # B attend la plus petite SANS tenir la sienne : deux connexions croisées ne s'attendent pas.
            assert verrou_libre(admin, haut)
            a.commit()
            await tache
        assert not active(admin, de_bas.id)

    async def test_l_id_le_plus_petit_prend_le_sien_puis_l_autre(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], deux: tuple[UUID, UUID]
    ) -> None:
        bas, haut = deux
        de_haut = fabrique.session(haut)
        with connecte(DSN_API) as a:
            a.execute(VERROU, (haut,))
            tache = asyncio.create_task(cree(base, bas, session_presentee=de_haut.empreinte))
            await attend_un_verrou(admin, "cree_session", a.info.backend_pid)
            assert not verrou_libre(admin, bas)  # elle tient la sienne, en ordre, en attendant la plus grande
            a.commit()
            await tache
        assert not active(admin, de_haut.id)

    async def test_deux_connexions_croisees_avec_dix_sessions_chacune_sans_40p01(
        self, base: Base, fabrique: Fabrique, deux: tuple[UUID, UUID]
    ) -> None:
        bas, haut = deux
        for _ in range(10):
            fabrique.session(bas)
            fabrique.session(haut)
        for _ in range(40):
            presentee_de_bas, presentee_de_haut = fabrique.session(bas), fabrique.session(haut)
            await asyncio.gather(
                cree(base, bas, session_presentee=presentee_de_haut.empreinte),
                cree(base, haut, session_presentee=presentee_de_bas.empreinte),
                cree(base, bas, session_presentee=presentee_de_haut.empreinte),
                cree(base, haut, session_presentee=presentee_de_bas.empreinte),
            )


class TestConnexionParMotDePasseEtSessionPresentee:
    """Le verrou pris en Python AVANT la preuve refaite doit déjà ordonner les deux personnes."""

    async def test_la_connexion_de_l_id_le_plus_grand_attend_la_plus_petite_sans_tenir_la_sienne(
        self, banc: Banc, fabrique: Fabrique, admin: psycopg.Connection[Ligne]
    ) -> None:
        un, adresse_un = banc.compte()
        autre, adresse_autre = banc.compte()
        (bas, _), (haut, adresse_haut) = sorted(
            ((un, adresse_un), (autre, adresse_autre)), key=lambda p: str(p[0])
        )
        cookie_de_bas = fabrique.session(bas)
        with connecte(DSN_API) as a:
            a.execute(VERROU, (bas,))
            tache = asyncio.create_task(
                banc.connecte(
                    adresse_haut,
                    MOT_DE_PASSE,
                    headers={"Cookie": f"__Host-popote_session={cookie_de_bas.jeton}"},
                )
            )
            await attend_un_verrou(admin, "verrouille_la_personne", a.info.backend_pid)
            assert verrou_libre(admin, haut)  # elle ne tient pas la sienne en attendant la plus petite
            a.commit()
            reponse = await tache
        assert reponse.status_code == 201
        assert not active(
            admin, cookie_de_bas.id
        )  # la session présentée de l'autre personne est fermée (B22)


# ── Les codes en attente meurent avec les autres sessions ───────────────────


class TestCodesEnAttente:
    async def test_ferme_les_autres_appareils_revoque_les_codes_de_la_personne_seulement(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        autre_personne = fabrique.personne(fabrique.foyer()).id
        courante = fabrique.session(personne)
        a_moi, a_l_autre = code_en_attente(admin, personne), code_en_attente(admin, autre_personne)
        try:
            await ferme_les_autres_appareils(base, personne, courante.id)
            assert revoque(admin, a_moi) and not revoque(admin, a_l_autre)
        finally:
            admin.execute("delete from public.login_code where account_key = any(%s)", ([a_moi, a_l_autre],))

    async def test_le_changement_de_mot_de_passe_revoque_les_codes_en_attente(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        courante = fabrique.session(personne)
        cle = code_en_attente(admin, personne)
        try:
            await confirme_le_mot_de_passe(base, personne, courante.id)
            assert revoque(admin, cle)
        finally:
            admin.execute("delete from public.login_code where account_key = %s", (cle,))

    async def test_un_code_deja_utilise_garde_sa_trace(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        courante = fabrique.session(personne)
        cle = code_en_attente(admin, personne)
        admin.execute("update public.login_code set used_at = now() where account_key = %s", (cle,))
        try:
            await ferme_les_autres_appareils(base, personne, courante.id)
            assert not revoque(admin, cle)
        finally:
            admin.execute("delete from public.login_code where account_key = %s", (cle,))


# ── Entrelacements : aucun interblocage ─────────────────────────────────────


class TestEntrelacements:
    async def test_deux_cents_operations_de_fermeture_et_de_creation_sans_40p01(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        hasard = random.Random(20261113)
        courante = fabrique.session(personne)
        for _ in range(40):  # 40 rondes de 5 opérations : le pool de l'API n'a que 5 connexions
            cible = fabrique.session(personne)
            operations: list[Awaitable[object]] = [
                cree(base, personne, session_presentee=cible.empreinte),
                ferme_les_autres_appareils(base, personne, courante.id),
                confirme_le_mot_de_passe(base, personne, courante.id),
                fait_tourner_et_ferme(base, cible.empreinte, token_bytes(32)),
                cree(base, personne),
            ]
            hasard.shuffle(operations)
            await asyncio.gather(*operations)  # une erreur, `40P01` comprise, fait échouer le test
        assert nombre_d_actives(admin, personne) <= 10

    async def test_une_reconnexion_avec_le_meme_cookie_n_attend_pas_une_requete_a_activite_perimee(
        self, base: Base, fabrique: Fabrique, personne: UUID
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)
        async with base.session(session.empreinte) as (lue, curseur):
            # La requête est ouverte, sa route n'a rien pris : l'activité s'est écrite à part, avant elle.
            await asyncio.wait_for(cree(base, personne, session_presentee=session.empreinte), timeout=5)
            await curseur.execute(FERME_LES_AUTRES, (lue.session,))

    async def test_cent_requetes_a_activite_perimee_contre_des_reconnexions_et_des_fermetures_sans_40p01(
        self, base: Base, fabrique: Fabrique, personne: UUID
    ) -> None:
        hasard = random.Random(7)
        vivante = fabrique.session(
            personne
        )  # celle qu'aucune fermeture ne vise : la route a toujours quelqu'un
        arrivees: list[UUID] = []

        async def requete(session: SessionDeTest, entree: asyncio.Event) -> None:
            async with base.session(session.empreinte) as (lue, curseur):
                arrivees.append(lue.session)
                entree.set()  # la route est ouverte : reconnexion et fermeture peuvent démarrer
                await asyncio.sleep(0)
                await curseur.execute(FERME_LES_AUTRES, (vivante.id,))

        for _ in range(100):
            session = fabrique.session(personne, vue_il_y_a=PERIMEE)
            entree = asyncio.Event()
            en_route = asyncio.create_task(requete(session, entree))
            await entree.wait()
            autres: list[Awaitable[object]] = [
                cree(base, personne, session_presentee=session.empreinte),
                ferme_les_autres_appareils(base, personne, vivante.id),
            ]
            hasard.shuffle(autres)
            await asyncio.gather(en_route, *autres)  # une erreur, `40P01` comprise, fait échouer le test
        assert len(arrivees) == 100  # chaque requête est arrivée jusqu'à sa route

    async def test_une_requete_a_activite_perimee_ne_tient_ni_ecriture_ni_verrou_a_l_entree_de_la_route(
        self, base: Base, fabrique: Fabrique, personne: UUID
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)
        async with base.session(session.empreinte) as (_, curseur):
            await curseur.execute(
                "select count(*) as n from pg_locks where pid = pg_backend_pid()"
                " and locktype in ('advisory', 'transactionid')"
            )
            ligne = await curseur.fetchone()
        assert ligne == {
            "n": 0
        }  # ni verrou de personne, ni transaction d'écriture : le foyer peut passer devant

    async def test_l_activite_perimee_s_ecrit_meme_si_la_route_echoue(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)
        avant = admin.execute(
            "select last_seen_at from public.login_session where id = %s", (session.id,)
        ).fetchone()
        with pytest.raises(RuntimeError, match="la route échoue"):
            async with base.session(session.empreinte):
                raise RuntimeError("la route échoue")
        apres = admin.execute(
            "select last_seen_at from public.login_session where id = %s", (session.id,)
        ).fetchone()
        assert avant is not None and apres is not None and apres[0] > avant[0]

    async def test_une_activite_qui_ne_peut_pas_s_ecrire_ne_fait_pas_echouer_la_requete(
        self,
        base: Base,
        fabrique: Fabrique,
        admin: psycopg.Connection[Ligne],
        personne: UUID,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """La personne est tenue plus longtemps que le délai de verrou : activité périmée, la route passe."""
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)
        requete = "select last_seen_at from public.login_session where id = %s"
        avant = admin.execute(requete, (session.id,)).fetchone()
        monkeypatch.setattr(db, "PREAMBULE_ACTIVITE", "set local lock_timeout = '200ms'")
        caplog.set_level(logging.WARNING)
        with connecte(DSN_API) as a:
            a.execute(VERROU, (personne,))
            async with base.session(session.empreinte) as (lue, _):
                assert lue.session == session.id  # la route a démarré
            a.rollback()
        assert admin.execute(requete, (session.id,)).fetchone() == avant
        assert "Activité de session non écrite : LockNotAvailable" in caplog.text

    @pytest.mark.parametrize(
        "erreur",
        [psycopg.errors.DeadlockDetected, psycopg.errors.QueryCanceled],
        ids=["interblocage", "delai"],
    )
    async def test_un_interblocage_ou_un_delai_a_l_ecriture_de_l_activite_n_echoue_pas_la_requete(
        self,
        base: Base,
        fabrique: Fabrique,
        personne: UUID,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        erreur: type[psycopg.Error],
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)

        @asynccontextmanager
        async def echoue(*_: object) -> AsyncIterator[None]:
            raise erreur("détail de la base")
            yield

        monkeypatch.setattr(db, "_contexte", echoue)
        caplog.set_level(logging.WARNING)
        async with base.session(session.empreinte) as (lue, _):
            assert lue.session == session.id
        assert f"Activité de session non écrite : {erreur.__name__}" in caplog.text
        assert "détail de la base" not in caplog.text

    async def test_une_annulation_pendant_l_ecriture_de_l_activite_repart(
        self, base: Base, fabrique: Fabrique, personne: UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)
        entree = asyncio.Event()

        @asynccontextmanager
        async def bloque(*_: object) -> AsyncIterator[None]:
            entree.set()
            await asyncio.sleep(60)
            yield

        async def requete() -> None:
            async with base.session(session.empreinte):
                pass

        monkeypatch.setattr(db, "_contexte", bloque)
        tache = asyncio.create_task(requete())
        await entree.wait()
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache

    async def test_une_session_fermee_pendant_l_ecriture_de_l_activite_rend_401_a_la_seconde_lecture(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)

        def ferme(a: psycopg.Connection[Ligne]) -> None:
            a.execute(VERROU, (personne,))
            a.execute("select public.ferme_session(%s)", (session.empreinte,))

        async def requete() -> bool:
            try:
                async with base.session(session.empreinte):
                    return False
            except SessionRefuseeError:
                return True

        assert await course(admin, ferme, requete, "note_l_activite_de_la_session") is True

    async def test_une_session_fermee_pendant_la_lecture_n_est_pas_rouverte(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)

        def ferme(a: psycopg.Connection[Ligne]) -> None:
            a.execute(VERROU, (personne,))
            a.execute("select public.ferme_session(%s)", (session.empreinte,))

        async def note() -> bool:
            async with base.connexion() as curseur:
                await curseur.execute(
                    "select public.note_l_activite_de_la_session(%s) as notee", (session.empreinte,)
                )
                ligne = await curseur.fetchone()
            assert ligne is not None
            return bool(ligne["notee"])

        # A tient la personne et ferme la session ; B (l'activité) attend, puis relit sous le verrou.
        assert await course(admin, ferme, note, "note_l_activite_de_la_session") is False
        assert not active(admin, session.id)


# ── Lire une session n'écrit rien et ne verrouille rien ─────────────────────


def cree_a(admin: psycopg.Connection[Ligne], personne: UUID, quand: datetime = T0) -> tuple[UUID, bytes]:
    empreinte = token_bytes(32)
    ligne = admin.execute(CREE, (personne, empreinte, quand)).fetchone()
    assert ligne is not None
    return ligne[0], empreinte  # type: ignore[return-value]


class TestLireSansEcrire:
    def test_l_activite_est_perimee_a_cinq_minutes_pile_pas_avant(
        self, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session, empreinte = cree_a(admin, personne)
        assert admin.execute(LIT, (empreinte, T0 + 5 * MIN - timedelta(seconds=1))).fetchone() == (
            personne,
            session,
            False,
        )
        assert admin.execute(LIT, (empreinte, T0 + 5 * MIN)).fetchone() == (personne, session, True)

    def test_lire_n_ecrit_rien(self, admin: psycopg.Connection[Ligne], personne: UUID) -> None:
        session, empreinte = cree_a(admin, personne)
        avant = admin.execute(
            "select last_seen_at, expires_at from public.login_session where id = %s", (session,)
        ).fetchone()
        admin.execute(LIT, (empreinte, T0 + 20 * MIN))
        apres = admin.execute(
            "select last_seen_at, expires_at from public.login_session where id = %s", (session,)
        ).fetchone()
        assert avant == apres

    def test_lire_ne_verrouille_pas_la_ligne(self, admin: psycopg.Connection[Ligne], personne: UUID) -> None:
        session, empreinte = cree_a(admin, personne)
        with connecte(DSN_API) as lecteur:
            lecteur.execute("select person_id from public.lit_la_session(%s)", (empreinte,))
            with psycopg.connect(admin.info.dsn, password=admin.info.password) as autre:
                autre.execute("set local lock_timeout = '300ms'")
                # La ligne se verrouille tout de suite : le lecteur, encore ouvert, n'en tient aucun.
                ligne = autre.execute(
                    "select id from public.login_session where id = %s for update nowait", (session,)
                ).fetchone()
                assert ligne == (session,)
            lecteur.rollback()

    @pytest.mark.parametrize(
        "etat",
        ["revoquee", "echue", "absolue_echue", "bannie", "supprimee", "inconnue"],
    )
    def test_une_session_qui_ne_vaut_plus_ne_rend_rien(
        self, etat: str, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session, empreinte = cree_a(admin, personne)
        lecture = T0 + MIN
        if etat == "revoquee":
            admin.execute("update public.login_session set revoked_at = %s where id = %s", (T0, session))
        elif etat == "echue":
            lecture = T0 + timedelta(days=31)
        elif etat == "absolue_echue":
            lecture = T0 + timedelta(days=91)
        elif etat == "bannie":
            admin.execute(
                "update auth.users set banned_until = %s where id = %s", (T0 + timedelta(days=1), personne)
            )
        elif etat == "supprimee":
            admin.execute("update auth.users set deleted_at = %s where id = %s", (T0, personne))
        else:
            empreinte = token_bytes(32)
        assert admin.execute(LIT, (empreinte, lecture)).fetchone() is None


class TestNoterLActivite:
    def test_une_session_vue_depuis_plus_de_cinq_minutes_est_repoussee(
        self, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session, empreinte = cree_a(admin, personne)
        quand = T0 + 6 * MIN
        assert admin.execute(NOTE, (empreinte, quand)).fetchone() == (True,)
        ligne = admin.execute(
            "select last_seen_at, expires_at from public.login_session where id = %s", (session,)
        ).fetchone()
        assert ligne == (quand, quand + timedelta(days=30))

    def test_l_echeance_ne_depasse_pas_l_absolue(
        self, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session, empreinte = cree_a(admin, personne)
        quand = T0 + timedelta(days=80)
        admin.execute(
            "update public.login_session set expires_at = %s where id = %s",
            (quand + timedelta(days=1), session),
        )
        admin.execute(NOTE, (empreinte, quand))
        ligne = admin.execute(
            "select expires_at from public.login_session where id = %s", (session,)
        ).fetchone()
        assert ligne == (T0 + timedelta(days=90),)

    def test_une_session_vue_il_y_a_moins_de_cinq_minutes_n_est_pas_touchee(
        self, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session, empreinte = cree_a(admin, personne)
        assert admin.execute(NOTE, (empreinte, T0 + 5 * MIN - timedelta(seconds=1))).fetchone() == (False,)
        ligne = admin.execute(
            "select last_seen_at from public.login_session where id = %s", (session,)
        ).fetchone()
        assert ligne == (T0,)

    @pytest.mark.parametrize(
        "etat", ["revoquee", "echue", "absolue_echue", "bannie", "supprimee", "inconnue"]
    )
    def test_une_session_qui_ne_vaut_plus_n_est_ni_rouverte_ni_repoussee(
        self, etat: str, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session, empreinte = cree_a(admin, personne)
        quand = T0 + 6 * MIN
        if etat == "revoquee":
            admin.execute("update public.login_session set revoked_at = %s where id = %s", (T0, session))
        elif etat == "echue":
            quand = T0 + timedelta(days=31)
        elif etat == "absolue_echue":
            quand = T0 + timedelta(days=91)
        elif etat == "bannie":
            admin.execute(
                "update auth.users set banned_until = %s where id = %s", (T0 + timedelta(days=1), personne)
            )
        elif etat == "supprimee":
            admin.execute("update auth.users set deleted_at = %s where id = %s", (T0, personne))
        else:
            empreinte = token_bytes(32)
        assert admin.execute(NOTE, (empreinte, quand)).fetchone() == (False,)
        ligne = admin.execute(
            "select last_seen_at from public.login_session where id = %s", (session,)
        ).fetchone()
        assert ligne == (T0,)

    async def test_l_ecriture_attend_la_personne_avant_la_ligne(
        self, base: Base, fabrique: Fabrique, admin: psycopg.Connection[Ligne], personne: UUID
    ) -> None:
        session = fabrique.session(personne, vue_il_y_a=PERIMEE)

        async def note() -> None:
            async with base.connexion() as curseur:
                await curseur.execute("select public.note_l_activite_de_la_session(%s)", (session.empreinte,))

        await course(admin, prend(personne), note, "note_l_activite_de_la_session")
        ligne = admin.execute(
            "select now() - last_seen_at < interval '1 minute' from public.login_session where id = %s",
            (session.id,),
        ).fetchone()
        assert ligne == (True,)
