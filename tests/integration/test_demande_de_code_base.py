"""0.4bis S5a : la demande de code côté base (migration 0147 ; spec § 3.6, § 4 ; D3, B6), en base locale.

Données inventées. Les fonctions publiques se jouent en `popote_api` (seul rôle qui les exécute) ; le temps
est injecté par les variantes à horloge de `private` (en administrateur). Chaque test tire ses clés et
retire ses lignes : la base est partagée.
"""

import re
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from secrets import token_bytes
from uuid import UUID, uuid4

import psycopg
import pytest
from _connexions import DSN_API, connecte
from _fabrique import Fabrique

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
T0 = datetime.fromisoformat("2031-03-01T12:00:00+00:00")
MIN = timedelta(minutes=1)
DEMANDE = "select personne, demande, nouveau from public.demande_un_code(%s, %s, %s, %s, %s, %s)"
CRENEAUX = "select private.prend_les_creneaux_de_demande(%s, %s, %s, 10, 3, 6, 900, 3600, %s)"
ENVOI = "select private.prend_un_envoi(60, 3600, %s)"
PORTEES_DE_S5 = {"code_ip", "code_paire", "code_compte", "mail_global"}


class Cles:
    """Les clés et les identifiants que le test a tirés : leurs lignes partent à la fin, même s'il échoue."""

    def __init__(self) -> None:
        self.octets: list[bytes] = []

    def neuve(self) -> bytes:
        cle = token_bytes(32)
        self.octets.append(cle)
        return cle


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


@pytest.fixture
def cles(admin: psycopg.Connection[Ligne]) -> Iterator[Cles]:
    tirees = Cles()
    yield tirees
    admin.execute("delete from public.login_code where account_key = any(%s)", (tirees.octets,))
    admin.execute("delete from public.security_event where account_key = any(%s)", (tirees.octets,))
    admin.execute("delete from public.login_throttle where key = any(%s)", (tirees.octets,))


@pytest.fixture
def sans_envoi_global(admin: psycopg.Connection[Ligne]) -> Iterator[None]:
    """La ligne du coupe-circuit est unique et partagée : vidée avant et après (écrite en 2031)."""
    admin.execute("delete from public.login_throttle where scope = 'mail_global'")
    yield
    admin.execute("delete from public.login_throttle where scope = 'mail_global'")


@pytest.fixture
def adresse_reelle(fabrique: Fabrique, admin: psycopg.Connection[Ligne]) -> tuple[UUID, str]:
    personne = fabrique.personne(fabrique.foyer())
    ligne = admin.execute("select email from auth.users where id = %s", (personne.id,)).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], str)
    return personne.id, ligne[0]


def inconnue() -> str:
    return f"inconnue-{uuid4().hex[:12]}@test.local"


def demande(
    email: str,
    cle: bytes,
    *,
    hash_: bytes | None = None,
    identifiant: UUID | None = None,
    request_id: str | None = None,
) -> tuple[UUID | None, UUID, bool]:
    """Une demande jouée en `popote_api`, validée : la fonction rend (personne, identifiant, code neuf)."""
    with connecte(DSN_API) as cx:
        ligne = cx.execute(
            DEMANDE,
            (email, cle, identifiant or uuid4(), hash_ or token_bytes(32), token_bytes(32), request_id),
        ).fetchone()
        cx.commit()
    assert ligne is not None
    return ligne  # type: ignore[return-value]


def codes(admin: psycopg.Connection[Ligne], cle: bytes) -> list[dict[str, object]]:
    curseur = admin.execute(
        "select id, person_id, code_hash, attempts, created_at, expires_at, used_at, revoked_at"
        " from public.login_code where account_key = %s order by created_at, id",
        (cle,),
    )
    noms = [colonne.name for colonne in curseur.description or []]
    return [dict(zip(noms, ligne, strict=True)) for ligne in curseur.fetchall()]


def actifs(admin: psycopg.Connection[Ligne], cle: bytes) -> int:
    return sum(1 for ligne in codes(admin, cle) if ligne["used_at"] is None and ligne["revoked_at"] is None)


def vieillit(admin: psycopg.Connection[Ligne], cle: bytes, de: timedelta) -> None:
    """Recule la naissance du code (et son échéance, que le CHECK lie à elle)."""
    admin.execute(
        "update public.login_code set created_at = created_at - %s, expires_at = expires_at - %s"
        " where account_key = %s",
        (de, de, cle),
    )


def evenements(admin: psycopg.Connection[Ligne], cle: bytes) -> list[Ligne]:
    return admin.execute(
        "select kind, person_id, session_id, invitation_id, ip_hash, request_id"
        " from public.security_event where account_key = %s",
        (cle,),
    ).fetchall()


# ── La demande : même travail pour une adresse connue et inconnue ───────────


class TestDemandeUnCode:
    def test_un_compte_reel_recoit_une_ligne_a_son_nom_et_un_evenement(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, email = adresse_reelle
        cle, hash_, identifiant = cles.neuve(), token_bytes(32), uuid4()
        marque = uuid4().hex
        rendu = demande(email, cle, hash_=hash_, identifiant=identifiant, request_id=marque)
        assert rendu == (personne, identifiant, True)
        (ligne,) = codes(admin, cle)
        assert ligne["id"] == identifiant and ligne["person_id"] == personne
        assert bytes(ligne["code_hash"]) == hash_  # type: ignore[arg-type]
        assert ligne["attempts"] == 0 and ligne["used_at"] is None and ligne["revoked_at"] is None
        assert ligne["expires_at"] - ligne["created_at"] == 10 * MIN  # type: ignore[operator]
        (evenement,) = evenements(admin, cle)
        assert evenement[:4] == ("code_demande", personne, None, None) and evenement[5] == marque

    def test_une_adresse_inconnue_recoit_une_ligne_factice_sans_evenement(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        cle, identifiant = cles.neuve(), uuid4()
        assert demande(inconnue(), cle, identifiant=identifiant) == (None, identifiant, True)
        (ligne,) = codes(admin, cle)
        assert ligne["person_id"] is None and ligne["expires_at"] - ligne["created_at"] == 10 * MIN  # type: ignore[operator]
        assert evenements(admin, cle) == []  # une IP ne remplit pas le journal (90 jours)

    @pytest.mark.parametrize("etat", ["banni", "supprime", "sans_profil"])
    def test_un_compte_banni_supprime_ou_sans_profil_recoit_une_ligne_factice(
        self,
        etat: str,
        adresse_reelle: tuple[UUID, str],
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        personne, email = adresse_reelle
        if etat == "banni":
            admin.execute(
                "update auth.users set banned_until = now() + interval '1 day' where id = %s", (personne,)
            )
        elif etat == "supprime":
            admin.execute("update auth.users set deleted_at = now() where id = %s", (personne,))
        else:
            admin.execute("delete from public.user_profile where id = %s", (personne,))
        cle = cles.neuve()
        rendu = demande(email, cle)
        assert rendu[0] is None and rendu[2] is True
        (ligne,) = codes(admin, cle)
        assert ligne["person_id"] is None
        assert evenements(admin, cle) == []

    def test_un_bannissement_echu_ne_compte_plus(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, email = adresse_reelle
        admin.execute(
            "update auth.users set banned_until = now() - interval '1 minute' where id = %s", (personne,)
        )
        assert demande(email, cles.neuve())[0] == personne

    def test_l_adresse_se_compare_en_minuscules(self, adresse_reelle: tuple[UUID, str], cles: Cles) -> None:
        personne, email = adresse_reelle
        assert demande(email, cles.neuve())[0] == personne
        assert demande(email.upper(), cles.neuve())[0] is None  # l'appelant passe la forme normalisée

    def test_une_nouvelle_demande_revoque_le_code_precedent(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        _, email = adresse_reelle
        cle = cles.neuve()
        premier, second = uuid4(), uuid4()
        demande(email, cle, identifiant=premier)
        vieillit(admin, cle, 61 * timedelta(seconds=1))
        assert demande(email, cle, identifiant=second)[1:] == (second, True)
        ancien, neuf = codes(admin, cle)
        assert ancien["id"] == premier and ancien["revoked_at"] is not None
        assert neuf["id"] == second and neuf["revoked_at"] is None
        assert actifs(admin, cle) == 1
        assert len(evenements(admin, cle)) == 2

    def test_un_code_de_moins_de_60_secondes_n_est_pas_remplace(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, email = adresse_reelle
        cle, hash_, premier = cles.neuve(), token_bytes(32), uuid4()
        demande(email, cle, hash_=hash_, identifiant=premier)
        vieillit(admin, cle, timedelta(seconds=59))
        rendu = demande(email, cle, hash_=token_bytes(32), identifiant=uuid4())
        assert rendu == (personne, premier, False)  # le même identifiant, rien de neuf
        (ligne,) = codes(admin, cle)
        assert ligne["id"] == premier and bytes(ligne["code_hash"]) == hash_ and ligne["revoked_at"] is None  # type: ignore[arg-type]
        assert len(evenements(admin, cle)) == 1

    def test_une_adresse_inconnue_se_comporte_de_meme_dans_les_60_secondes(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        email, cle, premier = inconnue(), cles.neuve(), uuid4()
        demande(email, cle, identifiant=premier)
        assert demande(email, cle) == (None, premier, False)
        assert len(codes(admin, cle)) == 1

    def test_au_dela_de_60_secondes_un_code_neuf_remplace_l_ancien(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        _, email = adresse_reelle
        cle = cles.neuve()
        demande(email, cle)
        vieillit(admin, cle, timedelta(seconds=61))
        assert demande(email, cle)[2] is True
        assert len(codes(admin, cle)) == 2

    def test_un_code_mort_aux_cinq_essais_ne_se_rejoue_pas(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        _, email = adresse_reelle
        cle = cles.neuve()
        demande(email, cle)
        admin.execute("update public.login_code set attempts = 5 where account_key = %s", (cle,))
        assert demande(email, cle)[2] is True
        assert actifs(admin, cle) == 1

    def test_un_code_utilise_n_est_pas_touche_par_la_revocation(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        _, email = adresse_reelle
        cle = cles.neuve()
        demande(email, cle)
        admin.execute("update public.login_code set used_at = now() where account_key = %s", (cle,))
        assert (
            demande(email, cle)[2] is True
        )  # un code utilisé n'est pas « actif » : pas de rejeu dans les 60 s
        utilise, neuf = codes(admin, cle)
        assert utilise["used_at"] is not None and utilise["revoked_at"] is None
        assert neuf["used_at"] is None and neuf["revoked_at"] is None

    @pytest.mark.parametrize("reelle", [True, False], ids=["connue", "inconnue"])
    def test_cinquante_demandes_simultanees_ne_laissent_qu_une_ligne_active(
        self,
        reelle: bool,
        adresse_reelle: tuple[UUID, str],
        cles: Cles,
        admin: psycopg.Connection[Ligne],
    ) -> None:
        email = adresse_reelle[1] if reelle else inconnue()
        cle = cles.neuve()
        depart = threading.Barrier(50)

        def une_demande(_: int) -> tuple[UUID | None, UUID, bool]:
            depart.wait(timeout=30)
            return demande(email, cle)

        with ThreadPoolExecutor(max_workers=50) as pool:
            rendus = list(pool.map(une_demande, range(50)))
        assert actifs(admin, cle) == 1 and len(codes(admin, cle)) == 1
        assert sum(1 for r in rendus if r[2]) == 1  # un seul code neuf : les 49 autres rejouent le même
        assert {r[1] for r in rendus} == {codes(admin, cle)[0]["id"]}

    @pytest.mark.parametrize(
        "choix",
        ["email", "cle", "identifiant", "hash", "ip", "cle_courte", "hash_court", "ip_courte"],
    )
    def test_un_parametre_nul_ou_de_mauvaise_taille_est_refuse(self, choix: str, cles: Cles) -> None:
        valeurs: dict[str, object] = {
            "email": inconnue(),
            "cle": cles.neuve(),
            "identifiant": uuid4(),
            "hash": token_bytes(32),
            "ip": token_bytes(32),
        }
        if choix.endswith("_courte") or choix.endswith("_court"):
            valeurs[choix.split("_")[0]] = token_bytes(31)
        else:
            valeurs[choix] = None
        with connecte(DSN_API) as cx, pytest.raises(psycopg.errors.InvalidParameterValue):
            cx.execute(
                DEMANDE,
                (
                    valeurs["email"],
                    valeurs["cle"],
                    valeurs["identifiant"],
                    valeurs["hash"],
                    valeurs["ip"],
                    None,
                ),
            )

    def test_supprimer_le_compte_emporte_ses_codes(
        self, adresse_reelle: tuple[UUID, str], cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        personne, email = adresse_reelle
        cle = cles.neuve()
        demande(email, cle)
        admin.execute("delete from public.user_profile where id = %s", (personne,))
        admin.execute("delete from auth.users where id = %s", (personne,))
        assert codes(admin, cle) == []


# ── La table ────────────────────────────────────────────────────────────────


class TestTable:
    def insere(self, admin: psycopg.Connection[Ligne], cle: bytes, **colonnes: object) -> None:
        valeurs: dict[str, object] = {"account_key": cle, "code_hash": token_bytes(32)} | colonnes
        noms = ", ".join(valeurs)
        admin.execute(
            f"insert into public.login_code ({noms}) values ({', '.join(['%s'] * len(valeurs))})",  # noqa: S608  # noms écrits ici
            tuple(valeurs.values()),
        )

    def test_la_base_refuse_une_echeance_de_plus_de_10_minutes(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            admin.execute(
                "insert into public.login_code (account_key, code_hash, expires_at)"
                " values (%s, %s, now() + interval '10 minutes 1 second')",
                (cles.neuve(), token_bytes(32)),
            )

    def test_la_base_refuse_une_echeance_avant_la_creation(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            self.insere(admin, cles.neuve(), expires_at=T0 - MIN, created_at=T0)

    @pytest.mark.parametrize("essais", [-1, 6])
    def test_la_base_refuse_un_nombre_d_essais_hors_de_0_a_5(
        self, essais: int, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            self.insere(admin, cles.neuve(), attempts=essais)

    @pytest.mark.parametrize("colonne", ["account_key", "code_hash"])
    def test_la_base_refuse_une_empreinte_qui_ne_fait_pas_32_octets(
        self, colonne: str, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            self.insere(admin, cles.neuve(), **{colonne: b"\x01" * 31})

    def test_un_seul_code_actif_par_cle_de_compte(self, cles: Cles, admin: psycopg.Connection[Ligne]) -> None:
        cle = cles.neuve()
        self.insere(admin, cle)
        with pytest.raises(psycopg.errors.UniqueViolation):
            self.insere(admin, cle)
        self.insere(admin, cles.neuve())  # une autre clé : autant qu'on veut

    @pytest.mark.parametrize("colonne", ["used_at", "revoked_at"])
    def test_un_code_utilise_ou_revoque_ne_tient_plus_la_place(
        self, colonne: str, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        cle = cles.neuve()
        self.insere(admin, cle, **{colonne: T0})
        self.insere(admin, cle)
        self.insere(admin, cle, **{colonne: T0})
        assert len(codes(admin, cle)) == 3


# ── Les créneaux de la demande ──────────────────────────────────────────────


def creneau(admin: psycopg.Connection[Ligne], ip: bytes, paire: bytes, compte: bytes, quand: datetime) -> int:
    ligne = admin.execute(CRENEAUX, (ip, paire, compte, quand)).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], int)
    return ligne[0]


def essais(admin: psycopg.Connection[Ligne], portee: str, cle: bytes) -> int | None:
    ligne = admin.execute(
        "select attempts from public.login_throttle where scope = %s and key = %s", (portee, cle)
    ).fetchone()
    return None if ligne is None else int(ligne[0])  # type: ignore[call-overload]


def sans_blocage(admin: psycopg.Connection[Ligne], portee: str, cle: bytes) -> bool:
    """Sans escalade : un refus n'écrit ni cran ni blocage, seulement l'attente de la fin de fenêtre."""
    ligne = admin.execute(
        "select strikes, blocked_until from public.login_throttle where scope = %s and key = %s",
        (portee, cle),
    ).fetchone()
    return ligne == (0, None)


class TestCreneauxDeLaDemande:
    def test_la_paire_passe_trois_fois_puis_le_quatrieme_attend(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        ip, paire, compte = cles.neuve(), cles.neuve(), cles.neuve()
        assert [creneau(admin, ip, paire, compte, T0) for _ in range(3)] == [0, 0, 0]
        attente = creneau(admin, ip, paire, compte, T0)
        assert attente == 900  # la fenêtre entière : sans escalade
        assert creneau(admin, ip, paire, cles.neuve(), T0 + 2 * MIN) == 780  # elle ne se prolonge pas

    def test_le_compte_passe_six_fois_par_heure_meme_depuis_six_ip(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        compte = cles.neuve()
        for _ in range(6):
            assert creneau(admin, cles.neuve(), cles.neuve(), compte, T0) == 0
        assert creneau(admin, cles.neuve(), cles.neuve(), compte, T0 + 10 * MIN) == 3000
        assert sans_blocage(admin, "code_compte", compte)

    def test_l_ip_passe_dix_fois_puis_le_onzieme_attend(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        ip = cles.neuve()
        for _ in range(10):
            assert creneau(admin, ip, cles.neuve(), cles.neuve(), T0) == 0
        assert creneau(admin, ip, cles.neuve(), cles.neuve(), T0) == 900
        assert sans_blocage(admin, "code_ip", ip)

    def test_dix_adresses_d_une_ip_ne_privent_personne_d_autre(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        ip_hostile, ip_de_la_personne = cles.neuve(), cles.neuve()
        for _ in range(10):
            creneau(admin, ip_hostile, cles.neuve(), cles.neuve(), T0)
        assert creneau(admin, ip_hostile, cles.neuve(), cles.neuve(), T0) > 0
        assert creneau(admin, ip_de_la_personne, cles.neuve(), cles.neuve(), T0) == 0

    def test_une_ip_bloquee_n_use_ni_la_paire_ni_le_compte(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        ip, paire, compte = cles.neuve(), cles.neuve(), cles.neuve()
        for _ in range(10):
            creneau(admin, ip, cles.neuve(), cles.neuve(), T0)
        assert creneau(admin, ip, paire, compte, T0) > 0
        assert essais(admin, "code_paire", paire) is None and essais(admin, "code_compte", compte) is None

    def test_une_paire_bloquee_n_use_pas_le_compte(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        ip, paire, compte = cles.neuve(), cles.neuve(), cles.neuve()
        for _ in range(3):
            creneau(admin, ip, paire, compte, T0)
        assert essais(admin, "code_compte", compte) == 3
        assert creneau(admin, ip, paire, compte, T0) > 0
        assert essais(admin, "code_compte", compte) == 3  # le refus de la paire n'a pas compté sur le compte

    def test_un_refus_ne_compte_pas_et_ne_pose_aucun_blocage(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        ip, paire, compte = cles.neuve(), cles.neuve(), cles.neuve()
        for _ in range(5):
            creneau(admin, ip, paire, compte, T0)
        assert essais(admin, "code_paire", paire) == 3 and essais(admin, "code_ip", ip) == 5
        assert sans_blocage(admin, "code_paire", paire)

    def test_la_paire_et_l_ip_repassent_apres_15_minutes_et_le_compte_apres_une_heure(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        ip, paire, compte = cles.neuve(), cles.neuve(), cles.neuve()
        for _ in range(3):
            creneau(admin, ip, paire, compte, T0)
        assert creneau(admin, ip, paire, compte, T0 + 15 * MIN - timedelta(seconds=1)) == 1
        assert creneau(admin, ip, paire, compte, T0 + 15 * MIN) == 0
        ip2, paire2, compte2 = cles.neuve(), cles.neuve(), cles.neuve()
        for _ in range(6):
            creneau(admin, cles.neuve(), cles.neuve(), compte2, T0)
        assert creneau(admin, ip2, paire2, compte2, T0 + 60 * MIN - timedelta(seconds=1)) == 1
        assert creneau(admin, ip2, paire2, compte2, T0 + 60 * MIN) == 0

    def test_les_portees_de_la_demande_ne_touchent_pas_celles_de_la_connexion(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        cle = cles.neuve()
        creneau(admin, cle, cle, cle, T0)
        lignes = admin.execute(
            "select scope from public.login_throttle where key = %s order by scope", (cle,)
        ).fetchall()
        assert lignes == [("code_compte",), ("code_ip",), ("code_paire",)]

    @pytest.mark.parametrize("position", [0, 1, 2])
    def test_une_cle_de_la_mauvaise_taille_est_refusee(
        self, position: int, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        trois = [cles.neuve(), cles.neuve(), cles.neuve()]
        trois[position] = b"\x01" * 31
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            creneau(admin, *trois, T0)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "bornes", ["0, 3, 6, 900, 3600", "10, 0, 6, 900, 3600", "10, 3, 0, 900, 3600", "10, 3, 6, 0, 3600"]
    )
    def test_une_limite_nulle_ne_desactive_pas_la_limite(
        self, bornes: str, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            admin.execute(
                f"select private.prend_les_creneaux_de_demande(%s, %s, %s, {bornes}, %s)",
                (cles.neuve(), cles.neuve(), cles.neuve(), T0),
            )

    def test_la_fonction_publique_applique_les_valeurs_du_plan(self, cles: Cles) -> None:
        ip, paire, compte = cles.neuve(), cles.neuve(), cles.neuve()
        with connecte(DSN_API) as cx:
            attentes = [
                cx.execute(
                    "select public.prend_les_creneaux_de_demande(%s, %s, %s)", (ip, paire, compte)
                ).fetchone()
                for _ in range(4)
            ]
            cx.commit()
        assert attentes[:3] == [(0,), (0,), (0,)]
        assert attentes[3] is not None and 0 < attentes[3][0] <= 900


class TestCoupeCircuitGlobal:
    def test_soixante_envois_par_heure_puis_le_suivant_attend(
        self, sans_envoi_global: None, admin: psycopg.Connection[Ligne]
    ) -> None:
        for _ in range(60):
            assert admin.execute(ENVOI, (T0,)).fetchone() == (0,)
        assert admin.execute(ENVOI, (T0 + 30 * MIN,)).fetchone() == (1800,)
        assert admin.execute(ENVOI, (T0 + 60 * MIN,)).fetchone() == (0,)

    def test_le_refus_ne_prolonge_rien(
        self, sans_envoi_global: None, admin: psycopg.Connection[Ligne]
    ) -> None:
        for _ in range(60):
            admin.execute(ENVOI, (T0,))
        for _ in range(5):
            admin.execute(ENVOI, (T0 + 10 * MIN,))
        assert admin.execute(ENVOI, (T0 + 60 * MIN,)).fetchone() == (0,)

    def test_la_fonction_publique_prend_un_envoi_en_popote_api(
        self, sans_envoi_global: None, admin: psycopg.Connection[Ligne]
    ) -> None:
        with connecte(DSN_API) as cx:
            assert cx.execute("select public.prend_un_envoi()").fetchone() == (0,)
            cx.commit()
        assert admin.execute(
            "select attempts from public.login_throttle where scope = 'mail_global'"
        ).fetchall() == [(1,)]


# ── La purge ────────────────────────────────────────────────────────────────

PASSE = datetime.fromisoformat(
    "2020-06-01T12:00:00+00:00"
)  # nul autre que ces tests n'a d'échéance si ancienne


class TestPurge:
    def ligne(self, admin: psycopg.Connection[Ligne], cle: bytes, echeance: datetime) -> None:
        admin.execute(
            "insert into public.login_code (account_key, code_hash, created_at, expires_at, revoked_at)"
            " values (%s, %s, %s, %s, %s)",
            (cle, token_bytes(32), echeance - 10 * MIN, echeance, PASSE),
        )

    def purge(self, admin: psycopg.Connection[Ligne], lot: int = 5000) -> int:
        ligne = admin.execute("select private.purge_login_code(%s, %s)", (PASSE, lot)).fetchone()
        assert ligne is not None
        assert isinstance(ligne[0], int)
        return ligne[0]

    def test_un_jour_moins_une_seconde_reste_un_jour_plus_une_seconde_part(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        garde, efface = cles.neuve(), cles.neuve()
        self.ligne(admin, garde, PASSE - timedelta(days=1) + timedelta(seconds=1))
        self.ligne(admin, efface, PASSE - timedelta(days=1) - timedelta(seconds=1))
        assert self.purge(admin) == 1
        assert len(codes(admin, garde)) == 1 and codes(admin, efface) == []

    def test_la_purge_est_idempotente_et_se_fait_par_lots(
        self, cles: Cles, admin: psycopg.Connection[Ligne]
    ) -> None:
        anciennes = [cles.neuve() for _ in range(5)]
        for cle in anciennes:
            self.ligne(admin, cle, PASSE - timedelta(days=3))
        assert self.purge(admin, lot=2) == 5
        assert self.purge(admin, lot=2) == 0
        assert all(codes(admin, cle) == [] for cle in anciennes)

    def test_un_lot_nul_est_refuse(self, admin: psycopg.Connection[Ligne]) -> None:
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            self.purge(admin, lot=0)


# ── Les portées et les droits ───────────────────────────────────────────────

FONCTIONS = [
    "public.demande_un_code(text, bytea, uuid, bytea, bytea, text)",
    "public.prend_un_envoi(integer, integer)",
    "public.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer, integer)",
    "private.purge_login_code(timestamptz, integer)",
]


@pytest.mark.parametrize("fonction", FONCTIONS)
def test_les_fonctions_security_definer_ont_un_search_path_vide(
    fonction: str, admin: psycopg.Connection[Ligne]
) -> None:
    ligne = admin.execute(
        "select prosecdef, proconfig from pg_proc where oid = %s::regprocedure", (fonction,)
    ).fetchone()
    assert ligne == (True, ['search_path=""'])


def test_les_portees_de_la_base_sont_celles_que_les_fonctions_emploient(
    admin: psycopg.Connection[Ligne],
) -> None:
    """Dérive : une fonction qui compterait sur une portée que le CHECK refuse échouerait en service."""
    definition = admin.execute(
        "select pg_get_constraintdef(oid) from pg_constraint where conname = 'login_throttle_scope_check'"
    ).fetchone()
    assert definition is not None
    autorisees = set(re.findall(r"'([a-z_]+)'::text", str(definition[0])))
    sources = "\n".join(
        str(ligne[0])
        for ligne in admin.execute(
            "select prosrc from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
            " where n.nspname in ('public', 'private') and prosrc like '%%prend_un_creneau(%%'"
        ).fetchall()
    )
    employees = set(re.findall(r"prend_un_creneau\(\s*'([a-z_]+)'", sources))
    assert employees <= autorisees
    assert PORTEES_DE_S5 <= employees <= autorisees
    assert autorisees == {
        "account", "ip", "reset", "invitation_ip", "invitation_link", *PORTEES_DE_S5,
    }  # fmt: skip
