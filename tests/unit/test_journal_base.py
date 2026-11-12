import logging

import pytest

from popote_api.infra import db


async def test_une_panne_de_base_est_journalisee_sans_le_message_de_la_bibliotheque(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="popote_api.infra.db"):
        assert await db.repond("postgresql://x:y@127.0.0.1:1/rien") is False
    enregistrements = [r for r in caplog.records if r.name == "popote_api.infra.db"]
    assert len(enregistrements) == 1
    assert enregistrements[0].levelno == logging.WARNING
    message = enregistrements[0].getMessage()
    assert "OperationalError" in message
    for secret in ("127.0.0.1", "rien", "refused", "refusée"):
        assert secret not in message
    assert enregistrements[0].exc_info is None
