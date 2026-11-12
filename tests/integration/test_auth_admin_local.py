"""Le client d'administration d'Auth contre la pile locale : un vrai compte en `@example.com`.

Crée, change et supprime un compte réel, et relit le hachage dans `auth.users` (lecture seule, en
`postgres` local) pour prouver que `crypt()` le reconnaît. Le compte est supprimé quoi qu'il arrive.
URL et clé de la pile viennent du `.env` local (`bash ops/env-local.sh`) : clés de démonstration seulement.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
from pydantic import SecretStr

from popote_api.infra.auth_admin import (
    AuthAdmin,
    AuthIndisponible,
    CompteDejaExistant,
    MotDePasseRefuseParAuth,
)

ADMIN_LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
PREFIXE_BCRYPT_GOTRUE = "$2a$"
ANCIEN = "premier mot de passe très long"
NOUVEAU = "second mot de passe très long"


def lit_le_env_local() -> dict[str, str]:
    """Lu à l'import comme `.env` : la fixture autouse de tests/conftest.py retire les POPOTE_* ensuite."""
    chemin = Path(__file__).resolve().parents[2] / ".env"
    if not chemin.exists():
        return {}
    lignes = [ligne.split("=", 1) for ligne in chemin.read_text().splitlines() if "=" in ligne]
    return {cle: valeur for cle, valeur in lignes}


ENV_LOCAL = lit_le_env_local()


@pytest.fixture
def admin() -> AuthAdmin:
    url, cle = ENV_LOCAL.get("POPOTE_SUPABASE_URL"), ENV_LOCAL.get("POPOTE_SUPABASE_SECRET_KEY")
    if not url or not cle:
        pytest.fail("Pas de .env local : lancer `bash ops/env-local.sh` (pile Supabase locale démarrée).")
    return AuthAdmin(url, SecretStr(cle))


@pytest.fixture
async def adresse() -> AsyncIterator[str]:
    """Une adresse neuve ; à la fin, plus aucun compte pour elle, même si le test a échoué en route."""
    courriel = f"popote-test-{uuid.uuid4().hex}@example.com"
    yield courriel
    with psycopg.connect(ADMIN_LOCAL, autocommit=True) as cx:
        cx.execute("delete from auth.users where email = %s", (courriel,))
        restants = cx.execute("select count(*) from auth.users where email = %s", (courriel,)).fetchone()
    assert restants == (0,)


def hachage_de(adresse: str) -> str | None:
    with psycopg.connect(ADMIN_LOCAL) as cx:
        ligne = cx.execute(
            "select encrypted_password from auth.users where email = %s", (adresse,)
        ).fetchone()
    return ligne[0] if ligne else None


def mot_de_passe_reconnu(identifiant: uuid.UUID, mot_de_passe: str) -> bool:
    """Vrai si `crypt()` de la base retrouve le hachage stocké depuis ce mot de passe."""
    with psycopg.connect(ADMIN_LOCAL) as cx:
        ligne = cx.execute(
            "select encrypted_password = extensions.crypt(%s, encrypted_password) "
            "from auth.users where id = %s",
            (mot_de_passe, identifiant),
        ).fetchone()
    assert ligne is not None
    return bool(ligne[0])


@pytest.mark.integration
async def test_creer_changer_puis_supprimer_un_compte_reel(admin: AuthAdmin, adresse: str) -> None:
    identifiant = await admin.cree_compte(adresse, ANCIEN)

    hachage = hachage_de(adresse)
    assert hachage is not None and hachage.startswith(PREFIXE_BCRYPT_GOTRUE)
    assert mot_de_passe_reconnu(identifiant, ANCIEN)
    assert not mot_de_passe_reconnu(identifiant, NOUVEAU)
    with psycopg.connect(ADMIN_LOCAL) as cx:
        ligne = cx.execute(
            "select email_confirmed_at is not null, raw_app_meta_data->>'cree_par', confirmation_sent_at "
            "from auth.users where id = %s",
            (identifiant,),
        ).fetchone()
    assert ligne == (True, "popote-api", None)  # confirmé, marqué, aucun message parti

    await admin.change_mot_de_passe(identifiant, NOUVEAU)

    assert mot_de_passe_reconnu(identifiant, NOUVEAU)
    assert not mot_de_passe_reconnu(identifiant, ANCIEN)

    await admin.supprime_compte(identifiant)

    assert hachage_de(adresse) is None
    await admin.supprime_compte(identifiant)  # déjà supprimé : un succès


@pytest.mark.integration
async def test_une_adresse_prise_leve_compte_deja_existant_et_ne_cree_pas_de_doublon(
    admin: AuthAdmin, adresse: str
) -> None:
    identifiant = await admin.cree_compte(adresse, ANCIEN)

    with pytest.raises(CompteDejaExistant):
        await admin.cree_compte(adresse.upper(), NOUVEAU)

    with psycopg.connect(ADMIN_LOCAL) as cx:
        comptes = cx.execute("select count(*) from auth.users where lower(email) = %s", (adresse,)).fetchone()
    assert comptes == (1,)
    assert mot_de_passe_reconnu(identifiant, ANCIEN)


@pytest.mark.integration
async def test_un_mot_de_passe_trop_court_est_refuse_par_auth_et_ne_cree_rien(
    admin: AuthAdmin, adresse: str
) -> None:
    with pytest.raises(MotDePasseRefuseParAuth):
        await admin.cree_compte(adresse, "abc")

    assert hachage_de(adresse) is None


@pytest.mark.integration
async def test_une_cle_fausse_est_refusee_sans_effet(admin: AuthAdmin, adresse: str) -> None:
    faux = AuthAdmin(ENV_LOCAL["POPOTE_SUPABASE_URL"], SecretStr("sb_secret_" + "x" * 30))

    with pytest.raises(AuthIndisponible, match="HTTP 401"):
        await faux.cree_compte(adresse, ANCIEN)

    assert hachage_de(adresse) is None
