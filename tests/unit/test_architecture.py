"""Garde-fous d'architecture sur `src/` (spec § 5.1, § 8.2).

1. Aucun `set role` ni `set` de session : tout se pose par `set local` ou `set_config(…, true)`, donc meurt
   avec la transaction. Un `set role` oublié survivrait au pooler et passerait au client suivant.
   Garde-fou de relecture : il lit les chaînes littérales, pas celles qu'on assemblerait à l'exécution.
2. `Base.service()` (le contournement de la RLS) n'est appelé que par les modules de la liste fermée.
3. `Base.connexion()` (le rôle de connexion nu, pour les fonctions réservées à `popote_api`) de même.
4. L'`Enveloppe` d'un mail (destinataire, objet, texte) n'est fabriquée que dans `infra/mails_textes.py` : une
   réalisation d'`EnvoiMail` n'envoie rien d'autre, donc jamais un objet qui porte un code ou un prénom.
5. La clé d'envoi des mails (`scaleway_tem_secret_key`) n'est lue que par `infra/mail_scaleway.py` ; seuls les
   réglages, la fabrique d'`EnvoiMail` et ce module la nomment (jamais pour la passer à un autre code).
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


# La clé d'envoi de Scaleway TEM : un seul module la lit (0.4bis S4). Les deux autres la nomment sans
# la lire : les réglages la déclarent, la fabrique passe le `SecretStr` tel quel.
CLE_TEM = "scaleway_tem_secret_key"
LECTEUR_DE_LA_CLE_TEM = "infra/mail_scaleway.py"
NOMMEURS_DE_LA_CLE_TEM: set[str] = {"config.py", "infra/mails.py", LECTEUR_DE_LA_CLE_TEM}


def _nomme_la_cle_tem(noeud: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Attribute) and n.attr == CLE_TEM)
        or (isinstance(n, ast.Name) and n.id == CLE_TEM)
        or (isinstance(n, ast.Constant) and isinstance(n.value, str) and CLE_TEM in n.value)
        for n in ast.walk(noeud)
    )


def nomme_la_cle_tem(source: str) -> bool:
    return _nomme_la_cle_tem(ast.parse(source))


def lit_la_cle_tem(source: str) -> bool:
    """Vrai si un `.get_secret_value()` s'applique à une expression qui nomme la clé."""
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get_secret_value"
        and _nomme_la_cle_tem(n.func.value)
        for n in ast.walk(ast.parse(source))
    )


def test_seul_le_module_d_envoi_lit_la_cle_tem() -> None:
    lecteurs = {
        str(chemin.relative_to(SRC)) for chemin in fichiers_source() if lit_la_cle_tem(chemin.read_text())
    }
    assert lecteurs <= {LECTEUR_DE_LA_CLE_TEM}


def test_seuls_les_reglages_la_fabrique_et_le_module_d_envoi_nomment_la_cle_tem() -> None:
    nommeurs = {
        str(chemin.relative_to(SRC)) for chemin in fichiers_source() if nomme_la_cle_tem(chemin.read_text())
    }
    assert nommeurs <= NOMMEURS_DE_LA_CLE_TEM
    assert LECTEUR_DE_LA_CLE_TEM in nommeurs  # le contrôle ne passe pas à vide


@pytest.mark.parametrize(
    "source",
    [
        "x = reglages.scaleway_tem_secret_key.get_secret_value()",
        "x = (r.scaleway_tem_secret_key or None).get_secret_value()",
        "secret = lambda: getattr(r, 'scaleway_tem_secret_key').get_secret_value()",
        "scaleway_tem_secret_key.get_secret_value()",
    ],
)
def test_le_controle_attrape_une_lecture_de_la_cle_tem(source: str) -> None:
    assert lit_la_cle_tem(source) and nomme_la_cle_tem(source)


@pytest.mark.parametrize(
    "source",
    [
        "x = reglages.supabase_secret_key.get_secret_value()",
        "x = Envoi(reglages.scaleway_tem_secret_key)",
        "x = self._cle.get_secret_value()",
    ],
)
def test_le_controle_laisse_passer_ce_qui_ne_lit_pas_la_cle_tem(source: str) -> None:
    assert not lit_la_cle_tem(source)


def test_le_controle_attrape_un_autre_code_qui_recoit_la_cle_tem() -> None:
    assert nomme_la_cle_tem("x = _secret(settings.scaleway_tem_secret_key)")
    assert not nomme_la_cle_tem("x = _secret(settings.supabase_secret_key)")


def lectures_de_secret_passees_a_un_appel(source: str, autorises: frozenset[str]) -> list[str]:
    """Les appels qui reçoivent directement le résultat d'un `.get_secret_value()` (hors `autorises`)."""
    fautes = []
    for appel in (n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)):
        nom = appel.func.id if isinstance(appel.func, ast.Name) else getattr(appel.func, "attr", "")
        arguments = [*appel.args, *(k.value for k in appel.keywords)]
        if nom not in autorises and any(
            isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "get_secret_value"
            for a in arguments
            for n in ast.walk(a)
        ):
            fautes.append(nom)
    return fautes


def test_le_module_d_envoi_ne_lit_la_cle_qu_a_deux_endroits_sans_la_passer_a_un_autre_code() -> None:
    source = (SRC / LECTEUR_DE_LA_CLE_TEM).read_text()
    # Le constructeur (nettoyage et contrôle) et l'en-tête de la requête : une troisième lecture se relit.
    assert appels_a_la_methode(source, "get_secret_value") == 2
    assert lectures_de_secret_passees_a_un_appel(source, frozenset({"SecretStr"})) == []


@pytest.mark.parametrize(
    "source",
    ["journal.info('%s', self._cle.get_secret_value())", "valide(self._cle.get_secret_value().strip())"],
)
def test_le_controle_attrape_la_cle_passee_a_un_appel(source: str) -> None:
    assert lectures_de_secret_passees_a_un_appel(source, frozenset({"SecretStr"})) != []


def test_le_controle_laisse_passer_secretstr_et_les_methodes_de_chaine() -> None:
    assert (
        lectures_de_secret_passees_a_un_appel(
            "x = SecretStr(c.get_secret_value().strip())", frozenset({"SecretStr"})
        )
        == []
    )
