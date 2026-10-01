"""Tool registry: JSON-schema specs for Ollama tool calling + async dispatch."""

import asyncio
import json
import time
from typing import Any, Awaitable, Callable

from backend.config import settings


def _make_blocking(fn: Callable[..., Any]) -> Callable[..., Awaitable[str]]:
    """Wrap a blocking (network/subprocess) callable to run in a thread."""

    async def call(**kwargs: Any) -> str:
        return await asyncio.to_thread(fn, **kwargs)

    return call


def tool_impls() -> dict[str, Callable[..., Awaitable[str]]]:
    from backend.tools import memory, pyexec, web_search

    return {
        "web_search": _make_blocking(web_search.web_search),
        "fetch_page": _make_blocking(web_search.fetch_page),
        "calc": _make_blocking(pyexec.calc),
        "python": _make_blocking(pyexec.run_python),
        "memory_write": memory.upsert,   # sync sqlite (sub-ms)
        "memory_list": memory.search,
    }


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information. Returns titles, urls and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "How many results, 1-8 (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "Fetch a URL and return its readable main content as markdown. Use after web_search to read a promising result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL including https://"},
                    "max_chars": {"type": "integer", "description": "Max characters returned (default 20000)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc",
            "description": "Evaluate a single arithmetic expression exactly (use instead of mental math for anything non-trivial).",
            "parameters": {
                "type": "object",
                "properties": {"expr": {"type": "string", "description": "e.g. (1200*1.24)/3, sqrt(2)*pi"}},
                "required": ["expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python",
            "description": "Run a short standalone Python 3 script (no network access) and return stdout. For multi-step computations, data parsing or simulation.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Python source code; print() the result"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "Save a fact about the user, their environment, preferences or ongoing work to long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The fact to remember, one self-contained sentence"},
                    "key": {"type": "string", "description": "Optional short label"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_list",
            "description": "List saved long-term notes, optionally filtered by a keyword.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Optional keyword filter"}},
                "required": [],
            },
        },
    },
]

_SPEC_NAMES = {s["function"]["name"] for s in TOOL_SPECS}
_TOOL_RESULT_PREVIEW = 500


async def dispatch(name: str, args: dict[str, Any]) -> tuple[str, bool, int]:
    """Execute one tool call. Returns (result_text, ok, duration_ms). Truncates to TOOL_RESULT_MAX_CHARS."""
    fn = tool_impls().get(name)
    if fn is None or name not in _SPEC_NAMES:
        return f"error: unknown tool '{name}'", False, 0
    started = time.monotonic()
    try:
        result = await fn(**args)
        ok = not result.startswith("error:")
    except Exception as exc:
        result = f"error: {exc.__class__.__name__}: {exc}"
        ok = False
    ms = int((time.monotonic() - started) * 1000)
    return result[: max(0, settings.tool_result_max_chars)], ok, ms


def preview(text: str) -> str:
    return text[:_TOOL_RESULT_PREVIEW] + ("…" if len(text) > _TOOL_RESULT_PREVIEW else "")


def args_to_json(args: dict[str, Any]) -> str:
    try:
        return json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"