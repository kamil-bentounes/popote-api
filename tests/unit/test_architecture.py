"""Garde-fous d'architecture sur `src/` (spec § 5.1, § 8.2).

1. Aucun `set role` ni `set` de session : tout se pose par `set local` ou `set_config(…, true)`, donc meurt
   avec la transaction. Un `set role` oublié survivrait au pooler et passerait au client suivant.
   Garde-fou de relecture : il lit les chaînes littérales, pas celles qu'on assemblerait à l'exécution.
2. `Base.service()` (le contournement de la RLS) n'est appelé que par les modules de la liste fermée.
3. `Base.connexion()` (le rôle de connexion nu, pour les fonctions réservées à `popote_api`) de même.
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
