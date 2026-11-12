from fastapi import APIRouter, Request

from popote_api.errors import Probleme

router = APIRouter(prefix="/api", tags=["santé"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    if not await request.app.state.sonde.disponible():
        raise Probleme(503, "base_indisponible", "La base ne répond pas pour l'instant.")
    return {"status": "ok"}
