"""Sessions CRUD + messages + markdown export."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from backend import auth as auth_mod
from backend import db
from backend.modes import get_mode
from backend.schemas import SessionPatch

router = APIRouter(prefix="/sessions", dependencies=[Depends(auth_mod.require_user)])


def _touch(session_id: str) -> None:
    db.qx("UPDATE sessions SET updated_at=? WHERE id=?", (db.now(), session_id))


@router.get("")
async def list_sessions() -> list[dict]:
    rows = db.q(
        "SELECT id, title, model, mode, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT 200"
    )
    return [dict(r) for r in rows]


@router.post("")
async def create_session(body: dict | None = None) -> dict:
    body = body or {}
    now = db.now()
    sid = db.new_id()
    db.qx(
        "INSERT INTO sessions (id, title, model, mode, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (
            sid,
            body.get("title") or "New chat",
            body.get("model") or "",
            get_mode(body.get("mode")).id,
            now,
            now,
        ),
    )
    row = db.one("SELECT id, title, model, mode, created_at, updated_at FROM sessions WHERE id=?", (sid,))
    return dict(row)


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict:
    srow = db.one(
        "SELECT id, title, model, mode, created_at, updated_at FROM sessions WHERE id=?", (session_id,)
    )
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
    # Attachment metadata only — the browser fetches the bytes lazily from
    # /api/images/{id}, so a message list stays small however many photos it holds.
    ids = [m["id"] for m in msgs]
    by_message: dict[str, list[dict]] = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for r in db.q(
            f"SELECT id, message_id, mime, name, width, height FROM message_images "
            f"WHERE message_id IN ({marks}) ORDER BY message_id, sort",
            tuple(ids),
        ):
            by_message.setdefault(r["message_id"], []).append(
                {
                    "id": r["id"],
                    "mime": r["mime"],
                    "name": r["name"],
                    "width": r["width"],
                    "height": r["height"],
                }
            )
    for m in msgs:
        m["images"] = by_message.get(m["id"], [])
    return {"session": dict(srow), "messages": msgs}


@router.patch("/{session_id}")
async def update_session(session_id: str, body: SessionPatch) -> dict:
    """Rename and/or re-mode. Partial on purpose: `title` used to be written
    unconditionally, which would now try `SET title=NULL` on a mode-only patch."""
    if not db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
        raise HTTPException(status_code=404, detail="session not found")
    if body.title is not None:
        db.qx("UPDATE sessions SET title=? WHERE id=?", (body.title, session_id))
    if body.mode is not None:
        db.qx("UPDATE sessions SET mode=? WHERE id=?", (body.mode, session_id))
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
        "SELECT id, role, content, quote, thinking, tool_calls_json, tool_name, created_at FROM messages "
        "WHERE session_id=? ORDER BY sort",
        (session_id,),
    )
    # Images are referenced by URL, never inlined as base64: a conversation with a
    # few dozen photos would otherwise export to a multi-megabyte .md. The link
    # resolves while the app runs and the reader is logged in.
    image_refs: dict[str, list[tuple[str, str]]] = {}
    for r in db.q(
        "SELECT message_id, id, name FROM message_images WHERE message_id IN "
        "(SELECT id FROM messages WHERE session_id=?) ORDER BY message_id, sort",
        (session_id,),
    ):
        image_refs.setdefault(r["message_id"], []).append((r["id"], r["name"]))
    parts = [f"# {srow['title']}", ""]
    for r in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))
        attached = image_refs.get(r["id"], [])
        if r["role"] == "user":
            parts += [f"## You · {stamp}", ""]
            quoted = (r["quote"] or "").strip()
            if quoted:
                parts += ["> " + "\n> ".join(quoted.splitlines()), ""]
            for image_id, image_name in attached:
                parts += [f"![{image_name or 'image'}](/api/images/{image_id})", ""]
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