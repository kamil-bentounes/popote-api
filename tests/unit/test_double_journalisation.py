import logging
from collections.abc import Iterator

import httpx
import pytest
from _commun import reglages

from popote_api.errors import DEJA_JOURNALISEE, DoubleJournalisation
from popote_api.main import create_app

MESSAGE_UVICORN = "Exception in ASGI application\n"


def enregistrement(exc: BaseException | None, message: str = MESSAGE_UVICORN) -> logging.LogRecord:
    infos = (type(exc), exc, exc.__traceback__) if exc else None
    return logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, message, None, infos)


def test_le_filtre_ecarte_l_enregistrement_d_uvicorn_d_une_exception_deja_journalisee() -> None:
    exc = RuntimeError("x")
    setattr(exc, DEJA_JOURNALISEE, True)
    assert DoubleJournalisation().filter(enregistrement(exc)) is False


def test_le_filtre_garde_l_enregistrement_d_une_exception_non_journalisee() -> None:
    assert DoubleJournalisation().filter(enregistrement(RuntimeError("x"))) is True


def test_le_filtre_garde_les_autres_messages_meme_pour_une_exception_journalisee() -> None:
    exc = RuntimeError("x")
    setattr(exc, DEJA_JOURNALISEE, True)
    assert DoubleJournalisation().filter(enregistrement(exc, "Autre chose")) is True


def test_le_filtre_garde_un_enregistrement_sans_exception() -> None:
    assert DoubleJournalisation().filter(enregistrement(None)) is True


@pytest.fixture
def logger_uvicorn() -> Iterator[logging.Logger]:
    journal = logging.getLogger("uvicorn.error")
    avant = list(journal.filters)
    yield journal
    journal.filters[:] = avant


def test_create_app_pose_le_filtre_une_seule_fois(logger_uvicorn: logging.Logger) -> None:
    create_app(reglages("local"))
    create_app(reglages("local"))
    assert sum(isinstance(f, DoubleJournalisation) for f in logger_uvicorn.filters) == 1


async def test_une_500_n_est_journalisee_qu_une_fois_sous_uvicorn(
    logger_uvicorn: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(reglages("local"))

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("interne")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            await c.get("/api/_test/boom")
        # après notre réponse, uvicorn journalise l'exception que notre gestionnaire a déjà marquée
        marquee = [r.exc_info[1] for r in caplog.records if r.name == "popote_api.errors" and r.exc_info]
        logger_uvicorn.error(MESSAGE_UVICORN, exc_info=marquee[0])
    uvicorn = [r for r in caplog.records if r.name == "uvicorn.error"]
    assert uvicorn == []
