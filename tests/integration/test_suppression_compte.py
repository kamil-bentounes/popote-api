"""T14a : ce que `efface_mes_donnees()` fait pour la base (B7, B8, B9, B26), et ce qui reste de l'ancienne.
La route `DELETE /me` est T14b. Données inventées."""

import os
import threading
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_ADMIN
from _fabrique import Fabrique, Personne
from _suppression import en_tant_que, nombre, seme_foyer
from psycopg import errors

pytestmark = pytest.mark.integration

# Des clés propres à chaque exécution : un reste d'un essai précédent ne fausse pas le décompte.
CLE_A = os.urandom(32)
CLE_B = os.urandom(32)


def efface(admin: psycopg.Connection[tuple[object, ...]], personne: UUID, *, ancienne: bool = False) -> None:
    with admin.transaction():
        en_tant_que(admin, personne)
        admin.execute(
            "select public.delete_my_account()" if ancienne else "select public.efface_mes_donnees()"
        )


def supprime_auth(admin: psycopg.Connection[tuple[object, ...]], personne: UUID) -> None:
    admin.execute("delete from auth.users where id = %s", (personne,))


def pose_ses_traces(fabrique: Fabrique, personne: Personne) -> None:
    """Des événements à clés, une clé d'idempotence, des sessions de l'API et de GoTrue."""
    admin = fabrique.admin
    admin.execute(
        "insert into public.security_event (kind, person_id, account_key, ip_hash)"
        " values ('connexion_reussie', %s, %s, %s), ('connexion_ratee', %s, %s, null)",
        (personne.id, CLE_A, CLE_B, personne.id, CLE_A),
    )
    admin.execute(
        "insert into public.idempotency_key (person_id, key, method, path, fingerprint, status, body)"
        " values (%s, 'cle-un', 'POST', '/api/v1/x', %s, 201, '\\x00')",
        (personne.id, "0" * 64),
    )
    fabrique.session(personne.id)
    admin.execute(
        "insert into auth.sessions (id, user_id, created_at, updated_at)"
        " values (gen_random_uuid(), %s, now(), now())",
        (personne.id,),
    )
    admin.execute(
        "insert into auth.refresh_tokens (instance_id, token, user_id, session_id)"
        " select '00000000-0000-0000-0000-000000000000', gen_random_uuid()::text, user_id::text, id"
        " from auth.sessions where user_id = %s",
        (personne.id,),
    )


def traces_restantes(admin: psycopg.Connection[tuple[object, ...]], personne: UUID) -> dict[str, int]:
    return {
        "idempotency_key": nombre(
            admin, "select count(*) from public.idempotency_key where person_id = %s", personne
        ),
        "login_session": nombre(
            admin, "select count(*) from public.login_session where person_id = %s", personne
        ),
        "auth.sessions": nombre(admin, "select count(*) from auth.sessions where user_id = %s", personne),
        "auth.refresh_tokens": nombre(
            admin, "select count(*) from auth.refresh_tokens where user_id = %s", str(personne)
        ),
    }


def test_il_ne_reste_aucune_trace_de_la_personne(fabrique: Fabrique) -> None:
    graine = seme_foyer(fabrique, a_deux=True)
    pose_ses_traces(fabrique, graine.a)
    admin = fabrique.admin
    assert all(v > 0 for v in traces_restantes(admin, graine.a.id).values())
    efface(admin, graine.a.id)
    supprime_auth(admin, graine.a.id)
    assert traces_restantes(admin, graine.a.id) == dict.fromkeys(
        ["idempotency_key", "login_session", "auth.sessions", "auth.refresh_tokens"], 0
    )
    # B7 : l'événement `compte_supprime` est gardé, sans personne ni clé.
    ligne = admin.execute(
        "select count(*) filter (where kind = 'compte_supprime'),"
        " count(*) filter (where account_key is not null or ip_hash is not null)"
        " from public.security_event where person_id is null and request_id is null and session_id is null"
        " and invitation_id is null and occurred_at > now() - interval '1 hour'"
    ).fetchone()
    assert ligne is not None
    assert ligne[0] >= 1
    assert ligne[1] == 0
    # Les clés de la personne ne sont plus dans aucun événement.
    assert (
        nombre(
            admin,
            "select count(*) from public.security_event where account_key = %s or ip_hash = %s",
            CLE_A,
            CLE_B,
        )
        == 0
    )
    nettoie_evenements(admin)


def nettoie_evenements(admin: psycopg.Connection[tuple[object, ...]]) -> None:
    admin.execute(
        "delete from public.security_event"
        " where person_id is null and occurred_at > now() - interval '1 hour'"
    )


def test_les_cles_de_la_personne_partent_avant_l_evenement_et_les_autres_restent(fabrique: Fabrique) -> None:
    graine = seme_foyer(fabrique, a_deux=True)
    assert graine.b is not None
    pose_ses_traces(fabrique, graine.a)
    fabrique.admin.execute(
        "insert into public.security_event (kind, person_id, account_key)"
        " values ('connexion_reussie', %s, %s)",
        (graine.b.id, CLE_B),
    )
    efface(fabrique.admin, graine.a.id)
    assert (
        nombre(
            fabrique.admin,
            "select count(*) from public.security_event where person_id = %s and account_key = %s",
            graine.b.id,
            CLE_B,
        )
        == 1
    )
    assert (
        nombre(
            fabrique.admin,
            "select count(*) from public.security_event where person_id = %s and account_key is not null",
            graine.a.id,
        )
        == 0
    )
    supprime_auth(fabrique.admin, graine.a.id)
    fabrique.admin.execute("delete from public.security_event where person_id = %s", (graine.b.id,))
    nettoie_evenements(fabrique.admin)


def test_le_dernier_membre_emporte_le_foyer_l_autre_foyer_reste(fabrique: Fabrique) -> None:
    seul = seme_foyer(fabrique, a_deux=False)
    autre = seme_foyer(fabrique, a_deux=True)
    admin = fabrique.admin
    avant = nombre(admin, "select count(*) from public.charge where household_id = %s", autre.foyer_id)
    efface(admin, seul.a.id)
    assert nombre(admin, "select count(*) from public.household where id = %s", seul.foyer_id) == 0
    assert nombre(admin, "select count(*) from public.charge where household_id = %s", seul.foyer_id) == 0
    assert (
        nombre(admin, "select count(*) from public.charge where household_id = %s", autre.foyer_id) == avant
    )
    assert nombre(admin, "select count(*) from public.household where id = %s", autre.foyer_id) == 1
    supprime_auth(admin, seul.a.id)
    nettoie_evenements(admin)


def test_l_autre_membre_garde_son_foyer_et_ses_donnees(fabrique: Fabrique) -> None:
    graine = seme_foyer(fabrique, a_deux=True)
    assert graine.b is not None
    admin = fabrique.admin
    efface(admin, graine.a.id)
    assert nombre(admin, "select count(*) from public.user_profile where id = %s", graine.a.id) == 0
    assert nombre(admin, "select count(*) from public.user_profile where id = %s", graine.b.id) == 1
    assert nombre(admin, "select count(*) from public.household where id = %s", graine.foyer_id) == 1
    assert nombre(admin, "select count(*) from public.revenu where user_profile_id = %s", graine.b.id) == 1
    assert (
        nombre(
            admin, "select count(*) from public.charge_participant where user_profile_id = %s", graine.b.id
        )
        >= 1
    )
    supprime_auth(admin, graine.a.id)
    nettoie_evenements(admin)


def test_un_membre_qui_a_accepte_un_lien_supprime_son_compte_et_le_lien_reste(fabrique: Fabrique) -> None:
    graine = seme_foyer(fabrique, a_deux=True, cloture=False)
    assert graine.b is not None
    admin = fabrique.admin
    lien = admin.execute(
        "insert into public.invite_link (household_id, created_by, token_hash, accepted_at, accepted_by)"
        " values (%s, %s, %s, now(), %s) returning id",
        (graine.foyer_id, graine.a.id, uuid4().bytes * 2, graine.b.id),
    ).fetchone()
    assert lien is not None
    efface(admin, graine.b.id)
    supprime_auth(admin, graine.b.id)
    assert admin.execute(
        "select created_by, accepted_by, accepted_at is not null from public.invite_link where id = %s",
        (lien[0],),
    ).fetchone() == (graine.a.id, None, True)
    nettoie_evenements(admin)


def test_deux_suppressions_du_meme_compte_se_passent_sans_erreur(fabrique: Fabrique) -> None:
    graine = seme_foyer(fabrique, a_deux=True)
    admin = fabrique.admin
    efface(admin, graine.a.id)
    efface(admin, graine.a.id)  # plus de profil : seules les sessions se ferment
    supprime_auth(admin, graine.a.id)
    efface(admin, graine.a.id)  # le compte Auth lui-même a disparu
    assert (
        nombre(
            admin,
            "select count(*) from public.security_event where kind = 'compte_supprime'"
            " and person_id is null and occurred_at > now() - interval '1 hour'",
        )
        == 1
    )
    nettoie_evenements(admin)


def test_une_nouvelle_tentative_apres_une_panne_d_auth_ferme_encore_les_sessions(fabrique: Fabrique) -> None:
    graine = seme_foyer(fabrique, a_deux=True)
    admin = fabrique.admin
    efface(admin, graine.a.id)
    fabrique.session(graine.a.id)  # une session posée entre-temps, comme une connexion pendant la panne
    efface(admin, graine.a.id)
    assert nombre(admin, "select count(*) from public.login_session where person_id = %s", graine.a.id) == 0
    supprime_auth(admin, graine.a.id)
    nettoie_evenements(admin)


def test_sans_identite_la_fonction_refuse_comme_l_ancienne(fabrique: Fabrique) -> None:
    admin = fabrique.admin
    for nom in ("efface_mes_donnees", "delete_my_account"):
        with pytest.raises(errors.InsufficientPrivilege), admin.transaction():
            admin.execute("set local role authenticated")
            admin.execute("select set_config('request.jwt.claims', '', true)")
            admin.execute(f"select public.{nom}()")


def test_anon_ne_peut_pas_l_executer(fabrique: Fabrique) -> None:
    admin = fabrique.admin
    for nom in ("efface_mes_donnees", "delete_my_account"):
        with pytest.raises(errors.InsufficientPrivilege), admin.transaction():
            admin.execute("set local role anon")
            admin.execute(f"select public.{nom}()")


def test_delete_my_account_garde_ses_droits_et_sa_forme(fabrique: Fabrique) -> None:
    ligne = fabrique.admin.execute(
        "select prosecdef, prorettype::regtype::text, proconfig, pronargs,"
        " has_function_privilege('authenticated', oid, 'execute'),"
        " has_function_privilege('anon', oid, 'execute'),"
        " has_function_privilege('public', oid, 'execute')"
        " from pg_proc where oid = 'public.delete_my_account()'::regprocedure"
    ).fetchone()
    assert ligne == (True, "void", ["search_path=public, pg_temp"], 0, True, False, False)


def test_deux_membres_qui_suppriment_en_meme_temps_ne_s_interbloquent_pas(fabrique: Fabrique) -> None:
    graine = seme_foyer(fabrique, a_deux=True)
    assert graine.b is not None
    erreurs: list[BaseException] = []
    barriere = threading.Barrier(2)

    def part(personne: UUID) -> None:
        try:
            with psycopg.connect(DSN_ADMIN, autocommit=True) as connexion:
                connexion.execute("set statement_timeout = '20s'")
                barriere.wait(timeout=10)
                efface(connexion, personne)
        except BaseException as erreur:
            erreurs.append(erreur)

    fils = [threading.Thread(target=part, args=(p.id,)) for p in (graine.a, graine.b)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=60)
    assert erreurs == []
    admin = fabrique.admin
    assert nombre(admin, "select count(*) from public.household where id = %s", graine.foyer_id) == 0
    assert nombre(admin, "select count(*) from public.depense where household_id = %s", graine.foyer_id) == 0
    for p in (graine.a, graine.b):
        supprime_auth(admin, p.id)
    nettoie_evenements(admin)


def test_avant_la_suppression_du_compte_auth_les_sessions_sont_deja_fermees(fabrique: Fabrique) -> None:
    """T14b supprime le compte Auth par l'API d'administration, après : la cascade ne compte pas."""
    graine = seme_foyer(fabrique, a_deux=True)
    pose_ses_traces(fabrique, graine.a)
    efface(fabrique.admin, graine.a.id)
    assert nombre(fabrique.admin, "select count(*) from auth.users where id = %s", graine.a.id) == 1
    assert traces_restantes(fabrique.admin, graine.a.id) == dict.fromkeys(
        ["idempotency_key", "login_session", "auth.sessions", "auth.refresh_tokens"], 0
    )
    supprime_auth(fabrique.admin, graine.a.id)
    nettoie_evenements(fabrique.admin)
