"""Les adresses de base des tests d'intégration.

Par défaut les tests visent la base locale. Pour les rejouer contre un autre serveur (le pooler Supavisor de
l'essai), poser `POPOTE_TEST_DSN_API` et `POPOTE_TEST_DSN_INTERNAL` : les mots de passe locaux ne sont alors
pas touchés (voir la fixture `mots_de_passe_locaux` de `conftest.py`).
"""

import os

import psycopg

ADMIN_LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
MOT_DE_PASSE_LOCAL = "essai-local"

# Lues à l'import : la fixture autouse de tests/conftest.py retire ensuite tout POPOTE_* de l'environnement.
DSN_API_DISTANT = os.environ.get("POPOTE_TEST_DSN_API")
DSN_INTERNAL_DISTANT = os.environ.get("POPOTE_TEST_DSN_INTERNAL")
# La préparation des données (foyers, personnes) : `POPOTE_TEST_DSN_ADMIN` la dirige vers un autre serveur.
DSN_ADMIN = os.environ.get("POPOTE_TEST_DSN_ADMIN") or ADMIN_LOCAL


def dsn_local(role: str) -> str:
    return f"postgresql://{role}:{MOT_DE_PASSE_LOCAL}@127.0.0.1:54322/postgres"


DSN_API = DSN_API_DISTANT or dsn_local("popote_api")
DSN_INTERNAL = DSN_INTERNAL_DISTANT or dsn_local("popote_internal")


def connecte(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    # Pas d'instruction préparée : le pooler (mode transaction) change de serveur d'une transaction à l'autre.
    return psycopg.connect(dsn, prepare_threshold=None, connect_timeout=15)
