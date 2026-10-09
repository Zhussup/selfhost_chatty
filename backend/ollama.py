"""Upstream Ollama Cloud client: streaming chat over httpx + model listing.

Handles NDJSON chunks from https://ollama.com/api/chat, normalizes tool_calls
(synthesized ids, dict-or-string arguments) and surfaces real usage counters
from the final chunk.
"""

import json
from typing import Any, AsyncIterator

import httpx

from backend.config import settings


class OllamaAuthError(Exception):
    """401/403 from upstream — key invalid or no access."""


class OllamaRateLimitError(Exception):
    """429 from upstream — capacity/concurrency."""


class OllamaUpstreamError(Exception):
    """5xx, network or malformed upstream stream."""


# Tests inject httpx.MockTransport here instead of building real clients.
INJECT_TRANSPORT: httpx.AsyncBaseTransport | None = None


def headers() -> dict[str, str]:
    if not settings.ollama_api_key:
        raise OllamaAuthError("OLLAMA_API_KEY is not set")
    return {"Authorization": f"Bearer {settings.ollama_api_key}", "Content-Type": "application/json"}


def _client_kwargs() -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if INJECT_TRANSPORT is not None:
        kw["transport"] = INJECT_TRANSPORT
    return kw


def _normalize_call(raw: dict[str, Any], index: int, iteration: int) -> dict[str, Any]:
    """Ollama may send arguments as dict or JSON string, and may omit ids entirely."""
    fn = raw.get("function") or {}
    name = fn.get("name") or raw.get("name") or f"tool_{index}"
    args = fn.get("arguments", raw.get("arguments", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"_raw": args}
    if not isinstance(args, dict):
        args = {}
    call_id = raw.get("id") or f"iter{iteration}call{index}"
    return {"id": str(call_id), "name": name, "arguments": args}


def _decode_line(line: str) -> dict[str, Any] | None:
    try:
        chunk = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(chunk, dict):
        return None
    return chunk


async def stream_chat(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Yield parsed upstream NDJSON chunks (already dict-decoded).

    Ollama may emit an {"error": "..."} object instead of a normal chunk
    (overload, closed model, ...) — surfaced as OllamaUpstreamError.
    """
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    body = dict(payload)
    body.setdefault("stream", True)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15), **_client_kwargs()) as client:
            async with client.stream("POST", url, json=body, headers=headers()) as resp:
                if resp.status_code in (401, 403):
                    await resp.aread()
                    raise OllamaAuthError(f"upstream {resp.status_code}")
                if resp.status_code == 429:
                    await resp.aread()
                    raise OllamaRateLimitError("upstream rate limited")
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "replace")[:300]
                    raise OllamaUpstreamError(f"upstream {resp.status_code}: {detail}")
                buf = ""
                async for raw in resp.aiter_text():
                    buf += raw
                    *lines, buf = buf.split("\n")
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if err := chunk.get("error"):
                            raise OllamaUpstreamError(f"upstream error: {err}")
                        yield chunk
                tail = buf.strip()
                if tail:
                    if (chunk := _decode_line(tail)) and chunk.get("error"):
                        raise OllamaUpstreamError(f"upstream error: {chunk['error']}")
    except httpx.HTTPError as exc:
        raise OllamaUpstreamError(f"network error: {exc}") from exc


async def list_models() -> list[dict[str, Any]]:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), **_client_kwargs()) as client:
        resp = await client.get(url, headers=headers())
        if resp.status_code in (401, 403):
            raise OllamaAuthError(f"upstream {resp.status_code}")
        if resp.status_code >= 400:
            raise OllamaUpstreamError(f"upstream {resp.status_code}")
        data = resp.json()
    models = data.get("models", [])
    return [
        {
            "name": m.get("name") or m.get("model") or "",
            "family": (m.get("details") or {}).get("family") or "",
            "size": m.get("size") or 0,
            "modified": m.get("modified_at") or "",
        }
        for m in models
        if m.get("name") or m.get("model")
    ]


async def model_capabilities(name: str) -> list[str]:
    """POST /api/show -> capabilities, e.g. ["completion","tools","vision"].

    This is the only place vision support is advertised: /api/tags has no
    capabilities field and its details.family is empty on ollama.com. Returns []
    on any per-model failure — one unknown model must not sink the whole list.
    """
    url = f"{settings.ollama_base_url.rstrip('/')}/api/show"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), **_client_kwargs()) as client:
            resp = await client.post(url, json={"model": name}, headers=headers())
            if resp.status_code >= 400:
                return []
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    caps = data.get("capabilities") if isinstance(data, dict) else None
    if not isinstance(caps, list):
        return []
    return [str(c) for c in caps]