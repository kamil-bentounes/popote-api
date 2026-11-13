"""Tests de ops/preuve_auth_sans_mot_de_passe.py contre un faux Supabase (transport httpx, aucun réseau)."""

import json
import re
import secrets
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))

import preuve_auth_sans_mot_de_passe as preuve
from aligne_droits import FORBIDDEN_PROJECT_REF

REF = "abcdefghijklmnopqrst"
JETON = "sbp_" + "j" * 40
CLE_SECRETE = "sb_secret_" + "s" * 30
CLE_PUBLIABLE = "sb_publishable_" + "p" * 30
ENVIRONNEMENT = {"ESSAI_REF": REF, "SUPABASE_ESSAI_TOKEN": JETON}
MARQUE = preuve.MARQUE


@dataclass
class Utilisateur:
    email: str
    hachage: str
    marque: str | None
    mail_parti: bool = False


@dataclass
class FauxSupabase:
    """Un Supabase qui se souvient des comptes. Les options provoquent chaque écart que la preuve guette."""

    nom: str = preuve.NOM_DU_PROJET_D_ESSAI
    utilisateurs: dict[str, Utilisateur] = field(default_factory=dict)
    sans_mot_de_passe_refuse: bool = False
    hachage_vide: bool = False
    mail_parti: bool = False
    non_confirme: bool = False
    hachage_fige: bool = False
    connexion_ouverte: bool = False
    connexion_limitee: bool = False
    doublon_de_casse_accepte: bool = False
    suppression_refusee: bool = False
    panne_de_connexion: bool = False
    cles_illisibles: bool = False
    connexion_en_erreur: bool = False
    base_illisible_avec_des_comptes: bool = False
    redirige_le_projet: bool = False
    appels: list[tuple[str, str]] = field(default_factory=list)
    corps_de_creation: list[dict[str, Any]] = field(default_factory=list)
    mots_de_passe_vus: list[str] = field(default_factory=list)
    hachages_vus: list[str] = field(default_factory=list)
    _compteur: int = 0

    def ecritures_d_auth(self) -> list[tuple[str, str]]:
        return [
            (m, u) for m, u in self.appels if "/auth/v1/admin/users" in u and m in ("POST", "PUT", "DELETE")
        ]

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.appels.append((requete.method, str(requete.url)))
        chemin = requete.url.path
        if requete.url.host == "api.supabase.com":
            return self._gestion(requete, chemin)
        return self._auth(requete, chemin)

    # --- API de gestion -----------------------------------------------------------------------------

    def _gestion(self, requete: httpx.Request, chemin: str) -> httpx.Response:
        if requete.headers.get("Authorization") != f"Bearer {JETON}":
            return httpx.Response(401, json={"message": "jeton"})
        if chemin == f"/v1/projects/{REF}":
            if self.redirige_le_projet:
                return httpx.Response(302, headers={"Location": "https://autre.example/v1/projects"})
            return httpx.Response(200, json={"name": self.nom, "ref": REF})
        if chemin.endswith("/api-keys"):
            if self.cles_illisibles:
                return httpx.Response(403, json={"message": "droit manquant"})
            return httpx.Response(
                200,
                json=[
                    {"type": "publishable", "api_key": CLE_PUBLIABLE},
                    {"type": "secret", "api_key": CLE_SECRETE},
                ],
            )
        if chemin.endswith("/database/query"):
            if self.base_illisible_avec_des_comptes and self.utilisateurs:
                return httpx.Response(500, json={"message": "base indisponible"})
            return httpx.Response(201, json=self._sql(json.loads(requete.content)["query"]))
        return httpx.Response(404)

    def _sql(self, requete: str) -> list[dict[str, Any]]:
        if "count(*)" in requete:
            adresse = re.search(r"lower\('([^']+)'\)", requete)
            assert adresse is not None
            return [
                {"n": sum(u.email.lower() == adresse.group(1).lower() for u in self.utilisateurs.values())}
            ]
        if "encrypted_password" in requete:
            identifiant = re.search(r"id = '([0-9a-f-]{36})'", requete)
            assert identifiant is not None
            utilisateur = self.utilisateurs.get(identifiant.group(1))
            if utilisateur is None:
                return []
            return [
                {
                    "encrypted_password": utilisateur.hachage,
                    "confirme": not self.non_confirme,
                    "mail_parti": utilisateur.mail_parti,
                }
            ]
        assert "select id from auth.users" in requete
        return [
            {"id": identifiant}
            for identifiant, u in self.utilisateurs.items()
            if re.fullmatch(r"preuve-auth-.*@example\.com", u.email.lower())
            and (u.marque == MARQUE or "cree_par" not in requete)
        ]

    # --- Auth ---------------------------------------------------------------------------------------

    def _auth(self, requete: httpx.Request, chemin: str) -> httpx.Response:
        if self.panne_de_connexion and chemin == "/auth/v1/token":
            raise httpx.ConnectError("réseau coupé", request=requete)
        if chemin == "/auth/v1/token":
            return self._connexion(requete)
        if requete.headers.get("apikey") != CLE_SECRETE:
            return httpx.Response(401, json={"error_code": "no_authorization"})
        if chemin == "/auth/v1/admin/users" and requete.method == "GET":
            return httpx.Response(200, json={"users": []})
        if chemin == "/auth/v1/admin/users" and requete.method == "POST":
            return self._cree(json.loads(requete.content))
        identifiant = chemin.rsplit("/", 1)[-1]
        if requete.method == "PUT":
            return self._remplace(identifiant, json.loads(requete.content))
        if requete.method == "DELETE":
            return self._supprime(identifiant)
        return httpx.Response(404)

    def _nouveau_hachage(self) -> str:
        self._compteur += 1
        hachage = f"$2a$10${self._compteur:04d}" + secrets.token_hex(26)
        self.hachages_vus.append(hachage)
        return hachage

    def _cree(self, corps: dict[str, Any]) -> httpx.Response:
        self.corps_de_creation.append(corps)
        if "password" not in corps and self.sans_mot_de_passe_refuse:
            return httpx.Response(422, json={"error_code": "validation_failed", "msg": "password requis"})
        adresse = corps["email"]
        meme_adresse = [u for u in self.utilisateurs.values() if u.email.lower() == adresse.lower()]
        sauf_casse = self.doublon_de_casse_accepte and adresse != adresse.lower()
        if meme_adresse and not sauf_casse:
            # Auth recopie l'adresse dans son message : le script ne doit jamais le relayer.
            return httpx.Response(
                422, json={"error_code": "email_exists", "msg": f"A user with {adresse} already exists"}
            )
        self._compteur += 1
        identifiant = f"00000000-0000-4000-8000-{self._compteur:012d}"
        hachage = "" if self.hachage_vide else self._nouveau_hachage()
        self.utilisateurs[identifiant] = Utilisateur(
            adresse, hachage, corps["app_metadata"]["cree_par"], self.mail_parti
        )
        return httpx.Response(200, json={"id": identifiant, "email": adresse})

    def _remplace(self, identifiant: str, corps: dict[str, Any]) -> httpx.Response:
        utilisateur = self.utilisateurs.get(identifiant)
        if utilisateur is None:
            return httpx.Response(404, json={"error_code": "user_not_found"})
        self.mots_de_passe_vus.append(corps["password"])
        if not self.hachage_fige:
            utilisateur.hachage = self._nouveau_hachage()
        return httpx.Response(200, json={"id": identifiant})

    def _supprime(self, identifiant: str) -> httpx.Response:
        if self.suppression_refusee:
            return httpx.Response(500, json={"msg": "panne"})
        if self.utilisateurs.pop(identifiant, None) is None:
            return httpx.Response(404, json={"error_code": "user_not_found"})
        return httpx.Response(200, json={})

    def _connexion(self, requete: httpx.Request) -> httpx.Response:
        if requete.headers.get("apikey") != CLE_PUBLIABLE:
            return httpx.Response(401, json={"error_code": "no_authorization"})
        if self.connexion_en_erreur:
            return httpx.Response(500, json={"error_code": "unexpected_failure"})
        if self.connexion_limitee:
            return httpx.Response(429, json={"error_code": "over_request_rate_limit"})
        if self.connexion_ouverte:
            return httpx.Response(200, json={"access_token": "jeton-de-session"})
        return httpx.Response(
            400, json={"error_code": "invalid_credentials", "msg": "Invalid login credentials"}
        )


def lance(
    faux: FauxSupabase,
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
    environnement: dict[str, str] | None = None,
) -> tuple[int, str]:
    code = preuve.main(list(arguments), environnement or ENVIRONNEMENT, transport=httpx.MockTransport(faux))
    capture = capsys.readouterr()
    return code, capture.out + capture.err


def compte_marque(
    adresse: str = "preuve-auth-aaaaaaaaaaaa@example.com", marque: str | None = MARQUE
) -> Utilisateur:
    return Utilisateur(adresse, "$2a$10$ancien", marque)


class TestPreuveReussie:
    def test_proof_on_a_clean_essai_passes_and_leaves_no_account(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase()

        code, sortie = lance(faux, capsys)

        assert code == 0
        assert "PREUVE COMPLÈTE" in sortie
        assert faux.utilisateurs == {}

    def test_account_is_created_without_password_and_marked(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase()

        lance(faux, capsys)

        premiere = faux.corps_de_creation[0]
        assert "password" not in premiere
        assert premiere["email_confirm"] is True
        assert premiere["app_metadata"] == {"cree_par": MARQUE}

    def test_replacement_password_has_64_characters_of_four_classes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase()

        lance(faux, capsys)

        (mot_de_passe,) = faux.mots_de_passe_vus
        assert len(mot_de_passe) == 64
        assert any(c in string.ascii_lowercase for c in mot_de_passe)
        assert any(c in string.ascii_uppercase for c in mot_de_passe)
        assert any(c in string.digits for c in mot_de_passe)
        assert any(c in preuve.SYMBOLES for c in mot_de_passe)

    def test_second_creation_is_tried_with_both_cases_of_the_address(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase()

        lance(faux, capsys)

        adresses = [corps["email"] for corps in faux.corps_de_creation]
        assert len(adresses) == 3
        assert adresses[1] == adresses[0]
        assert adresses[2] == adresses[0].upper() != adresses[0]

    def test_two_runs_in_a_row_give_the_same_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase()

        premier = lance(faux, capsys)
        second = lance(faux, capsys)

        assert premier[0] == second[0] == 0
        assert premier[1] == second[1]

    def test_leftover_accounts_of_a_previous_run_are_swept_first(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(utilisateurs={"11111111-1111-4111-8111-111111111111": compte_marque()})

        code, sortie = lance(faux, capsys)

        assert code == 0
        assert "d'une exécution précédente" in sortie
        assert faux.utilisateurs == {}

    @pytest.mark.parametrize(
        "autre",
        [
            compte_marque(marque=None),
            compte_marque(marque="popote-api"),
            compte_marque(adresse="lea.martin@example.com"),
        ],
        ids=["sans marque", "autre marque", "autre adresse"],
    )
    def test_accounts_that_are_not_ours_are_never_deleted(
        self, autre: Utilisateur, capsys: pytest.CaptureFixture[str]
    ) -> None:
        identifiant = "22222222-2222-4222-8222-222222222222"
        faux = FauxSupabase(utilisateurs={identifiant: autre})

        code, _ = lance(faux, capsys)

        assert code == 0
        assert list(faux.utilisateurs) == [identifiant]


class TestEcarts:
    @pytest.mark.parametrize(
        ("option", "attendu"),
        [
            ({"sans_mot_de_passe_refuse": True}, "createUser sans mot de passe est refusé"),
            ({"hachage_vide": True}, "Aucun hachage n'a été écrit"),
            ({"non_confirme": True}, "n'est pas confirmé"),
            ({"mail_parti": True}, "mail de confirmation"),
            ({"connexion_ouverte": True}, "a ouvert une session"),
            ({"connexion_limitee": True}, "à reprendre plus tard"),
            ({"connexion_en_erreur": True}, "ne refuse pas comme attendu"),
            ({"hachage_fige": True}, "Le hachage n'a pas changé"),
            ({"doublon_de_casse_accepte": True}, "autre casse"),
        ],
        ids=[
            "création refusée",
            "hachage vide",
            "e-mail non confirmé",
            "mail parti",
            "connexion ouverte",
            "429",
            "connexion en 500",
            "hachage fixe",
            "doublon",
        ],
    )
    def test_each_deviation_exits_1_and_still_removes_the_test_accounts(
        self, option: dict[str, bool], attendu: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(**option)

        code, sortie = lance(faux, capsys)

        assert code == 1
        assert attendu in sortie
        assert "PREUVE COMPLÈTE" not in sortie
        assert faux.utilisateurs == {}

    def test_network_failure_in_the_middle_exits_2_and_still_cleans_up(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(panne_de_connexion=True)

        code, sortie = lance(faux, capsys)

        assert code == 2
        assert "ConnectError" in sortie
        assert faux.utilisateurs == {}

    def test_created_account_is_removed_even_when_the_database_cannot_be_read(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(base_illisible_avec_des_comptes=True)

        code, sortie = lance(faux, capsys)

        assert code == 2
        assert "Lecture de la base de l'essai impossible" in sortie
        assert faux.utilisateurs == {}

    def test_unexpected_exception_in_a_step_still_removes_the_account(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        faux = FauxSupabase()

        def explose(*_: object) -> None:
            raise RuntimeError("bug provoqué")

        monkeypatch.setattr(preuve, "etape_connexion_publique_refusee", explose)
        sorties: list[str] = []
        with httpx.Client(transport=httpx.MockTransport(faux)) as http:
            essai = preuve.Essai(preuve.Acces(REF, JETON), http, ENVIRONNEMENT)
            with pytest.raises(RuntimeError, match="bug provoqué"):
                preuve.joue_la_preuve(essai, sorties.append)

        assert faux.utilisateurs == {}

    def test_account_that_cannot_be_deleted_is_reported_and_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(suppression_refusee=True)

        code, sortie = lance(faux, capsys)

        assert code == 1
        assert "des comptes de test restent" in sortie
        assert "suppression d'un compte de test refusée" in sortie
        assert len(faux.utilisateurs) == 1


class TestGardeFous:
    def test_prod_reference_is_refused_before_any_call(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase()

        code, sortie = lance(
            faux, capsys, environnement={**ENVIRONNEMENT, "ESSAI_REF": FORBIDDEN_PROJECT_REF}
        )

        assert code == 2
        assert "prod" in sortie
        assert faux.appels == []

    @pytest.mark.parametrize("variable", ["ESSAI_REF", "SUPABASE_ESSAI_TOKEN"])
    def test_missing_variable_is_refused_before_any_call(
        self, variable: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase()
        environnement = {k: v for k, v in ENVIRONNEMENT.items() if k != variable}

        code, sortie = lance(faux, capsys, environnement=environnement)

        assert code == 2
        assert variable in sortie
        assert faux.appels == []

    @pytest.mark.parametrize("ref", ["court", "ABCDEFGHIJKLMNOPQRST", "abcdefghijklmnopqrst/../x", "a" * 21])
    def test_reference_with_a_wrong_shape_is_refused(
        self, ref: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase()

        code, _ = lance(faux, capsys, environnement={**ENVIRONNEMENT, "ESSAI_REF": ref})

        assert code == 2
        assert faux.appels == []

    @pytest.mark.parametrize("arguments", [(), ("--a-blanc",)])
    def test_project_with_another_name_is_refused_without_writing(
        self, arguments: tuple[str, ...], capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(nom="popote-prod")

        code, sortie = lance(faux, capsys, *arguments)

        assert code == 2
        assert "ne s'appelle pas" in sortie
        assert faux.ecritures_d_auth() == []

    def test_redirection_is_not_followed(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase(redirige_le_projet=True)

        code, _ = lance(faux, capsys)

        assert code == 2
        assert all(httpx.URL(url).host != "autre.example" for _, url in faux.appels)

    def test_unreadable_api_keys_exit_2_and_say_what_to_set(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase(cles_illisibles=True)

        code, sortie = lance(faux, capsys)

        assert code == 2
        assert "ESSAI_SUPABASE_SECRET_KEY" in sortie
        assert faux.ecritures_d_auth() == []

    def test_keys_from_the_environment_skip_the_api_keys_call(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(cles_illisibles=True)
        environnement = {
            **ENVIRONNEMENT,
            "ESSAI_SUPABASE_SECRET_KEY": CLE_SECRETE,
            "ESSAI_SUPABASE_PUBLISHABLE_KEY": CLE_PUBLIABLE,
        }

        code, _ = lance(faux, capsys, environnement=environnement)

        assert code == 0
        assert not any(url.endswith("/api-keys?reveal=true") for _, url in faux.appels)

    def test_only_the_essai_hosts_are_called(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase()

        lance(faux, capsys)

        hotes = {httpx.URL(url).host for _, url in faux.appels}
        assert hotes == {"api.supabase.com", f"{REF}.supabase.co"}

    @pytest.mark.parametrize("adresse", ["x'; drop table auth.users; --@example.com", "lea@example.com", ""])
    def test_an_address_that_the_script_did_not_make_never_reaches_sql(self, adresse: str) -> None:
        with httpx.Client(transport=httpx.MockTransport(FauxSupabase())) as http:
            essai = preuve.Essai(preuve.Acces(REF, JETON), http, ENVIRONNEMENT)

            with pytest.raises(ValueError, match="adresse de test"):
                essai.nombre_de_comptes_a_l_adresse(adresse)


class TestAblanc:
    def test_dry_run_reads_only_and_succeeds(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase()

        code, sortie = lance(faux, capsys, "--a-blanc")

        assert code == 0
        assert "A BLANC terminé" in sortie
        assert faux.ecritures_d_auth() == []
        assert faux.utilisateurs == {}

    def test_dry_run_does_not_delete_leftover_accounts(self, capsys: pytest.CaptureFixture[str]) -> None:
        faux = FauxSupabase(utilisateurs={"11111111-1111-4111-8111-111111111111": compte_marque()})

        code, sortie = lance(faux, capsys, "--a-blanc")

        assert code == 0
        assert "1 compte(s) de test présent(s)" in sortie
        assert len(faux.utilisateurs) == 1

    def test_dry_run_exits_1_when_admin_refuses_the_secret_key(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase()
        environnement = {
            **ENVIRONNEMENT,
            "ESSAI_SUPABASE_SECRET_KEY": "sb_secret_" + "x" * 30,
            "ESSAI_SUPABASE_PUBLISHABLE_KEY": CLE_PUBLIABLE,
        }

        code, sortie = lance(faux, capsys, "--a-blanc", environnement=environnement)

        assert code == 1
        assert "refuse la clé secrète" in sortie


class TestRienNeFuite:
    @pytest.mark.parametrize(
        "option",
        [
            {},
            {"hachage_fige": True},
            {"panne_de_connexion": True},
            {"suppression_refusee": True},
            {"cles_illisibles": True},
        ],
        ids=["succès", "écart", "panne", "reste", "clés"],
    )
    def test_output_contains_no_secret_address_password_or_hash(
        self, option: dict[str, bool], capsys: pytest.CaptureFixture[str]
    ) -> None:
        faux = FauxSupabase(**option)

        _, sortie = lance(faux, capsys)

        interdits = [
            JETON,
            CLE_SECRETE,
            CLE_PUBLIABLE,
            "example.com",
            "preuve-auth-",
            *faux.mots_de_passe_vus,
        ]
        interdits += faux.hachages_vus + list(faux.utilisateurs)
        assert [valeur for valeur in interdits if valeur in sortie] == []

    def test_error_code_with_the_shape_of_a_message_is_dropped(self) -> None:
        reponse = preuve.Reponse(422, json.dumps({"error_code": "A user lea@example.com exists"}).encode())

        assert reponse.code() is None
        assert "lea" not in reponse.decrit()

    def test_repr_of_access_and_client_hide_the_token(self) -> None:
        with httpx.Client(transport=httpx.MockTransport(FauxSupabase())) as http:
            essai = preuve.Essai(preuve.Acces(REF, JETON), http, ENVIRONNEMENT)

            assert JETON not in repr(preuve.Acces(REF, JETON)) + repr(essai)


class TestOutils:
    @pytest.mark.parametrize("tirage", range(20))
    def test_random_password_always_has_the_four_classes(self, tirage: int) -> None:
        mot_de_passe = preuve.mot_de_passe_aleatoire()

        assert len(mot_de_passe) == preuve.LONGUEUR_DU_MOT_DE_PASSE
        classes = (string.ascii_lowercase, string.ascii_uppercase, string.digits, preuve.SYMBOLES)
        assert all(any(c in classe for c in mot_de_passe) for classe in classes)

    def test_test_address_has_the_shape_the_cleanup_looks_for(self) -> None:
        assert preuve.ADRESSE_DE_TEST.fullmatch(preuve.adresse_de_test())

    @pytest.mark.parametrize(
        ("hachage", "attendu"),
        [
            ("$2a$10$" + "x" * 53, "2a, coût 10"),
            ("$2b$12$" + "x" * 53, "2b, coût 12"),
            ("", "vide"),
            ("argon2id$abc", "inconnu"),
        ],
    )
    def test_hash_state_shows_scheme_and_cost_but_never_the_hash(self, hachage: str, attendu: str) -> None:
        identifiant = "00000000-0000-4000-8000-000000000001"
        faux = FauxSupabase(utilisateurs={identifiant: Utilisateur("a@example.com", hachage, None)})
        with httpx.Client(transport=httpx.MockTransport(faux)) as http:
            essai = preuve.Essai(preuve.Acces(REF, JETON), http, ENVIRONNEMENT)

            etat = essai.etat_du_compte(preuve.UUID(identifiant))

        assert etat.decrit_le_hachage() == attendu
        assert hachage == "" or hachage not in repr(etat)

    def test_missing_account_in_the_database_is_a_deviation(self) -> None:
        with httpx.Client(transport=httpx.MockTransport(FauxSupabase())) as http:
            essai = preuve.Essai(preuve.Acces(REF, JETON), http, ENVIRONNEMENT)

            with pytest.raises(preuve.EcartError):
                essai.etat_du_compte(preuve.UUID(int=1))

    def test_oversized_response_is_refused(self) -> None:
        def enorme(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * (preuve.OCTETS_MAX_REPONSE + 1))

        with httpx.Client(transport=httpx.MockTransport(enorme)) as http:
            essai = preuve.Essai(preuve.Acces(REF, JETON), http, ENVIRONNEMENT)

            with pytest.raises(preuve.AccesError, match="trop grosse"):
                essai.exige_le_projet_d_essai()
