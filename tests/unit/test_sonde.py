import asyncio

import httpx
import pytest
from _commun import DSN, reglages

from popote_api.infra.db import Base, SondeBase
from popote_api.main import create_app


class Horloge:
    def __init__(self) -> None:
        self.maintenant = 1000.0

    def __call__(self) -> float:
        return self.maintenant


class Compteur:
    """Une vérification factice qui compte ses appels et rend le résultat voulu."""

    def __init__(self, resultat: bool = True) -> None:
        self.appels = 0
        self.resultat = resultat

    async def __call__(self) -> bool:
        self.appels += 1
        await asyncio.sleep(0.01)
        return self.resultat


async def test_deux_appels_rapproches_n_ouvrent_qu_une_connexion() -> None:
    verifie = Compteur()
    sonde = SondeBase(verifie, horloge=Horloge())
    assert await sonde.disponible() is True
    assert await sonde.disponible() is True
    assert verifie.appels == 1


async def test_des_appels_simultanes_partagent_un_seul_appel_en_vol() -> None:
    verifie = Compteur()
    sonde = SondeBase(verifie, horloge=Horloge())
    resultats = await asyncio.gather(*[sonde.disponible() for _ in range(8)])
    assert resultats == [True] * 8
    assert verifie.appels == 1


async def test_un_echec_est_mis_en_cache_aussi() -> None:
    verifie = Compteur(resultat=False)
    sonde = SondeBase(verifie, horloge=Horloge())
    assert await sonde.disponible() is False
    assert await sonde.disponible() is False
    assert verifie.appels == 1


async def test_le_cache_expire_apres_cinq_secondes() -> None:
    verifie = Compteur()
    horloge = Horloge()
    sonde = SondeBase(verifie, horloge=horloge)
    await sonde.disponible()
    horloge.maintenant += 4.9
    await sonde.disponible()
    assert verifie.appels == 1
    horloge.maintenant += 0.2
    await sonde.disponible()
    assert verifie.appels == 2


async def test_sans_verification_la_sonde_rend_false() -> None:
    assert await SondeBase(None, horloge=Horloge()).disponible() is False


async def test_readyz_n_ouvre_qu_une_connexion_pour_deux_appels_rapproches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifie = Compteur()
    monkeypatch.setattr(Base, "repond", verifie)
    app = create_app(reglages("local", database_url=DSN))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        premier = await c.get("/api/readyz")
        second = await c.get("/api/readyz")
    assert (premier.status_code, second.status_code) == (200, 200)
    assert verifie.appels == 1
