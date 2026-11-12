"""Schemathesis éprouve l'API en mémoire contre son propre contrat (spec § 9.2).

Les quatre contrôles : pas de 5xx non documenté, réponse conforme au schéma, type de contenu conforme,
statut documenté. La sonde de la base est factice (`SondeBase(verifie)`) : `/api/readyz` rend ainsi
ses deux réponses documentées, 200 et 503, sans base ; la vraie base est éprouvée par
`tests/integration/test_readyz.py`.
"""

from collections.abc import Awaitable, Callable

import pytest
import schemathesis
from schemathesis import checks
from schemathesis.config import SchemathesisConfig
from schemathesis.pytest.lazy import LazySchema
from schemathesis.specs.openapi.schemas import OpenApiSchema

from popote_api.config import Settings
from popote_api.infra.db import SondeBase
from popote_api.main import create_app

CONTROLES = [
    checks.not_a_server_error,
    checks.response_schema_conformance,
    checks.content_type_conformance,
    checks.status_code_conformance,
]
# `readyz` documente son 503 : c'est sa réponse voulue quand la base ne répond pas, pas une panne.
CONFIGURATION = SchemathesisConfig.from_dict(
    {
        "operations": [
            {
                "include-path": "/api/readyz",
                "checks": {"not_a_server_error": {"expected-statuses": ["2xx", "3xx", "4xx", "503"]}},
            }
        ],
        "generation": {"database": "none"},  # pas de dossier .hypothesis écrit dans le dépôt
    }
)


def _schema(verifie: Callable[[], Awaitable[bool]]) -> OpenApiSchema:
    app = create_app(Settings.model_validate({"env": "local"}))
    app.state.sonde = SondeBase(verifie)
    return schemathesis.openapi.from_asgi("/api/openapi.json", app, config=CONFIGURATION)


async def _repond() -> bool:
    return True


async def _ne_repond_pas() -> bool:
    return False


@pytest.fixture
def schema_base_vivante() -> OpenApiSchema:
    return _schema(_repond)


@pytest.fixture
def schema_base_muette() -> OpenApiSchema:
    return _schema(_ne_repond_pas)


vivante: LazySchema = schemathesis.pytest.from_fixture("schema_base_vivante")
muette: LazySchema = schemathesis.pytest.from_fixture("schema_base_muette")


@vivante.parametrize()
def test_l_api_respecte_son_contrat_quand_la_base_repond(case: schemathesis.Case) -> None:
    case.call_and_validate(checks=CONTROLES)


@muette.parametrize()
def test_l_api_respecte_son_contrat_quand_la_base_ne_repond_pas(case: schemathesis.Case) -> None:
    case.call_and_validate(checks=CONTROLES)
