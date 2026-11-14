"""T14b : `DELETE /api/v1/me` (spec § 4, § 7.7 ; B3, B4, B7, B9), en base locale et contre l'Auth local.

Données inventées. Le chemin complet passe par le vrai Auth de la pile locale ; les pannes et le `404` sont
simulés. Le journal des événements garde `compte_supprime` sans personne ni clé : les lignes relues sont
celles que le test a fait naître.
"""

# ruff: noqa: F811, F401

import asyncio
import logging
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from _client import cookie
from _fabrique import SessionDeTest
from pydantic import SecretStr
from test_auth_admin_local import ENV_LOCAL
from test_connexion import ECRITURE, MOT_DE_PASSE
from test_reauthentification import Personne, fabrique_de_banc, moi

from popote_api.infra.auth_admin import AuthAdmin, AuthIndisponible

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/me"
TOUS_LES_JETONS_VIDES = (
    "update auth.users set confirmation_token = '', recovery_token = '', email_change_token_new = '', "
    "email_change = '', email_change_token_current = '', phone_change = '', phone_change_token = '', "
    "reauthentication_token = '' where id = %s"
)


class AuthEnregistre(AuthAdmin):
    """Le vrai client d'Auth (pile locale), qui se souvient de ce qu'on lui a demandé."""

    def __init__(self) -> None:
        url, cle = ENV_LOCAL.get("POPOTE_SUPABASE_URL"), ENV_LOCAL.get("POPOTE_SUPABASE_SECRET_KEY")
        if not url or not cle:
            pytest.fail("Pas de .env local : lancer `bash ops/env-local.sh` (pile Supabase locale démarrée).")
        super().__init__(url, SecretStr(cle))
        self.appels: list[UUID] = []

    async def supprime_compte(self, identifiant: UUID) -> None:
        self.appels.append(identifiant)
        await super().supprime_compte(identifiant)


class AuthEnPanne(AuthAdmin):
    def __init__(self) -> None:
        super().__init__(None, None)
        self.appels: list[UUID] = []

    async def supprime_compte(self, identifiant: UUID) -> None:
        self.appels.append(identifiant)
        raise AuthIndisponible("panne simulée")


class AuthSansEffet(AuthAdmin):
    """Ni réseau ni Auth : le compte `auth.users` reste, les tests lisent ce que la base a fait."""

    def __init__(self) -> None:
        super().__init__(None, None)
        self.appels: list[UUID] = []

    async def supprime_compte(self, identifiant: UUID) -> None:
        self.appels.append(identifiant)


def auth_repondant(statut: int, corps: dict[str, Any]) -> AuthAdmin:
    transport = httpx.MockTransport(lambda requete: httpx.Response(statut, json=corps))
    return AuthAdmin("http://auth.invalide", SecretStr("cle-de-test-sans-valeur"), transport=transport)


def repare_les_jetons(moi: Personne, *personnes: UUID) -> None:
    # GoTrue ne sait pas lire une ligne insérée à la main dont les jetons sont NULL.
    for identifiant in (moi.id, *personnes):
        moi.banc.fabrique.admin.execute(TOUS_LES_JETONS_VIDES, (identifiant,))


@pytest.fixture
def evenements_avant(moi: Personne) -> Iterator[Callable[[], list[tuple[Any, ...]]]]:
    """Les `compte_supprime` nés pendant le test : ce qui s'ajoute à ce qu'il y avait ; retirés à la fin."""

    def ids() -> set[int]:
        return {
            r[0]
            for r in moi.banc.lignes("select id from public.security_event where kind = 'compte_supprime'")
        }

    avant = ids()

    def nouveaux() -> list[tuple[Any, ...]]:
        return moi.banc.lignes(
            "select person_id, account_key, ip_hash, session_id from public.security_event "
            "where kind = 'compte_supprime' and id <> all(%s)",
            list(avant),
        )

    yield nouveaux
    moi.banc.fabrique.admin.execute(
        "delete from public.security_event where kind = 'compte_supprime' and id <> all(%s)", (list(avant),)
    )


def supprime(
    moi: Personne, *, session: SessionDeTest | None = None, jeton: str | None = None, origine: bool = True
) -> Any:
    entetes = (
        {"Cookie": f"{moi.banc.reglages.nom_du_cookie_de_session}={jeton}"}
        if jeton
        else cookie(session or moi.session)
    )
    return moi.banc.client().delete(ROUTE, headers=entetes | (ECRITURE if origine else {}))


def existe(moi: Personne, requete: str, *args: object) -> bool:
    (ligne,) = moi.banc.lignes(f"select exists({requete})", *args)
    return bool(ligne[0])


def profil(moi: Personne, personne: UUID | None = None) -> bool:
    return existe(moi, "select 1 from public.user_profile where id = %s", personne or moi.id)


def compte_auth(moi: Personne, personne: UUID | None = None) -> bool:
    return existe(moi, "select 1 from auth.users where id = %s", personne or moi.id)


def sessions(moi: Personne, personne: UUID | None = None) -> int:
    (ligne,) = moi.banc.lignes(
        "select count(*) from public.login_session where person_id = %s", personne or moi.id
    )
    return int(ligne[0])


def foyer_de(moi: Personne, personne: UUID | None = None) -> UUID:
    (ligne,) = moi.banc.lignes(
        "select household_id from public.user_profile where id = %s", personne or moi.id
    )
    return ligne[0]  # type: ignore[no-any-return]


def foyer_existe(moi: Personne, foyer: UUID) -> bool:
    return existe(moi, "select 1 from public.household where id = %s", foyer)


class TestGarde:
    async def test_sans_reauthentification_recente_403_et_rien_n_est_supprime(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        auth = moi.banc.app.state.auth_admin = AuthSansEffet()
        moi.vieillit()
        reponse = await supprime(moi)
        assert reponse.status_code == 403
        assert reponse.json()["code"] == "reauthentification_requise"
        assert "set-cookie" not in reponse.headers
        assert auth.appels == []
        assert profil(moi) and compte_auth(moi) and sessions(moi) == 1
        assert evenements_avant() == []

    @pytest.mark.parametrize(("secondes", "statut"), [(299, 204), (300, 204), (301, 403)])
    async def test_la_fenetre_est_de_300_secondes(
        self, moi: Personne, evenements_avant: Any, secondes: int, statut: int
    ) -> None:
        moi.banc.app.state.auth_admin = AuthSansEffet()
        pose = moi.reauth_at()
        moi.banc.app.state.horloge = lambda: pose + timedelta(seconds=secondes)
        assert (await supprime(moi)).status_code == statut
        assert profil(moi) is (statut == 403)

    async def test_sans_origine_403_et_rien_n_est_supprime(self, moi: Personne) -> None:
        moi.banc.app.state.auth_admin = auth = AuthSansEffet()
        assert (await supprime(moi, origine=False)).status_code == 403
        assert profil(moi) and auth.appels == []

    async def test_sans_session_401(self, moi: Personne) -> None:
        assert (await moi.banc.client().delete(ROUTE, headers=ECRITURE)).status_code == 401


class TestSuppression:
    async def test_le_chemin_complet_avec_le_vrai_auth(
        self, moi: Personne, evenements_avant: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        repare_les_jetons(moi)
        moi.banc.app.state.auth_admin = auth = AuthEnregistre()
        moi.banc.fabrique.session(moi.id)  # une seconde session : toutes partent
        foyer = foyer_de(moi)
        caplog.set_level(logging.DEBUG)
        reponse = await supprime(moi)
        assert reponse.status_code == 204
        assert reponse.content == b""
        assert auth.appels == [moi.id]
        assert not compte_auth(moi) and not profil(moi) and sessions(moi) == 0
        assert not foyer_existe(moi, foyer)  # le dernier (ici le seul) membre emporte le foyer
        (evenement,) = evenements_avant()
        assert (
            evenement[0] is None
        )  # `person_id` nul : `auth.users` a disparu, la clé étrangère l'a remis à null
        assert evenement[1] is None and evenement[2] is None  # ni clé de compte ni empreinte d'IP
        # Les mêmes identifiants ne donnent plus rien, comme une adresse inconnue.
        connexion = await moi.banc.connecte_par_code(moi.email, None)  # sans compte : une ligne factice
        assert connexion.status_code == 401
        assert connexion.json()["code"] == "code_incorrect"
        # Ni le mot de passe ni le jeton de session n'ont touché le journal.
        assert MOT_DE_PASSE not in caplog.text
        assert moi.session.jeton not in caplog.text

    async def test_le_cookie_est_vide_avec_les_attributs_du_cookie_pose(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        moi.banc.app.state.auth_admin = AuthSansEffet()
        entete = (await supprime(moi)).headers["set-cookie"]
        attributs = {a.strip().lower() for a in entete.split(";")}
        nom = moi.banc.reglages.nom_du_cookie_de_session
        assert entete.startswith(f'{nom}=""') or entete.startswith(f"{nom}=;")
        assert {"max-age=0", "path=/", "httponly", "samesite=lax"} <= attributs
        assert ("secure" in attributs) is moi.banc.reglages.session_cookie_secure
        assert not any(a.startswith("domain") for a in attributs)

    async def test_l_evenement_compte_supprime_est_ecrit_une_fois_par_l_effacement(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        moi.banc.app.state.auth_admin = AuthSansEffet()
        assert (await supprime(moi)).status_code == 204
        (evenement,) = evenements_avant()
        assert evenement[1] is None and evenement[2] is None  # sans clé de la personne

    async def test_le_dernier_membre_emporte_le_foyer_l_autre_foyer_reste(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        moi.banc.app.state.auth_admin = AuthSansEffet()
        autre = moi.banc.fabrique.personne(moi.banc.fabrique.foyer())
        foyer_autre = foyer_de(moi, autre.id)
        assert (await supprime(moi)).status_code == 204
        assert profil(moi, autre.id) and foyer_existe(moi, foyer_autre) and compte_auth(moi, autre.id)

    async def test_l_autre_membre_garde_son_foyer_et_ses_donnees(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        moi.banc.app.state.auth_admin = AuthSansEffet()
        foyer = foyer_de(moi)
        autre = moi.banc.fabrique.personne(foyer)
        session_autre = moi.banc.fabrique.session(autre.id)
        assert (await supprime(moi)).status_code == 204
        assert foyer_existe(moi, foyer) and profil(moi, autre.id) and sessions(moi, autre.id) == 1
        assert not profil(moi)
        assert (await moi.banc.client().get(ROUTE, headers=cookie(session_autre))).status_code == 200

    async def test_deux_membres_qui_suppriment_en_meme_temps_emportent_le_foyer_sans_interblocage(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        moi.banc.app.state.auth_admin = AuthSansEffet()
        foyer = foyer_de(moi)
        autre = moi.banc.fabrique.personne(foyer)
        session_autre = moi.banc.fabrique.session(autre.id)
        reponses = await asyncio.wait_for(
            asyncio.gather(supprime(moi), supprime(moi, session=session_autre)), timeout=20
        )
        assert [r.status_code for r in reponses] == [204, 204]
        assert not foyer_existe(moi, foyer) and not profil(moi) and not profil(moi, autre.id)
        assert len(evenements_avant()) == 2

    async def test_deux_suppressions_du_meme_compte_donnent_204_puis_401(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        moi.banc.app.state.auth_admin = auth = AuthSansEffet()
        assert (await supprime(moi)).status_code == 204
        seconde = await supprime(moi)
        assert seconde.status_code == 401
        assert seconde.json()["code"] == "pas_de_session"
        assert auth.appels == [moi.id]
        assert len(evenements_avant()) == 1


class TestAuthEnPanne:
    async def test_503_les_donnees_sont_parties_le_compte_reste_et_on_recommence_apres_reconnexion(
        self, moi: Personne, evenements_avant: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        repare_les_jetons(moi)
        moi.banc.app.state.auth_admin = panne = AuthEnPanne()
        caplog.set_level(logging.DEBUG)
        reponse = await supprime(moi)
        assert reponse.status_code == 503
        assert reponse.json()["code"] == "suppression_incomplete"
        assert "max-age=0" in reponse.headers["set-cookie"].lower()  # la session n'existe plus
        assert panne.appels == [moi.id]
        assert not profil(moi) and sessions(moi) == 0 and compte_auth(moi)
        assert len(evenements_avant()) == 1
        assert (await moi.banc.client().get(ROUTE, headers=cookie(moi.session))).status_code == 401
        # Une session neuve (le compte Auth reste ; sans profil, la personne n'entre plus par code : A1)...
        jeton = moi.banc.fabrique.session(moi.id).jeton
        # ... et recommence, Auth étant revenu : l'effacement se rejoue sans erreur.
        moi.banc.app.state.auth_admin = auth = AuthEnregistre()
        assert (await supprime(moi, jeton=jeton)).status_code == 204
        assert auth.appels == [moi.id]
        assert not compte_auth(moi) and sessions(moi) == 0
        assert len(evenements_avant()) == 1  # pas un second `compte_supprime` : le profil était déjà parti
        assert MOT_DE_PASSE not in caplog.text and jeton not in caplog.text

    async def test_un_404_d_auth_vaut_succes(self, moi: Personne, evenements_avant: Any) -> None:
        moi.banc.app.state.auth_admin = auth_repondant(404, {"error_code": "user_not_found", "msg": "x"})
        assert (await supprime(moi)).status_code == 204
        assert not profil(moi)

    async def test_un_404_d_une_autre_origine_n_est_pas_un_succes(
        self, moi: Personne, evenements_avant: Any
    ) -> None:
        moi.banc.app.state.auth_admin = auth_repondant(404, {"message": "page introuvable"})
        reponse = await supprime(moi)
        assert reponse.status_code == 503
        assert reponse.json()["code"] == "suppression_incomplete"

    async def test_une_reponse_5xx_d_auth_donne_503(self, moi: Personne, evenements_avant: Any) -> None:
        moi.banc.app.state.auth_admin = auth_repondant(500, {"msg": "boum"})
        assert (await supprime(moi)).status_code == 503
        assert compte_auth(moi) and not profil(moi)
