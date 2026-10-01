"""Model list proxy (upstream /api/tags) with a small TTL cache."""

import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend import auth as auth_mod
from backend import ollama
from backend.ollama import OllamaAuthError, OllamaUpstreamError

router = APIRouter(prefix="/models", dependencies=[Depends(auth_mod.require_user)])

_cache: list[dict[str, Any]] = []
_cache_at: float = 0.0
_TTL = 300.0


@router.get("")
async def models() -> Any:
    global _cache, _cache_at
    if _cache and (time.time() - _cache_at) < _TTL:
        return {"models": _cache, "cached": True}
    try:
        data = await ollama.list_models()
    except OllamaAuthError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    except OllamaUpstreamError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    _cache = data
    _cache_at = time.time()
    return {"models": data, "cached": False}