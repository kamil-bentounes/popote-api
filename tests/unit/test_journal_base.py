import logging

import pytest

from popote_api.infra.db import Base


async def test_une_panne_de_base_est_journalisee_sans_le_message_de_la_bibliotheque(
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = Base.depuis_dsn("postgresql://x:y@127.0.0.1:1/rien", None)
    await base.ouvre()
    try:
        with caplog.at_level(logging.WARNING, logger="popote_api.infra.db"):
            assert await base.repond() is False
    finally:
        await base.ferme()
    enregistrements = [r for r in caplog.records if r.name == "popote_api.infra.db"]
    assert len(enregistrements) == 1
    assert enregistrements[0].levelno == logging.WARNING
    message = enregistrements[0].getMessage()
    assert "PoolTimeout" in message
    for secret in ("127.0.0.1", "rien", "refused", "refusée"):
        assert secret not in message
    assert enregistrements[0].exc_info is None
    # Le pool journalise lui aussi, avec l'hôte et le port de la base : seul le début du message passe.
    assert "127.0.0.1" not in caplog.text
    assert "refused" not in caplog.text
    assert "error connecting" in caplog.text
