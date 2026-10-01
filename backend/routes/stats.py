"""Stats endpoints — all aggregations over the requests/tool_calls ledger."""

from fastapi import APIRouter, Depends, Query

from backend import auth as auth_mod
from backend import db

router = APIRouter(prefix="/stats", dependencies=[Depends(auth_mod.require_user)])


@router.get("/summary")
async def summary() -> dict:
    req = db.one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(prompt_tokens),0) AS p, COALESCE(SUM(completion_tokens),0) AS c, "
        "COALESCE(SUM(cached_tokens),0) AS cached FROM requests WHERE status='ok'"
    )
    req_err = db.one("SELECT COUNT(*) AS n FROM requests WHERE status!='ok'")
    sessions = db.one("SELECT COUNT(*) AS n FROM sessions")
    messages = db.one("SELECT COUNT(*) AS n FROM messages WHERE role='user'")
    tools = db.one("SELECT COUNT(*) AS n FROM tool_calls")
    days_active = db.one(
        "SELECT COUNT(DISTINCT date(created_at,'unixepoch','localtime')) AS n FROM requests WHERE status='ok'"
    )
    return {
        "requests": req["n"],
        "requests_failed": req_err["n"],
        "sessions": sessions["n"],
        "user_messages": messages["n"],
        "prompt_tokens": req["p"],
        "completion_tokens": req["c"],
        "cached_tokens": req["cached"],
        "tool_calls": tools["n"],
        "days_active": days_active["n"],
    }


@router.get("/timeseries")
async def timeseries(days: int = Query(default=30, ge=1, le=366)) -> list[dict]:
    rows = db.q(
        "SELECT date(created_at,'unixepoch','localtime') AS day, "
        "SUM(prompt_tokens) AS prompt, SUM(completion_tokens) AS completion, "
        "COUNT(*) AS requests, COALESCE(SUM(cached_tokens),0) AS cached "
        "FROM requests WHERE status='ok' AND created_at >= ? "
        "GROUP BY day ORDER BY day",
        (db.now() - days * 86400,),
    )
    return [dict(r) for r in rows]


@router.get("/top-models")
async def top_models(limit: int = Query(default=10, ge=1, le=50)) -> list[dict]:
    rows = db.q(
        "SELECT model, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt, SUM(completion_tokens) AS completion, "
        "COALESCE(AVG(duration_ms),0) AS avg_ms FROM requests WHERE status='ok' GROUP BY model ORDER BY "
        "(SUM(prompt_tokens) + SUM(completion_tokens)) DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


@router.get("/tools")
async def tools_stats(limit: int = Query(default=20, ge=1, le=50)) -> list[dict]:
    rows = db.q(
        "SELECT name, COUNT(*) AS calls, "
        "ROUND(100.0 * SUM(ok) / COUNT(*), 1) AS ok_rate, "
        "COALESCE(AVG(ms),0) AS avg_ms "
        "FROM tool_calls GROUP BY name ORDER BY calls DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


@router.get("/sessions")
async def top_sessions(limit: int = Query(default=20, ge=1, le=50)) -> list[dict]:
    rows = db.q(
        "SELECT s.id, s.title, s.model, MAX(s.updated_at) AS updated_at, "
        "COUNT(r.id) AS requests, COALESCE(SUM(r.prompt_tokens),0) AS prompt, "
        "COALESCE(SUM(r.completion_tokens),0) AS completion "
        "FROM sessions s LEFT JOIN requests r ON r.session_id = s.id AND r.status='ok' "
        "GROUP BY s.id ORDER BY (SUM(COALESCE(r.prompt_tokens,0)) + SUM(COALESCE(r.completion_tokens,0))) DESC, s.updated_at DESC "
        "LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]