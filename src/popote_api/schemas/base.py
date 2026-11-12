"""Les deux bases de tout modèle de l'API (spec § 3.10).

Une entrée refuse les champs inconnus : un client ne pose pas un champ que le serveur possède (`household_id`,
`created_at`, un rôle...) en l'ajoutant au corps, et une faute de frappe se voit au lieu d'être ignorée. Une
sortie ne liste que ce qu'on veut montrer ; elle ne s'écrit jamais d'après une ligne de base entière.
`tests/unit/test_modeles.py` garde que tout modèle de `schemas/` hérite de l'une ou de l'autre, et que tout
corps de requête hérite d'`Entree`.
"""

from pydantic import BaseModel, ConfigDict


class Entree(BaseModel):
    """Un corps de requête : tout champ inconnu est un `422`."""

    model_config = ConfigDict(extra="forbid")


class Sortie(BaseModel):
    """Un corps de réponse."""
