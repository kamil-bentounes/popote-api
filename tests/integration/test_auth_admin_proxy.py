"""La clé secrète ne passe jamais par un mandataire de l'environnement (`trust_env=False`).

Deux faux serveurs sur la boucle locale (aucune pile Supabase requise) : un faux Auth et un faux mandataire
désigné par `HTTP_PROXY`. Seul le faux Auth doit voir la requête.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from pydantic import SecretStr

from popote_api.infra.auth_admin import AuthAdmin

CLE = "sb_secret_" + "k" * 30
IDENTIFIANT = UUID("11111111-2222-3333-4444-555555555555")
REPONSE = (
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
)


@asynccontextmanager
async def faux_serveur(vus: list[bytes]) -> AsyncIterator[int]:
    async def sert(lecteur: asyncio.StreamReader, ecrivain: asyncio.StreamWriter) -> None:
        vus.append(await lecteur.readuntil(b"\r\n\r\n"))
        ecrivain.write(REPONSE)
        await ecrivain.drain()
        ecrivain.close()

    serveur = await asyncio.start_server(sert, "127.0.0.1", 0)
    try:
        yield serveur.sockets[0].getsockname()[1]
    finally:
        serveur.close()
        await serveur.wait_closed()


@pytest.mark.integration
async def test_un_mandataire_de_l_environnement_ne_voit_pas_la_cle(monkeypatch: pytest.MonkeyPatch) -> None:
    vus_par_auth: list[bytes] = []
    vus_par_le_mandataire: list[bytes] = []
    async with faux_serveur(vus_par_auth) as port_auth, faux_serveur(vus_par_le_mandataire) as port_proxy:
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{port_proxy}")
        monkeypatch.setenv("ALL_PROXY", f"http://127.0.0.1:{port_proxy}")
        monkeypatch.setenv("NO_PROXY", "")
        admin = AuthAdmin(f"http://127.0.0.1:{port_auth}", SecretStr(CLE))

        await admin.supprime_compte(IDENTIFIANT)

    assert len(vus_par_auth) == 1 and CLE.encode() in vus_par_auth[0]
    assert vus_par_le_mandataire == []
