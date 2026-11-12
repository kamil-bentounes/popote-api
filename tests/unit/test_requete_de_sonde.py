"""La sonde lit une vraie table, sous le rôle `authenticated`, sans rien en rendre ni en journaliser."""

import logging
from types import TracebackType
from typing import Any, Self

import psycopg
import pytest

from popote_api.infra import db
from popote_api.infra.db import Base


class CurseurFactice:
    def __init__(self, connexion: "ConnexionFactice") -> None:
        self._connexion = connexion

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, requete: str, _parametres: object = None) -> None:
        self._connexion.evenements.append(requete)
        if self._connexion.erreur is not None and not requete.startswith("set local"):
            raise self._connexion.erreur

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._connexion.lignes[0] if self._connexion.lignes else None


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
        self.lignes = lignes
        self.erreur = erreur

    def transaction(self) -> TransactionFactice:
        return TransactionFactice(self)

    def cursor(self, **_: object) -> CurseurFactice:
        return CurseurFactice(self)


class PoolFactice:
    def __init__(self, connexion: ConnexionFactice) -> None:
        self._connexion = connexion

    def connection(self) -> "PoolFactice":
        return self

    async def __aenter__(self) -> ConnexionFactice:
        return self._connexion

    async def __aexit__(self, *_: object) -> None:
        return None


def base_avec(connexion: ConnexionFactice) -> Base:
    pool: Any = PoolFactice(connexion)
    return Base(pool, None)


async def test_la_sonde_lit_une_vraie_table_sous_authenticated_dans_une_transaction() -> None:
    connexion = ConnexionFactice([(1,)])
    assert await base_avec(connexion).repond() is True
    assert connexion.evenements == ["debut", db.PREAMBULE_PERSONNE, db.REQUETE_DE_SONDE, "fin"]
    assert db.PREAMBULE_PERSONNE.startswith("set local role authenticated")
    assert "from public.instance_setting" in db.REQUETE_DE_SONDE


async def test_une_table_vide_rend_false_et_le_dit_au_journal(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="popote_api.infra.db"):
        assert await base_avec(ConnexionFactice([])).repond() is False
    assert "aucune ligne" in caplog.text


async def test_un_refus_de_droit_rend_false_sans_le_message_de_la_base(
    caplog: pytest.LogCaptureFixture,
) -> None:
    refus = psycopg.errors.InsufficientPrivilege('permission denied for table "instance_setting"')
    with caplog.at_level(logging.WARNING, logger="popote_api.infra.db"):
        assert await base_avec(ConnexionFactice([(1,)], erreur=refus)).repond() is False
    assert "InsufficientPrivilege" in caplog.text
    assert "instance_setting" not in caplog.text
