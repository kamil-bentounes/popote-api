"""Écrit `openapi.json` à la racine du dépôt. Commande : `uv run python scripts/exporte_contrat.py`."""

from pathlib import Path

from popote_api.contrat import contrat_publie

CHEMIN = Path(__file__).resolve().parent.parent / "openapi.json"

if __name__ == "__main__":
    CHEMIN.write_text(contrat_publie(), encoding="utf-8")
    print(f"{CHEMIN.name} écrit.")
