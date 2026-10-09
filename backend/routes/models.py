"""Model list proxy (upstream /api/tags) with a small TTL cache, enriched with the
capabilities from /api/show (which models can read images, use tools, think)."""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend import auth as auth_mod
from backend import ollama, vision
from backend.ollama import OllamaAuthError, OllamaUpstreamError

router = APIRouter(prefix="/models", dependencies=[Depends(auth_mod.require_user)])

_cache: list[dict[str, Any]] = []
_cache_at: float = 0.0
_TTL = 300.0


async def _enrich(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach `vision` / `capabilities` to every model, probing /api/show only for
    the ones the cache does not already know. A failed probe degrades that one
    entry (vision: false) and never fails the list."""
    names = [m["name"] for m in tags if m.get("name")]
    missing = [n for n in names if not vision.is_fresh(n)]
    if missing:
        results = await asyncio.gather(*(ollama.model_capabilities(n) for n in missing))
        for name, caps in zip(missing, results, strict=True):
            vision.prime(name, caps, ttl=None if caps else vision.NEGATIVE_TTL)
    vision.retain(set(names))

    out: list[dict[str, Any]] = []
    for m in tags:
        caps = vision.cached(m["name"]) or frozenset()
        out.append({**m, "vision": "vision" in caps, "capabilities": sorted(caps)})
    return out


@router.get("")
async def models() -> Any:
    global _cache, _cache_at
    if _cache and (time.time() - _cache_at) < _TTL:
        return {"models": _cache, "cached": True}
    try:
        tags = await ollama.list_models()
    except OllamaAuthError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    except OllamaUpstreamError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    _cache = await _enrich(tags)
    _cache_at = time.time()
    return {"models": _cache, "cached": False}
