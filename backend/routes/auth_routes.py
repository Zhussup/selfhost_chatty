"""Login / logout / me."""

from fastapi import APIRouter, HTTPException, Request, Response

from backend import auth
from backend.schemas import LoginIn

router = APIRouter(prefix="/api/auth")


@router.post("/login")
async def login(body: LoginIn, response: Response) -> dict:
    if not auth.check_password(body.password):
        await auth.fail_login_delay()
        raise HTTPException(status_code=401, detail="wrong password")
    auth.set_auth_cookie(response, auth.issue_token())
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    auth.clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request) -> dict:
    try:
        auth.require_user(request)
    except Exception:
        raise HTTPException(status_code=401, detail="not logged in")
    return {"ok": True}