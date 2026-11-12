"""Routes de preuve de l'étape 0.2 (relais, cookie, IP). Montées seulement sur l'essai ; retirées en 0.3."""

import secrets

from fastapi import APIRouter, Request, Response

from popote_api.relais import ip_de

router = APIRouter(prefix="/api/_preuves", tags=["preuves"])
NOM = "__Host-popote_preuve"


@router.post("/cookie")
async def pose(response: Response) -> dict[str, bool]:
    response.set_cookie(NOM, secrets.token_urlsafe(16), httponly=True, secure=True, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"pose": True}


@router.get("/cookie")
async def lit(request: Request, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return {"cookie_recu": NOM in request.cookies, "ip": ip_de(request)}
