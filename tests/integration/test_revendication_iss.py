"""Spec § 5.1 : le contexte personne pose les revendications que le SQL lit, comme PostgREST les poserait.

Le cas qui le prouve : `tg_recipe_photo` lit `iss` pour savoir de quel projet vient l'adresse d'une photo.
"""

import psycopg
import pytest
from _fabrique import Fabrique

from popote_api.infra.db import Base, Pool

pytestmark = pytest.mark.integration

EMETTEUR = "http://127.0.0.1:54321/auth/v1"


def adresse_de_photo(foyer: object) -> str:
    return f"http://127.0.0.1:54321/storage/v1/object/public/photos-des-plats/{foyer}/plat.jpg"


async def pose_la_photo(base: Base, personne_id: object, recette: object, foyer: object) -> int:
    async with base.personne(personne_id) as curseur:  # type: ignore[arg-type]
        await curseur.execute(
            "update public.recipe set image_url = %s where id = %s", (adresse_de_photo(foyer), recette)
        )
        return curseur.rowcount


async def test_avec_iss_la_personne_pose_la_photo_de_sa_recette(
    pools: tuple[Pool, Pool], fabrique: Fabrique
) -> None:
    foyer = fabrique.foyer()
    personne = fabrique.personne(foyer)
    recette = fabrique.recette(foyer)
    base = Base(*pools, emetteur=EMETTEUR)
    assert await pose_la_photo(base, personne.id, recette, foyer) == 1


async def test_sans_iss_le_declencheur_refuse_la_photo(pools: tuple[Pool, Pool], fabrique: Fabrique) -> None:
    foyer = fabrique.foyer()
    personne = fabrique.personne(foyer)
    recette = fabrique.recette(foyer)
    with pytest.raises(psycopg.errors.CheckViolation):
        await pose_la_photo(Base(*pools), personne.id, recette, foyer)


async def test_un_iss_etranger_ne_valide_pas_l_adresse(pools: tuple[Pool, Pool], fabrique: Fabrique) -> None:
    foyer = fabrique.foyer()
    personne = fabrique.personne(foyer)
    recette = fabrique.recette(foyer)
    base = Base(*pools, emetteur="https://autre-projet.supabase.co/auth/v1")
    with pytest.raises(psycopg.errors.CheckViolation):
        await pose_la_photo(base, personne.id, recette, foyer)
