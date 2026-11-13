"""T13 : lire et accepter une invitation (spec § 4 ; B1, B10, B11, B20, B23, B24), en base locale et contre l'Auth
local. Données inventées. La liste de fuites est toujours un faux (aucun réseau) ; Auth est le vrai client, qui
se souvient de ses appels et que chaque test peut faire échouer.
"""

# ruff: noqa: E501, F811, F401

import asyncio
import hashlib
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from _fabrique import Fabrique
from pydantic import SecretStr
from test_auth_admin_local import ENV_LOCAL
from test_connexion import ECRITURE, MOT_DE_PASSE, Banc, banc_avec
from test_verifie_mot_de_passe import Comptes, comptes

from popote_api.infra.auth_admin import AuthAdmin, AuthIndisponible, CompteDejaExistant
from popote_api.infra.db import Base
from popote_api.infra.fuites import CauseIndisponibilite, ResultatFuite
from popote_api.security import acceptation_invitation as modele

pytestmark = pytest.mark.integration

INSPECTION = "/api/v1/invitations/inspections"
ACCEPTATION = "/api/v1/invitations/acceptances"
NOUVEAU = "un mot de passe tout neuf, long"
CHAMPS_INSPECTION = {"invited_by", "expires_at"}
TOKENS_VIDES = (
    "confirmation_token = '', recovery_token = '', email_change_token_new = '', email_change = '', "
    "email_change_token_current = '', phone_change = '', phone_change_token = '', reauthentication_token = ''"
)


class FauxFuites:
    def __init__(self) -> None:
        self.verdict, self.appels = ResultatFuite.sain(), 0

    async def verifie(self, mot_de_passe: str) -> ResultatFuite:
        self.appels += 1
        return self.verdict


class EspionAuth(AuthAdmin):
    """Le vrai client d'Auth local, qui se souvient de ses appels et qu'on peut faire échouer."""

    def __init__(self) -> None:
        url, cle = ENV_LOCAL.get("POPOTE_SUPABASE_URL"), ENV_LOCAL.get("POPOTE_SUPABASE_SECRET_KEY")
        if not url or not cle:
            pytest.fail("Pas de .env local : lancer `bash ops/env-local.sh` (pile Supabase locale démarrée).")
        super().__init__(url, SecretStr(cle))
        self.creations: list[str] = []
        self.suppressions: list[UUID] = []
        self.changements: list[UUID] = []
        self.panne_creation = False
        self.course_adresse = False
        self.panne_suppression = False

    async def cree_compte(self, email: str, mot_de_passe: str) -> UUID:
        self.creations.append(email)
        if self.panne_creation:
            raise AuthIndisponible("panne simulée")
        if self.course_adresse:
            raise CompteDejaExistant("course simulée")
        return await super().cree_compte(email, mot_de_passe)

    async def change_mot_de_passe(self, identifiant: UUID, mot_de_passe: str, **plus: Any) -> None:
        self.changements.append(identifiant)
        await super().change_mot_de_passe(identifiant, mot_de_passe, **plus)

    async def supprime_compte(self, identifiant: UUID) -> None:
        self.suppressions.append(identifiant)
        if self.panne_suppression:
            raise AuthIndisponible("panne simulée")
        await super().supprime_compte(identifiant)

    @property
    def appels(self) -> int:
        return len(self.creations) + len(self.changements)


class Cadre:
    """Un foyer, son hôte, des liens, un banc, et de quoi tout retirer à la fin."""

    def __init__(self, banc: Banc, fabrique: Fabrique, fuites: FauxFuites, auth: EspionAuth) -> None:
        self.banc, self.fabrique, self.fuites, self.auth = banc, fabrique, fuites, auth
        self.foyer = fabrique.foyer()
        self.hote = fabrique.personne(self.foyer)
        self.liens: list[UUID] = []
        self.adresses: list[str] = []
        banc.app.state.fuites, banc.app.state.auth_admin = fuites, auth

    def lien(
        self, *, delai: str = "6 days", revoque: bool = False, utilise: bool = False
    ) -> tuple[str, UUID]:
        jeton = secrets.token_urlsafe(32)
        (ligne,) = self.banc.lignes(
            "insert into public.invite_link (household_id, created_by, token_hash, created_at, expires_at, revoked_at, "
            "accepted_at) values (%s, %s, %s, now() - interval '1 day', now() + %s::interval, case when %s then now() end, "
            "case when %s then now() end) returning id",
            self.foyer,
            self.hote.id,
            hashlib.sha256(jeton.encode("ascii")).digest(),
            delai,
            revoque,
            utilise,
        )
        self.liens.append(ligne[0])
        cles = [self.banc.empreintes.cle_lien_requise(hashlib.sha256(jeton.encode("ascii")).digest())]
        self.banc.cles += cles
        return jeton, ligne[0]

    def adresse(self, nom: str | None = None) -> str:
        adresse = f"{nom or 'nouvelle-' + uuid4().hex[:10]}@test.local"
        self.adresses.append(adresse)
        return adresse

    def compte(
        self, *, hachage: bool = False, profil: bool = False, nom: str | None = None
    ) -> tuple[UUID, str]:
        """Un compte déjà là : par défaut un orphelin (sans profil, sans hachage)."""
        adresse, identifiant = self.adresse(nom), uuid4()
        self.fabrique.admin.execute(
            "insert into auth.users (instance_id, id, aud, role, email, encrypted_password, "
            "email_confirmed_at, created_at, updated_at, confirmation_token, recovery_token, "
            "email_change_token_new, email_change, email_change_token_current, phone_change, "
            "phone_change_token, reauthentication_token) values "
            "('00000000-0000-0000-0000-000000000000', %s, 'authenticated', 'authenticated', %s, %s, now(), "
            "now(), now(), '', '', '', '', '', '', '', '')",
            (
                identifiant,
                adresse,
                "$2a$10$TomZERTB2nLik39KZPllf.Hj5WyG1pEvK9axxrIM7a3IdbHay1/Q2" if hachage else "",
            ),
        )
        if profil:
            self.fabrique.admin.execute(
                "insert into public.user_profile (id, household_id, display_name) values (%s, %s, 'x')",
                (identifiant, self.foyer),
            )
        return identifiant, adresse

    def etat(self, lien: UUID) -> str:
        (ligne,) = self.banc.lignes(
            "select etat from public.etat_invitation((select token_hash from public.invite_link where id = %s))",
            lien,
        )
        return str(ligne[0])

    def comptes_de(self, adresse: str) -> list[UUID]:
        return [
            r[0]
            for r in self.banc.lignes("select id from auth.users where lower(email) = %s", adresse.lower())
        ]

    def membres(self) -> int:
        return int(
            self.banc.lignes("select count(*) from public.user_profile where household_id = %s", self.foyer)[
                0
            ][0]
        )

    async def accepte(
        self, jeton: str, adresse: str, mot_de_passe: str = NOUVEAU, **plus: Any
    ) -> httpx.Response:
        corps = {"token": jeton, "email": adresse, "password": mot_de_passe}
        return await self.banc.client().post(
            ACCEPTATION, json=corps, headers=ECRITURE | plus.pop("headers", {})
        )

    async def inspecte(self, jeton: str) -> httpx.Response:
        return await self.banc.client().post(INSPECTION, json={"token": jeton}, headers=ECRITURE)

    def nettoie(self) -> None:
        adm = self.fabrique.admin
        ids = [
            r[0]
            for r in adm.execute(
                "select id from auth.users where lower(email) = any(%s)",
                ([a.lower() for a in self.adresses],),
            ).fetchall()
        ]
        adm.execute(
            "delete from public.security_event where person_id = any(%s) or invitation_id = any(%s)",
            (ids, self.liens),
        )
        adm.execute("delete from public.reprise_en_cours")
        adm.execute("delete from public.user_profile where id = any(%s)", (ids,))
        adm.execute("delete from public.login_throttle where key = any(%s)", (self.banc.cles,))
        adm.execute("delete from auth.users where id = any(%s)", (ids,))


@pytest.fixture
async def cadre_de(
    base: Base, fabrique: Fabrique, banc_avec: Callable[..., Banc]
) -> AsyncIterator[Callable[..., Cadre]]:
    cadres: list[Cadre] = []

    def cree(**reglages: Any) -> Cadre:
        banc = banc_avec(**({"invitation_essais_par_ip": 10000} | reglages))
        banc.cles.append(banc.empreintes.cle_ip_requise(banc.ip))
        cadres.append(Cadre(banc, fabrique, FauxFuites(), EspionAuth()))
        return cadres[-1]

    yield cree
    for cadre in cadres:
        cadre.nettoie()


@pytest.fixture
def cadre(cadre_de: Callable[..., Cadre]) -> Cadre:
    return cadre_de()


# ── Inspection ──────────────────────────────────────────────────────────────
async def test_inspection_d_un_lien_valide_sans_aucune_ecriture(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    avant = cadre.banc.lignes(
        "select accepted_at, revoked_at, accepted_by from public.invite_link where id = %s", lien
    )
    reponse = await cadre.inspecte(jeton)
    assert reponse.status_code == 200
    corps = reponse.json()
    assert set(corps) == CHAMPS_INSPECTION
    assert corps["invited_by"].startswith("personne-")
    assert "@" not in reponse.text
    assert avant == cadre.banc.lignes(
        "select accepted_at, revoked_at, accepted_by from public.invite_link where id = %s", lien
    )
    assert cadre.fuites.appels == 0 and cadre.auth.appels == 0


async def test_inspection_inconnu_et_mal_forme_ont_le_meme_corps(cadre: Cadre) -> None:
    inconnu = await cadre.inspecte(secrets.token_urlsafe(32))
    mal_forme = await cadre.inspecte("pas un jeton")
    assert inconnu.status_code == mal_forme.status_code == 404
    assert {k: v for k, v in inconnu.json().items() if k != "instance"} == {
        k: v for k, v in mal_forme.json().items() if k != "instance"
    }
    assert inconnu.json()["code"] == "invitation_inconnue"


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"delai": "-1 second"}, "invitation_expiree"),
        ({"utilise": True}, "invitation_utilisee"),
        ({"revoque": True}, "invitation_revoquee"),
    ],
)
async def test_inspection_d_un_lien_refuse(cadre: Cadre, options: dict[str, Any], code: str) -> None:
    jeton, _ = cadre.lien(**options)
    reponse = await cadre.inspecte(jeton)
    assert (reponse.status_code, reponse.json()["code"]) == (410, code)


async def test_la_31e_inspection_d_une_ip_rend_429(cadre_de: Callable[..., Cadre]) -> None:
    cadre = cadre_de(invitation_essais_par_ip=30)
    for _ in range(30):
        assert (await cadre.inspecte("pas un jeton")).status_code == 404
    reponse = await cadre.inspecte("pas un jeton")
    assert reponse.status_code == 429
    assert int(reponse.headers["retry-after"]) > 0


# ── Acceptation : le succès ─────────────────────────────────────────────────
async def test_acceptation_cree_le_compte_le_profil_et_la_session(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    adresse = cadre.adresse()
    reponse = await cadre.accepte(jeton, f"  {adresse.upper()} ")
    assert reponse.status_code == 201, reponse.text
    assert "__Host-popote_session=" in reponse.headers["set-cookie"]
    assert set(reponse.json()) == {"id"}
    (personne,) = cadre.comptes_de(adresse)  # écrite en minuscules, une seule fois
    (profil,) = cadre.banc.lignes(
        "select household_id, display_name, password_set, "
        "entre_le = (date_trunc('month', now() at time zone 'Europe/Paris') + interval '1 month')::date "
        "from public.user_profile where id = %s",
        personne,
    )
    assert profil == (cadre.foyer, "", True, True)
    assert cadre.banc.lignes(
        "select accepted_by, accepted_at is not null from public.invite_link where id = %s", lien
    ) == [(personne, True)]
    assert cadre.membres() == 2
    assert cadre.banc.lignes("select count(*) from public.login_session where person_id = %s", personne) == [
        (1,)
    ]
    assert cadre.banc.lignes(
        "select count(*) from public.security_event where kind = 'invitation_acceptee' and person_id = %s",
        personne,
    ) == [(1,)]
    connexion = await cadre.banc.connecte(adresse, NOUVEAU)
    assert connexion.status_code == 201
    assert cadre.fuites.appels == 1


async def test_ni_jeton_ni_mot_de_passe_ni_adresse_dans_les_journaux(
    cadre: Cadre, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    jeton, _ = cadre.lien()
    adresse = cadre.adresse()
    cadre.fuites.verdict = ResultatFuite.indisponible(CauseIndisponibilite.delai)
    assert (await cadre.accepte(jeton, adresse)).status_code == 201
    for secret in (jeton, NOUVEAU, adresse, adresse.split("@")[0]):
        assert secret not in caplog.text
    (personne,) = cadre.comptes_de(adresse)
    # B23 : liste hors service -> accepté, l'événement le dit.
    assert cadre.banc.lignes(
        "select count(*) from public.security_event where kind = 'verification_fuites_indisponible' and person_id = %s",
        personne,
    ) == [(1,)]


async def test_origine_etrangere_refusee(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    reponse = await cadre.accepte(jeton, cadre.adresse(), headers={"Origin": "https://autre.example"})
    assert reponse.status_code == 403
    assert cadre.etat(lien) == "valide"


# ── Acceptation : l'ordre (B1) et les limites (B11) ─────────────────────────
async def test_jeton_inconnu_avec_une_adresse_connue_rend_404_jamais_409(cadre: Cadre) -> None:
    _, adresse = cadre.compte(profil=True, hachage=True)
    reponse = await cadre.accepte(secrets.token_urlsafe(32), adresse)
    assert (reponse.status_code, reponse.json()["code"]) == (404, "invitation_inconnue")
    assert cadre.fuites.appels == 0 and cadre.auth.appels == 0


@pytest.mark.parametrize("options", [{"delai": "-1 second"}, {"utilise": True}, {"revoque": True}])
async def test_lien_perime_ne_coute_ni_fuites_ni_auth(cadre: Cadre, options: dict[str, Any]) -> None:
    jeton, _ = cadre.lien(**options)
    reponse = await cadre.accepte(jeton, cadre.adresse())
    assert reponse.status_code == 410
    assert cadre.fuites.appels == 0 and cadre.auth.appels == 0
    # La limite du lien n'est comptée qu'après la lecture : un lien refusé n'a pas de compteur.
    assert cadre.banc.lignes(
        "select count(*) from public.login_throttle where scope = 'invitation_link' and key = any(%s)",
        cadre.banc.cles,
    ) == [(0,)]


async def test_ordre_ip_puis_lecture_puis_lien(cadre_de: Callable[..., Cadre]) -> None:
    cadre = cadre_de(invitation_essais_par_ip=1)
    jeton, _ = cadre.lien()
    assert (await cadre.accepte(secrets.token_urlsafe(32), cadre.adresse())).status_code == 404
    # L'IP a épuisé son créneau : même un lien valide est refusé AVANT toute lecture, et sans appel externe.
    reponse = await cadre.accepte(jeton, cadre.adresse())
    assert reponse.status_code == 429
    assert cadre.fuites.appels == 0 and cadre.auth.appels == 0


async def test_la_11e_acceptation_du_meme_lien_rend_429_sans_appel_externe(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    _, connue = cadre.compte(profil=True, hachage=True)
    for _ in range(10):
        assert (await cadre.accepte(jeton, connue)).status_code == 409
    appels = cadre.fuites.appels
    reponse = await cadre.accepte(jeton, connue)
    assert reponse.status_code == 429 and int(reponse.headers["retry-after"]) > 0
    assert cadre.fuites.appels == appels == 10
    assert cadre.etat(lien) == "valide"


# ── Acceptation : adresse et mot de passe ───────────────────────────────────
@pytest.mark.parametrize("sujet", ["avec-foyer", "sans-foyer-avec-hachage", "autre-casse", "pleine-largeur"])
async def test_adresse_connue_rend_409_et_le_lien_reste_valide(cadre: Cadre, sujet: str) -> None:
    jeton, lien = cadre.lien()
    _, adresse = cadre.compte(profil=sujet == "avec-foyer", hachage=True, nom="victime-" + uuid4().hex[:8])
    envoyee = {
        "autre-casse": adresse.upper(),
        "pleine-largeur": adresse.translate({c: c + 0xFEE0 for c in range(0x21, 0x7F)}),
    }.get(sujet, adresse)
    reponse = await cadre.accepte(jeton, envoyee)
    assert (reponse.status_code, reponse.json()["code"]) == (409, "compte_existant")
    assert cadre.etat(lien) == "valide" and cadre.auth.appels == 0


async def test_regression_de_l_ancien_ilike(cadre: Cadre) -> None:
    jeton, _ = cadre.lien()
    _, victime = cadre.compte(profil=True, hachage=True, nom="victime-1")
    motif = cadre.adresse("victime-%")
    reponse = await cadre.accepte(jeton, motif)
    assert reponse.status_code == 201, reponse.text
    assert len(cadre.comptes_de(victime)) == 1 and len(cadre.comptes_de(motif)) == 1


@pytest.mark.parametrize(
    "adresse",
    [
        "sans-arobase.test.local",
        "a@b@test.local",
        "a b@test.local",
        "a" * 250 + "@test.local",
        "a\x01b@test.local",
        "é@test.local",
        "a@tést.local",
    ],
)
async def test_adresses_invalides_rendent_422(cadre: Cadre, adresse: str) -> None:
    jeton, lien = cadre.lien()
    reponse = await cadre.accepte(jeton, adresse)
    assert reponse.status_code == 422
    assert cadre.etat(lien) == "valide" and cadre.auth.appels == 0


@pytest.mark.parametrize("mot_de_passe", ["a" * 14, "é" * 80, "x" * 300])
async def test_mot_de_passe_refuse_ne_consomme_pas_le_lien(cadre: Cadre, mot_de_passe: str) -> None:
    jeton, lien = cadre.lien()
    reponse = await cadre.accepte(jeton, cadre.adresse(), mot_de_passe)
    assert reponse.status_code == 422
    assert cadre.etat(lien) == "valide" and cadre.auth.appels == 0


async def test_mot_de_passe_fuite_ne_consomme_pas_le_lien(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    cadre.fuites.verdict = ResultatFuite.fuite()
    reponse = await cadre.accepte(jeton, cadre.adresse())
    assert reponse.status_code == 422 and reponse.json()["errors"][0]["pointer"] == "/password"
    assert cadre.etat(lien) == "valide" and cadre.auth.appels == 0


# ── Acceptation : la course et les échecs ───────────────────────────────────
@pytest.mark.parametrize("combien", [2, 10])
async def test_acceptations_simultanees_du_meme_lien(cadre: Cadre, combien: int) -> None:
    jeton, lien = cadre.lien()
    adresses = [cadre.adresse() for _ in range(combien)]
    reponses = await asyncio.gather(*(cadre.accepte(jeton, a) for a in adresses))
    assert sorted(r.status_code for r in reponses) == [201] + [410] * (combien - 1)
    assert sum(len(cadre.comptes_de(a)) for a in adresses) == 1
    assert cadre.membres() == 2
    assert cadre.etat(lien) == "utilisee"


async def test_meme_adresse_avec_deux_liens(cadre: Cadre) -> None:
    (j1, l1), (j2, l2) = cadre.lien(), cadre.lien()
    adresse = cadre.adresse()
    reponses = await asyncio.gather(cadre.accepte(j1, adresse), cadre.accepte(j2, adresse))
    assert sorted(r.status_code for r in reponses) == [201, 409]
    assert len(cadre.comptes_de(adresse)) == 1
    assert sorted(cadre.etat(x) for x in (l1, l2)) == ["utilisee", "valide"]  # le perdant retrouve son lien


async def test_course_d_adresse_rouvre_le_lien(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    cadre.auth.course_adresse = True
    reponse = await cadre.accepte(jeton, cadre.adresse())
    assert (reponse.status_code, reponse.json()["code"]) == (409, "compte_existant")
    assert cadre.etat(lien) == "valide"


async def test_auth_en_panne_brule_le_lien(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    adresse = cadre.adresse()
    cadre.auth.panne_creation = True
    assert (await cadre.accepte(jeton, adresse)).status_code == 503
    assert cadre.etat(lien) == "utilisee" and cadre.membres() == 1 and not cadre.comptes_de(adresse)
    assert cadre.banc.lignes("select accepted_by from public.invite_link where id = %s", lien) == [(None,)]


async def test_profil_en_echec_supprime_le_compte_et_brule_le_lien(
    cadre: Cadre, monkeypatch: pytest.MonkeyPatch
) -> None:
    jeton, lien = cadre.lien()
    adresse = cadre.adresse()
    monkeypatch.setattr(modele, "PROFIL", "select %s::uuid, %s::uuid from public.table_inexistante")
    assert (await cadre.accepte(jeton, adresse)).status_code == 500
    assert len(cadre.auth.suppressions) == 1 and not cadre.comptes_de(adresse)
    assert cadre.etat(lien) == "utilisee" and cadre.membres() == 1


async def test_compensation_en_echec_signale_le_compte_sans_adresse(
    cadre: Cadre, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    jeton, _ = cadre.lien()
    adresse = cadre.adresse()
    monkeypatch.setattr(modele, "PROFIL", "select %s::uuid, %s::uuid from public.table_inexistante")
    cadre.auth.panne_suppression = True
    assert (await cadre.accepte(jeton, adresse)).status_code == 503
    (personne,) = cadre.comptes_de(adresse)  # il reste, à nettoyer
    assert f"compte_orphelin_a_nettoyer personne={personne}" in caplog.text
    assert adresse not in caplog.text and jeton not in caplog.text


# ── Reprise d'un compte orphelin (B10) ──────────────────────────────────────
async def test_orphelin_sans_hachage_est_repris(cadre: Cadre) -> None:
    jeton, lien = cadre.lien()
    personne, adresse = cadre.compte()
    reponse = await cadre.accepte(jeton, adresse)
    assert reponse.status_code == 201, reponse.text
    assert cadre.comptes_de(adresse) == [personne] and cadre.membres() == 2
    assert cadre.banc.lignes("select accepted_by from public.invite_link where id = %s", lien) == [
        (personne,)
    ]
    assert cadre.banc.lignes(
        "select count(*) from public.security_event where kind = 'compte_repris' and person_id = %s", personne
    ) == [(1,)]
    assert (await cadre.banc.connecte(adresse, NOUVEAU)).status_code == 201
    assert cadre.banc.lignes(
        "select email_confirmed_at is not null from auth.users where id = %s", personne
    ) == [(True,)]


@pytest.mark.parametrize("etat", ["hachage", "profil"])
async def test_orphelin_avec_hachage_ou_profil_n_est_pas_repris(cadre: Cadre, etat: str) -> None:
    jeton, lien = cadre.lien()
    _, adresse = cadre.compte(hachage=etat == "hachage", profil=etat == "profil")
    if etat == "hachage":
        cadre.fabrique.admin.execute(
            "update auth.users set encrypted_password = %s where email = %s",
            ("$2a$10$TomZERTB2nLik39KZPllf.Hj5WyG1pEvK9axxrIM7a3IdbHay1/Q2", adresse),
        )
    reponse = await cadre.accepte(jeton, adresse)
    assert (reponse.status_code, reponse.json()["code"]) == (409, "compte_existant")
    assert cadre.etat(lien) == "valide" and cadre.auth.changements == []


async def test_deux_liens_pour_le_meme_orphelin_un_seul_gagne(cadre: Cadre) -> None:
    (j1, _), (j2, _) = cadre.lien(), cadre.lien()
    personne, adresse = cadre.compte()
    reponses = await asyncio.gather(
        cadre.accepte(j1, adresse, "premier mot de passe très long"),
        cadre.accepte(j2, adresse, "second mot de passe très long!"),
    )
    codes = sorted(r.status_code for r in reponses)
    assert codes[0] == 201 and codes[1] in (409, 410)
    gagnant = 0 if reponses[0].status_code == 201 else 1
    mot_de_passe = ("premier mot de passe très long", "second mot de passe très long!")[gagnant]
    assert (await cadre.banc.connecte(adresse, mot_de_passe)).status_code == 201
    assert cadre.membres() == 2 and cadre.auth.changements == [personne]


# ── Droits ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize(
    "appel",
    [
        "select * from public.consomme_invitation('\\x00'::bytea)",
        "select public.rend_invitation(gen_random_uuid())",
        "select * from public.compte_pour_email('a@b.c')",
        "select public.reserve_reprise(decode(repeat('00', 32), 'hex'))",
    ],
)
def test_fonctions_de_service_refusees_aux_roles_publics(cadre: Cadre, role: str, appel: str) -> None:
    import psycopg

    adm = cadre.fabrique.admin
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with adm.transaction(force_rollback=True):
            adm.execute(f"set local role {role}")
            adm.execute(appel)  # type: ignore[call-overload]
