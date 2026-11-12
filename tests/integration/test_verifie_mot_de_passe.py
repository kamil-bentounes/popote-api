"""Spec § 4, B15, B24 : `verifie_mot_de_passe` et `verifie_mot_de_passe_de` (migration 0137).

Base locale par défaut ; `POPOTE_TEST_DSN_API` et `POPOTE_TEST_DSN_ADMIN` les rejouent sur un autre serveur.
La fonction se joue comme `popote_api`, le seul rôle qui l'exécute ; le droit se lit aussi par
`set local role`
(le rôle COURANT, B3). Les hachages sont écrits en direct dans `auth.users` ; un compte réel de GoTrue local
(administration d'Auth) prouve que son hachage est reconnu.
"""

import statistics
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from _connexions import DSN_API, connecte
from _fabrique import Fabrique
from psycopg import errors, sql

from popote_api.security.empreintes import email_normalise

pytestmark = pytest.mark.integration

Ligne = tuple[object, ...]
VERIFIE = "select public.verifie_mot_de_passe(%s, %s)"
VERIFIE_DE = "select public.verifie_mot_de_passe_de(%s, %s)"
MOT_DE_PASSE = "un-mot-de-passe-assez-long"
SEPT_CENT = 72
FACTICE = "$2a$10$TomZERTB2nLik39KZPllf.Hj5WyG1pEvK9axxrIM7a3IdbHay1/Q2"
MAL_FORME = "$2a$10$" + "!" * 53  # 60 caractères, préfixe juste, sel illisible


@pytest.fixture
def cx_api() -> Iterator[psycopg.Connection[Ligne]]:
    with connecte(DSN_API) as cx:
        assert cx.execute("select session_user").fetchone() == ("popote_api",)
        cx.rollback()
        yield cx


@pytest.fixture
def admin(fabrique: Fabrique) -> psycopg.Connection[Ligne]:
    return fabrique.admin


def hache(admin: psycopg.Connection[Ligne], mot_de_passe: str, cout: int = 10) -> str:
    ligne = admin.execute(
        "select extensions.crypt(%s, extensions.gen_salt('bf', %s))", (mot_de_passe, cout)
    ).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], str)
    assert ligne[0].startswith("$2a$")
    return ligne[0]


class Comptes:
    """Des comptes de test avec le hachage et l'état voulus ; `fabrique.nettoie()` les retire."""

    def __init__(self, fabrique: Fabrique) -> None:
        self.fabrique = fabrique
        self.admin = fabrique.admin

    def cree(self, hash_: str | None, **colonnes: object) -> tuple[UUID, str]:
        personne = self.fabrique.personne(self.fabrique.foyer())
        ligne = self.admin.execute("select email from auth.users where id = %s", (personne.id,)).fetchone()
        assert ligne is not None
        assert isinstance(ligne[0], str)
        valeurs = {"encrypted_password": hash_, **colonnes}
        affectations = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(nom)) for nom in valeurs)
        requete = sql.SQL("update auth.users set {} where id = %s").format(affectations)
        self.admin.execute(requete, (*valeurs.values(), personne.id))
        return personne.id, ligne[0]

    def bon(self, mot_de_passe: str = MOT_DE_PASSE, **colonnes: object) -> tuple[UUID, str]:
        return self.cree(hache(self.admin, mot_de_passe), **colonnes)


@pytest.fixture
def comptes(fabrique: Fabrique) -> Comptes:
    return Comptes(fabrique)


def verifie(cx: psycopg.Connection[Ligne], email: str | None, mot_de_passe: str | None) -> object:
    """Le résultat en sa propre transaction, comme une requête de l'API (contexte connexion)."""
    with cx.transaction():
        ligne = cx.execute(VERIFIE, (email, mot_de_passe)).fetchone()
    assert ligne is not None
    return ligne[0]


def verifie_de(cx: psycopg.Connection[Ligne], personne: UUID | None, mot_de_passe: str | None) -> object:
    with cx.transaction():
        ligne = cx.execute(VERIFIE_DE, (personne, mot_de_passe)).fetchone()
    assert ligne is not None
    return ligne[0]


# ── Le chemin normal ────────────────────────────────────────────────────────


def test_le_bon_mot_de_passe_rend_la_personne(cx_api: psycopg.Connection[Ligne], comptes: Comptes) -> None:
    personne, email = comptes.bon()
    assert verifie(cx_api, email, MOT_DE_PASSE) == personne


def test_un_mauvais_mot_de_passe_rend_null(cx_api: psycopg.Connection[Ligne], comptes: Comptes) -> None:
    _, email = comptes.bon()
    assert verifie(cx_api, email, MOT_DE_PASSE + "x") is None
    assert verifie(cx_api, email, MOT_DE_PASSE.upper()) is None


@pytest.mark.parametrize(
    "forme", [str.upper, lambda e: f"  {e} ", lambda e: email_normalise(f"\t{e.upper()}\n")]
)
def test_la_casse_et_les_espaces_de_l_adresse_ne_changent_pas_le_compte(
    forme: Callable[[str], str], cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    personne, email = comptes.bon()
    assert verifie(cx_api, forme(email), MOT_DE_PASSE) == personne


def test_la_forme_normalisee_de_l_api_retrouve_le_compte_pleine_largeur_comprise(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    personne, email = comptes.bon()
    # Le même texte écrit en caractères pleine largeur (U+FF01 à U+FF5E), que l'API ramène à l'ASCII.
    pleine_largeur = "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in email.upper())
    assert pleine_largeur != email
    assert verifie(cx_api, email_normalise(pleine_largeur), MOT_DE_PASSE) == personne


def test_une_adresse_n_est_pas_un_motif(cx_api: psycopg.Connection[Ligne], comptes: Comptes) -> None:
    _, email = comptes.bon()
    local, domaine = email.split("@")
    assert verifie(cx_api, f"{local[:3]}%@{domaine}", MOT_DE_PASSE) is None
    assert verifie(cx_api, f"{local[:3]}_{local[4:]}@{domaine}", MOT_DE_PASSE) is None


# ── Tous les refus rendent null, sans exception ─────────────────────────────

REFUS: dict[str, dict[str, object]] = {
    "hachage_vide": {"hash": ""},
    "hachage_nul": {"hash": None},
    "argon2id": {"hash": "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"},
    "malforme": {"hash": MAL_FORME},
    "trop_court": {"hash": "$2a$10$abc"},
    "banni_a_l_infini": {"colonnes": {"banned_until": "infinity"}},
    "banni_demain": {"colonnes": {"banned_until": "now() + interval '1 day'"}},
    "supprime": {"colonnes": {"deleted_at": "now()"}},
    "sso": {"colonnes": {"is_sso_user": True}},
    "anonyme": {"colonnes": {"is_anonymous": True}},
}
PREFIXES_REFUSES = {"md5": "$1$", "blowfish_y": "$2y$", "blowfish_b": "$2b$", "blowfish_x": "$2x$"}


def cree_refus(comptes: Comptes, cas: dict[str, object]) -> tuple[UUID, str]:
    colonnes: dict[str, object] = dict(cas.get("colonnes", {}))  # type: ignore[call-overload]
    for nom, valeur in list(colonnes.items()):
        if valeur == "now()" or str(valeur).startswith("now() +"):
            ligne = comptes.admin.execute(f"select {valeur}").fetchone()
            assert ligne is not None
            colonnes[nom] = ligne[0]
    if "hash" in cas:
        return comptes.cree(cas["hash"], **colonnes)  # type: ignore[arg-type]
    return comptes.bon(**colonnes)


@pytest.mark.parametrize("nom", list(REFUS))
def test_chaque_refus_rend_null_sans_exception(
    nom: str, cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    personne, email = cree_refus(comptes, REFUS[nom])
    assert verifie(cx_api, email, MOT_DE_PASSE) is None
    assert verifie_de(cx_api, personne, MOT_DE_PASSE) is False


@pytest.mark.parametrize("prefixe", list(PREFIXES_REFUSES.values()), ids=list(PREFIXES_REFUSES))
def test_seul_le_prefixe_2a_est_accepte_les_autres_sont_refuses_sans_exception(
    prefixe: str, cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    autre = prefixe + hache(comptes.admin, MOT_DE_PASSE)[4:]
    personne, email = comptes.cree(autre)
    assert verifie(cx_api, email, MOT_DE_PASSE) is None
    assert verifie_de(cx_api, personne, MOT_DE_PASSE) is False


def test_un_hachage_md5_crypt_valide_est_refuse(cx_api: psycopg.Connection[Ligne], comptes: Comptes) -> None:
    ligne = comptes.admin.execute(
        "select extensions.crypt(%s, extensions.gen_salt('md5'))", (MOT_DE_PASSE,)
    ).fetchone()
    assert ligne is not None
    _, email = comptes.cree(str(ligne[0]))
    assert str(ligne[0]).startswith("$1$")
    assert verifie(cx_api, email, MOT_DE_PASSE) is None


def test_un_hachage_2a_mal_forme_est_rattrape_et_ne_rend_pas_d_erreur(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    _, email = comptes.cree(MAL_FORME)
    assert verifie(cx_api, email, MOT_DE_PASSE) is None


def test_une_adresse_inconnue_vide_ou_nulle_rend_null(cx_api: psycopg.Connection[Ligne]) -> None:
    assert verifie(cx_api, f"{uuid4().hex}@inconnu.test", MOT_DE_PASSE) is None
    assert verifie(cx_api, "", MOT_DE_PASSE) is None
    assert verifie(cx_api, "   ", MOT_DE_PASSE) is None
    assert verifie(cx_api, None, MOT_DE_PASSE) is None


def test_une_adresse_vide_ne_retrouve_pas_un_compte_sans_adresse(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    personne, _ = comptes.bon(email="")
    assert verifie(cx_api, "", MOT_DE_PASSE) is None
    assert verifie_de(cx_api, personne, MOT_DE_PASSE) is True


def test_deux_comptes_pour_la_meme_adresse_a_la_casse_pres_sont_refuses(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    _, email = comptes.bon()
    comptes.bon(email=email.upper())
    assert verifie(cx_api, email, MOT_DE_PASSE) is None
    assert verifie(cx_api, email.upper(), MOT_DE_PASSE) is None


def test_un_bannissement_echu_est_accepte(cx_api: psycopg.Connection[Ligne], comptes: Comptes) -> None:
    echu = comptes.admin.execute("select now() - interval '1 second'").fetchone()
    assert echu is not None
    personne, email = comptes.bon(banned_until=echu[0])
    assert verifie(cx_api, email, MOT_DE_PASSE) == personne


# ── Coûts, longueurs, valeurs limites ───────────────────────────────────────


@pytest.mark.parametrize("cout", [4, 10, 12])
def test_un_hachage_2a_de_n_importe_quel_cout_est_accepte(
    cout: int, cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    personne, email = comptes.cree(hache(comptes.admin, MOT_DE_PASSE, cout))
    assert verifie(cx_api, email, MOT_DE_PASSE) == personne
    assert verifie_de(cx_api, personne, MOT_DE_PASSE) is True


def test_soixante_douze_octets_sont_acceptes_soixante_treize_refuses_meme_avec_le_bon_prefixe(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    exact = "a" * SEPT_CENT
    trop_long = exact + "b"
    personne, email = comptes.cree(hache(comptes.admin, exact))
    assert verifie(cx_api, email, exact) == personne
    # bcrypt n'écoute que les 72 premiers octets : sans la borne, ce mot de passe passerait.
    assert verifie(cx_api, email, trop_long) is None
    assert verifie_de(cx_api, personne, trop_long) is False
    # Même un hachage écrit à partir de 73 octets ne s'ouvre pas avec eux.
    personne2, email2 = comptes.cree(hache(comptes.admin, trop_long))
    assert verifie(cx_api, email2, trop_long) is None
    assert verifie_de(cx_api, personne2, trop_long) is False


def test_les_octets_comptent_pas_les_caracteres(cx_api: psycopg.Connection[Ligne], comptes: Comptes) -> None:
    trente_six = "é" * 36  # 72 octets
    personne, email = comptes.cree(hache(comptes.admin, trente_six))
    assert verifie(cx_api, email, trente_six) == personne
    assert verifie(cx_api, email, "é" * 37) is None  # 74 octets
    assert verifie(cx_api, email, "é" * 72) is None  # 72 caractères, 144 octets


def test_un_mot_de_passe_vide_ou_nul_est_refuse_meme_si_le_hachage_est_celui_du_vide(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    personne, email = comptes.cree(hache(comptes.admin, ""))
    assert verifie(cx_api, email, "") is None
    assert verifie(cx_api, email, None) is None
    assert verifie_de(cx_api, personne, "") is False
    assert verifie_de(cx_api, personne, None) is False


def test_la_variante_par_personne_refuse_une_personne_inconnue_ou_nulle(
    cx_api: psycopg.Connection[Ligne],
) -> None:
    assert verifie_de(cx_api, uuid4(), MOT_DE_PASSE) is False
    assert verifie_de(cx_api, None, MOT_DE_PASSE) is False


def test_la_variante_par_personne_accepte_le_bon_mot_de_passe_et_refuse_le_mauvais(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    personne, _ = comptes.bon()
    assert verifie_de(cx_api, personne, MOT_DE_PASSE) is True
    assert verifie_de(cx_api, personne, MOT_DE_PASSE + "x") is False


# ── Un hachage écrit par GoTrue ─────────────────────────────────────────────


def reglages_locaux() -> tuple[str, str] | None:
    fichier = Path(__file__).parents[2] / ".env"
    if not fichier.exists():
        return None
    valeurs = dict(ligne.split("=", 1) for ligne in fichier.read_text().splitlines() if "=" in ligne)
    url, cle = valeurs.get("VITE_SUPABASE_URL"), valeurs.get("SUPABASE_SERVICE_ROLE_KEY")
    return (url, cle) if url and cle else None


def test_un_hachage_ecrit_par_gotrue_local_est_reconnu(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    reglages = reglages_locaux()
    if reglages is None:
        pytest.skip("pile locale sans .env : pas d'administration d'Auth")
    url, cle = reglages
    email = f"gotrue-{uuid4().hex[:12]}@test.local"
    entetes = {"apikey": cle, "Authorization": f"Bearer {cle}"}
    try:
        reponse = httpx.post(
            f"{url}/auth/v1/admin/users",
            headers=entetes,
            json={"email": email, "password": MOT_DE_PASSE, "email_confirm": True},
            timeout=10,
        )
    except httpx.TransportError:
        pytest.skip("administration d'Auth locale injoignable")
    assert reponse.status_code == 200
    identifiant = UUID(reponse.json()["id"])
    try:
        assert verifie(cx_api, email, MOT_DE_PASSE) == identifiant
        assert verifie(cx_api, email, MOT_DE_PASSE + "x") is None
        assert verifie_de(cx_api, identifiant, MOT_DE_PASSE) is True
    finally:
        httpx.delete(f"{url}/auth/v1/admin/users/{identifiant}", headers=entetes, timeout=10)


# ── Qui peut l'exécuter (par rôle courant, B3) ──────────────────────────────

FONCTIONS = [
    ("public.verifie_mot_de_passe(text, text)", VERIFIE, ("a@x.test", "mdp")),
    ("public.verifie_mot_de_passe_de(uuid, text)", VERIFIE_DE, (UUID(int=1), "mdp")),
]


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role"])
@pytest.mark.parametrize(("nom", "requete", "arguments"), FONCTIONS, ids=["email", "personne"])
def test_les_roles_empruntables_ne_peuvent_pas_verifier(
    role: str, nom: str, requete: str, arguments: tuple[object, ...], admin: psycopg.Connection[Ligne]
) -> None:
    with pytest.raises(errors.InsufficientPrivilege), admin.transaction():
        admin.execute(f"set local role {role}")
        admin.execute(requete, arguments)


@pytest.mark.parametrize(("nom", "requete", "arguments"), FONCTIONS, ids=["email", "personne"])
def test_popote_api_apres_emprunt_d_authenticated_ne_peut_plus_verifier(
    nom: str, requete: str, arguments: tuple[object, ...], cx_api: psycopg.Connection[Ligne]
) -> None:
    with pytest.raises(errors.InsufficientPrivilege), cx_api.transaction():
        cx_api.execute("set local role authenticated")
        cx_api.execute(requete, arguments)


@pytest.mark.parametrize(("nom", "requete", "arguments"), FONCTIONS, ids=["email", "personne"])
def test_popote_internal_ne_peut_pas_verifier(nom: str, requete: str, arguments: tuple[object, ...]) -> None:
    from _connexions import DSN_INTERNAL

    with connecte(DSN_INTERNAL) as cx, pytest.raises(errors.InsufficientPrivilege):
        cx.execute(requete, arguments)


@pytest.mark.parametrize(("nom", "requete", "arguments"), FONCTIONS, ids=["email", "personne"])
def test_seul_popote_api_a_le_droit_d_execution(
    nom: str, requete: str, arguments: tuple[object, ...], admin: psycopg.Connection[Ligne]
) -> None:
    roles = ["anon", "authenticated", "service_role", "popote_api", "popote_internal"]
    droits = {
        role: admin.execute(
            "select has_function_privilege(%s, %s::regprocedure, 'execute')", (role, nom)
        ).fetchone()
        for role in roles
    }
    assert {role for role, ligne in droits.items() if ligne == (True,)} == {"popote_api"}


# ── Le temps ne dit rien ────────────────────────────────────────────────────

ESSAIS = 15


def mediane(cx: psycopg.Connection[Ligne], email: str, mot_de_passe: str = MOT_DE_PASSE + "x") -> float:
    verifie(cx, email, mot_de_passe)  # chauffe
    durees = []
    for _ in range(ESSAIS):
        debut = time.perf_counter()
        verifie(cx, email, mot_de_passe)
        durees.append(time.perf_counter() - debut)
    return statistics.median(durees)


def test_un_compte_inconnu_coute_le_meme_temps_qu_un_mauvais_mot_de_passe(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    _, connu = comptes.bon()
    reference = mediane(cx_api, connu)
    inconnu = mediane(cx_api, f"{uuid4().hex}@inconnu.test")
    assert 0.5 <= inconnu / reference <= 2, (inconnu, reference)


@pytest.mark.parametrize("nom", ["hachage_vide", "malforme", "banni_a_l_infini", "supprime", "sso"])
def test_un_refus_coute_le_meme_temps_qu_un_mauvais_mot_de_passe(
    nom: str, cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    _, connu = comptes.bon()
    _, refuse = cree_refus(comptes, REFUS[nom])
    reference = mediane(cx_api, connu)
    assert 0.5 <= mediane(cx_api, refuse) / reference <= 2


def test_un_prefixe_2b_et_un_mot_de_passe_trop_long_coutent_le_meme_temps(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    _, connu = comptes.bon()
    _, en_2b = comptes.cree("$2b$" + hache(comptes.admin, MOT_DE_PASSE)[4:])
    reference = mediane(cx_api, connu)
    assert 0.5 <= mediane(cx_api, en_2b) / reference <= 2
    assert 0.5 <= mediane(cx_api, connu, "z" * 100) / reference <= 2


# ── Le mot de passe ne reste nulle part ─────────────────────────────────────


def test_le_mot_de_passe_n_entre_pas_dans_les_statistiques_de_requetes(
    cx_api: psycopg.Connection[Ligne], comptes: Comptes
) -> None:
    secret = f"secret-{uuid4().hex}"
    _, email = comptes.bon(secret)
    verifie(cx_api, email, secret)
    ligne = comptes.admin.execute(
        "select count(*) from pg_stat_statements where query like %s", (f"%{secret}%",)
    ).fetchone()
    assert ligne == (0,)
