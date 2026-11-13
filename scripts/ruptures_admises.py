"""Le contrôle de rupture du contrat OpenAPI, avec les ruptures admises une fois par demande de fusion.

`oasdiff breaking --fail-on ERR` reste la garde. Une demande de fusion qui rompt le contrat ajoute un
fichier `docs/ruptures-admises/<AAAAMMJJ>-<sujet>.txt` dont les lignes sont celles de `genere` ; seuls les
fichiers AJOUTÉS par la demande s'appliquent (après la fusion, le fichier est de l'histoire).
Mode d'emploi : docs/ruptures-admises/LISEZMOI.md.

    uv run python scripts/ruptures_admises.py genere --oasdiff <oasdiff> --base <openapi de main> \\
        --revision openapi.json --raison "<pourquoi>"
    uv run python scripts/ruptures_admises.py controle --oasdiff <oasdiff> --base <openapi de main> \\
        --revision openapi.json --autorisees "$CONTRAT_RUPTURES_ADMISES"
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

DOSSIER = "docs/ruptures-admises"
PREFIXE_RAISON = "# Raison :"
# Ce qui suit ce marqueur sur une ligne est un commentaire de l'auteur (une date, un renvoi) ; oasdiff
# n'écrit jamais deux espaces avant un dièse.
MARQUEUR_DE_COMMENTAIRE = "  # "
PREFIXE_RUPTURE = "error at "
RESUME_OASDIFF = re.compile(r"^\d+ changes?: (\d+) errors?,", re.MULTILINE)
# Noms relatifs et constants : `oasdiff` met le nom du fichier dans la ligne, et prend pour chemin de la
# rupture le premier mot qui commence par « / » : un chemin absolu fausserait la correspondance.
NOM_BASE = "base.json"
NOM_REVISION = "revision.json"
DELAI_OASDIFF_S = 60
DELAI_GIT_S = 30


class RuptureError(Exception):
    """Base des refus du contrôle : l'intégration continue échoue avec le message."""


class OasdiffError(RuptureError):
    """`oasdiff` n'a pas rendu ce que le contrôle sait lire."""


class AdmissionError(RuptureError):
    """Un fichier de ruptures admises est refusé, ou ne couvre pas exactement les ruptures réelles."""


class GitError(RuptureError):
    """La liste des fichiers ajoutés par la demande de fusion n'a pas pu être lue."""


def _lance_oasdiff(
    oasdiff: Path, base: Path, revision: Path, *options: str
) -> subprocess.CompletedProcess[str]:
    """Lance `oasdiff breaking` dans un dossier temporaire, avec deux noms relatifs constants."""
    with tempfile.TemporaryDirectory() as dossier:
        travail = Path(dossier)
        shutil.copyfile(base, travail / NOM_BASE)
        shutil.copyfile(revision, travail / NOM_REVISION)
        arguments = [str(oasdiff.resolve()), "breaking", NOM_BASE, NOM_REVISION, *options]
        try:
            return subprocess.run(  # noqa: S603  # binaire figé et vérifié par la CI, aucun argument d'utilisateur
                arguments, cwd=travail, capture_output=True, text=True, timeout=DELAI_OASDIFF_S, check=False
            )
        except subprocess.TimeoutExpired as erreur:
            raise OasdiffError(f"oasdiff n'a pas fini en {DELAI_OASDIFF_S} s") from erreur


def _options_communes() -> tuple[str, ...]:
    return ("--deprecation-days-stable", "30", "--format", "singleline")


def ruptures_reelles(oasdiff: Path, base: Path, revision: Path) -> list[str]:
    """Les lignes `oasdiff` de niveau ERR entre `base` et `revision`, sans espace final."""
    resultat = _lance_oasdiff(oasdiff, base, revision, *_options_communes())
    if resultat.returncode != 0:
        raise OasdiffError(f"oasdiff a échoué (code {resultat.returncode}) : {resultat.stderr.strip()[:300]}")
    lignes = [ligne.strip() for ligne in resultat.stdout.splitlines() if ligne.startswith(PREFIXE_RUPTURE)]
    resume = RESUME_OASDIFF.search(resultat.stdout)
    annonces = int(resume.group(1)) if resume else 0
    # Une ligne que le contrôle ne saurait pas lire serait une rupture acceptée en silence.
    if annonces != len(lignes):
        raise OasdiffError(f"oasdiff annonce {annonces} erreur(s) mais {len(lignes)} ligne(s) sont lisibles")
    return lignes


def lignes_admises(texte: str) -> list[str]:
    """Les lignes d'un fichier de ruptures admises : sans blancs, sans commentaires ni lignes vides."""
    lignes = []
    for brute in texte.splitlines():
        ligne = brute.split(MARQUEUR_DE_COMMENTAIRE, 1)[0].strip()
        if ligne and not ligne.startswith("#"):
            lignes.append(ligne)
    return lignes


def _raison(texte: str) -> str:
    return next(
        (
            ligne[len(PREFIXE_RAISON) :].strip()
            for ligne in texte.splitlines()
            if ligne.startswith(PREFIXE_RAISON)
        ),
        "",
    )


def verifie_les_fichiers(fichiers: dict[Path, str]) -> list[str]:
    """Refuse un fichier sans raison ; rend les lignes admises de tous les fichiers."""
    admises: list[str] = []
    for chemin, texte in fichiers.items():
        if not _raison(texte):
            raise AdmissionError(
                f"{chemin} : la raison manque (ligne « {PREFIXE_RAISON} <pourquoi> » en tête)"
            )
        admises.extend(lignes_admises(texte))
    return admises


def compare(reelles: Sequence[str], admises: Sequence[str]) -> None:
    """Chaque rupture réelle est admise, et chaque ligne admise correspond à une rupture réelle."""
    non_listees = [ligne for ligne in reelles if ligne not in admises]
    if non_listees:
        raise AdmissionError(
            "rupture non admise (la demande qui rompt ajoute un fichier, voir `genere`) :\n"
            + "\n".join(f"  {ligne}" for ligne in non_listees)
        )
    perimees = [ligne for ligne in admises if ligne not in reelles]
    if perimees:
        raise AdmissionError(
            "ligne admise qui ne correspond à aucune rupture (acceptation périmée) :\n"
            + "\n".join(f"  {ligne}" for ligne in perimees)
        )


def verifie_la_variable(autorisees: str) -> None:
    """Hors de la bascule, une rupture exige `/v2` ou `Deprecation` et `Sunset` : plus de fichier admis."""
    if autorisees != "oui":
        raise AdmissionError(
            "des ruptures admises sont ajoutées mais CONTRAT_RUPTURES_ADMISES ne vaut pas « oui » : "
            "une rupture ouvre /v2 (docs/normes-api.md § 3.9)"
        )


def fichiers_ajoutes(depot: Path, reference: str) -> list[Path]:
    """Les fichiers de ruptures admises AJOUTÉS depuis `reference` (diff à trois points : ceux de la demande).

    `--no-renames` : un fichier renommé compte comme ajouté, jamais comme déjà connu.
    """
    commande = ["git", "diff", "-z", "--no-renames", "--diff-filter=A", "--name-only"]
    commande += [f"{reference}...HEAD", "--", f"{DOSSIER}/*.txt"]
    try:
        resultat = subprocess.run(  # noqa: S603  # commande fixe ; `reference` est une branche du dépôt
            commande, cwd=depot, capture_output=True, text=True, timeout=DELAI_GIT_S, check=False
        )
    except subprocess.TimeoutExpired as erreur:
        raise GitError(f"git n'a pas fini en {DELAI_GIT_S} s") from erreur
    if resultat.returncode != 0:
        raise GitError(f"git diff a échoué : {resultat.stderr.strip()[:300]}")
    # `-z` : git ne met pas un nom accentué entre guillemets ; `*` traverse les `/`, d'où le filtre.
    chemins = [Path(nom) for nom in resultat.stdout.split("\0") if nom]
    return [chemin for chemin in chemins if chemin.parent == Path(DOSSIER)]


def refuse_les_ruptures(oasdiff: Path, base: Path, revision: Path, admises: Sequence[str]) -> None:
    """La garde d'origine : `oasdiff breaking --fail-on ERR`, sauf pour les lignes admises."""
    options = [*_options_communes(), "--fail-on", "ERR"]
    with tempfile.TemporaryDirectory() as dossier:
        if admises:
            exceptions = Path(dossier) / "admises.txt"
            exceptions.write_text("\n".join(admises) + "\n", encoding="utf-8")
            options += ["--err-ignore", str(exceptions)]
        resultat = _lance_oasdiff(oasdiff, base, revision, *options)
    if resultat.returncode != 0:
        raise OasdiffError(
            f"oasdiff refuse le contrat (code {resultat.returncode}) :\n{resultat.stdout.strip()}"
        )


def _lit(chemin: Path) -> str:
    """Le texte d'un fichier de ruptures admises ; un lien symbolique n'est pas « ajouté par la demande »."""
    if chemin.is_symlink():
        raise AdmissionError(f"{chemin} : un lien symbolique n'est pas admis")
    try:
        return chemin.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as erreur:
        raise AdmissionError(f"{chemin} : illisible ({erreur.__class__.__name__})") from erreur


def controle(
    *, oasdiff: Path, base: Path, revision: Path, depot: Path, reference: str, autorisees: str
) -> int:
    """Le contrôle de la CI ; rend le nombre de ruptures admises (0 : le contrat ne rompt pas)."""
    ajoutes = fichiers_ajoutes(depot, reference)
    if ajoutes:
        verifie_la_variable(autorisees)
    admises = verifie_les_fichiers({chemin: _lit(depot / chemin) for chemin in ajoutes})
    reelles = ruptures_reelles(oasdiff, base, revision)
    compare(reelles, admises)
    refuse_les_ruptures(oasdiff, base, revision, reelles)
    return len(reelles)


def genere(*, oasdiff: Path, base: Path, revision: Path, raison: str) -> str:
    """Le texte d'un fichier de ruptures admises pour les ruptures actuelles."""
    if not raison.strip():
        raise AdmissionError("--raison est obligatoire")
    reelles = ruptures_reelles(oasdiff, base, revision)
    if not reelles:
        raise AdmissionError("aucune rupture : rien à admettre")
    texte = "\n".join([f"{PREFIXE_RAISON} {raison.strip()}", *reelles]) + "\n"
    # Le fichier doit passer le contrôle tel quel : un nom exotique (`  # `, `\r`) casserait sa relecture.
    admises = lignes_admises(texte)
    compare(reelles, admises)
    refuse_les_ruptures(oasdiff, base, revision, admises)
    return texte


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sous_commandes = analyseur.add_subparsers(dest="commande", required=True)
    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--oasdiff", type=Path, required=True)
    commun.add_argument("--base", type=Path, required=True, help="l'openapi.json de main")
    commun.add_argument("--revision", type=Path, default=Path("openapi.json"))
    generation = sous_commandes.add_parser("genere", parents=[commun], help="écrit les lignes à admettre")
    generation.add_argument("--raison", required=True)
    verification = sous_commandes.add_parser("controle", parents=[commun], help="le contrôle de la CI")
    verification.add_argument("--depot", type=Path, default=Path("."))
    verification.add_argument("--reference", default="origin/main")
    verification.add_argument("--autorisees", default="", help="valeur de CONTRAT_RUPTURES_ADMISES")
    return analyseur.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        if arguments.commande == "genere":
            sys.stdout.write(
                genere(
                    oasdiff=arguments.oasdiff,
                    base=arguments.base,
                    revision=arguments.revision,
                    raison=arguments.raison,
                )
            )
        else:
            admises = controle(
                oasdiff=arguments.oasdiff,
                base=arguments.base,
                revision=arguments.revision,
                depot=arguments.depot,
                reference=arguments.reference,
                autorisees=arguments.autorisees,
            )
            print(f"Contrat : aucune rupture non admise ({admises} admise(s) par cette demande).")
    except RuptureError as erreur:
        # Le message tient sur une ligne pour GitHub ; le détail suit dans le journal.
        premiere, _, suite = str(erreur).partition("\n")
        print(f"::error::{premiere}")
        if suite:
            print(suite)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
