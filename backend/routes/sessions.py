"""Sessions CRUD + messages + markdown export."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from backend import auth as auth_mod
from backend import db
from backend.schemas import SessionPatch

router = APIRouter(prefix="/sessions", dependencies=[Depends(auth_mod.require_user)])


def _touch(session_id: str) -> None:
    db.qx("UPDATE sessions SET updated_at=? WHERE id=?", (db.now(), session_id))


@router.get("")
async def list_sessions() -> list[dict]:
    rows = db.q("SELECT id, title, model, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT 200")
    return [dict(r) for r in rows]


@router.post("")
async def create_session(body: dict | None = None) -> dict:
    body = body or {}
    now = db.now()
    sid = db.new_id()
    db.qx(
        "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?,?,?,?,?)",
        (sid, body.get("title") or "New chat", body.get("model") or "", now, now),
    )
    row = db.one("SELECT id, title, model, created_at, updated_at FROM sessions WHERE id=?", (sid,))
    return dict(row)


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict:
    srow = db.one("SELECT id, title, model, created_at, updated_at FROM sessions WHERE id=?", (session_id,))
    if srow is None:
        raise HTTPException(status_code=404, detail="session not found")
    mrows = db.q(
        "SELECT id, role, content, quote, thinking, tool_calls_json, tool_call_id, tool_name, error, model, sort, created_at "
        "FROM messages WHERE session_id=? ORDER BY sort",
        (session_id,),
    )
    msgs = []
    for r in mrows:
        d = dict(r)
        if d["tool_calls_json"]:
            try:
                d["tool_calls"] = json.loads(d["tool_calls_json"])
            except json.JSONDecodeError:
                d["tool_calls"] = []
        else:
            d["tool_calls"] = None
        del d["tool_calls_json"]
        msgs.append(d)
    return {"session": dict(srow), "messages": msgs}


@router.patch("/{session_id}")
async def rename_session(session_id: str, body: SessionPatch) -> dict:
    if not db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
        raise HTTPException(status_code=404, detail="session not found")
    db.qx("UPDATE sessions SET title=? WHERE id=?", (body.title, session_id))
    return {"ok": True}


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    if not db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
        raise HTTPException(status_code=404, detail="session not found")
    db.qx("DELETE FROM messages WHERE session_id=?", (session_id,))
    db.qx("DELETE FROM sessions WHERE id=?", (session_id,))
    return {"ok": True}


@router.get("/{session_id}/export.md", response_class=PlainTextResponse)
async def export_md(session_id: str) -> PlainTextResponse:
    srow = db.one("SELECT title FROM sessions WHERE id=?", (session_id,))
    if srow is None:
        raise HTTPException(status_code=404, detail="session not found")
    # created_at is read below for the stamps — it must be selected (sqlite3.Row
    # raises IndexError on a column the query did not return).
    rows = db.q(
        "SELECT role, content, quote, thinking, tool_calls_json, tool_name, created_at FROM messages "
        "WHERE session_id=? ORDER BY sort",
        (session_id,),
    )
    parts = [f"# {srow['title']}", ""]
    for r in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))
        if r["role"] == "user":
            parts += [f"## You · {stamp}", ""]
            quoted = (r["quote"] or "").strip()
            if quoted:
                parts += ["> " + "\n> ".join(quoted.splitlines()), ""]
            parts += [r["content"], ""]
        elif r["role"] == "assistant":
            parts += [f"## Assistant · {stamp}", ""]
            if r["thinking"]:
                parts += [f"<details><summary>thinking</summary>\n\n{r['thinking']}\n\n</details>", ""]
            if r["tool_calls_json"]:
                parts += [f"```json\ntool_calls: {r['tool_calls_json']}\n```", ""]
            if r["content"]:
                parts += [r["content"], ""]
        elif r["role"] == "tool":
            parts += [f"### tool result — {r['tool_name'] or '?'}", "", "```\n" + r["content"] + "\n```", ""]
    return PlainTextResponse("\n".join(parts), media_type="text/markdown; charset=utf-8")