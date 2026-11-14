"""0.4bis S8b : tables et fonctions de l'enregistrement d'une clé d'accès (migration 0153), en base locale.

Données inventées. Les fonctions publiques se jouent comme le fait l'API : en `popote_api`, sous le rôle
`authenticated` et l'identité de la personne (`en_tant_que`). Le temps est injecté par les variantes à
horloge de `private` (en administrateur). Les courses passent par `_course.py`.
"""

import asyncio
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from secrets import token_bytes
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_API, connecte
from _course import attend_un_verrou
from _fabrique import Fabrique, Personne
from psycopg import errors

pytestmark = pytest.mark.integration

Ligne = tuple[Any, ...]
T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
MIN = timedelta(minutes=1)
DIX_ANS = timedelta(days=3650)
IDENTIFIANT = "select public.mon_identifiant_webauthn(%s)"
DEFI = "select public.cree_un_defi(%s, %s, %s)"
CONSOMME = "select public.consomme_un_defi(%s, %s, %s)"
ENREGISTRE = (
    "select etat, id, created_at"
    " from public.enregistre_une_cle(%s, %s, %s, %s, %s::text[], %s, %s, %s, %s, %s, %s)"
)
DEFI_A = "select private.cree_un_defi(%s, %s, %s, %s, %s)"
CONSOMME_A = "select private.consomme_un_defi(%s, %s, %s, %s, %s)"
ENREGISTRE_A = (
    "select etat, id, created_at from private.enregistre_une_cle("
    "%s, %s, %s, %s, %s, %s::text[], %s, %s, %s, %s, %s, %s, %s)"
)


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


@pytest.fixture
def moi(fabrique: Fabrique, admin: psycopg.Connection[Ligne]) -> Iterator[Personne]:
    personne = fabrique.personne(fabrique.foyer())
    yield personne
    admin.execute("delete from public.security_event where person_id = %s", (personne.id,))


@contextmanager
def en_tant_que(personne: UUID) -> Iterator[psycopg.Cursor[Ligne]]:
    """Une transaction `popote_api` qui agit comme la personne (rôle `authenticated`), validée en sortie."""
    with connecte(DSN_API) as cx:
        curseur = cx.cursor()
        curseur.execute("set local role authenticated")
        curseur.execute(
            "select set_config('request.jwt.claims', %s, true)",
            (f'{{"sub": "{personne}", "role": "authenticated"}}',),
        )
        yield curseur
        cx.commit()


def un(curseur: psycopg.Cursor[Ligne]) -> Ligne:
    ligne = curseur.fetchone()
    assert ligne is not None
    return ligne


def identifiant_de(personne: UUID) -> bytes:
    with en_tant_que(personne) as curseur:
        curseur.execute(IDENTIFIANT, (token_bytes(64),))
        return bytes(un(curseur)[0])


def a_l_etat(
    admin: psycopg.Connection[Ligne], personne: UUID, session: UUID, defi: bytes, maintenant: datetime
) -> str:
    identifiant_de(personne)
    ligne = admin.execute(DEFI_A, (personne, session, "registration", defi, maintenant)).fetchone()
    assert ligne is not None
    return str(ligne[0])


def cle_a(
    admin: psycopg.Connection[Ligne],
    personne: UUID,
    session: UUID,
    maintenant: datetime,
    *,
    identifiant: bytes | None = None,
    transports: list[str] | None = None,
    be: bool = False,
    bs: bool = False,
    nom: str = "Clé",
    requete: str | None = None,
) -> Ligne:
    """`private.enregistre_une_cle` : l'horloge est donnée. Rend (etat, id, created_at)."""
    ligne = admin.execute(
        ENREGISTRE_A,
        (
            personne, session, identifiant or token_bytes(32), b"\x01" * 77, 0, transports or [], be, bs,
            True, uuid4(), nom, requete, maintenant,
        ),
    ).fetchone()  # fmt: skip
    assert ligne is not None
    return ligne


def sessions_fraiches(fabrique: Fabrique, personne: UUID) -> UUID:
    """Une session ouverte, valable encore en 2031 (l'horloge des variantes de `private` y est posée)."""
    return fabrique.session(personne, echeance_dans=DIX_ANS, absolue_dans=DIX_ANS).id


def nombre(admin: psycopg.Connection[Ligne], requete: str, *valeurs: object) -> int:
    ligne = admin.execute(requete, valeurs).fetchone()
    assert ligne is not None
    return int(ligne[0])


# ── L'identifiant d'utilisateur ─────────────────────────────────────────────


class TestIdentifiantWebauthn:
    def test_il_fait_64_octets_et_reste_le_meme_pour_une_personne(self, moi: Personne) -> None:
        premier = identifiant_de(moi.id)
        assert len(premier) == 64
        assert identifiant_de(moi.id) == premier  # le candidat suivant est ignoré : la ligne existe déjà

    def test_deux_personnes_ont_deux_identifiants(self, fabrique: Fabrique, moi: Personne) -> None:
        autre = fabrique.personne(fabrique.foyer())
        assert identifiant_de(moi.id) != identifiant_de(autre.id)

    @pytest.mark.parametrize("candidat", [None, b"", token_bytes(63), token_bytes(65)])
    def test_un_candidat_qui_n_a_pas_64_octets_est_refuse(
        self, moi: Personne, candidat: bytes | None
    ) -> None:
        with pytest.raises(errors.InvalidParameterValue), en_tant_que(moi.id) as curseur:
            curseur.execute(IDENTIFIANT, (candidat,))

    def test_sans_personne_dans_le_contexte_la_fonction_refuse(self) -> None:
        with connecte(DSN_API) as cx:
            cx.execute("set local role authenticated")
            with pytest.raises(errors.InvalidAuthorizationSpecification):
                cx.execute(IDENTIFIANT, (token_bytes(64),))

    def test_la_fonction_prend_le_verrou_de_la_personne(
        self, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        async def b() -> bytes:
            return await asyncio.to_thread(identifiant_de, moi.id)

        async def jeu() -> bytes:
            with connecte(DSN_API) as a:
                a.execute("select public.verrouille_la_personne(%s)", (moi.id,))
                tache = asyncio.create_task(b())
                try:
                    await attend_un_verrou(admin, "mon_identifiant_webauthn", a.info.backend_pid)
                finally:
                    a.commit()
                return await tache

        assert len(asyncio.run(jeu())) == 64

    def test_deux_premieres_demandes_en_parallele_rendent_le_meme_identifiant(
        self, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        barriere = threading.Barrier(8)

        def appel() -> bytes:
            barriere.wait()
            return identifiant_de(moi.id)

        with ThreadPoolExecutor(8) as pool:
            rendus = {f.result() for f in [pool.submit(appel) for _ in range(8)]}
        assert len(rendus) == 1
        assert nombre(admin, "select count(*) from public.webauthn_user where person_id = %s", moi.id) == 1


# ── Le défi ─────────────────────────────────────────────────────────────────


class TestDefi:
    def test_un_defi_se_cree_pour_la_personne_et_la_session(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        defi = token_bytes(32)
        assert a_l_etat(admin, moi.id, session, defi, T0) == "creee"
        ligne = admin.execute(
            "select purpose, person_id, session_id, created_at, expires_at from public.webauthn_challenge"
            " where challenge = %s",
            (defi,),
        ).fetchone()
        assert ligne == ("registration", moi.id, session, T0, T0 + 10 * MIN)

    def test_une_session_fermee_perimee_ou_d_une_autre_personne_est_refusee(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        autre = fabrique.personne(fabrique.foyer())
        maintenant = datetime.now(tz=T0.tzinfo)
        refusees = {
            "fermee": fabrique.session(moi.id, revoquee=True).id,
            "echue": fabrique.session(moi.id, echeance_dans=timedelta(seconds=-1)).id,
            "d-une-autre-personne": fabrique.session(autre.id).id,
            "inconnue": uuid4(),
        }
        for nom, session in refusees.items():
            assert a_l_etat(admin, moi.id, session, token_bytes(32), maintenant) == "session_perimee", nom
        assert (
            nombre(admin, "select count(*) from public.webauthn_challenge where person_id = %s", moi.id) == 0
        )

    def test_une_personne_bannie_est_refusee(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        admin.execute(
            "update auth.users set banned_until = now() + interval '1 day' where id = %s", (moi.id,)
        )
        assert (
            a_l_etat(admin, moi.id, session, token_bytes(32), datetime.now(tz=T0.tzinfo)) == "session_perimee"
        )

    def test_dix_cles_ferment_la_porte_des_la_demande_du_defi(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        maintenant = datetime.now(tz=T0.tzinfo)
        identifiant_de(moi.id)
        for _ in range(10):
            assert cle_a(admin, moi.id, session, maintenant)[0] == "creee"
        assert a_l_etat(admin, moi.id, session, token_bytes(32), maintenant) == "trop_de_cles"

    @pytest.mark.parametrize("defi", [None, token_bytes(31), token_bytes(33)])
    def test_un_defi_qui_n_a_pas_32_octets_est_refuse(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne], defi: bytes | None
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        with pytest.raises(errors.InvalidParameterValue):
            admin.execute(DEFI_A, (moi.id, session, "registration", defi, T0))

    def test_un_but_inconnu_est_refuse(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        with pytest.raises(errors.InvalidParameterValue):
            admin.execute(DEFI_A, (moi.id, session, "autre", token_bytes(32), T0))

    def test_le_defi_ne_se_consomme_qu_une_fois_et_rend_les_memes_octets(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        defi = token_bytes(32)
        a_l_etat(admin, moi.id, session, defi, T0)
        premiere = admin.execute(CONSOMME_A, (moi.id, session, "registration", defi, T0 + MIN)).fetchone()
        seconde = admin.execute(CONSOMME_A, (moi.id, session, "registration", defi, T0 + MIN)).fetchone()
        assert premiere is not None and seconde is not None
        assert (bytes(premiere[0]), seconde[0]) == (defi, None)

    def test_dix_minutes_exactement_le_defi_est_echu_et_une_seconde_avant_il_vit(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        a_temps, a_la_limite = token_bytes(32), token_bytes(32)
        a_l_etat(admin, moi.id, session, a_temps, T0)
        a_l_etat(admin, moi.id, session, a_la_limite, T0)
        vit = admin.execute(
            CONSOMME_A, (moi.id, session, "registration", a_temps, T0 + 10 * MIN - timedelta(seconds=1))
        ).fetchone()
        echu = admin.execute(
            CONSOMME_A, (moi.id, session, "registration", a_la_limite, T0 + 10 * MIN)
        ).fetchone()
        assert vit is not None and echu is not None
        assert (bytes(vit[0]), echu[0]) == (a_temps, None)

    def test_le_defi_d_un_autre_but_d_une_autre_personne_ou_d_une_autre_session_ne_sort_pas_et_reste(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        autre = fabrique.personne(fabrique.foyer())
        session, seconde = sessions_fraiches(fabrique, moi.id), sessions_fraiches(fabrique, moi.id)
        defi = token_bytes(32)
        a_l_etat(admin, moi.id, session, defi, T0)
        refus = [
            (moi.id, session, "authentication"),
            (autre.id, session, "registration"),
            (moi.id, seconde, "registration"),
        ]
        for personne, s, but in refus:
            ligne = admin.execute(CONSOMME_A, (personne, s, but, defi, T0 + MIN)).fetchone()
            assert ligne == (None,), (personne, s, but)
        assert nombre(admin, "select count(*) from public.webauthn_challenge where challenge = %s", defi) == 1

    def test_deux_consommations_en_parallele_n_en_rendent_qu_une(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        defi = token_bytes(32)
        a_l_etat(admin, moi.id, session, defi, datetime.now(tz=T0.tzinfo))
        barriere = threading.Barrier(6)

        def appel() -> bytes | None:
            barriere.wait()
            with en_tant_que(moi.id) as curseur:
                curseur.execute(CONSOMME, (session, "registration", defi))
                rendu = un(curseur)[0]
                return None if rendu is None else bytes(rendu)

        with ThreadPoolExecutor(6) as pool:
            rendus = [f.result() for f in [pool.submit(appel) for _ in range(6)]]
        assert sorted(r is None for r in rendus) == [False] + [True] * 5


# ── L'enregistrement ────────────────────────────────────────────────────────


class TestEnregistrementEnBase:
    def test_la_cle_s_ecrit_avec_son_evenement(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        identifiant_de(moi.id)
        requete = uuid4().hex
        admin.execute("update public.login_session set reauth_at = %s where id = %s", (T0 - 3 * MIN, session))
        etat, id_, cree = cle_a(
            admin, moi.id, session, T0 - 2 * MIN, transports=["usb"], be=True, bs=True, requete=requete
        )
        assert (etat, cree) == ("creee", T0 - 2 * MIN)
        ligne = admin.execute(
            "select person_id, transports, backup_eligible, backup_state, name"
            " from public.webauthn_credential where id = %s",
            (id_,),
        ).fetchone()
        assert ligne == (moi.id, ["usb"], True, True, "Clé")
        evenement = admin.execute(
            "select person_id, session_id, request_id from public.security_event"
            " where kind = 'cle_ajoutee' and person_id = %s",
            (moi.id,),
        ).fetchone()
        assert evenement == (moi.id, session, requete)

    def test_la_preuve_de_300_secondes_passe_et_celle_de_301_est_refusee(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        identifiant_de(moi.id)
        admin.execute("update public.login_session set reauth_at = %s where id = %s", (T0, session))
        passe = cle_a(admin, moi.id, session, T0 + timedelta(seconds=300))
        refusee = cle_a(admin, moi.id, session, T0 + timedelta(seconds=301))
        assert (passe[0], refusee[0]) == ("creee", "preuve_perimee")
        assert (
            nombre(admin, "select count(*) from public.webauthn_credential where person_id = %s", moi.id) == 1
        )

    def test_une_session_perimee_n_ecrit_rien(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        identifiant_de(moi.id)
        autre = fabrique.personne(fabrique.foyer())
        maintenant = datetime.now(tz=T0.tzinfo)
        sessions = [
            fabrique.session(moi.id, revoquee=True).id,
            fabrique.session(moi.id, echeance_dans=timedelta(seconds=-1)).id,
            fabrique.session(autre.id).id,
            uuid4(),
        ]
        assert [cle_a(admin, moi.id, s, maintenant)[0] for s in sessions] == ["session_perimee"] * 4
        assert (
            nombre(admin, "select count(*) from public.webauthn_credential where person_id = %s", moi.id) == 0
        )
        assert (
            nombre(
                admin,
                "select count(*) from public.security_event where kind = 'cle_ajoutee' and person_id = %s",
                moi.id,
            )
            == 0
        )

    def test_une_personne_bannie_n_enregistre_rien(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        identifiant_de(moi.id)
        admin.execute(
            "update auth.users set banned_until = now() + interval '1 day' where id = %s", (moi.id,)
        )
        assert cle_a(admin, moi.id, session, datetime.now(tz=T0.tzinfo))[0] == "session_perimee"

    def test_la_onzieme_cle_est_refusee_et_les_dix_premieres_passent(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        identifiant_de(moi.id)
        maintenant = datetime.now(tz=T0.tzinfo)
        etats = [cle_a(admin, moi.id, session, maintenant)[0] for _ in range(11)]
        assert etats == ["creee"] * 10 + ["trop_de_cles"]

    def test_un_identifiant_de_cle_se_prend_une_fois_pour_tout_le_monde(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        autre = fabrique.personne(fabrique.foyer())
        identifiant_de(moi.id)
        identifiant_de(autre.id)
        maintenant = datetime.now(tz=T0.tzinfo)
        pris = token_bytes(32)
        assert (
            cle_a(admin, moi.id, sessions_fraiches(fabrique, moi.id), maintenant, identifiant=pris)[0]
            == "creee"
        )
        for personne in (moi.id, autre.id):
            ligne = cle_a(
                admin, personne, sessions_fraiches(fabrique, personne), maintenant, identifiant=pris
            )
            assert ligne[0] == "cle_deja_enregistree"

    def test_quinze_enregistrements_en_parallele_en_laissent_exactement_dix(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        identifiant_de(moi.id)
        barriere = threading.Barrier(15)

        def appel() -> str:
            barriere.wait()
            with en_tant_que(moi.id) as curseur:
                curseur.execute(
                    ENREGISTRE,
                    (session, token_bytes(32), b"\x01" * 77, 0, [], False, False, True, uuid4(), "Clé", None),
                )
                return str(un(curseur)[0])

        with ThreadPoolExecutor(15) as pool:
            etats = sorted(f.result() for f in [pool.submit(appel) for _ in range(15)])
        assert etats == ["creee"] * 10 + ["trop_de_cles"] * 5
        assert (
            nombre(admin, "select count(*) from public.webauthn_credential where person_id = %s", moi.id)
            == 10
        )

    @pytest.mark.parametrize(
        ("colonne", "valeur"),
        [
            ("transports", ["bluetooth"]),
            ("credential_id", token_bytes(15)),
            ("credential_id", token_bytes(1024)),
            ("public_key", b""),
            ("sign_count", -1),
            ("sign_count", 4294967296),
            ("name", ""),
            ("name", "x" * 41),
        ],
    )
    def test_les_contraintes_de_la_table_refusent_une_valeur_hors_borne(
        self, moi: Personne, admin: psycopg.Connection[Ligne], colonne: str, valeur: object
    ) -> None:
        identifiant_de(moi.id)
        valeurs: dict[str, object] = {
            "person_id": moi.id, "credential_id": token_bytes(32), "public_key": b"\x01", "sign_count": 0,
            "transports": [], "backup_eligible": False, "backup_state": False, "uv_initialized": True,
            "aaguid": uuid4(), "name": "Clé",
        }  # fmt: skip
        valeurs[colonne] = valeur
        noms = ", ".join(valeurs)
        marques = ", ".join("%s::text[]" if n == "transports" else "%s" for n in valeurs)
        with pytest.raises(errors.CheckViolation):
            admin.execute(
                f"insert into public.webauthn_credential ({noms}) values ({marques})",  # noqa: S608
                list(valeurs.values()),
            )

    def test_une_sauvegarde_sans_eligibilite_est_refusee_par_la_table(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        identifiant_de(moi.id)
        with pytest.raises(errors.CheckViolation):
            cle_a(admin, moi.id, session, datetime.now(tz=T0.tzinfo), be=False, bs=True)

    def test_la_fonction_publique_relit_la_session_sous_le_verrou_apres_une_fermeture_en_cours(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        """A ferme les autres sessions sous son verrou ; B enregistre avec la session fermée : refusée."""
        identifiant_de(moi.id)
        a_fermer, gardee = sessions_fraiches(fabrique, moi.id), sessions_fraiches(fabrique, moi.id)

        def b() -> str:
            with en_tant_que(moi.id) as curseur:
                curseur.execute(
                    ENREGISTRE,
                    (
                        a_fermer,
                        token_bytes(32),
                        b"\x01" * 77,
                        0,
                        [],
                        False,
                        False,
                        True,
                        uuid4(),
                        "Clé",
                        None,
                    ),
                )
                return str(un(curseur)[0])

        async def jeu() -> str:
            with connecte(DSN_API) as a:
                a.execute(
                    "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (moi.id, gardee)
                )
                tache = asyncio.create_task(asyncio.to_thread(b))
                try:
                    await attend_un_verrou(admin, "enregistre_une_cle", a.info.backend_pid)
                except BaseException:
                    tache.cancel()
                    a.rollback()
                    await asyncio.gather(tache, return_exceptions=True)
                    raise
                a.commit()
                return await tache

        assert asyncio.run(jeu()) == "session_perimee"
        assert (
            nombre(admin, "select count(*) from public.webauthn_credential where person_id = %s", moi.id) == 0
        )

    def test_la_requete_de_l_evenement_doit_avoir_la_forme_attendue(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        identifiant_de(moi.id)
        with pytest.raises(errors.InvalidParameterValue):
            cle_a(admin, moi.id, session, datetime.now(tz=T0.tzinfo), requete="pas-un-identifiant")


# ── Les clés à exclure, la suppression en cascade et la purge ───────────────


class TestAutour:
    def test_les_identifiants_a_exclure_sont_ceux_de_la_personne_du_contexte_seulement(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        autre = fabrique.personne(fabrique.foyer())
        identifiant_de(moi.id)
        identifiant_de(autre.id)
        maintenant = datetime.now(tz=T0.tzinfo)
        a_moi = token_bytes(32)
        cle_a(
            admin,
            moi.id,
            sessions_fraiches(fabrique, moi.id),
            maintenant,
            identifiant=a_moi,
            transports=["usb"],
        )
        cle_a(admin, autre.id, sessions_fraiches(fabrique, autre.id), maintenant)
        with en_tant_que(moi.id) as curseur:
            curseur.execute("select identifiant, transports from public.mes_identifiants_de_cle()")
            lignes = curseur.fetchall()
        assert [(bytes(i), t) for i, t in lignes] == [(a_moi, ["usb"])]

    def test_supprimer_la_personne_emporte_ses_cles_ses_defis_et_son_identifiant(
        self, fabrique: Fabrique, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne = fabrique.personne(fabrique.foyer())
        session = sessions_fraiches(fabrique, personne.id)
        a_l_etat(admin, personne.id, session, token_bytes(32), datetime.now(tz=T0.tzinfo))
        cle_a(admin, personne.id, session, datetime.now(tz=T0.tzinfo))
        admin.execute("delete from auth.users where id = %s", (personne.id,))
        for table in ("webauthn_user", "webauthn_credential", "webauthn_challenge"):
            assert (
                nombre(admin, f"select count(*) from public.{table} where person_id = %s", personne.id) == 0  # noqa: S608
            )

    def test_la_purge_efface_les_defis_echus_depuis_plus_d_un_jour_et_se_fait_par_lots(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        vieux = [token_bytes(32) for _ in range(5)]
        recent = token_bytes(32)
        for defi in (*vieux, recent):
            a_l_etat(admin, moi.id, session, defi, T0)
        # Les cinq premiers sont échus depuis plus d'un jour (T0 + 10 min + 1 jour), le dernier depuis moins.
        maintenant = T0 + 10 * MIN + timedelta(days=1, seconds=1)
        admin.execute(
            "update public.webauthn_challenge set created_at = %s, expires_at = %s where challenge = %s",
            (maintenant - 20 * MIN, maintenant - 10 * MIN, recent),
        )
        ligne = admin.execute("select private.purge_webauthn_challenge(%s, 2)", (maintenant,)).fetchone()
        assert ligne == (5,)
        assert admin.execute("select private.purge_webauthn_challenge(%s, 2)", (maintenant,)).fetchone() == (
            0,
        )
        assert (
            nombre(admin, "select count(*) from public.webauthn_challenge where person_id = %s", moi.id) == 1
        )
        with pytest.raises(errors.InvalidParameterValue):
            admin.execute("select private.purge_webauthn_challenge(%s, 0)", (maintenant,))

    def test_les_identifiants_du_defi_sont_uniques(
        self, fabrique: Fabrique, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        session = sessions_fraiches(fabrique, moi.id)
        defi = token_bytes(32)
        a_l_etat(admin, moi.id, session, defi, T0)
        with pytest.raises(errors.UniqueViolation):
            admin.execute(DEFI_A, (moi.id, session, "registration", defi, T0))
