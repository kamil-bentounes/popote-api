"""`GET /api/v1/me` : la personne connectée, son adresse et son foyer."""

from typing import Any, Final, LiteralString

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from popote_api.conditionnel import etag_de_contenu, repond_ou_304
from popote_api.errors import reponses_erreur
from popote_api.schemas.moi import Moi
from popote_api.security.session import PersonneDeLaSession

router = APIRouter(prefix="/me", tags=["moi"])

# Sous la RLS de la personne : `user_profile` et `household` ne rendent que son foyer. L'adresse n'est pas
# dans `user_profile`, et `authenticated` ne lit pas `auth.users` : elle vient de `mon_email()` (0134).
# Sans profil, la jointure rend le foyer et le prénom absents ; la ligne existe toujours.
LIT_MOI: Final[LiteralString] = """
    select public.mon_email() as email, p.display_name, h.id as household_id, h.name as household_name
      from (select 1) as moi
      left join public.user_profile p on p.id = auth.uid()
      left join public.household h on h.id = p.household_id
"""


def _corps(personne: PersonneDeLaSession, ligne: dict[str, Any]) -> dict[str, Any]:
    foyer = {"id": ligne["household_id"], "name": ligne["household_name"]} if ligne["household_id"] else None
    moi = Moi.model_validate(
        {
            "id": personne.id,
            "email": ligne["email"],
            "display_name": ligne["display_name"],
            "household": foyer,
        }
    )
    return moi.model_dump(mode="json")


@router.get(
    "",
    operation_id="get_me",
    summary="La personne connectée",
    response_description="La personne, son adresse et son foyer.",
    response_model=Moi,
    responses={
        200: {
            "headers": {"ETag": {"description": "Empreinte du contenu (fort).", "schema": {"type": "string"}}}
        },
        304: {"description": "Non modifiée : `If-None-Match` correspond à l'`ETag` actuel."},
        **reponses_erreur(400, 412),
    },
)
async def lire_moi(request: Request, personne: PersonneDeLaSession) -> Response:
    await personne.curseur.execute(LIT_MOI)
    ligne = await personne.curseur.fetchone()
    assert ligne is not None  # noqa: S101  # `select … from (select 1)` rend toujours une ligne
    corps = _corps(personne, ligne)
    # L'`ETag` est celui des octets que `repond_ou_304` enverra : il change quand la représentation change.
    etag = etag_de_contenu(bytes(JSONResponse(corps).body))
    return repond_ou_304(request, etag, corps)
