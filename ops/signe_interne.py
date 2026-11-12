#!/usr/bin/env python3
"""Signe une requête vers `/internal/*` et écrit la valeur de l'en-tête `X-Popote-Signature`.

Usage :
    POPOTE_INTERNAL_SECRET=... uv run python ops/signe_interne.py POST /internal/purges [--corps fichier]

Le secret ne se lit que dans l'environnement (jamais en argument : il finirait dans l'historique et la
liste des processus) et n'est jamais écrit. `CHEMIN` est celui des octets envoyés, sans chaîne de requête.
Sans `--corps`, le corps est vide ; avec, c'est le contenu exact du fichier, à envoyer tel quel
(`curl --data-binary @fichier`).
Codes de sortie : 0 signé, 2 erreur d'utilisation (secret absent ou trop court, fichier illisible).
"""

import argparse
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from popote_api.config import LONGUEUR_MINIMALE_DU_SECRET
from popote_api.security import signature

VARIABLE = "POPOTE_INTERNAL_SECRET"


def main(argv: Sequence[str], environ: Mapping[str, str], instant: int) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    analyseur.add_argument("methode", help="GET, POST…")
    analyseur.add_argument("chemin", help="par exemple /internal/purges")
    analyseur.add_argument("--corps", type=Path, help="fichier dont le contenu est le corps envoyé")
    arguments = analyseur.parse_args(argv)

    secret = environ.get(VARIABLE, "")
    if len(secret) < LONGUEUR_MINIMALE_DU_SECRET or not secret.isascii():
        print(
            f"{VARIABLE} absente ou invalide ({LONGUEUR_MINIMALE_DU_SECRET} caractères ASCII au moins).",
            file=sys.stderr,
        )
        return 2
    if not arguments.chemin.startswith(signature.PREFIXE_INTERNE) or "?" in arguments.chemin:
        print(
            f"Le chemin commence par {signature.PREFIXE_INTERNE} et ne porte aucune chaîne de requête.",
            file=sys.stderr,
        )
        return 2
    try:
        corps = arguments.corps.read_bytes() if arguments.corps else b""
    except OSError as erreur:
        print(f"Corps illisible : {erreur.strerror}.", file=sys.stderr)
        return 2
    valeur = signature.signe(secret.encode(), arguments.methode, arguments.chemin.encode(), corps, instant)
    print(valeur)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ, int(time.time())))
