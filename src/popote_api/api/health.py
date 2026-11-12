from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from popote_api.errors import Probleme, reponses_erreur

router = APIRouter(prefix="/api", tags=["santé"])


class Etat(BaseModel):
    status: Literal["ok"]


@router.get(
    "/healthz",
    operation_id="healthz",
    summary="Le processus répond",
    response_description="Le processus répond.",
    responses=reponses_erreur(500),
)
async def healthz() -> Etat:
    return Etat(status="ok")


@router.get(
    "/readyz",
    operation_id="readyz",
    summary="Le processus et sa base répondent",
    response_description="La base répond.",
    responses=reponses_erreur(500, 503),
)
async def readyz(request: Request) -> Etat:
    if not await request.app.state.sonde.disponible():
        raise Probleme(503, "base_indisponible", "La base ne répond pas pour l'instant.")
    return Etat(status="ok")
