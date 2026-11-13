"""Garde-fous d'architecture sur `src/` (spec § 5.1, § 8.2).

1. Aucun `set role` ni `set` de session : tout se pose par `set local` ou `set_config(…, true)`, donc meurt
   avec la transaction. Un `set role` oublié survivrait au pooler et passerait au client suivant.
   Garde-fou de relecture : il lit les chaînes littérales, pas celles qu'on assemblerait à l'exécution.
2. `Base.service()` (le contournement de la RLS) n'est appelé que par les modules de la liste fermée.
3. `Base.connexion()` (le rôle de connexion nu, pour les fonctions réservées à `popote_api`) de même.
4. L'`Enveloppe` d'un mail (destinataire, objet, texte) n'est fabriquée que dans `infra/mails_textes.py` : une
   réalisation d'`EnvoiMail` n'envoie rien d'autre, donc jamais un objet qui porte un code ou un prénom.
5. Toute fonction SQL qui écrit `login_session.revoked_at` ou supprime des lignes de `login_session` prend
   d'abord `verrouille_la_personne` (0.4bis S6) : sinon une connexion en vol survit à la fermeture.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC = Path(__file__).parents[2] / "src" / "popote_api"
# La liste fermée : chaque tâche qui ajoute un usage de `service()` ajoute son module ici, relu en revue.
# À venir : les routes internes (T10), l'acceptation d'une invitation et les purges.
APPELANTS_DU_SERVICE: set[str] = {"security/acceptation_invitation.py"}
# Idem pour `connexion()` : la connexion, les limites, les sessions et la vérification du mot de passe.
APPELANTS_DE_LA_CONNEXION: set[str] = {
    "security/connexion.py",
    "security/acceptation_invitation.py",
    "security/code_de_connexion.py",
}

SET_DE_SESSION = re.compile(r"(?is)^\s*set\s+(?!local\b)")  # `set x = …` sans `local`, en tête d'instruction
CHANGEMENT_DE_ROLE = re.compile(
    r"(?is)\bset\s+(session\s+)?role\b|\bsession\s+authorization\b|\breset\s+role\b"
)
SET_CONFIG_DE_SESSION = re.compile(r"(?is)set_config\s*\([^)]*,\s*false\s*\)")
SET_CONFIG_DU_ROLE = re.compile(r"(?is)set_config\s*\(\s*'(role|session_authorization)'")


def chaines(arbre: ast.AST) -> Iterator[str]:
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            yield noeud.value


def defauts_de_session(source: str) -> list[str]:
    """Les chaînes qui changent le rôle ou posent un réglage au-delà de la transaction."""
    fautes = []
    for texte in chaines(ast.parse(source)):
        instructions = texte.split(";")
        if (
            CHANGEMENT_DE_ROLE.search(texte)
            or SET_CONFIG_DE_SESSION.search(texte)
            or SET_CONFIG_DU_ROLE.search(texte)
            or any(SET_DE_SESSION.match(i) for i in instructions)
        ):
            fautes.append(texte)
    return fautes


def appels_a_la_methode(source: str, methode: str) -> int:
    return sum(
        1
        for noeud in ast.walk(ast.parse(source))
        if isinstance(noeud, ast.Call)
        and isinstance(noeud.func, ast.Attribute)
        and noeud.func.attr == methode
    )


def appels_a_service(source: str) -> int:
    return appels_a_la_methode(source, "service")


def appels_a_connexion(source: str) -> int:
    return appels_a_la_methode(source, "connexion")


def fichiers_source() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("chemin", fichiers_source(), ids=lambda c: str(c.relative_to(SRC)))
def test_aucun_set_de_session_ni_set_role_dans_le_code(chemin: Path) -> None:
    assert defauts_de_session(chemin.read_text()) == []


@pytest.mark.parametrize(
    "sql",
    [
        "set role service_role",
        "SET SESSION ROLE authenticated",
        "set session authorization postgres",
        "reset role",
        "set statement_timeout = '8s'",
        "set local role authenticated; set search_path = public",
        "select set_config('request.jwt.claims', %s, false)",
        "select set_config('role', 'service_role', true)",
    ],
)
def test_le_controle_attrape_un_set_de_session(sql: str) -> None:
    assert defauts_de_session(f"requete = {sql!r}") == [sql]


@pytest.mark.parametrize(
    "sql",
    [
        "set local role authenticated; set local statement_timeout = '8s'",
        "select set_config('request.jwt.claims', %s, true)",
        "update public.recipe set title = %s where id = %s",
    ],
)
def test_le_controle_laisse_passer_ce_qui_meurt_avec_la_transaction(sql: str) -> None:
    assert defauts_de_session(f"requete = {sql!r}") == []


def test_seuls_les_modules_autorises_appellent_service() -> None:
    appelants = {
        str(chemin.relative_to(SRC)) for chemin in fichiers_source() if appels_a_service(chemin.read_text())
    }
    assert appelants <= APPELANTS_DU_SERVICE


def test_le_controle_attrape_un_appel_a_service() -> None:
    assert appels_a_service("async def f(base):\n    async with base.service() as c:\n        pass") == 1
    assert appels_a_service("async def f(base):\n    async with base.personne(p) as c:\n        pass") == 0


def test_seuls_les_modules_autorises_appellent_connexion() -> None:
    appelants = {
        str(chemin.relative_to(SRC)) for chemin in fichiers_source() if appels_a_connexion(chemin.read_text())
    }
    assert appelants <= APPELANTS_DE_LA_CONNEXION


def test_le_controle_attrape_un_appel_a_connexion() -> None:
    assert appels_a_connexion("async def f(base):\n    async with base.connexion() as c:\n        pass") == 1
    assert appels_a_connexion("async def f(base):\n    async with base.service() as c:\n        pass") == 0
    assert appels_a_connexion("async def f(base):\n    async with base.personne(p) as c:\n        pass") == 0


FABRIQUE_DES_ENVELOPPES = "infra/mails_textes.py"


def appels_a_enveloppe(source: str) -> int:
    return sum(
        1
        for noeud in ast.walk(ast.parse(source))
        if isinstance(noeud, ast.Call)
        and (
            (isinstance(noeud.func, ast.Name) and noeud.func.id == "Enveloppe")
            or (isinstance(noeud.func, ast.Attribute) and noeud.func.attr == "Enveloppe")
        )
    )


def test_seul_mails_textes_fabrique_une_enveloppe() -> None:
    fabricants = {
        str(chemin.relative_to(SRC)) for chemin in fichiers_source() if appels_a_enveloppe(chemin.read_text())
    }
    assert fabricants == {FABRIQUE_DES_ENVELOPPES}  # et pas un autre : le contrôle ne passe pas à vide


def test_le_controle_attrape_une_enveloppe_fabriquee_ailleurs() -> None:
    assert appels_a_enveloppe("e = Enveloppe(a, 'Code 123456', t, c)") == 1
    assert appels_a_enveloppe("e = textes.Enveloppe(a, 'Code 123456', t, c)") == 1
    assert appels_a_enveloppe("e = textes.enveloppe_du_code(m)") == 0


# Les réalisations qui envoient pour de bon (`infra/mail_*.py`, hors `mails.py` et `mails_textes.py`) ne
# voient que l'`Enveloppe` : jamais le code, le lien, le prénom ni la durée d'un message, jamais le cachet.
ATTRIBUTS_DES_MESSAGES = frozenset({"code", "lien", "prenom_invite", "prenom_hote", "validite_min"})
NOMS_DES_MESSAGES = frozenset({"MessageCode", "MessageInvitation"})


def acces_interdits_a_un_message(source: str) -> list[str]:
    fautes = []
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.Attribute) and noeud.attr in ATTRIBUTS_DES_MESSAGES:
            fautes.append(noeud.attr)
        elif isinstance(noeud, ast.Name) and noeud.id in NOMS_DES_MESSAGES | {"_CACHET"}:
            fautes.append(noeud.id)
        elif isinstance(noeud, ast.alias) and noeud.name in NOMS_DES_MESSAGES | {"_CACHET"}:
            fautes.append(noeud.name)
    return fautes


def realisations_reelles() -> list[Path]:
    return sorted(p for p in (SRC / "infra").glob("mail_*.py"))


@pytest.mark.parametrize("chemin", realisations_reelles(), ids=lambda c: c.name)
def test_une_realisation_reelle_ne_voit_que_l_enveloppe(chemin: Path) -> None:
    assert acces_interdits_a_un_message(chemin.read_text()) == []


@pytest.mark.parametrize(
    "source",
    [
        "subject = f'Code {message.code}'",
        "lien = message.lien",
        "from popote_api.infra.mails import MessageCode",
        "x: MessageInvitation",
        "from popote_api.infra.mails_textes import _CACHET",
        "n = message.validite_min",
    ],
)
def test_le_controle_attrape_une_realisation_qui_lit_le_message(source: str) -> None:
    assert acces_interdits_a_un_message(source) != []


def test_le_controle_laisse_passer_l_enveloppe() -> None:
    source = "def f(enveloppe: Enveloppe) -> str:\n    return enveloppe.objet + enveloppe.texte"
    assert acces_interdits_a_un_message(source) == []


def test_le_cachet_des_enveloppes_n_est_nomme_que_par_mails_textes() -> None:
    nommeurs = {
        str(chemin.relative_to(SRC)) for chemin in fichiers_source() if "_CACHET" in chemin.read_text()
    }
    assert nommeurs == {FABRIQUE_DES_ENVELOPPES}


# ── 5. Le verrou de personne (0.4bis S6, migration 0148) ────────────────────

MIGRATIONS = Path(__file__).parents[2] / "supabase" / "migrations"
COMMENTAIRE_DE_LIGNE = re.compile(r"--[^\n]*")
COMMENTAIRE_DE_BLOC = re.compile(r"/\*.*?\*/", re.DOTALL)
FONCTION = re.compile(
    r"create\s+(?:or\s+replace\s+)?function\s+([\w.]+)\s*\((.*?)\)\s*returns\b.*?\bas\s+(\$\w*\$)(.*?)\3",
    re.DOTALL | re.IGNORECASE,
)
ECRIT_LES_SESSIONS = re.compile(
    r"update\s+(?:only\s+)?public\.login_session\b[^;]*?\brevoked_at\s*="
    r"|delete\s+from\s+(?:only\s+)?public\.login_session\b"
    r"|truncate\s+(?:table\s+)?(?:only\s+)?public\.login_session\b"
    r"|merge\s+into\s+public\.login_session\b",
    re.IGNORECASE,
)
LE_VERROU = re.compile(
    r"\b(?:perform|select)\s+(?:private\.|public\.)?verrouille_la_personne\s*\(", re.IGNORECASE
)
UNE_ECRITURE = re.compile(r"\b(?:update|delete|insert|truncate|merge)\b", re.IGNORECASE)
# Les fonctions qui ferment des sessions SANS la personne, chacune avec sa raison (une fonction ajoutée ici se
# justifie en relecture). `efface_mes_donnees` y reste jusqu'à S14, qui lui donne les trois verrous.
SANS_VERROU_DE_PERSONNE: dict[str, str] = {
    "public.ferme_session/1": "une seule session, désignée par son jeton : les autres ne sont pas visées",
    "public.ferme_un_appareil/2": "une seule session désignée par la personne : pas les autres",
    "private.purge_login_session/2": "la purge nocturne efface des lignes mortes depuis 30 jours",
    "public.efface_mes_donnees/0": "S14 (0156) la redéfinit avec les trois verrous",
}


def arite(parametres: str) -> int:
    profondeur, virgules = 0, 0
    for caractere in parametres:
        profondeur += caractere in "(["
        profondeur -= caractere in ")]"
        virgules += caractere == "," and profondeur == 0
    return virgules + 1 if parametres.strip() else 0


def nettoie(source: str) -> str:
    """Sans commentaire ni guillemet d'identifiant : `public."login_session"` vaut `public.login_session`."""
    return COMMENTAIRE_DE_BLOC.sub(" ", COMMENTAIRE_DE_LIGNE.sub(" ", source)).replace('"', "")


def fonctions_sql(sources: list[str]) -> dict[str, str]:
    """Le corps de chaque fonction (`schéma.nom/arité`) telle que la dernière migration la définit."""
    corps: dict[str, str] = {}
    for source in sources:
        propre = nettoie(source)
        for nom, parametres, _, texte in FONCTION.findall(propre):
            qualifie = nom.lower() if "." in nom else f"public.{nom.lower()}"
            corps[f"{qualifie}/{arite(parametres)}"] = texte.lower()
    return corps


def fonctions_des_migrations() -> dict[str, str]:
    return fonctions_sql([chemin.read_text() for chemin in sorted(MIGRATIONS.glob("*.sql"))])


def ferment_des_sessions_sans_verrou(fonctions: dict[str, str]) -> list[str]:
    """Les fonctions qui ferment des sessions sans prendre le verrou AVANT leur première écriture."""
    fautives = []
    for nom, texte in fonctions.items():
        if not ECRIT_LES_SESSIONS.search(texte) or nom in SANS_VERROU_DE_PERSONNE:
            continue
        verrou, ecriture = LE_VERROU.search(texte), UNE_ECRITURE.search(texte)
        if verrou is None or (ecriture is not None and ecriture.start() < verrou.start()):
            fautives.append(nom)
    return sorted(fautives)


def ecritures_hors_des_fonctions() -> list[str]:
    """Les migrations qui écrivent `login_session` hors d'une fonction analysée (`do`, `begin atomic`…)."""
    fautes = []
    for chemin in sorted(MIGRATIONS.glob("*.sql")):
        reste = FONCTION.sub(" ", nettoie(chemin.read_text()))
        if ECRIT_LES_SESSIONS.search(reste):
            fautes.append(chemin.name)
    return fautes


def test_toute_fonction_qui_ferme_des_sessions_prend_d_abord_le_verrou_de_la_personne() -> None:
    assert ferment_des_sessions_sans_verrou(fonctions_des_migrations()) == []


def test_les_exceptions_au_verrou_de_personne_existent_encore_et_ferment_bien_des_sessions() -> None:
    fonctions = fonctions_des_migrations()
    for nom in SANS_VERROU_DE_PERSONNE:
        assert nom in fonctions, f"{nom} n'existe plus : retirer l'exception"
        assert ECRIT_LES_SESSIONS.search(fonctions[nom]), (
            f"{nom} ne ferme plus de session : retirer l'exception"
        )


def test_aucune_migration_n_ecrit_les_sessions_hors_d_une_fonction_analysee() -> None:
    assert ecritures_hors_des_fonctions() == []


@pytest.mark.parametrize(
    "nom",
    [
        "private.cree_session/6",
        "private.ferme_les_autres_sessions/3",
        "public.ferme_les_autres_appareils/1",
        "private.fait_tourner_et_ferme_les_autres/3",
        "public.confirme_le_changement_de_mot_de_passe/3",
    ],
)
def test_ces_fermetures_prennent_le_verrou_avant_toute_ecriture(nom: str) -> None:
    texte = fonctions_des_migrations()[nom]
    verrou = LE_VERROU.search(texte)
    assert verrou is not None, nom
    assert all(ecriture.start() > verrou.start() for ecriture in UNE_ECRITURE.finditer(texte)), nom


FERME_SANS_VERROU = """
create or replace function public.ferme_tout(p_person uuid) returns void language sql as $$
  update public.login_session set revoked_at = now() where person_id = p_person;
$$;
"""
FERME_AVEC_VERROU = """
create or replace function public.ferme_tout(p_person uuid) returns void language plpgsql as $$
begin
  perform private.verrouille_la_personne(p_person);
  delete from public.login_session where person_id = p_person;
end;
$$;
"""


FERME_PUIS_VERROUILLE = """
create or replace function public.ferme_tout(p_person uuid) returns void language plpgsql as $$
begin
  update public.login_session set revoked_at = now() where person_id = p_person;
  perform private.verrouille_la_personne(p_person);
end;
$$;
"""
FERMETURES_DEGUISEES = [
    "update only public.login_session set revoked_at = now()",
    'update public."login_session" set revoked_at = now()',
    "delete from only public.login_session",
    "truncate public.login_session",
    "truncate table public.login_session",
    "merge into public.login_session s using x on true when matched then delete",
]


def test_le_controle_attrape_une_fonction_qui_ferme_sans_le_verrou() -> None:
    assert ferment_des_sessions_sans_verrou(fonctions_sql([FERME_SANS_VERROU])) == ["public.ferme_tout/1"]
    assert ferment_des_sessions_sans_verrou(fonctions_sql([FERME_AVEC_VERROU])) == []


def test_le_controle_attrape_une_fonction_qui_ecrit_avant_de_verrouiller() -> None:
    assert ferment_des_sessions_sans_verrou(fonctions_sql([FERME_PUIS_VERROUILLE])) == ["public.ferme_tout/1"]


@pytest.mark.parametrize("ecriture", FERMETURES_DEGUISEES)
def test_le_controle_attrape_les_ecritures_deguisees(ecriture: str) -> None:
    source = f"create function public.f() returns void language sql as $$ {ecriture}; $$;"
    assert ferment_des_sessions_sans_verrou(fonctions_sql([source])) == ["public.f/0"]


def test_un_verrou_cite_dans_une_chaine_ou_un_autre_nom_ne_compte_pas() -> None:
    source = (
        "create function public.f() returns void language plpgsql as $$ begin "
        "perform 'verrouille_la_personne(' ; perform x.ne_verrouille_la_personne(1); "
        "delete from public.login_session; end $$;"
    )
    assert ferment_des_sessions_sans_verrou(fonctions_sql([source])) == ["public.f/0"]


def test_la_derniere_definition_d_une_fonction_est_celle_qui_compte() -> None:
    assert ferment_des_sessions_sans_verrou(fonctions_sql([FERME_SANS_VERROU, FERME_AVEC_VERROU])) == []
    assert ferment_des_sessions_sans_verrou(fonctions_sql([FERME_AVEC_VERROU, FERME_SANS_VERROU])) == [
        "public.ferme_tout/1"
    ]


def test_un_commentaire_qui_cite_une_fonction_n_en_cree_pas_une() -> None:
    source = "-- create function public.ferme_tout() returns void as $$ delete from public.login_session $$;"
    assert fonctions_sql([source]) == {}


def test_le_controle_ne_passe_pas_a_vide() -> None:
    fonctions = fonctions_des_migrations()
    assert "private.cree_session/6" in fonctions and "public.ferme_session/1" in fonctions
    assert sum(1 for texte in fonctions.values() if ECRIT_LES_SESSIONS.search(texte)) >= 7
