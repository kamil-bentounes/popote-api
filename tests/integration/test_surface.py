"""La surface de droits des objets de 0.4 (B3, B17, B19) : qui lit une table neuve, qui exécute quoi.

Chaque migration de 0.4 ajoute ici ses tables et ses fonctions : une fonction `security definer` qui n'est pas
listée est un échec (le défaut de Postgres l'ouvre à `public`). Les rôles se lisent par `set local role` quand
l'administrateur peut les emprunter (`anon`, `authenticated`, `service_role` : le rôle COURANT, B3), et par le
catalogue pour les deux rôles de connexion, qui ne s'empruntent pas depuis l'administrateur.
"""

import psycopg
import pytest
from _fabrique import Fabrique

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
EMPRUNTABLES = ["anon", "authenticated", "service_role"]
ROLES = [*EMPRUNTABLES, "popote_api", "popote_internal"]
PRIVILEGES_DE_TABLE = ["select", "insert", "update", "delete", "truncate", "references", "trigger"]

# Les tables de 0.4 : aucun droit aux rôles applicatifs, RLS forcée, sans politique. Une migration en ajoute.
TABLES = ["public.security_event", "public.login_throttle", "public.invite_link", "public.reprise_en_cours"]

# Les fonctions de 0.4 et les rôles qui peuvent les exécuter (rôle COURANT). Une migration en ajoute.
EXECUTABLES_PAR: dict[str, set[str]] = {
    "public.journalise(text, uuid, uuid, uuid, bytea, bytea, text)": {"popote_api", "service_role"},
    "private.ecrit_evenement(text, uuid, uuid, uuid, bytea, bytea, text)": set(),
    "public.cree_session(uuid, bytea, text, text, bytea)": {"popote_api", "service_role"},
    "public.session_courante(bytea)": {"popote_api", "service_role"},
    "public.fait_tourner_session(bytea, bytea)": {"popote_api", "service_role"},
    "public.ferme_session(bytea)": {"popote_api", "service_role"},
    "public.marque_reauth(uuid, uuid)": {"popote_api", "service_role"},
    "public.session_personne(bytea)": {"popote_api"},
    "private.session_valide(bytea, timestamptz)": set(),
    "private.cree_session(uuid, bytea, text, text, bytea, timestamptz)": set(),
    "private.fait_tourner_session(bytea, bytea, timestamptz)": set(),
    "private.purge_login_session(timestamptz, integer)": set(),
    "private.purge_journal_securite(timestamp with time zone, integer)": set(),
    "public.verifie_mot_de_passe(text, text)": {"popote_api"},
    "public.verifie_mot_de_passe_de(uuid, text)": {"popote_api"},
    "private.mot_de_passe_correspond(text, text)": set(),
    "public.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer)": {
        "popote_api",
        "service_role",
    },
    "public.prend_un_creneau_reinit(bytea, integer, integer)": {"popote_api", "service_role"},
    "public.libere_compte(bytea)": {"popote_api", "service_role"},
    "private.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer, timestamptz)": set(),
    "private.prend_un_creneau(text, bytea, integer, integer, integer, boolean, timestamptz)": set(),
    "private.prend_un_creneau_reinit(bytea, integer, integer, timestamptz)": set(),
    "private.purge_login_throttle(timestamptz, integer)": set(),
    "public.mes_sessions(integer, timestamptz, uuid)": {"authenticated"},
    "public.ferme_un_appareil(uuid, uuid)": {"authenticated"},
    "public.ferme_les_autres_appareils(uuid)": {"authenticated"},
    "public.fait_tourner_et_ferme_les_autres(bytea, bytea)": {"popote_api"},
    "public.confirme_le_changement_de_mot_de_passe(uuid, uuid, text)": {"popote_api"},
    "private.fait_tourner_et_ferme_les_autres(bytea, bytea, timestamptz)": set(),
    "private.ferme_les_sessions_auth(uuid)": set(),
    "private.ferme_les_autres_sessions(uuid, uuid, timestamptz)": set(),
    "public.cree_invitation(bytea)": {"authenticated"},
    "public.mes_invitations(integer, timestamptz, uuid)": {"authenticated"},
    "public.revoque_invitation(uuid)": {"authenticated"},
    "private.cree_invitation(uuid, bytea, timestamptz)": set(),
    "private.purge_invite_link(timestamptz, integer)": set(),
    "public.prend_un_creneau_invitation(text, bytea, integer, integer)": {"popote_api", "service_role"},
    "public.etat_invitation(bytea)": {"popote_api", "service_role"},
    "public.consomme_invitation(bytea)": {"service_role"},
    "public.rend_invitation(uuid)": {"service_role"},
    "public.termine_invitation(uuid, uuid)": {"service_role"},
    "public.compte_pour_email(text)": {"service_role"},
    "public.reserve_reprise(bytea)": {"service_role"},
    "public.libere_reprise(bytea, uuid)": {"service_role"},
}
# Les rôles qui ont `usage` sur `private` : aucun tant qu'une migration n'en a pas besoin.
USAGE_DE_PRIVATE: set[str] = set()


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


def vrai(admin: psycopg.Connection[Ligne], requete: str, *parametres: object) -> bool:
    ligne = admin.execute(requete, parametres).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], bool)
    return ligne[0]


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("role", ROLES)
def test_une_table_neuve_n_a_aucun_droit_pour_un_role_applicatif(
    table: str, role: str, admin: psycopg.Connection[Ligne]
) -> None:
    for privilege in PRIVILEGES_DE_TABLE:
        assert not vrai(admin, "select has_table_privilege(%s, %s::regclass, %s)", role, table, privilege), (
            f"{role} a {privilege} sur {table}"
        )


@pytest.mark.parametrize("table", TABLES)
def test_une_table_neuve_ne_donne_rien_a_public_et_force_la_rls_sans_politique(
    table: str, admin: psycopg.Connection[Ligne]
) -> None:
    grantees = admin.execute(
        "select distinct a.grantee from pg_class c, aclexplode(c.relacl) a where c.oid = %s::regclass",
        (table,),
    ).fetchall()
    assert (0,) not in grantees, "PUBLIC a un droit"
    assert vrai(
        admin, "select relrowsecurity and relforcerowsecurity from pg_class where oid = %s::regclass", table
    )
    politiques = admin.execute(
        "select count(*) from pg_policy where polrelid = %s::regclass", (table,)
    ).fetchone()
    assert politiques == (0,)


@pytest.mark.parametrize("fonction", sorted(EXECUTABLES_PAR))
def test_une_fonction_n_est_executable_que_par_les_roles_listes(
    fonction: str, admin: psycopg.Connection[Ligne]
) -> None:
    attendus = EXECUTABLES_PAR[fonction]
    for role in ROLES:
        a_le_droit = vrai(
            admin, "select has_function_privilege(%s, %s::regprocedure, 'execute')", role, fonction
        )
        assert a_le_droit == (role in attendus), f"{role} sur {fonction}"
    # Les trois rôles empruntables, joués pour de vrai : c'est le rôle courant qui compte (B3).
    oid = admin.execute("select %s::regprocedure::oid", (fonction,)).fetchone()
    assert oid is not None
    for role in EMPRUNTABLES:
        with admin.transaction():
            admin.execute(f"set local role {role}")
            # Par l'oid : résoudre le nom d'une fonction de `private` demande `usage`, que le rôle n'a pas.
            courant = vrai(admin, "select has_function_privilege(current_user, %s::oid, 'execute')", oid[0])
        assert courant == (role in attendus), f"{role} (rôle courant) sur {fonction}"


@pytest.mark.parametrize("fonction", sorted(EXECUTABLES_PAR))
def test_une_fonction_neuve_ne_garde_pas_le_droit_par_defaut_de_public(
    fonction: str, admin: psycopg.Connection[Ligne]
) -> None:
    ligne = admin.execute(
        "select proacl is null, coalesce(bool_or(a.grantee = 0), false)"
        " from pg_proc p left join lateral aclexplode(p.proacl) a on true"
        " where p.oid = %s::regprocedure group by p.proacl",
        (fonction,),
    ).fetchone()
    assert ligne == (False, False)


def test_toute_fonction_du_schema_prive_est_declaree(admin: psycopg.Connection[Ligne]) -> None:
    presentes = {
        ligne[0]
        for ligne in admin.execute(
            "select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
            " where n.nspname = 'private'"
        ).fetchall()
    }
    declarees = {
        ligne[0]
        for nom in EXECUTABLES_PAR
        if nom.startswith("private.")
        for ligne in [admin.execute("select %s::regprocedure::text", (nom,)).fetchone() or ("",)]
    }
    assert presentes == declarees


@pytest.mark.parametrize("role", ROLES)
def test_le_schema_prive_n_est_ouvert_qu_aux_roles_listes(
    role: str, admin: psycopg.Connection[Ligne]
) -> None:
    usage = vrai(admin, "select has_schema_privilege(%s, 'private', 'usage')", role)
    creation = vrai(admin, "select has_schema_privilege(%s, 'private', 'create')", role)
    assert usage == (role in USAGE_DE_PRIVATE)
    assert creation is False


def test_le_schema_prive_ne_donne_rien_a_public(admin: psycopg.Connection[Ligne]) -> None:
    grantees = admin.execute(
        "select a.grantee from pg_namespace n, aclexplode(n.nspacl) a where n.nspname = 'private'"
    ).fetchall()
    assert (0,) not in grantees


def test_aucune_table_du_schema_prive_n_est_ouverte(admin: psycopg.Connection[Ligne]) -> None:
    ouvertes = admin.execute(
        "select c.oid::regclass::text, a.grantee"
        " from pg_class c join pg_namespace n on n.oid = c.relnamespace, aclexplode(c.relacl) a"
        " where n.nspname = 'private' and a.grantee in (0, 'anon'::regrole, 'authenticated'::regrole)"
    ).fetchall()
    assert ouvertes == []


def test_aucune_fonction_ouverte_a_authenticated_n_a_de_parametre_d_horloge(
    admin: psycopg.Connection[Ligne],
) -> None:
    """B19 : une personne ne choisit pas sa date. L'horloge ne vit que dans des variantes réservées."""
    fautives = admin.execute(
        """
        select p.oid::regprocedure::text
          from pg_proc p join pg_namespace n on n.oid = p.pronamespace
         where n.nspname in ('public', 'private')
           and (has_function_privilege('authenticated', p.oid, 'execute')
                or has_function_privilege('anon', p.oid, 'execute'))
           and exists (select 1 from generate_subscripts(p.proargtypes, 1) i
                        where p.proargtypes[i] = 'timestamptz'::regtype
                          and p.proargnames[i + 1] ~ '^p_(now|maintenant|horloge|clock|today)')
        """
    ).fetchall()
    assert fautives == []
