"""Spec § 4 : `session_personne` et la table `login_session` (migration 0133).

Base locale par défaut ; `POPOTE_TEST_DSN_API` et `POPOTE_TEST_DSN_ADMIN` les rejouent sur un autre serveur.
La fonction se lit comme `popote_api`, le seul rôle qui l'exécute ; les droits se lisent dans le catalogue.
"""

from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_ADMIN, DSN_API, connecte
from _fabrique import Fabrique, SessionDeTest
from psycopg import sql

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
CINQ_MINUTES = timedelta(minutes=5)
TRENTE_JOURS = timedelta(days=30)
APPEL = "select public.session_personne(%s)"
ROLES_FERMES = ["anon", "authenticated", "service_role", "popote_internal"]


@pytest.fixture
def cx_api() -> Iterator[psycopg.Connection[Ligne]]:
    with connecte(DSN_API) as cx:
        assert cx.execute("select session_user").fetchone() == ("popote_api",)
        cx.rollback()
        yield cx


def personne_de(cx: psycopg.Connection[Ligne], empreinte: bytes) -> object:
    """Le résultat de `session_personne` en sa propre transaction, comme une requête de l'API."""
    with cx.transaction():
        ligne = cx.execute(APPEL, (empreinte,)).fetchone()
    assert ligne is not None
    return ligne[0]


def note_l_activite(cx: psycopg.Connection[Ligne], empreinte: bytes) -> None:
    """L'écriture de l'activité, en sa propre transaction (0148) : la lecture, elle, n'écrit plus."""
    with cx.transaction():
        cx.execute("select public.note_l_activite_de_la_session(%s)", (empreinte,))


def une_personne(fabrique: Fabrique) -> UUID:
    return fabrique.personne(fabrique.foyer()).id


def ligne_de(fabrique: Fabrique, session: SessionDeTest) -> tuple[object, object]:
    ligne = fabrique.admin.execute(
        "select last_seen_at, expires_at from public.login_session where id = %s", (session.id,)
    ).fetchone()
    assert ligne is not None
    return ligne[0], ligne[1]


def test_session_valide_rend_sa_personne(cx_api: psycopg.Connection[Ligne], fabrique: Fabrique) -> None:
    personne = une_personne(fabrique)
    session = fabrique.session(personne)
    assert personne_de(cx_api, session.empreinte) == personne


def test_empreinte_inconnue_ne_rend_personne(cx_api: psycopg.Connection[Ligne]) -> None:
    assert personne_de(cx_api, b"\x00" * 32) is None


def test_empreinte_de_mauvaise_longueur_ne_rend_personne_sans_erreur(
    cx_api: psycopg.Connection[Ligne],
) -> None:
    assert personne_de(cx_api, b"court") is None


@pytest.fixture(params=[timedelta(0), timedelta(hours=1)], ids=["vue_a_l_instant", "vue_il_y_a_une_heure"])
def vue_il_y_a(request: pytest.FixtureRequest) -> timedelta:
    """Récente ou plus vieille que 5 minutes : les refus valent dans la voie de lecture comme d'écriture."""
    return request.param  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "refus",
    [
        {"echeance_dans": -timedelta(minutes=1)},
        {"revoquee": True},
        {"echeance_dans": -timedelta(days=1), "absolue_dans": -timedelta(seconds=1)},
    ],
    ids=["echue", "revoquee", "au_bout_des_90_jours"],
)
def test_session_refusee_ne_rend_personne_et_ne_repousse_rien(
    cx_api: psycopg.Connection[Ligne], fabrique: Fabrique, refus: dict[str, object], vue_il_y_a: timedelta
) -> None:
    session = fabrique.session(une_personne(fabrique), vue_il_y_a=vue_il_y_a, **refus)  # type: ignore[arg-type]
    avant = ligne_de(fabrique, session)
    assert personne_de(cx_api, session.empreinte) is None
    assert ligne_de(fabrique, session) == avant


@pytest.mark.parametrize(
    "bascule",
    [
        "update auth.users set banned_until = now() + interval '1 hour' where id = %s",
        "update auth.users set deleted_at = now() where id = %s",
    ],
    ids=["bannie", "supprimee"],
)
def test_personne_refusee_ne_rend_personne_et_ne_repousse_rien(
    cx_api: psycopg.Connection[Ligne], fabrique: Fabrique, bascule: str, vue_il_y_a: timedelta
) -> None:
    personne = une_personne(fabrique)
    session = fabrique.session(personne, vue_il_y_a=vue_il_y_a)
    fabrique.admin.execute(bascule, (personne,))  # type: ignore[call-overload]  # texte constant du test
    avant = ligne_de(fabrique, session)
    assert personne_de(cx_api, session.empreinte) is None
    assert ligne_de(fabrique, session) == avant


def test_bannissement_leve_la_session_revit(cx_api: psycopg.Connection[Ligne], fabrique: Fabrique) -> None:
    personne = une_personne(fabrique)
    session = fabrique.session(personne)
    fabrique.admin.execute(
        "update auth.users set banned_until = now() - interval '1 hour' where id = %s", (personne,)
    )
    assert personne_de(cx_api, session.empreinte) == personne


def test_personne_supprimee_ne_rend_personne(cx_api: psycopg.Connection[Ligne], fabrique: Fabrique) -> None:
    personne = une_personne(fabrique)
    session = fabrique.session(personne)
    fabrique.admin.execute("update auth.users set deleted_at = now() where id = %s", (personne,))
    assert personne_de(cx_api, session.empreinte) is None


def test_session_vue_depuis_plus_de_5_minutes_repousse_l_echeance_glissante(
    cx_api: psycopg.Connection[Ligne], fabrique: Fabrique
) -> None:
    session = fabrique.session(
        une_personne(fabrique),
        vue_il_y_a=CINQ_MINUTES + timedelta(seconds=1),
        echeance_dans=timedelta(days=1),
    )
    note_l_activite(cx_api, session.empreinte)
    ligne = fabrique.admin.execute(
        """
        select now() - last_seen_at < interval '1 minute',
               abs(extract(epoch from (expires_at - (now() + interval '30 days')))) < 60
          from public.login_session where id = %s
        """,
        (session.id,),
    ).fetchone()
    assert ligne == (True, True)


def test_la_lecture_n_ecrit_plus_l_activite_meme_vue_depuis_longtemps(
    cx_api: psycopg.Connection[Ligne], fabrique: Fabrique
) -> None:
    """Le code déjà déployé lit par `session_personne` : il ne tient plus de ligne (0148, déploiement)."""
    session = fabrique.session(une_personne(fabrique), vue_il_y_a=timedelta(hours=1))
    avant = ligne_de(fabrique, session)
    assert personne_de(cx_api, session.empreinte) is not None
    assert ligne_de(fabrique, session) == avant


def test_echeance_glissante_ne_depasse_jamais_l_echeance_absolue(
    cx_api: psycopg.Connection[Ligne], fabrique: Fabrique
) -> None:
    session = fabrique.session(
        une_personne(fabrique),
        vue_il_y_a=timedelta(hours=1),
        echeance_dans=timedelta(days=5),
        absolue_dans=timedelta(days=10),
    )
    note_l_activite(cx_api, session.empreinte)
    ligne = fabrique.admin.execute(
        "select expires_at = absolute_expires_at from public.login_session where id = %s", (session.id,)
    ).fetchone()
    assert ligne == (True,)


def test_last_seen_at_n_est_pas_reecrit_a_chaque_requete(
    cx_api: psycopg.Connection[Ligne], fabrique: Fabrique
) -> None:
    session = fabrique.session(
        une_personne(fabrique),
        vue_il_y_a=CINQ_MINUTES - timedelta(seconds=30),
        echeance_dans=timedelta(days=2),
    )
    avant = ligne_de(fabrique, session)
    personne_de(cx_api, session.empreinte)
    personne_de(cx_api, session.empreinte)
    assert ligne_de(fabrique, session) == avant


def test_une_lecture_heritee_ne_verrouille_pas_la_ligne_de_la_session(
    cx_api: psycopg.Connection[Ligne], fabrique: Fabrique
) -> None:
    """Une lecture héritée encore ouverte : une autre connexion verrouille la ligne sans attendre."""
    session = fabrique.session(une_personne(fabrique), vue_il_y_a=CINQ_MINUTES * 2)
    with cx_api.transaction(force_rollback=True):
        cx_api.execute(APPEL, (session.empreinte,))
        with psycopg.connect(DSN_ADMIN) as autre:
            ligne = autre.execute(
                "select id from public.login_session where id = %s for update nowait", (session.id,)
            ).fetchone()
    assert ligne == (session.id,)


def test_la_session_disparait_avec_la_personne(fabrique: Fabrique) -> None:
    personne = une_personne(fabrique)
    session = fabrique.session(personne)
    fabrique.admin.execute("delete from auth.users where id = %s", (personne,))
    ligne = fabrique.admin.execute("select count(*) from public.login_session where id = %s", (session.id,))
    assert ligne.fetchone() == (0,)


def test_une_empreinte_n_existe_qu_une_fois(fabrique: Fabrique) -> None:
    session = fabrique.session(une_personne(fabrique))
    with pytest.raises(psycopg.errors.UniqueViolation):
        fabrique.admin.execute(
            "insert into public.login_session (token_hash, person_id) values (%s, %s)",
            (session.empreinte, une_personne(fabrique)),
        )


def test_le_jeton_en_clair_n_est_pas_une_empreinte_valide(fabrique: Fabrique) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        fabrique.admin.execute(
            "insert into public.login_session (token_hash, person_id) values (%s, %s)",
            (b"un jeton de longueur quelconque", une_personne(fabrique)),
        )


def test_echeance_glissante_au_dela_de_l_absolue_est_refusee(fabrique: Fabrique) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        fabrique.session(
            une_personne(fabrique), echeance_dans=timedelta(days=91), absolue_dans=timedelta(days=90)
        )


# --- droits, lus dans le catalogue : ce qui est écrit dans la base, pas ce que la migration dit ---


def droit_fonction(cx: psycopg.Connection[Ligne], role: str) -> object:
    ligne = cx.execute(
        "select has_function_privilege(%s, 'public.session_personne(bytea)', 'execute')", (role,)
    ).fetchone()
    assert ligne is not None
    return ligne[0]


def test_seul_popote_api_execute_la_fonction(fabrique: Fabrique) -> None:
    assert droit_fonction(fabrique.admin, "popote_api") is True
    assert [droit_fonction(fabrique.admin, role) for role in ROLES_FERMES] == [False] * len(ROLES_FERMES)


def test_public_n_a_pas_le_droit_d_executer_la_fonction(fabrique: Fabrique) -> None:
    ligne = fabrique.admin.execute(
        """
        select exists (select 1 from pg_proc p, aclexplode(p.proacl) a
                        where p.oid = 'public.session_personne(bytea)'::regprocedure and a.grantee = 0)
        """
    ).fetchone()
    assert ligne == (False,)


@pytest.mark.parametrize("role", ["authenticated", "anon", "service_role"])
def test_un_role_emprunte_ne_peut_pas_appeler_la_fonction(
    cx_api: psycopg.Connection[Ligne], role: str
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege), cx_api.transaction():
        cx_api.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
        cx_api.execute(APPEL, (uuid4().bytes + uuid4().bytes,))


@pytest.mark.parametrize("role", ["popote_api", "popote_internal", "anon", "authenticated", "service_role"])
def test_aucun_role_n_a_de_droit_sur_la_table(fabrique: Fabrique, role: str) -> None:
    ligne = fabrique.admin.execute(
        "select has_table_privilege(%s, 'public.login_session', 'select, insert, update, delete, truncate, "
        "references, trigger')",
        (role,),
    ).fetchone()
    assert ligne == (False,)


def test_la_table_a_la_rls_sans_politique(fabrique: Fabrique) -> None:
    ligne = fabrique.admin.execute(
        """
        select c.relrowsecurity,
               (select count(*) from pg_policy where polrelid = c.oid)
          from pg_class c where c.oid = 'public.login_session'::regclass
        """
    ).fetchone()
    assert ligne == (True, 0)


def test_la_fonction_est_definer_avec_un_search_path_vide(fabrique: Fabrique) -> None:
    ligne = fabrique.admin.execute(
        "select prosecdef, proconfig from pg_proc where oid = 'public.session_personne(bytea)'::regprocedure"
    ).fetchone()
    assert ligne == (True, ['search_path=""'])
