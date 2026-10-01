"""Auth: password from env -> signed HttpOnly cookie (itsdangerous) -> require_user dependency."""

import asyncio

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.config import settings

COOKIE_NAME = "shc_auth"
MAX_AGE = 7 * 24 * 3600  # 7 days

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="auth")


def issue_token() -> str:
    return _serializer.dumps("me")


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=settings.cookie_secure,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def require_user(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="not logged in")
    try:
        _serializer.loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="session expired")


def check_password(password: str) -> bool:
    import hmac

    return hmac.compare_digest(password, settings.auth_password)


async def fail_login_delay() -> None:
    await asyncio.sleep(0.7)