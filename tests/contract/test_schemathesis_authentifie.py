"""Le contrat de `GET /api/v1/me` éprouvé avec une session : ses réponses 200 et 304, sur la base locale.

`test_schemathesis.py` n'atteint que le `401` de `/me` (pas de cookie, pas de base). Ici la fabrique pose une
vraie session ; la requête passe par httpx, dans la boucle du test (le pool de la base y reste),
et Schemathesis valide la réponse contre le contrat : statut documenté, type de contenu, schéma, en-têtes.
"""

import pytest
import schemathesis
from _client import application_de_test, client_de, cookie
from _fixtures import base, fabrique, mots_de_passe_locaux, pools  # noqa: F401  # fixtures du module partagé
from schemathesis import checks

from popote_api.infra.db import Base

pytestmark = pytest.mark.integration

CONTROLES = [
    checks.not_a_server_error,
    checks.response_schema_conformance,
    checks.content_type_conformance,
    checks.status_code_conformance,
    checks.response_headers_conformance,
]


async def test_me_avec_une_session_respecte_son_contrat_en_200_puis_en_304(
    base: Base,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    fabrique,  # type: ignore[no-untyped-def]  # noqa: F811
) -> None:
    app = application_de_test(base, monkeypatch)
    operation = schemathesis.openapi.from_asgi("/api/openapi.json", app)["/api/v1/me"]["GET"]
    entetes = cookie(fabrique.session(fabrique.personne(fabrique.foyer()).id))
    async with client_de(app) as client:
        lecture = await client.get("/api/v1/me", headers=entetes)
        relecture = await client.get(
            "/api/v1/me", headers=entetes | {"If-None-Match": lecture.headers["etag"]}
        )
    assert (lecture.status_code, relecture.status_code) == (200, 304)
    for reponse in (lecture, relecture):
        operation.Case().validate_response(reponse, checks=CONTROLES)
