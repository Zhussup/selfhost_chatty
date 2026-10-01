"""POST /api/chat — the tool loop: streams NDJSON events to the frontend,
proxies upstream to Ollama Cloud, executes tools, records the token ledger.

Event protocol (each line is one JSON object):
  meta, delta, thinking, assistant_tool_calls, tool_result, usage, ping, done, error
Unknown `t` values must be ignored by clients (forward compatible).
"""

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend import auth as auth_mod
from backend import db
from backend.config import settings
from backend.ollama import (
    OllamaAuthError,
    OllamaRateLimitError,
    OllamaUpstreamError,
    _normalize_call,
    stream_chat,
)
from backend.prompt import build_messages
from backend.schemas import ChatIn
from backend.tools import memory
from backend.tools.registry import TOOL_SPECS, args_to_json, dispatch, preview

router = APIRouter(prefix="/api", dependencies=[Depends(auth_mod.require_user)])

_slot = asyncio.Semaphore(2)                 # parallel turns (plan concurrency)
_session_locks: dict[str, asyncio.Lock] = {}  # per-session serialization
_PING_INTERVAL = 5.0
_RETRY_AFTER_RATELIMIT = 3.0

_NUDGE = "Tool budget reached. Answer now using any results and information you already have."


class _Busy(Exception):
    pass


def _event(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def _err_event(code: str, message: str) -> dict[str, Any]:
    return {"t": "error", "code": code, "message": message}


def _next_sort(session_id: str) -> int:
    row = db.one("SELECT COALESCE(MAX(sort),0)+1 AS nxt FROM messages WHERE session_id=?", (session_id,))
    return row["nxt"] if row else 1


def _touch_session(session_id: str) -> None:
    db.qx("UPDATE sessions SET updated_at=? WHERE id=?", (db.now(), session_id))


def _save_message(
    session_id: str,
    role: str,
    content: str = "",
    *,
    message_id: str | None = None,
    thinking: str = "",
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    error: str | None = None,
    model: str | None = None,
) -> str:
    mid = message_id or db.new_id()
    db.qx(
        "INSERT INTO messages (id, session_id, role, sort, content, thinking, tool_calls_json, tool_call_id, tool_name, error, model, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mid,
            session_id,
            role,
            _next_sort(session_id),
            content,
            thinking,
            json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
            tool_call_id,
            tool_name,
            error,
            model,
            db.now(),
        ),
    )
    _touch_session(session_id)
    return mid


def _record_request(
    session_id: str,
    message_id: str | None,
    model: str,
    iteration: int,
    usage: dict[str, Any],
    status: str,
    duration_ms: int,
) -> None:
    db.qx(
        "INSERT INTO requests (id, session_id, message_id, model, iter, prompt_tokens, cached_tokens, "
        "completion_tokens, status, duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            db.new_id(),
            session_id,
            message_id,
            model,
            iteration,
            int(usage.get("prompt_eval_count", 0) or 0),
            int(usage.get("prompt_eval_cached_count", 0) or 0),
            int(usage.get("eval_count", 0) or 0),
            status,
            duration_ms,
            db.now(),
        ),
    )


def _record_tool_call(session_id: str, message_id: str, name: str, args_json: str, ok: bool, ms: int) -> None:
    db.qx(
        "INSERT INTO tool_calls (id, session_id, message_id, name, args_json, ok, ms, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (db.new_id(), session_id, message_id, name, args_json, 1 if ok else 0, ms, db.now()),
    )


def _truncate_after_last_user(session_id: str) -> None:
    row = db.one("SELECT MAX(sort) AS s FROM messages WHERE session_id=? AND role='user'", (session_id,))
    last_sort = row["s"] if row is not None else None
    if last_sort is not None:
        db.qx("DELETE FROM messages WHERE session_id=? AND sort>?", (session_id, last_sort))


def _upstream_tool_msg(call: dict[str, Any]) -> dict[str, Any]:
    msg: dict[str, Any] = {"function": {"name": call["name"], "arguments": call["arguments"]}}
    if call.get("id"):
        msg["id"] = call["id"]
    return msg


async def _ping_loop(out_q: asyncio.Queue) -> None:
    while True:
        await asyncio.sleep(_PING_INTERVAL)
        await out_q.put({"t": "ping"})


async def _run_one_call(
    idx: int, call: dict[str, Any], session_id: str, message_id: str, out_q: asyncio.Queue
) -> None:
    args = call["arguments"]
    result, ok, ms = await dispatch(call["name"], args)
    truncated = result[: max(0, settings.tool_result_max_chars)]
    _record_tool_call(session_id, message_id, call["name"], args_to_json(args), ok, ms)
    await out_q.put({
        "_index": idx,
        "t": "tool_result",
        "id": call["id"],
        "name": call["name"],
        "ok": ok,
        "ms": ms,
        "result": preview(truncated),
        "full": truncated,
    })


async def _upstream_call(
    body: ChatIn,
    hist: list[dict[str, Any]],
    base_payload: dict[str, Any],
    with_tools: bool,
    iteration: int,
) -> AsyncIterator[dict[str, Any]]:
    """Yields delta/thinking/ping events, then a final {"_result": ...} carrying
    (content, thinking, tool_calls, usage, done_reason). Retries once on 429."""
    content_acc: list[str] = []
    thinking_acc: list[str] = []
    calls: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    done_reason = ""

    for attempt in range(1, 3):  # 1 try + 1 retry on 429
        req = dict(base_payload, messages=hist, stream=True)
        if not with_tools:
            req.pop("tools", None)
        try:
            async for chunk in stream_chat(req):
                msg = chunk.get("message") or {}
                if text := msg.get("content") or "":
                    content_acc.append(text)
                    yield {"t": "delta", "v": text}
                if (think_text := msg.get("thinking") or "") and body.think is not None:
                    thinking_acc.append(think_text)
                    yield {"t": "thinking", "v": think_text}
                for j, raw in enumerate(msg.get("tool_calls") or []):
                    calls.append(_normalize_call(raw, j, iteration))
                if chunk.get("done"):
                    usage = chunk
                    done_reason = chunk.get("done_reason") or ""
                    break
            yield {
                "_result": (
                    "".join(content_acc),
                    "".join(thinking_acc),
                    calls,
                    usage,
                    done_reason,
                )
            }
            return
        except OllamaRateLimitError:
            if attempt < 2 and not content_acc and not calls:
                yield {"t": "ping"}
                await asyncio.sleep(_RETRY_AFTER_RATELIMIT)
                continue
            raise

    raise OllamaUpstreamError("stream ended without completion")


@router.post("/chat")
async def chat(body: ChatIn) -> StreamingResponse:
    if _slot.locked():
        busied = _event(_err_event("rate_limited", "another turn is already running"))
        return StreamingResponse(iter([busied]), media_type="application/x-ndjson", status_code=409)
    await _slot.acquire()

    return StreamingResponse(
        _run_turn(body),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _run_turn(body: ChatIn) -> AsyncIterator[str]:
    """Owns the slot: releases it in finally (cancel-safe). Serializes per session."""
    turn_started = time.monotonic()
    turn_prompt = 0
    turn_completion = 0
    turn_tool_calls = 0
    saved = False            # final/partial assistant row persisted?
    session_id = body.session_id
    model = body.model
    message_id = db.new_id()
    partial_content = ""
    partial_thinking = ""    # cancellation-safe accumulators
    lock_key = body.session_id or "__new__"

    try:
        async with _session_locks.setdefault(lock_key, asyncio.Lock()):
            # --- session bootstrap -------------------------------------------------
            if session_id is None or not db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
                session_id = db.new_id()
                now = db.now()
                title = body.content[:60] or "New chat"
                db.qx(
                    "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?,?,?,?,?)",
                    (session_id, title, model, now, now),
                )
            else:
                _touch_session(session_id)

            yield _event({"t": "meta", "session_id": session_id, "message_id": message_id})

            if body.regenerate:
                _truncate_after_last_user(session_id)
            else:
                _save_message(session_id, "user", body.content)

            # --- upstream history ----------------------------------------------
            rows = db.q(
                "SELECT role, content, thinking, tool_calls_json, tool_call_id, tool_name FROM messages "
                "WHERE session_id=? ORDER BY sort",
                (session_id,),
            )
            notes = memory.snapshot(settings.notes_snapshot_chars) if settings.notes_snapshot_chars else ""
            messages = build_messages(list(rows), notes)
            base_payload: dict[str, Any] = {"model": model, "options": {"num_ctx": 16384}}
            if body.think is not None:
                base_payload["think"] = body.think
            if body.use_tools:
                base_payload["tools"] = TOOL_SPECS

            final_done = False
            for iteration in range(1, settings.tool_max_iter + 1):
                budget_last = iteration == settings.tool_max_iter and body.use_tools
                if budget_last:
                    messages.append({"role": "user", "content": _NUDGE})

                partial_content = ""      # each upstream call has its own partial window
                partial_thinking = ""
                started = time.monotonic()
                content = thinking = ""
                tool_calls: list[dict[str, Any]] = []
                usage: dict[str, Any] = {}
                done_reason = ""

                agen = _upstream_call(
                    body, list(messages), base_payload,
                    with_tools=not budget_last, iteration=iteration,
                )
                async for chunk_ev in agen:
                    kind = chunk_ev.get("t")
                    if kind == "delta":
                        partial_content += chunk_ev["v"]
                    elif kind == "thinking":
                        partial_thinking += chunk_ev["v"]
                    if "_result" in chunk_ev:
                        content, thinking, tool_calls, usage, done_reason = chunk_ev["_result"]
                    else:
                        yield _event(chunk_ev)
                await agen.aclose()

                if not usage:
                    raise OllamaUpstreamError("stream ended without completion")

                ms = int((time.monotonic() - started) * 1000)
                _record_request(session_id, message_id, model, iteration, usage, "ok", ms)
                turn_prompt += int(usage.get("prompt_eval_count", 0) or 0)
                turn_completion += int(usage.get("eval_count", 0) or 0)
                yield _event({
                    "t": "usage",
                    "iter": iteration,
                    "prompt": turn_prompt,
                    "cached": int(usage.get("prompt_eval_cached_count", 0) or 0),
                    "completion": turn_completion,
                })

                if not tool_calls:
                    saved = True
                    _save_message(
                        session_id, "assistant", content,
                        message_id=message_id,
                        thinking=thinking if body.think is not None else "",
                        model=model,
                    )
                    yield _event({
                        "t": "done",
                        "message_id": message_id,
                        # the nudged final answer still marks the exhausted budget
                        "reason": "tool_budget" if budget_last else (done_reason or "stop"),
                        "prompt": turn_prompt,
                        "completion": turn_completion,
                        "tool_calls": turn_tool_calls,
                        "ms": int((time.monotonic() - turn_started) * 1000),
                    })
                    final_done = True
                    return

                turn_tool_calls += len(tool_calls)
                yield _event({"t": "assistant_tool_calls", "iter": iteration, "calls": tool_calls})
                assistant_row_id = _save_message(
                    session_id, "assistant", content,
                    thinking=thinking if body.think is not None else "",
                    tool_calls=tool_calls,
                    model=model,
                )

                out_q: asyncio.Queue = asyncio.Queue()
                tasks = [
                    asyncio.create_task(_run_one_call(i, call, session_id, assistant_row_id, out_q))
                    for i, call in enumerate(tool_calls)
                ]
                pinger = asyncio.create_task(_ping_loop(out_q))
                results: list[dict[str, Any] | None] = [None] * len(tasks)
                try:
                    finished = 0
                    while finished < len(tasks):
                        res_ev = await out_q.get()
                        if res_ev.get("t") == "ping":
                            yield _event(res_ev)
                            continue
                        idx = res_ev["_index"]
                        del res_ev["_index"]
                        results[idx] = res_ev
                        yield _event(res_ev)
                        finished += 1
                finally:
                    pinger.cancel()
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [_upstream_tool_msg(c) for c in tool_calls],
                })
                for call, res in zip(tool_calls, results, strict=True):
                    res = res or {"full": "error: tool did not return a result"}
                    messages.append({
                        "role": "tool",
                        "content": res.get("full", "error: tool did not return a result"),
                        "tool_name": call["name"],
                        **({"tool_call_id": call["id"]} if call.get("id") else {}),
                    })
                    _save_message(
                        session_id, "tool",
                        res.get("full", "error: tool did not return a result"),
                        tool_call_id=call.get("id"),
                        tool_name=call["name"],
                    )
                # loop continues: the model answers from tool results on the next iteration

            if not final_done:
                saved = True
                _save_message(
                    session_id, "assistant", partial_content,
                    message_id=message_id,
                    thinking=partial_thinking if body.think is not None else "",
                    model=model,
                )
                yield _event({
                    "t": "done",
                    "message_id": message_id,
                    "reason": "tool_budget",
                    "prompt": turn_prompt,
                    "completion": turn_completion,
                    "tool_calls": turn_tool_calls,
                    "ms": int((time.monotonic() - turn_started) * 1000),
                })

    except asyncio.CancelledError:
        # client disconnected: persist whatever streamed, then propagate
        if not saved and session_id and db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
            try:
                if partial_content:
                    _save_message(
                        session_id, "assistant", partial_content,
                        thinking=partial_thinking if body.think is not None else "",
                        model=model,
                    )
            except Exception:
                pass
        raise
    except (OllamaAuthError, OllamaRateLimitError, OllamaUpstreamError) as exc:
        code = {"OllamaAuthError": "ollama_auth", "OllamaRateLimitError": "rate_limited"}.get(
            type(exc).__name__, "ollama_upstream"
        )
        if session_id and not saved:
            try:
                _save_message(
                    session_id, "assistant", partial_content,
                    thinking=partial_thinking if body.think is not None else "",
                    error=type(exc).__name__, model=model,
                )
            except Exception:
                pass
        yield _event(_err_event(code, str(exc)))
    finally:
        _slot.release()
        _session_locks.pop(lock_key, None)