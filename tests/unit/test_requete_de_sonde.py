"""La sonde lit une vraie table, sous le rôle `authenticated`, sans rien en rendre ni en journaliser."""

import logging
from types import TracebackType
from typing import Self

import psycopg
import pytest

from popote_api.infra import db

DSN = "postgresql://x:y@127.0.0.1:1/rien"


class CurseurFactice:
    def __init__(self, lignes: list[tuple[object, ...]]) -> None:
        self._lignes = lignes

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._lignes[0] if self._lignes else None


class TransactionFactice:
    def __init__(self, connexion: "ConnexionFactice") -> None:
        self._connexion = connexion

    async def __aenter__(self) -> Self:
        self._connexion.evenements.append("debut")
        return self

    async def __aexit__(
        self, type_: type[BaseException] | None, valeur: BaseException | None, pile: TracebackType | None
    ) -> None:
        self._connexion.evenements.append("fin")


class ConnexionFactice:
    """Note les instructions dans l'ordre ; la lecture rend `lignes`, ou lève `erreur`."""

    def __init__(self, lignes: list[tuple[object, ...]], erreur: Exception | None = None) -> None:
        self.evenements: list[str] = []
        self._lignes = lignes
        self._erreur = erreur

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, type_: type[BaseException] | None, valeur: BaseException | None, pile: TracebackType | None
    ) -> None:
        return None

    def transaction(self) -> TransactionFactice:
        return TransactionFactice(self)

    async def execute(self, requete: str) -> CurseurFactice:
        self.evenements.append(requete)
        if self._erreur is not None and not requete.startswith("set local"):
            raise self._erreur
        return CurseurFactice(self._lignes)


def branche(monkeypatch: pytest.MonkeyPatch, connexion: ConnexionFactice) -> None:
    async def connecte(*_args: object, **_kwargs: object) -> ConnexionFactice:
        return connexion

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connecte)


async def test_la_sonde_lit_une_vraie_table_sous_authenticated_dans_une_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connexion = ConnexionFactice([(1,)])
    branche(monkeypatch, connexion)
    assert await db.repond(DSN) is True
    assert connexion.evenements == [
        "debut",
        "set local role authenticated",
        db.REQUETE_DE_SONDE,
        "fin",
    ]
    assert "from public.instance_setting" in db.REQUETE_DE_SONDE


async def test_une_table_vide_rend_false_et_le_dit_au_journal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    branche(monkeypatch, ConnexionFactice([]))
    with caplog.at_level(logging.WARNING, logger="popote_api.infra.db"):
        assert await db.repond(DSN) is False
    assert "aucune ligne" in caplog.text


async def test_un_refus_de_droit_rend_false_sans_le_message_de_la_base(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    refus = psycopg.errors.InsufficientPrivilege('permission denied for table "instance_setting"')
    branche(monkeypatch, ConnexionFactice([(1,)], erreur=refus))
    with caplog.at_level(logging.WARNING, logger="popote_api.infra.db"):
        assert await db.repond(DSN) is False
    assert "InsufficientPrivilege" in caplog.text
    assert "instance_setting" not in caplog.text
