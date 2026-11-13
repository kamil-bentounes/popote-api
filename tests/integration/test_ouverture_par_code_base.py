"""0.4bis S7a : la vérification du code et l'ouverture de la session côté base (0149 ; spec § 4 ; A1).

En base locale, données inventées. Les fonctions publiques se jouent en `popote_api` ; le temps est injecté
par les variantes à horloge de `private` (en administrateur). Le « code » est une empreinte de 32 octets
tirée au hasard : la base compare des empreintes, jamais un code. Les courses passent par `_course.py`.
"""

# ruff: noqa: F811  # les fixtures de test_demande_de_code_base sont reprises par import

import asyncio
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from secrets import token_bytes
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_ADMIN, DSN_API, connecte
from _course import attend_un_verrou, course
from _fabrique import Fabrique
from test_demande_de_code_base import Cles, adresse_reelle, cles, demande, evenements, inconnue  # noqa: F401

from popote_api.infra.db import Base

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
Resultat = tuple[bool, UUID | None, UUID | None]
REFUS: Resultat = (False, None, None)
OUVRE = (
    "select ouverte, session, personne from public.ouvre_une_session_par_code(%s, %s, %s, %s, %s, %s, %s, %s)"
)
OUVRE_A_HORLOGE = (
    "select ouverte, session, personne"
    " from private.ouvre_une_session_par_code(%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
CRENEAU = "select attente_s from private.prend_un_creneau('account', %s, 5, 900, 86400, true, %s)"
HEURE = timedelta(hours=1)
JOUR = 24 * HEURE


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


@dataclass(frozen=True)
class Code:
    """Une ligne `login_code` posée en direct : sa demande, la clé du compte, l'empreinte du bon code."""

    id: UUID
    cle: bytes
    empreinte: bytes
    personne: UUID | None


def pose(admin: psycopg.Connection[Ligne], cles: Cles, personne: UUID | None) -> Code:
    code = Code(uuid4(), cles.neuve(), token_bytes(32), personne)
    admin.execute(
        "insert into public.login_code (id, account_key, person_id, code_hash) values (%s, %s, %s, %s)",
        (code.id, code.cle, personne, code.empreinte),
    )
    return code


def ouvre(
    code: Code,
    *,
    empreinte: bytes | None = None,
    cle: bytes | None = None,
    demande_id: UUID | None = None,
    presentee: bytes | None = None,
    session: bytes | None = None,
    maintenant: datetime | None = None,
    admin: psycopg.Connection[Ligne] | None = None,
    marque: str | None = None,
    cx: psycopg.Connection[Ligne] | None = None,
) -> Resultat:
    """Une vérification jouée en `popote_api` (ou, avec `maintenant`, en variante à horloge), validée."""
    valeurs = (
        demande_id or code.id, cle or code.cle, empreinte or code.empreinte, session or token_bytes(32),
        "chrome", "linux", presentee,
    )  # fmt: skip
    if maintenant is None:
        with cx or connecte(DSN_API) as connexion:
            ligne = connexion.execute(OUVRE, (*valeurs, marque)).fetchone()
            connexion.commit()
    else:
        assert admin is not None
        ligne = admin.execute(OUVRE_A_HORLOGE, (*valeurs, maintenant, marque)).fetchone()
    assert ligne is not None
    return ligne  # type: ignore[return-value]


def faux() -> bytes:
    return token_bytes(32)


def essais(admin: psycopg.Connection[Ligne], code: Code) -> tuple[int, bool, bool]:
    """(essais comptés, utilisé, révoqué)."""
    ligne = admin.execute(
        "select attempts, used_at is not null, revoked_at is not null from public.login_code where id = %s",
        (code.id,),
    ).fetchone()
    assert ligne is not None
    return ligne  # type: ignore[return-value]


def sessions(admin: psycopg.Connection[Ligne], personne: UUID) -> list[tuple[UUID, str]]:
    return admin.execute(  # type: ignore[return-value]
        "select id, opened_with from public.login_session where person_id = %s and revoked_at is null",
        (personne,),
    ).fetchall()


def active(admin: psycopg.Connection[Ligne], session: UUID) -> bool:
    ligne = admin.execute(
        "select revoked_at is null from public.login_session where id = %s", (session,)
    ).fetchone()
    assert ligne is not None
    return bool(ligne[0])


# ── Le parcours ─────────────────────────────────────────────────────────────


class TestOuverture:
    def test_le_bon_code_ouvre_une_session_nee_du_code_et_est_journalise(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code, marque = pose(admin, cles, personne), uuid4().hex
        ouverte, session, titulaire = ouvre(code, marque=marque)
        assert ouverte and titulaire == personne and session is not None
        assert sessions(admin, personne) == [(session, "code")]
        assert essais(admin, code) == (0, True, False)
        (evenement,) = evenements(admin, code.cle)
        assert evenement == ("connexion_par_code", personne, session, None, None, marque)

    def test_le_parcours_complet_de_la_demande_a_la_session(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, email = adresse_reelle
        cle, empreinte = cles.neuve(), token_bytes(32)
        _, identifiant, _ = demande(email, cle, hash_=empreinte)
        code = Code(identifiant, cle, empreinte, personne)
        assert ouvre(code, empreinte=faux()) == REFUS
        assert ouvre(code)[0] is True

    def test_le_code_ne_sert_qu_une_fois(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        assert ouvre(code)[0] is True
        assert ouvre(code) == REFUS
        assert len(sessions(admin, personne)) == 1

    def test_un_faux_code_est_refuse_et_compte_sans_rien_ouvrir(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        assert ouvre(code, empreinte=faux()) == REFUS
        assert essais(admin, code) == (1, False, False)
        assert sessions(admin, personne) == [] and evenements(admin, code.cle) == []

    def test_cinq_faux_tuent_le_code_et_le_bon_ne_passe_plus(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        for _ in range(5):
            assert ouvre(code, empreinte=faux()) == REFUS
        assert ouvre(code) == REFUS
        assert essais(admin, code) == (5, False, False)  # le sixième n'est pas compté : la ligne est morte
        assert sessions(admin, personne) == []

    def test_le_bon_code_au_cinquieme_essai_passe(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        for _ in range(4):
            assert ouvre(code, empreinte=faux()) == REFUS
        assert ouvre(code)[0] is True
        assert essais(admin, code) == (4, True, False)

    def test_un_code_echu_est_refuse_a_la_seconde_pres(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        ligne = admin.execute("select expires_at from public.login_code where id = %s", (code.id,)).fetchone()
        assert ligne is not None
        echeance: datetime = ligne[0]  # type: ignore[assignment]
        assert ouvre(code, maintenant=echeance, admin=admin) == REFUS
        assert essais(admin, code) == (0, False, False)  # échu : rien à compter
        assert ouvre(code, maintenant=echeance - timedelta(seconds=1), admin=admin)[0] is True

    def test_un_code_d_une_autre_adresse_ou_d_une_autre_demande_est_refuse_sans_toucher_la_ligne(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        assert ouvre(code, cle=cles.neuve()) == REFUS
        assert ouvre(code, demande_id=uuid4()) == REFUS
        assert essais(admin, code) == (0, False, False)
        assert sessions(admin, personne) == []

    def test_l_empreinte_du_code_d_une_autre_demande_est_un_faux_code_de_celle_ci(
        self,
        adresse_reelle: tuple[UUID, str],
        fabrique: Fabrique,
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        personne, _ = adresse_reelle
        a = pose(admin, cles, personne)
        b = pose(admin, cles, fabrique.personne(fabrique.foyer()).id)
        assert ouvre(a, empreinte=b.empreinte) == REFUS
        assert essais(admin, a) == (1, False, False) and essais(admin, b) == (0, False, False)
        assert sessions(admin, personne) == []

    def test_une_demande_revoquee_par_une_plus_recente_est_refusee(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, email = adresse_reelle
        cle, empreinte = cles.neuve(), token_bytes(32)
        _, ancienne, _ = demande(email, cle, hash_=empreinte)
        admin.execute(
            "update public.login_code set created_at = created_at - interval '2 minutes',"
            " expires_at = expires_at - interval '2 minutes' where id = %s",
            (ancienne,),
        )
        demande(email, cle)
        assert ouvre(Code(ancienne, cle, empreinte, personne)) == REFUS
        assert sessions(admin, personne) == []

    def test_la_ligne_factice_compte_l_essai_comme_une_vraie_et_ne_reussit_jamais(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        vraie, factice = pose(admin, cles, personne), pose(admin, cles, None)
        assert ouvre(vraie, empreinte=faux()) == ouvre(factice, empreinte=faux()) == REFUS
        assert ouvre(factice) == REFUS  # même l'empreinte JUSTE d'une ligne factice ne passe pas
        assert essais(admin, vraie) == (1, False, False) and essais(admin, factice) == (2, False, False)
        assert sessions(admin, personne) == [] and evenements(admin, factice.cle) == []

    def test_un_faux_code_se_refuse_dans_le_meme_temps_pour_une_ligne_reelle_et_factice(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        """Pas d'énumération de comptes par la durée : médiane de 30 essais (annulés), tolérance de 3 ms."""
        vraie, factice = pose(admin, cles, adresse_reelle[0]), pose(admin, cles, None)

        def mediane(code: Code) -> float:
            durees = []
            with connecte(DSN_API) as cx:
                for _ in range(30):
                    valeurs = (code.id, code.cle, faux(), token_bytes(32), "chrome", "linux", None, None)
                    debut = time.perf_counter()
                    cx.execute(OUVRE, valeurs).fetchone()
                    durees.append(time.perf_counter() - debut)
                    cx.rollback()
            return sorted(durees)[15]

        assert abs(mediane(vraie) - mediane(factice)) < 0.003


# ── La personne qui ne peut pas entrer : un refus, jamais une exception ─────


class TestPersonneQuiNePeutPasEntrer:
    @pytest.mark.parametrize("etat", ["banni", "supprime", "sans_profil"])
    def test_le_bon_code_est_refuse_sans_etre_consomme_et_l_essai_compte(
        self,
        etat: str,
        adresse_reelle: tuple[UUID, str],
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        if etat == "banni":
            admin.execute(
                "update auth.users set banned_until = now() + interval '1 day' where id = %s", (personne,)
            )
        elif etat == "supprime":
            admin.execute("update auth.users set deleted_at = now() where id = %s", (personne,))
        else:
            admin.execute("delete from public.user_profile where id = %s", (personne,))
        assert ouvre(code) == REFUS  # pas de `503` : le refus est un résultat
        assert essais(admin, code) == (1, False, False)
        assert sessions(admin, personne) == [] and evenements(admin, code.cle) == []

    def test_un_bannissement_echu_ne_compte_plus(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        admin.execute(
            "update auth.users set banned_until = now() - interval '1 minute' where id = %s", (personne,)
        )
        assert ouvre(code)[0] is True

    @pytest.mark.parametrize(
        "etat", ["profil", "banni", "banni_echu", "supprime", "sans_profil", "inconnue", "nulle"]
    )
    def test_personne_peut_entrer(
        self, etat: str, adresse_reelle: tuple[UUID, str], admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        cible: UUID | None = personne
        if etat == "banni":
            admin.execute(
                "update auth.users set banned_until = now() + interval '1 day' where id = %s", (personne,)
            )
        elif etat == "banni_echu":
            admin.execute(
                "update auth.users set banned_until = now() - interval '1 day' where id = %s", (personne,)
            )
        elif etat == "supprime":
            admin.execute("update auth.users set deleted_at = now() where id = %s", (personne,))
        elif etat == "sans_profil":
            admin.execute("delete from public.user_profile where id = %s", (personne,))
        elif etat == "inconnue":
            cible = uuid4()
        elif etat == "nulle":
            cible = None
        ligne = admin.execute("select private.personne_peut_entrer(%s)", (cible,)).fetchone()
        assert ligne == (etat in {"profil", "banni_echu"},)

    def test_aucune_fonction_n_ecrit_elle_meme_l_existence_du_profil(
        self, admin: psycopg.Connection[Ligne]
    ) -> None:
        """A1 : « peut entrer » s'écrit une fois ; la demande et la vérification l'appellent."""
        for fonction in (
            "public.demande_un_code(text, bytea, uuid, bytea, bytea, text)",
            "public.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, text)",
            "private.ouvre_une_session_par_code"
            "(uuid, bytea, bytea, bytea, text, text, bytea, timestamptz, text)",
        ):
            ligne = admin.execute(
                "select prosrc from pg_proc where oid = %s::regprocedure", (fonction,)
            ).fetchone()
            assert ligne is not None
            source = str(ligne[0])
            assert "user_profile" not in source, fonction
        assert "personne_peut_entrer" in str(
            admin.execute(
                "select prosrc from pg_proc where oid = 'public.demande_un_code'::regproc"
            ).fetchone()
        )


# ── La session présentée ────────────────────────────────────────────────────


class TestSessionPresentee:
    def test_un_cookie_valide_est_revoque_et_journalise(
        self,
        adresse_reelle: tuple[UUID, str],
        fabrique: Fabrique,
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        personne, _ = adresse_reelle
        ancienne = fabrique.session(personne)
        code = pose(admin, cles, personne)
        ouverte, session, _ = ouvre(code, presentee=ancienne.empreinte)
        assert ouverte and session is not None and not active(admin, ancienne.id) and active(admin, session)
        assert admin.execute(
            "select count(*) from public.security_event where kind = 'session_fermee' and session_id = %s",
            (ancienne.id,),
        ).fetchone() == (1,)

    def test_le_cookie_d_une_autre_personne_est_revoque_aussi(
        self,
        adresse_reelle: tuple[UUID, str],
        fabrique: Fabrique,
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        personne, _ = adresse_reelle
        autre = fabrique.personne(fabrique.foyer()).id
        ancienne = fabrique.session(autre)
        assert ouvre(pose(admin, cles, personne), presentee=ancienne.empreinte)[0] is True
        assert not active(admin, ancienne.id)

    def test_un_refus_ne_ferme_pas_la_session_presentee(
        self,
        adresse_reelle: tuple[UUID, str],
        fabrique: Fabrique,
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        personne, _ = adresse_reelle
        ancienne = fabrique.session(personne)
        assert ouvre(pose(admin, cles, personne), empreinte=faux(), presentee=ancienne.empreinte) == REFUS
        assert active(admin, ancienne.id)

    def test_une_empreinte_inconnue_est_ignoree(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        assert ouvre(pose(admin, cles, personne), presentee=token_bytes(32))[0] is True


# ── Les paramètres, l'erreur de la base, les droits ─────────────────────────


class TestRobustesse:
    @pytest.mark.parametrize(
        "surcharge",
        [
            {"demande": None}, {"cle": None}, {"code": None}, {"session": None},
            {"cle": b"\x01"}, {"code": b"\x01"}, {"session": b"\x01"}, {"marque": "pas-une-marque"},
        ],
        ids=["demande", "cle", "code", "session", "cle_courte", "code_courte", "session_courte", "marque"],
    )  # fmt: skip
    def test_un_parametre_nul_ou_mal_forme_leve(
        self,
        surcharge: dict[str, object],
        adresse_reelle: tuple[UUID, str],
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        v = {
            "demande": code.id,
            "cle": code.cle,
            "code": code.empreinte,
            "session": token_bytes(32),
            "marque": None,
        }
        v.update(surcharge)
        with pytest.raises(psycopg.errors.InvalidParameterValue), connecte(DSN_API) as cx:
            cx.execute(
                OUVRE, (v["demande"], v["cle"], v["code"], v["session"], "chrome", "linux", None, v["marque"])
            )
        assert essais(admin, code) == (0, False, False)

    def test_une_erreur_de_la_base_annule_tout_et_laisse_le_code_valable(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        """Leçon 3 : un déclencheur qui lève sur `login_session` : ni essai, ni code consommé, ni session."""
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        nom = f"s7a_leve_{uuid4().hex[:8]}"
        admin.execute(
            f"create function public.{nom}() returns trigger language plpgsql as $$ begin"
            f" if new.person_id = '{personne}' then"
            " raise exception 'erreur injectee' using errcode = 'XX000';"
            f" end if; return new; end $$"
        )
        admin.execute(
            f"create trigger {nom} before insert on public.login_session"
            f" for each row execute function public.{nom}()"
        )
        try:
            with pytest.raises(psycopg.errors.InternalError_):
                ouvre(code)
        finally:
            admin.execute(f"drop trigger {nom} on public.login_session")
            admin.execute(f"drop function public.{nom}()")
        assert essais(admin, code) == (0, False, False)
        assert sessions(admin, personne) == [] and evenements(admin, code.cle) == []
        assert ouvre(code)[0] is True  # la nouvelle tentative réussit

    def test_la_base_refuse_une_facon_de_naitre_inconnue(
        self, adresse_reelle: tuple[UUID, str], admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        with pytest.raises(psycopg.errors.CheckViolation), connecte(DSN_API) as cx:
            cx.execute(
                "select public.ouvre_la_session(%s, %s, 'chrome', 'linux', null, 'magie')",
                (personne, token_bytes(32)),
            )

    @pytest.mark.parametrize(
        "fonction", ["ouvre_une_session_par_code", "personne_peut_entrer", "ouvre_la_session"]
    )
    def test_les_fonctions_security_definer_ont_un_search_path_vide(
        self, fonction: str, admin: psycopg.Connection[Ligne]
    ) -> None:
        lignes = admin.execute(
            "select p.prosecdef, p.proconfig from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
            " where p.proname = %s and n.nspname in ('public', 'private')",
            (fonction,),
        ).fetchall()
        assert lignes and all(ligne == (True, ['search_path=""']) for ligne in lignes)


# ── `ouvre_la_session` et `cree_session` ────────────────────────────────────


class TestOuvreLaSession:
    @pytest.mark.parametrize("facon", ["code", "cle", "invitation", "autre"])
    def test_la_session_garde_sa_facon_de_naitre(
        self, facon: str, adresse_reelle: tuple[UUID, str], admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        with connecte(DSN_API) as cx:
            cx.execute(
                "select public.ouvre_la_session(%s, %s, 'firefox', 'macos', null, %s)",
                (personne, token_bytes(32), facon),
            )
            cx.commit()
        assert [f for _, f in sessions(admin, personne)] == [facon]

    def test_cree_session_est_intacte_et_ouvre_une_session_autre(
        self, adresse_reelle: tuple[UUID, str], admin: psycopg.Connection[Ligne]
    ) -> None:
        """Le code déjà déployé l'appelle avec cinq paramètres pendant le déploiement."""
        personne, _ = adresse_reelle
        with connecte(DSN_API) as cx:
            cx.execute(
                "select public.cree_session(%s, %s, 'chrome', 'linux', null)", (personne, token_bytes(32))
            )
            cx.commit()
        assert [f for _, f in sessions(admin, personne)] == ["autre"]

    def test_la_onzieme_session_ferme_la_plus_ancienne(
        self, adresse_reelle: tuple[UUID, str], fabrique: Fabrique, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        anciennes = [fabrique.session(personne, vue_il_y_a=timedelta(minutes=10 + i)) for i in range(10)]
        with connecte(DSN_API) as cx:
            cx.execute(
                "select public.ouvre_la_session(%s, %s, 'chrome', 'linux', null, 'code')",
                (personne, token_bytes(32)),
            )
            cx.commit()
        assert len(sessions(admin, personne)) == 10 and not active(admin, anciennes[-1].id)

    def test_une_personne_bannie_ne_s_ouvre_pas_de_session(
        self, adresse_reelle: tuple[UUID, str], admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        admin.execute(
            "update auth.users set banned_until = now() + interval '1 day' where id = %s", (personne,)
        )
        with pytest.raises(psycopg.errors.InvalidAuthorizationSpecification), connecte(DSN_API) as cx:
            cx.execute(
                "select public.ouvre_la_session(%s, %s, 'chrome', 'linux', null, 'code')",
                (personne, token_bytes(32)),
            )


# ── La concurrence ──────────────────────────────────────────────────────────


def en_parallele[T](fois: int, travail: Callable[[], T]) -> list[T]:
    depart = threading.Barrier(fois)

    def un_appel(_: int) -> T:
        depart.wait(timeout=30)
        return travail()

    with ThreadPoolExecutor(max_workers=fois) as pool:
        return list(pool.map(un_appel, range(fois)))


def ouvre_ensemble(code: Code, fois: int, empreinte: Callable[[], bytes | None]) -> list[Resultat]:
    """`fois` vérifications parties ENSEMBLE : les connexions sont ouvertes avant la barrière."""
    connexions = [connecte(DSN_API) for _ in range(fois)]
    depart = threading.Barrier(fois)

    def un_appel(cx: psycopg.Connection[Ligne]) -> Resultat:
        depart.wait(timeout=30)
        return ouvre(code, empreinte=empreinte(), cx=cx)

    try:
        with ThreadPoolExecutor(max_workers=fois) as pool:
            return list(pool.map(un_appel, connexions))
    finally:
        for cx in connexions:
            cx.close()


class TestConcurrence:
    @pytest.mark.parametrize("reelle", [True, False], ids=["connue", "inconnue"])
    def test_cinquante_faux_en_parallele_font_exactement_cinq_verifications(
        self, reelle: bool, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        code = pose(admin, cles, adresse_reelle[0] if reelle else None)
        rendus = ouvre_ensemble(code, 50, faux)
        assert set(rendus) == {REFUS}
        assert essais(admin, code) == (5, False, False)

    def test_vingt_soumissions_du_bon_code_ouvrent_une_seule_session(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)
        rendus = ouvre_ensemble(code, 20, lambda: None)
        assert sum(1 for ouverte, _, _ in rendus if ouverte) == 1
        assert len(sessions(admin, personne)) == 1 and essais(admin, code)[1] is True

    async def test_une_fermeture_de_toutes_les_sessions_qui_precede_fait_refuser_le_code(
        self,
        base: Base,
        adresse_reelle: tuple[UUID, str],
        fabrique: Fabrique,
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        """S6 : B (ouverture par code) attend le verrou tenu par A (fermeture) ; A valide, B est refusé."""
        personne, _ = adresse_reelle
        gardee = fabrique.session(personne)
        code = pose(admin, cles, personne)

        def fermeture(a: psycopg.Connection[Ligne]) -> None:
            a.execute(
                "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)", (personne, gardee.id)
            )

        async def b() -> Resultat:
            async with base.connexion() as curseur:
                await curseur.execute(
                    OUVRE, (code.id, code.cle, code.empreinte, token_bytes(32), "chrome", "linux", None, None)
                )
                ligne = await curseur.fetchone()
            assert ligne is not None
            return ligne["ouverte"], ligne["session"], ligne["personne"]

        assert await course(admin, fermeture, b, "ouvre_une_session_par_code") == REFUS
        assert essais(admin, code) == (0, False, True)  # révoqué par la fermeture, rien d'ouvert après elle
        assert [s for s, _ in sessions(admin, personne)] == [gardee.id]

    async def test_la_verification_attend_le_verrou_de_la_personne_puis_reussit(
        self, base: Base, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        """Le verrou seul, sans toucher la ligne du code : B attend A, puis ouvre la session."""
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)

        async def b() -> Resultat:
            async with base.connexion() as curseur:
                valeurs = (code.id, code.cle, code.empreinte, token_bytes(32), "chrome", "linux", None, None)
                await curseur.execute(OUVRE, valeurs)
                ligne = await curseur.fetchone()
            assert ligne is not None
            return ligne["ouverte"], ligne["session"], ligne["personne"]

        ouverte, _, titulaire = await course(
            admin, lambda a: a.execute("select public.verrouille_la_personne(%s)", (personne,)), b,
            "ouvre_une_session_par_code",
        )  # fmt: skip
        assert ouverte and titulaire == personne

    async def test_la_verification_prend_la_ligne_d_auth_avant_celle_du_code(
        self, base: Base, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        """Compte en cours de suppression (Auth) : B attend la ligne d'`auth.users` sans tenir celle du code.

        Sinon B tiendrait le code et attendrait le compte pendant que la suppression, qui tient le compte,
        attend le code (cascade) : `40P01`, et la victime pourrait être la suppression."""
        personne, _ = adresse_reelle
        code = pose(admin, cles, personne)

        async def b() -> Resultat:
            async with base.connexion() as curseur:
                valeurs = (code.id, code.cle, code.empreinte, token_bytes(32), "chrome", "linux", None, None)
                await curseur.execute(OUVRE, valeurs)
                ligne = await curseur.fetchone()
            assert ligne is not None
            return ligne["ouverte"], ligne["session"], ligne["personne"]

        with psycopg.connect(DSN_ADMIN) as a:
            # La ligne du compte tenue comme le fait sa suppression, sans toucher la ligne du code.
            a.execute("select 1 from auth.users where id = %s for update", (personne,))
            tache = asyncio.create_task(b())
            try:
                pid = await attend_un_verrou(admin, "ouvre_une_session_par_code", a.info.backend_pid)
                ecrit = admin.execute(
                    "select 1 from pg_locks where pid = %s and locktype = 'transactionid' and granted", (pid,)
                ).fetchone()
                assert ecrit is None, "B tient déjà une ligne (le code) en attendant le compte"
            finally:
                a.rollback()  # B reprend
            assert (await tache)[0] is True

    def test_demande_verification_et_fermeture_entrelacees_ne_s_interbloquent_jamais(
        self,
        adresse_reelle: tuple[UUID, str],
        fabrique: Fabrique,
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        """L'ordre clé de compte, personne, lignes : aucun `40P01` entre trois fonctions qui se croisent."""
        personne, email = adresse_reelle
        gardee = fabrique.session(personne)
        reelle, factice = (cles.neuve(), token_bytes(32)), (cles.neuve(), token_bytes(32))
        adresse_factice = inconnue()

        def demande_puis_verifie(
            adresse: str, cle_et_empreinte: tuple[bytes, bytes], titulaire: UUID | None
        ) -> Resultat:
            cle, empreinte = cle_et_empreinte  # la même empreinte à chaque tour : le bon code reste le bon
            identifiant = demande(adresse, cle, hash_=empreinte)[1]
            return ouvre(Code(identifiant, cle, empreinte, titulaire))

        def ferme_tout() -> Resultat:
            with connecte(DSN_API) as cx:
                cx.execute(
                    "select public.confirme_le_changement_de_mot_de_passe(%s, %s, null)",
                    (personne, gardee.id),
                )
            return REFUS

        actions: list[Callable[[], Resultat]] = [
            lambda: demande_puis_verifie(email, reelle, personne),
            lambda: demande_puis_verifie(adresse_factice, factice, None),
            ferme_tout,
        ]
        tour, verrou = iter(range(10_000)), threading.Lock()

        def travail() -> Resultat:
            with verrou:
                numero = next(tour)
            return actions[numero % len(actions)]()

        rendus = en_parallele(24, travail)  # une exception d'un fil (`40P01` compris) remonte par `pool.map`
        ouvertes = [session for ouverte, session, _ in rendus if ouverte]
        assert ouvertes, "le chemin de succès n'a jamais été joué"
        presentes = admin.execute(
            "select count(*) from public.login_session where id = any(%s)", (ouvertes,)
        ).fetchone()
        assert presentes == (len(ouvertes),)


# ── Les crans retombent 24 h après la FIN du blocage (S7, relevé en revue) ──

T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")


@pytest.fixture
def cle_de_limite(admin: psycopg.Connection[Ligne]) -> Iterator[bytes]:
    cle = token_bytes(32)
    yield cle
    admin.execute("delete from public.login_throttle where key = %s", (cle,))


def attente(admin: psycopg.Connection[Ligne], cle: bytes, quand: datetime) -> int:
    ligne = admin.execute(CRENEAU, (cle, quand)).fetchone()
    assert ligne is not None
    return int(ligne[0])  # type: ignore[call-overload]


def jusqu_au_plafond(admin: psycopg.Connection[Ligne], cle: bytes) -> datetime:
    """Escalade pour de vrai (cinq essais, le sixième bloque, on attend la fin) jusqu'à 24 h ; rend la fin."""
    maintenant, derniere = T0, 0
    while derniere != 86400:
        assert [attente(admin, cle, maintenant) for _ in range(5)] == [0] * 5
        derniere = attente(admin, cle, maintenant)
        assert derniere > 0
        maintenant += timedelta(seconds=derniere)
    return maintenant


class TestRetombeeDesCrans:
    def test_apres_le_blocage_de_24_h_un_essai_immediat_passe_puis_le_blocage_est_de_24_h(
        self, admin: psycopg.Connection[Ligne], cle_de_limite: bytes
    ) -> None:
        fin = jusqu_au_plafond(admin, cle_de_limite)
        assert [attente(admin, cle_de_limite, fin) for _ in range(5)] == [0] * 5
        assert attente(admin, cle_de_limite, fin) == 86400  # jamais 15 minutes

    @pytest.mark.parametrize(
        ("apres_la_fin", "bloquee"),
        [(JOUR - timedelta(seconds=1), 86400), (JOUR, 900)],
        ids=["une_seconde_avant_24h", "24h_apres_la_fin"],
    )
    def test_les_crans_retombent_24_h_apres_la_fin_du_blocage_pas_avant(
        self, apres_la_fin: timedelta, bloquee: int, admin: psycopg.Connection[Ligne], cle_de_limite: bytes
    ) -> None:
        fin = jusqu_au_plafond(admin, cle_de_limite) + apres_la_fin
        assert [attente(admin, cle_de_limite, fin) for _ in range(5)] == [0] * 5
        assert attente(admin, cle_de_limite, fin) == bloquee

    def test_la_premiere_escalade_est_toujours_de_15_minutes(
        self, admin: psycopg.Connection[Ligne], cle_de_limite: bytes
    ) -> None:
        assert [attente(admin, cle_de_limite, T0) for _ in range(5)] == [0] * 5
        assert attente(admin, cle_de_limite, T0) == 900


def test_la_facon_de_naitre_est_une_liste_fermee(admin: psycopg.Connection[Ligne]) -> None:
    ligne = admin.execute(
        "select pg_get_constraintdef(oid) from pg_constraint"
        " where conname = 'login_session_opened_with_check'"
    ).fetchone()
    assert ligne is not None
    assert set(re.findall(r"'([a-z]+)'::text", str(ligne[0]))) == {"code", "cle", "invitation", "autre"}
