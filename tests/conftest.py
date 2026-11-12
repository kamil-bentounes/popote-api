import os

import pytest


@pytest.fixture(autouse=True)
def _environnement_propre(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucune variable POPOTE_* du poste ne doit influencer un test."""
    for nom in [n for n in os.environ if n.startswith("POPOTE_")]:
        monkeypatch.delenv(nom)
