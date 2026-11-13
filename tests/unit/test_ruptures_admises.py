"""Tests de scripts/ruptures_admises.py : le contrôle de rupture du contrat et ses ruptures admises.

Les tests marqués `oasdiff` lancent le binaire figé de la CI (variable `OASDIFF`) ; ils tournent dans le job
`contrat`. Les autres n'ont besoin ni de lui ni du réseau.
"""

import copy
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import ruptures_admises as outil

RAISON = "# Raison : la nouvelle appli n'est pas en ligne"
BASE: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "essai", "version": "1"},
    "paths": {
        "/a": {"get": {"operationId": "a", "responses": {"200": {"description": "ok"}}}},
        "/b": {
            "post": {
                "operationId": "b",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"x": {"type": "string"}}}
                        }
                    }
                },
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


def _contrat_sans_a() -> dict[str, Any]:
    """Rupture « supprimé » : la route /a disparaît."""
    revision = copy.deepcopy(BASE)
    del revision["paths"]["/a"]
    return revision


def _contrat_avec_x_requis() -> dict[str, Any]:
    """Rupture « ajouté » : le champ x devient obligatoire."""
    revision = copy.deepcopy(BASE)
    revision["paths"]["/b"]["post"]["requestBody"]["content"]["application/json"]["schema"]["required"] = [
        "x"
    ]
    return revision


def _contrat_avec_les_deux_ruptures() -> dict[str, Any]:
    revision = _contrat_sans_a()
    revision["paths"]["/b"] = _contrat_avec_x_requis()["paths"]["/b"]
    return revision


@pytest.fixture(scope="session")
def oasdiff() -> Path:
    chemin = os.environ.get("OASDIFF")
    if chemin:
        return Path(chemin)
    if os.environ.get("CI"):
        pytest.fail("OASDIFF doit désigner le binaire figé dans le job contrat")
    pytest.skip("OASDIFF n'est pas défini : ces tests tournent dans le job contrat de la CI")


def _git(depot: Path, *arguments: str) -> None:
    commande = ["git", "-c", "user.name=essai", "-c", "user.email=essai@example.org"]
    commande += ["-c", "commit.gpgsign=false", *arguments]
    subprocess.run(commande, cwd=depot, check=True, capture_output=True)  # noqa: S603  # arguments écrits ici


def _ecrit(chemin: Path, contenu: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


class Demande:
    """Un dépôt de test : `main` porte le contrat de base, la branche `demande` porte la révision."""

    def __init__(self, racine: Path) -> None:
        self.racine = racine
        self.depot = racine / "depot"
        self.depot.mkdir()
        self.base = racine / "openapi-main.json"
        _ecrit(self.base, json.dumps(BASE))
        _git(self.depot, "init", "--quiet", "--initial-branch", "main")
        _ecrit(self.depot / "openapi.json", json.dumps(BASE))
        self.commite("base")

    def commite(self, message: str) -> None:
        _git(self.depot, "add", "-A")
        _git(self.depot, "commit", "--quiet", "--allow-empty", "-m", message)

    def ouvre_la_demande(self, revision: dict[str, Any], fichiers: dict[str, str] | None = None) -> None:
        """Ouvre la branche `demande` ; `fichiers` : nom -> contenu, ajoutés dans docs/ruptures-admises."""
        _git(self.depot, "checkout", "--quiet", "-b", "demande")
        _ecrit(self.depot / "openapi.json", json.dumps(revision))
        for nom, contenu in (fichiers or {}).items():
            _ecrit(self.depot / outil.DOSSIER / nom, contenu)
        self.commite("demande")

    def fichier_genere(self, oasdiff: Path, revision: dict[str, Any]) -> str:
        """Le fichier que `genere` écrit pour une révision du contrat, quelle que soit la branche."""
        chemin = self.racine / "revision-genere.json"
        _ecrit(chemin, json.dumps(revision))
        return outil.genere(oasdiff=oasdiff, base=self.base, revision=chemin, raison="essai")

    def controle(self, oasdiff: Path, *, autorisees: str = "oui") -> int:
        return outil.controle(
            oasdiff=oasdiff,
            base=self.base,
            revision=self.depot / "openapi.json",
            depot=self.depot,
            reference="main",
            autorisees=autorisees,
        )


@pytest.fixture
def demande(tmp_path: Path) -> Demande:
    return Demande(tmp_path)


# --- Lecture, raison, comparaison, variable ---------------------------------------------------------------

LIGNE = "error at base.json, in API GET /a x [id]."


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("# commentaire\n\n   \n# autre\n", []),
        (f"{LIGNE}  # admis le 2026-11-13\n", [LIGNE]),
        (f"  {LIGNE}  \n", [LIGNE]),
    ],
)
def test_lignes_admises_ignore_commentaires_blancs_et_suffixe_de_l_auteur(
    texte: str, attendu: list[str]
) -> None:
    assert outil.lignes_admises(texte) == attendu


@pytest.mark.parametrize(
    "texte", ["error at base.json x\n", "# Raison :\nerror at base.json x\n", "# Raison :   \n"]
)
def test_verifie_les_fichiers_refuse_l_absence_de_raison(texte: str) -> None:
    with pytest.raises(outil.AdmissionError, match="la raison manque"):
        outil.verifie_les_fichiers({Path("docs/ruptures-admises/20261113-sujet.txt"): texte})


def test_verifie_les_fichiers_rend_les_lignes_de_tous_les_fichiers() -> None:
    fichiers = {Path("un.txt"): f"{RAISON}\nligne 1\n", Path("deux.txt"): f"{RAISON}\nligne 2\n"}
    assert outil.verifie_les_fichiers(fichiers) == ["ligne 1", "ligne 2"]


@pytest.mark.parametrize(("reelles", "admises"), [(["a", "b"], ["b", "a"]), ([], [])])
def test_compare_accepte_des_ruptures_toutes_admises(reelles: list[str], admises: list[str]) -> None:
    outil.compare(reelles, admises)


@pytest.mark.parametrize(
    ("reelles", "admises", "message", "ligne"),
    [
        (["a", "b"], ["a"], "rupture non admise", "  b"),
        (["a"], ["a", "disparue"], "acceptation périmée", "  disparue"),
        ([], ["a"], "acceptation périmée", "  a"),
    ],
)
def test_compare_refuse_une_rupture_non_listee_et_une_ligne_perimee(
    reelles: list[str], admises: list[str], message: str, ligne: str
) -> None:
    with pytest.raises(outil.AdmissionError, match=message) as erreur:
        outil.compare(reelles, admises)
    assert ligne in str(erreur.value)


@pytest.mark.parametrize("autorisees", ["non", "", "Oui", "oui ", "true", "1"])
def test_verifie_la_variable_refuse_tout_ce_qui_n_est_pas_oui(autorisees: str) -> None:
    with pytest.raises(outil.AdmissionError, match="CONTRAT_RUPTURES_ADMISES"):
        outil.verifie_la_variable(autorisees)


# --- Les fichiers ajoutés par la demande ----------------------------------------------------------------

ANCIEN = f"{outil.DOSSIER}/20261001-ancien.txt"
NOUVEAU = f"{outil.DOSSIER}/20261113-nouveau.txt"


def _ancien_sur_main(demande: Demande) -> None:
    _ecrit(demande.depot / ANCIEN, f"{RAISON}\n")
    demande.commite("ancien")


def test_fichiers_ajoutes_ne_rend_que_ceux_de_la_demande(demande: Demande) -> None:
    _ancien_sur_main(demande)
    demande.ouvre_la_demande(BASE, {"20261113-nouveau.txt": f"{RAISON}\n"})
    assert outil.fichiers_ajoutes(demande.depot, "main") == [Path(NOUVEAU)]


def test_fichiers_ajoutes_ignore_un_fichier_modifie_sur_la_branche(demande: Demande) -> None:
    _ancien_sur_main(demande)
    demande.ouvre_la_demande(BASE, {"20261001-ancien.txt": f"{RAISON}\nligne ajoutée\n"})
    assert outil.fichiers_ajoutes(demande.depot, "main") == []


def test_fichiers_ajoutes_compte_un_fichier_renomme_comme_ajoute(demande: Demande) -> None:
    _ancien_sur_main(demande)
    demande.ouvre_la_demande(BASE)
    _git(demande.depot, "mv", ANCIEN, NOUVEAU)
    demande.commite("renomme")
    assert outil.fichiers_ajoutes(demande.depot, "main") == [Path(NOUVEAU)]


def test_fichiers_ajoutes_ignore_ce_qui_n_est_pas_un_txt(demande: Demande) -> None:
    demande.ouvre_la_demande(BASE, {"LISEZMOI.md": "# mode d'emploi\n"})
    assert outil.fichiers_ajoutes(demande.depot, "main") == []


@pytest.mark.parametrize("nom", ["20261113-épices.txt", '20261113-a"q.txt'])
def test_fichiers_ajoutes_lit_les_noms_que_git_met_entre_guillemets(demande: Demande, nom: str) -> None:
    demande.ouvre_la_demande(BASE, {nom: f"{RAISON}\n"})
    assert outil.fichiers_ajoutes(demande.depot, "main") == [Path(outil.DOSSIER) / nom]


def test_fichiers_ajoutes_ignore_un_sous_dossier(demande: Demande) -> None:
    demande.ouvre_la_demande(BASE, {"sous/20261113-x.txt": f"{RAISON}\n"})
    assert outil.fichiers_ajoutes(demande.depot, "main") == []


def test_controle_refuse_un_lien_symbolique(demande: Demande, tmp_path: Path) -> None:
    demande.ouvre_la_demande(BASE, {"20261113-cible.txt": f"{RAISON}\n"})
    (demande.depot / outil.DOSSIER / "20261113-lien.txt").symlink_to("20261113-cible.txt")
    demande.commite("lien")
    with pytest.raises(outil.AdmissionError, match="lien symbolique"):
        demande.controle(tmp_path / "inutile")


def test_controle_refuse_un_fichier_illisible(demande: Demande, tmp_path: Path) -> None:
    demande.ouvre_la_demande(BASE, {"20261113-binaire.txt": ""})
    (demande.depot / outil.DOSSIER / "20261113-binaire.txt").write_bytes(b"\xff\xfe")
    demande.commite("binaire")
    with pytest.raises(outil.AdmissionError, match="illisible"):
        demande.controle(tmp_path / "inutile")


def test_fichiers_ajoutes_echoue_sur_une_reference_inconnue(demande: Demande) -> None:
    with pytest.raises(outil.GitError, match="git diff a échoué"):
        outil.fichiers_ajoutes(demande.depot, "origin/main")


# --- oasdiff : un binaire qui ne rend pas ce que le contrôle sait lire ----------------------------------


@pytest.mark.parametrize(
    ("script", "message"),
    [
        ("echo '2 changes: 2 error, 0 warning, 0 info'; echo 'error at base.json, une'", "annonce 2 erreur"),
        ("echo 'error at base.json, une'", "annonce 0 erreur"),
        ("echo 'Error: failed to load' >&2; exit 102", "code 102"),
    ],
)
def test_ruptures_reelles_refuse_ce_qu_elle_ne_sait_pas_lire(
    tmp_path: Path, script: str, message: str
) -> None:
    faux = tmp_path / "faux-oasdiff"
    faux.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    faux.chmod(faux.stat().st_mode | stat.S_IEXEC)
    _ecrit(tmp_path / "contrat.json", "{}")
    with pytest.raises(outil.OasdiffError, match=message):
        outil.ruptures_reelles(faux, tmp_path / "contrat.json", tmp_path / "contrat.json")


def test_controle_laisse_le_dernier_mot_a_oasdiff_quand_la_lecture_ne_voit_rien(
    demande: Demande, tmp_path: Path
) -> None:
    """Si oasdiff écrivait ses erreurs autrement, la lecture n'en verrait aucune ; `--fail-on ERR`, si."""
    faux = tmp_path / "faux-oasdiff"
    faux.write_text(
        '#!/bin/sh\ncase "$*" in *--fail-on*) echo "rupture inconnue"; exit 1;; esac\n', encoding="utf-8"
    )
    faux.chmod(faux.stat().st_mode | stat.S_IEXEC)
    demande.ouvre_la_demande(BASE)
    with pytest.raises(outil.OasdiffError, match="rupture inconnue"):
        demande.controle(faux)


def test_ruptures_reelles_echoue_quand_oasdiff_depasse_son_delai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(outil, "DELAI_OASDIFF_S", 0.2)
    lent = tmp_path / "lent"
    lent.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    lent.chmod(lent.stat().st_mode | stat.S_IEXEC)
    _ecrit(tmp_path / "contrat.json", "{}")
    with pytest.raises(outil.OasdiffError, match="n'a pas fini"):
        outil.ruptures_reelles(lent, tmp_path / "contrat.json", tmp_path / "contrat.json")


# --- Le contrôle de bout en bout, avec l'oasdiff figé de la CI ------------------------------------------


@pytest.mark.oasdiff
def test_genere_ecrit_des_lignes_relatives_pour_une_rupture_supprimee_et_une_ajoutee(
    demande: Demande, oasdiff: Path
) -> None:
    texte = demande.fichier_genere(oasdiff, _contrat_avec_les_deux_ruptures())
    lignes = outil.lignes_admises(texte)
    assert texte.startswith("# Raison : essai\n")
    assert sorted(ligne.split(",")[0] for ligne in lignes) == ["error at base.json", "error at revision.json"]


@pytest.mark.oasdiff
@pytest.mark.parametrize("propriete", ["p  # q", "p\rq"])
def test_genere_refuse_une_rupture_que_controle_ne_saurait_pas_relire(
    demande: Demande, oasdiff: Path, propriete: str
) -> None:
    revision = _contrat_avec_x_requis()
    corps = revision["paths"]["/b"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    corps["properties"][propriete] = {"type": "string"}
    corps["required"] = [propriete]
    with pytest.raises(outil.RuptureError):
        demande.fichier_genere(oasdiff, revision)


@pytest.mark.oasdiff
def test_genere_refuse_sans_rupture_et_sans_raison(demande: Demande, oasdiff: Path) -> None:
    with pytest.raises(outil.AdmissionError, match="aucune rupture"):
        demande.fichier_genere(oasdiff, BASE)
    _ecrit(demande.racine / "r.json", json.dumps(_contrat_sans_a()))
    with pytest.raises(outil.AdmissionError, match="--raison"):
        outil.genere(oasdiff=oasdiff, base=demande.base, revision=demande.racine / "r.json", raison="  ")


@pytest.mark.oasdiff
def test_controle_passe_avec_le_fichier_genere(demande: Demande, oasdiff: Path) -> None:
    """Rupture « supprimé » (route retirée) et « ajouté » (champ requis) : les deux passent."""
    revision = _contrat_avec_les_deux_ruptures()
    demande.ouvre_la_demande(revision, {"20261113-rompre.txt": demande.fichier_genere(oasdiff, revision)})
    assert demande.controle(oasdiff) == 2


@pytest.mark.oasdiff
def test_controle_passe_sans_rupture_ni_fichier(demande: Demande, oasdiff: Path) -> None:
    demande.ouvre_la_demande(BASE)
    assert demande.controle(oasdiff, autorisees="non") == 0


@pytest.mark.oasdiff
def test_controle_applique_deux_fichiers_ajoutes_par_la_meme_demande(demande: Demande, oasdiff: Path) -> None:
    revision = _contrat_avec_les_deux_ruptures()
    supprime, requis = outil.lignes_admises(demande.fichier_genere(oasdiff, revision))
    fichiers = {"20261113-un.txt": f"{RAISON}\n{supprime}\n", "20261113-deux.txt": f"{RAISON}\n{requis}\n"}
    demande.ouvre_la_demande(revision, fichiers)
    assert demande.controle(oasdiff) == 2


@pytest.mark.oasdiff
def test_controle_reconnait_une_ligne_suivie_d_un_commentaire_de_l_auteur(
    demande: Demande, oasdiff: Path
) -> None:
    revision = _contrat_sans_a()
    (ligne,) = outil.lignes_admises(demande.fichier_genere(oasdiff, revision))
    demande.ouvre_la_demande(revision, {"20261113-rompre.txt": f"{RAISON}\n{ligne}  # admis le 2026-11-13\n"})
    assert demande.controle(oasdiff) == 1


@pytest.mark.oasdiff
def test_controle_refuse_une_rupture_sans_fichier(demande: Demande, oasdiff: Path) -> None:
    demande.ouvre_la_demande(_contrat_sans_a())
    with pytest.raises(outil.AdmissionError, match="rupture non admise"):
        demande.controle(oasdiff)


@pytest.mark.oasdiff
def test_controle_refuse_une_rupture_que_le_fichier_ne_couvre_pas(demande: Demande, oasdiff: Path) -> None:
    fichier = demande.fichier_genere(oasdiff, _contrat_sans_a())  # ne couvre pas le champ devenu requis
    demande.ouvre_la_demande(_contrat_avec_les_deux_ruptures(), {"20261113-partiel.txt": fichier})
    with pytest.raises(outil.AdmissionError, match="rupture non admise") as erreur:
        demande.controle(oasdiff)
    assert "became required" in str(erreur.value)


@pytest.mark.oasdiff
def test_controle_refuse_une_ligne_perimee(demande: Demande, oasdiff: Path) -> None:
    fichier = demande.fichier_genere(oasdiff, _contrat_avec_les_deux_ruptures())
    demande.ouvre_la_demande(
        _contrat_avec_x_requis(), {"20261113-perime.txt": fichier}
    )  # /a n'est plus retirée
    with pytest.raises(outil.AdmissionError, match="acceptation périmée"):
        demande.controle(oasdiff)


@pytest.mark.oasdiff
def test_controle_ignore_un_fichier_deja_sur_main(demande: Demande, oasdiff: Path) -> None:
    """Le même fichier est de l'histoire : il documente, il ne s'applique plus jamais."""
    _ecrit(demande.depot / ANCIEN, demande.fichier_genere(oasdiff, _contrat_sans_a()))
    demande.commite("ancien")
    demande.ouvre_la_demande(_contrat_sans_a())
    with pytest.raises(outil.AdmissionError, match="rupture non admise"):
        demande.controle(oasdiff)


@pytest.mark.oasdiff
def test_controle_ignore_un_fichier_qui_ne_porte_que_des_commentaires(
    demande: Demande, oasdiff: Path
) -> None:
    commentaire = "# error at base.json, in API GET /a api path removed without deprecation"
    demande.ouvre_la_demande(_contrat_sans_a(), {"20261113-vide.txt": f"{RAISON}\n{commentaire}\n"})
    with pytest.raises(outil.AdmissionError, match="rupture non admise"):
        demande.controle(oasdiff)


@pytest.mark.oasdiff
def test_controle_refuse_un_fichier_quand_la_variable_ne_vaut_pas_oui(
    demande: Demande, oasdiff: Path
) -> None:
    revision = _contrat_sans_a()
    demande.ouvre_la_demande(revision, {"20261113-rompre.txt": demande.fichier_genere(oasdiff, revision)})
    with pytest.raises(outil.AdmissionError, match="CONTRAT_RUPTURES_ADMISES"):
        demande.controle(oasdiff, autorisees="non")


@pytest.mark.oasdiff
@pytest.mark.parametrize(("revision", "code"), [(BASE, 0), (_contrat_sans_a(), 1)])
def test_main_rend_le_code_du_controle_et_signale_le_refus_pour_github(
    demande: Demande, oasdiff: Path, capsys: pytest.CaptureFixture[str], revision: dict[str, Any], code: int
) -> None:
    demande.ouvre_la_demande(revision)
    arguments = [
        "controle",
        "--oasdiff",
        str(oasdiff),
        "--base",
        str(demande.base),
        "--depot",
        str(demande.depot),
    ]
    arguments += ["--revision", str(demande.depot / "openapi.json"), "--reference", "main"]
    assert outil.main(arguments) == code
    sortie = capsys.readouterr().out
    attendu = "::error::rupture non admise" if code else "Contrat : aucune rupture non admise"
    assert sortie.startswith(attendu)
