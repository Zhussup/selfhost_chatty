"""Persistent notes (tool storage) — the model's long-term memory."""

import sqlite3

from backend import db


def upsert(content: str, key: str = "") -> str:
    if not content.strip():
        return "empty note ignored"
    now = db.now()
    nid = db.new_id()
    try:
        with db._lock:
            db.conn().execute(
                "INSERT INTO notes (id, content, created_at, updated_at) VALUES (?,?,?,?)",
                (nid, content.strip(), now, now),
            )
            db.conn().commit()
    except sqlite3.Error as exc:
        return f"error saving note: {exc}"
    return f"note saved ({len(content)} chars)"


def search(query: str = "", limit: int = 50) -> str:
    if query:
        rows = db.q(
            "SELECT id, content, updated_at FROM notes WHERE content LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (f"%{query}%", limit),
        )
    else:
        rows = db.q("SELECT id, content, updated_at FROM notes ORDER BY updated_at DESC LIMIT ?", (limit,))
    if not rows:
        return "no notes found"
    import time

    lines = []
    for r in rows:
        stamp = time.strftime("%Y-%m-%d", time.localtime(r["updated_at"]))
        lines.append(f"[{r['id'][:8]}] ({stamp}) {r['content']}")
    return "\n".join(lines)


def snapshot(char_limit: int) -> str:
    """Short recent notes for the system prompt."""
    rows = db.q("SELECT content FROM notes ORDER BY updated_at DESC LIMIT 20")
    if not rows:
        return ""
    return "\n".join(r["content"] for r in rows)[:char_limit]