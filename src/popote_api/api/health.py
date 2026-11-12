from fastapi import APIRouter, Request

from popote_api.errors import Probleme
from popote_api.infra import db

router = APIRouter(prefix="/api", tags=["santé"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    url = request.app.state.settings.database_url
    if url is None or not await db.repond(url.get_secret_value()):
        raise Probleme(503, "base_indisponible", "La base ne répond pas pour l'instant.")
    return {"status": "ok"}
