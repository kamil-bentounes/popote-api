"""0.4bis S9a : la connexion par clé d'accès côté base (migration 0154), en base locale.

Données inventées. Les variantes à horloge de `private` (administrateur) donnent le temps ; les fonctions
publiques se jouent en `popote_api`, comme l'API. Les courses passent par `_course.py`.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
from secrets import token_bytes
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_API, connecte
from _fabrique import Fabrique, Personne
from psycopg import errors

pytestmark = pytest.mark.integration

Ligne = tuple[Any, ...]
T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
MIN = timedelta(minutes=1)
CREE = "select private.cree_un_defi_anonyme(%s, %s, %s)"
CONSOMME = "select private.consomme_un_defi_anonyme(%s, %s)"
LIT = (
    "select personne, cle, compteur, cle_publique, peut_etre_sauvegardee, identifiant_utilisateur"
    " from private.cle_pour_connexion(%s, %s, %s)"
)
OUVRE = (
    "select session, personne"
    " from private.ouvre_une_session_par_cle(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


@pytest.fixture
def moi(fabrique: Fabrique, admin: psycopg.Connection[Ligne]) -> Iterator[Personne]:
    personne = fabrique.personne(fabrique.foyer())
    yield personne
    admin.execute("delete from public.security_event where person_id = %s", (personne.id,))


@pytest.fixture
def defis(admin: psycopg.Connection[Ligne]) -> Iterator[list[bytes]]:
    """Les défis posés par un test : retirés à la fin, avec tout défi de connexion que le test a laissé."""
    posees: list[bytes] = []
    yield posees
    admin.execute("delete from public.webauthn_challenge where challenge = any(%s)", (posees,))


def defi_neuf(defis: list[bytes]) -> bytes:
    defi = token_bytes(32)
    defis.append(defi)
    return defi


def un(curseur: psycopg.Cursor[Ligne]) -> Ligne:
    ligne = curseur.fetchone()
    assert ligne is not None
    return ligne


def pose_une_cle(
    admin: psycopg.Connection[Ligne], personne: UUID, *, compteur: int = 0, be: bool = False, bs: bool = False
) -> tuple[UUID, bytes, bytes]:
    """Une clé enregistrée en direct : (id de la ligne, identifiant de clé, identifiant d'utilisateur)."""
    poignee = token_bytes(64)
    admin.execute(
        "insert into public.webauthn_user (person_id, user_handle) values (%s, %s)"
        " on conflict (person_id) do nothing",
        (personne, poignee),
    )
    ligne = admin.execute(
        "select user_handle from public.webauthn_user where person_id = %s", (personne,)
    ).fetchone()
    assert ligne is not None
    identifiant = token_bytes(32)
    cle = admin.execute(
        "insert into public.webauthn_credential"
        " (person_id, credential_id, public_key, sign_count, backup_eligible, backup_state, "
        "uv_initialized, aaguid, name)"
        " values (%s, %s, %s, %s, %s, %s, false, %s, 'Clé') returning id",
        (personne, identifiant, b"\x01" * 77, compteur, be, bs, uuid4()),
    ).fetchone()
    assert cle is not None
    return cle[0], identifiant, bytes(ligne[0])


def ouvre(
    admin: psycopg.Connection[Ligne],
    cle: UUID,
    *,
    ancien: int = 0,
    nouveau: int = 1,
    bs: bool = False,
    uv: bool = True,
    maintenant: datetime = T0,
    vieux_jeton: bytes | None = None,
) -> Ligne | None:
    return admin.execute(
        OUVRE,
        (cle, ancien, nouveau, bs, uv, token_bytes(32), "chrome", "linux", vieux_jeton, maintenant, None),
    ).fetchone()


def sessions(admin: psycopg.Connection[Ligne], personne: UUID) -> list[Ligne]:
    return admin.execute(
        "select opened_with, opened_with_credential from public.login_session"
        " where person_id = %s and revoked_at is null order by created_at",
        (personne,),
    ).fetchall()


class TestDefisAnonymes:
    def test_un_defi_cree_se_consomme_une_seule_fois(
        self, admin: psycopg.Connection[Ligne], defis: list[bytes]
    ) -> None:
        defi = defi_neuf(defis)
        assert un(admin.execute(CREE, (defi, 5000, T0)))[0] == "creee"
        assert bytes(un(admin.execute(CONSOMME, (defi, T0 + MIN)))[0]) == defi
        assert un(admin.execute(CONSOMME, (defi, T0 + MIN)))[0] is None

    def test_un_defi_echu_n_est_ni_rendu_ni_brule(
        self, admin: psycopg.Connection[Ligne], defis: list[bytes]
    ) -> None:
        defi = defi_neuf(defis)
        admin.execute(CREE, (defi, 5000, T0))
        assert un(admin.execute(CONSOMME, (defi, T0 + 10 * MIN)))[0] is None  # à l'échéance exacte : échu
        assert un(admin.execute(CONSOMME, (defi, T0 + 10 * MIN - timedelta(seconds=1))))[0] is not None

    def test_un_defi_d_enregistrement_ne_se_consomme_pas_comme_un_defi_de_connexion(
        self, admin: psycopg.Connection[Ligne], moi: Personne, fabrique: Fabrique, defis: list[bytes]
    ) -> None:
        defi = defi_neuf(defis)
        session = fabrique.session(moi.id).id
        pose_une_cle(admin, moi.id)
        admin.execute(
            "insert into public.webauthn_challenge (challenge, purpose, person_id, session_id)"
            " values (%s, 'registration', %s, %s)",
            (defi, moi.id, session),
        )
        assert un(admin.execute(CONSOMME, (defi, T0)))[0] is None
        admin.execute(
            "update public.webauthn_challenge set expires_at = now() + interval '5 minutes' where "
            "challenge = %s",
            (defi,),
        )
        assert un(admin.execute(CONSOMME, (defi, datetime.now(T0.tzinfo))))[0] is None
        assert (
            un(admin.execute("select count(*) from public.webauthn_challenge where challenge = %s", (defi,)))[
                0
            ]
            == 1
        )

    @pytest.mark.parametrize("taille", [0, 5, 31, 33, 4096])
    def test_un_defi_de_mauvaise_taille_ne_se_consomme_pas_et_ne_leve_pas(
        self, admin: psycopg.Connection[Ligne], taille: int
    ) -> None:
        assert un(admin.execute(CONSOMME, (token_bytes(taille), T0)))[0] is None

    def test_un_defi_de_mauvaise_taille_ne_se_cree_pas(self, admin: psycopg.Connection[Ligne]) -> None:
        with pytest.raises(errors.InvalidParameterValue):
            admin.execute(CREE, (token_bytes(31), 5000, T0))

    def test_le_plafond_des_defis_vivants_refuse_le_suivant_et_les_echus_ne_comptent_pas(
        self, admin: psycopg.Connection[Ligne], defis: list[bytes]
    ) -> None:
        vivants = un(admin.execute(
            "select count(*) from public.webauthn_challenge where purpose = 'authentication' and "
            "expires_at > %s",
            (T0,),
        ))[0]  # fmt: skip
        plafond = vivants + 2
        assert [un(admin.execute(CREE, (defi_neuf(defis), plafond, T0)))[0] for _ in range(3)] == [
            "creee", "creee", "trop_de_defis",
        ]  # fmt: skip
        # Onze minutes plus tard, les deux premiers sont échus : ils ne comptent plus.
        assert un(admin.execute(CREE, (defi_neuf(defis), plafond, T0 + 11 * MIN)))[0] == "creee"

    @pytest.mark.parametrize("plafond", [0, -1, 1_000_001])
    def test_un_plafond_hors_bornes_leve(self, admin: psycopg.Connection[Ligne], plafond: int) -> None:
        with pytest.raises(errors.InvalidParameterValue):
            admin.execute(CREE, (token_bytes(32), plafond, T0))

    def test_la_base_refuse_un_defi_de_connexion_avec_personne_et_un_defi_d_enregistrement_sans(
        self, admin: psycopg.Connection[Ligne], moi: Personne, defis: list[bytes]
    ) -> None:
        with pytest.raises(errors.CheckViolation):
            admin.execute(
                "insert into public.webauthn_challenge (challenge, purpose, person_id) values (%s, "
                "'authentication', %s)",
                (defi_neuf(defis), moi.id),
            )
        with pytest.raises(errors.CheckViolation):
            admin.execute(
                "insert into public.webauthn_challenge (challenge, purpose) values (%s, 'registration')",
                (defi_neuf(defis),),
            )

    def test_la_purge_n_efface_que_les_defis_de_connexion_echus(
        self, admin: psycopg.Connection[Ligne], defis: list[bytes]
    ) -> None:
        echu, vivant = defi_neuf(defis), defi_neuf(defis)
        admin.execute(CREE, (echu, 5000, T0))
        admin.execute(CREE, (vivant, 5000, T0 + 9 * MIN))
        admin.execute("select private.purge_defis_anonymes(%s)", (T0 + 11 * MIN,))
        restants = {
            bytes(ligne[0])
            for ligne in admin.execute("select challenge from public.webauthn_challenge").fetchall()
        }
        assert echu not in restants
        assert vivant in restants


class TestCreneauxDeCle:
    @pytest.fixture
    def cle_ip(self, admin: psycopg.Connection[Ligne]) -> Iterator[bytes]:
        cle = token_bytes(32)
        yield cle
        admin.execute("delete from public.login_throttle where key = %s", (cle,))

    def test_une_limite_inconnue_leve(self, admin: psycopg.Connection[Ligne], cle_ip: bytes) -> None:
        with pytest.raises(errors.InvalidParameterValue):
            admin.execute("select * from public.prend_un_creneau_de_cle('ip', %s, 2, 900, 3600)", (cle_ip,))

    def test_les_verifications_escaladent_puis_le_blocage_ne_compte_qu_une_fois(
        self, admin: psycopg.Connection[Ligne], cle_ip: bytes
    ) -> None:
        requete = (
            "select attente_s, nouveau_blocage"
            " from public.prend_un_creneau_de_cle('cle_ip', %s, 2, 900, 3600)"
        )
        assert [tuple(un(admin.execute(requete, (cle_ip,)))) for _ in range(2)] == [(0, False), (0, False)]
        assert tuple(un(admin.execute(requete, (cle_ip,)))) == (900, True)
        attente, nouveau = un(admin.execute(requete, (cle_ip,)))
        assert 0 < attente <= 900
        assert nouveau is False

    def test_les_defis_ne_font_qu_attendre_la_fin_de_la_fenetre(
        self, admin: psycopg.Connection[Ligne], cle_ip: bytes
    ) -> None:
        requete = (
            "select attente_s, nouveau_blocage"
            " from public.prend_un_creneau_de_cle('cle_defi_ip', %s, 2, 900, 3600)"
        )
        for _ in range(2):
            admin.execute(requete, (cle_ip,))
        attente, nouveau = un(admin.execute(requete, (cle_ip,)))
        assert 0 < attente <= 900
        assert nouveau is False
        ligne = un(
            admin.execute(
                "select strikes, blocked_until from public.login_throttle where scope = 'cle_defi_ip' "
                "and key = %s",
                (cle_ip,),
            )
        )
        assert tuple(ligne) == (0, None)

    def test_les_deux_limites_sont_independantes(
        self, admin: psycopg.Connection[Ligne], cle_ip: bytes
    ) -> None:
        for _ in range(3):
            admin.execute(
                "select * from public.prend_un_creneau_de_cle('cle_defi_ip', %s, 2, 900, 3600)", (cle_ip,)
            )
        assert (
            un(
                admin.execute(
                    "select attente_s from public.prend_un_creneau_de_cle('cle_ip', %s, 2, 900, 3600)",
                    (cle_ip,),
                )
            )[0]
            == 0
        )


class TestCleDeLaConnexion:
    def test_la_cle_se_lit_par_son_identifiant_avec_sa_personne_et_son_identifiant_d_utilisateur(
        self, admin: psycopg.Connection[Ligne], moi: Personne
    ) -> None:
        cle, identifiant, poignee = pose_une_cle(admin, moi.id, compteur=7, be=True)
        ligne = un(admin.execute(LIT, (identifiant, None, T0)))
        assert (ligne[0], ligne[1], ligne[2], ligne[4], bytes(ligne[5])) == (moi.id, cle, 7, True, poignee)

    def test_une_cle_inconnue_ne_rend_rien(self, admin: psycopg.Connection[Ligne]) -> None:
        assert admin.execute(LIT, (token_bytes(32), None, T0)).fetchall() == []

    @pytest.mark.parametrize("taille", [0, 15, 1024])
    def test_un_identifiant_de_taille_inadmise_leve(
        self, admin: psycopg.Connection[Ligne], taille: int
    ) -> None:
        with pytest.raises(errors.InvalidParameterValue):
            admin.execute(LIT, (token_bytes(taille), None, T0))

    @pytest.mark.parametrize("etat", ["bannie", "supprimee", "sans_profil"])
    def test_une_personne_qui_ne_peut_pas_entrer_ne_rend_rien(
        self, admin: psycopg.Connection[Ligne], moi: Personne, etat: str
    ) -> None:
        _, identifiant, _ = pose_une_cle(admin, moi.id)
        match etat:
            case "bannie":
                admin.execute(
                    "update auth.users set banned_until = now() + interval '1 day' where id = %s", (moi.id,)
                )
            case "supprimee":
                admin.execute("update auth.users set deleted_at = now() where id = %s", (moi.id,))
            case "sans_profil":
                admin.execute("delete from public.user_profile where id = %s", (moi.id,))
        assert admin.execute(LIT, (identifiant, None, T0)).fetchall() == []


class TestSessionDeLaCle:
    def test_la_session_nait_par_cle_avec_la_cle_et_met_la_cle_a_jour(
        self, admin: psycopg.Connection[Ligne], moi: Personne
    ) -> None:
        cle, _, _ = pose_une_cle(admin, moi.id, compteur=3, be=True)
        ligne = ouvre(admin, cle, ancien=3, nouveau=4, bs=True)
        assert ligne is not None
        assert ligne[1] == moi.id
        assert sessions(admin, moi.id) == [("cle", cle)]
        assert tuple(un(admin.execute(
            "select sign_count, backup_state, uv_initialized, last_used_at from "
            "public.webauthn_credential where id = %s",
            (cle,),
        ))) == (4, True, True, T0)  # fmt: skip
        assert un(admin.execute(
            "select count(*) from public.security_event"
            " where person_id = %s and kind = 'connexion_par_cle'",
            (moi.id,),
        ))[0] == 1  # fmt: skip

    @pytest.mark.parametrize(
        ("compteur_de_la_cle", "ancien", "nouveau"),
        [
            pytest.param(5, 5, 5, id="egal"),
            pytest.param(5, 5, 4, id="regression"),
            pytest.param(0, 0, 4294967296, id="hors_bornes"),
            pytest.param(5, 4, 9, id="compteur_change_depuis_la_lecture"),
        ],
    )
    def test_un_compteur_qui_ne_croit_pas_ou_qui_a_change_ouvre_rien(
        self,
        admin: psycopg.Connection[Ligne],
        moi: Personne,
        compteur_de_la_cle: int,
        ancien: int,
        nouveau: int,
    ) -> None:
        cle, _, _ = pose_une_cle(admin, moi.id, compteur=compteur_de_la_cle)
        if nouveau >= 2**32:
            with pytest.raises(errors.InvalidParameterValue):
                ouvre(admin, cle, ancien=ancien, nouveau=nouveau)
        else:
            assert ouvre(admin, cle, ancien=ancien, nouveau=nouveau) is None
        assert sessions(admin, moi.id) == []
        assert (
            un(admin.execute("select sign_count from public.webauthn_credential where id = %s", (cle,)))[0]
            == compteur_de_la_cle
        )

    def test_deux_zeros_sont_acceptes_et_zero_apres_un_compteur_positif_ne_l_est_pas(
        self, admin: psycopg.Connection[Ligne], moi: Personne
    ) -> None:
        synchronisee, _, _ = pose_une_cle(admin, moi.id, compteur=0)
        assert ouvre(admin, synchronisee, ancien=0, nouveau=0) is not None
        comptee, _, _ = pose_une_cle(admin, moi.id, compteur=2)
        assert ouvre(admin, comptee, ancien=2, nouveau=0) is None

    def test_un_etat_de_sauvegarde_sans_eligibilite_est_refuse(
        self, admin: psycopg.Connection[Ligne], moi: Personne
    ) -> None:
        cle, _, _ = pose_une_cle(admin, moi.id, be=False)
        assert ouvre(admin, cle, bs=True) is None
        assert sessions(admin, moi.id) == []

    @pytest.mark.parametrize("etat", ["bannie", "supprimee", "sans_profil", "cle_disparue"])
    def test_une_personne_qui_ne_peut_plus_entrer_ou_une_cle_disparue_n_ouvre_rien(
        self, admin: psycopg.Connection[Ligne], moi: Personne, etat: str
    ) -> None:
        cle, _, _ = pose_une_cle(admin, moi.id)
        match etat:
            case "bannie":
                admin.execute(
                    "update auth.users set banned_until = now() + interval '1 day' where id = %s", (moi.id,)
                )
            case "supprimee":
                admin.execute("update auth.users set deleted_at = now() where id = %s", (moi.id,))
            case "sans_profil":
                admin.execute("delete from public.user_profile where id = %s", (moi.id,))
            case "cle_disparue":
                admin.execute("delete from public.webauthn_credential where id = %s", (cle,))
        assert ouvre(admin, cle) is None
        assert sessions(admin, moi.id) == []

    def test_la_session_presentee_est_revoquee(
        self, admin: psycopg.Connection[Ligne], moi: Personne, fabrique: Fabrique
    ) -> None:
        cle, _, _ = pose_une_cle(admin, moi.id)
        ancienne = fabrique.session(
            moi.id, echeance_dans=timedelta(days=3650), absolue_dans=timedelta(days=3650)
        )
        assert ouvre(admin, cle, vieux_jeton=ancienne.empreinte) is not None
        assert un(
            admin.execute(
                "select revoked_at is not null from public.login_session where id = %s", (ancienne.id,)
            )
        )[0]
        assert sessions(admin, moi.id) == [("cle", cle)]

    def test_la_fonction_publique_ne_s_ouvre_qu_a_popote_api(
        self, moi: Personne, admin: psycopg.Connection[Ligne]
    ) -> None:
        cle, identifiant, _ = pose_une_cle(admin, moi.id)
        with connecte(DSN_API) as cx:
            lue = un(cx.execute("select personne from public.cle_pour_connexion(%s, null)", (identifiant,)))
            assert lue[0] == moi.id
            ouverte = un(cx.execute(
                "select session, personne from public.ouvre_une_session_par_cle(%s, 0, 1, false, true, %s)",
                (cle, token_bytes(32)),
            ))  # fmt: skip
            assert ouverte[1] == moi.id
            cx.commit()
