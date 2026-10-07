"""History projection: DB message rows -> upstream messages list."""

import json
from typing import Any

from backend.config import settings
from backend.modes import Mode, soft_rules


def system_prompt(notes: str = "", mode: Mode | None = None) -> str:
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    # Order matters: the frame (date), then the rules that survive the mode, then
    # the mode's own block, and the user's notes last of all.
    parts = [f"Today is {today}.", *soft_rules(mode)]
    if mode is not None and mode.block:
        parts.append(mode.block)
    if notes:
        parts.append(f"Long-term notes the user asked you to remember:\n{notes}")
    return "\n\n".join(parts)


def _field(row: Any, key: str) -> str:
    """Read a column without presuming the row shape: sqlite3.Row has no .get and
    raises IndexError on an unknown label, hand-built dicts (tests) raise KeyError.
    Anything that is not a string — None included — counts as absent."""
    try:
        value = row[key]
    except (KeyError, IndexError):
        return ""
    return value if isinstance(value, str) else ""


def _quote_prefix(quote: str) -> str:
    """The quoted fragment as a markdown blockquote, separated from the reply by a
    blank line. A blank line inside the quote becomes a bare ">": without it the
    blockquote would end early and the rest of the quote would read as user prose."""
    lines = quote.strip().splitlines()
    if not lines:
        return ""
    return "\n".join(f"> {line}" if line.strip() else ">" for line in lines) + "\n\n"


def build_messages(rows: list, notes: str = "", mode: Mode | None = None) -> list[dict[str, Any]]:
    """Rows ordered oldest->newest, already filtered to last N; system injected fresh at the top."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(notes, mode)}]
    for r in rows:
        role = r["role"]
        if role == "system":
            continue
        if role == "user":
            content = r["content"]
            quote = _field(r, "quote").strip()
            if quote:
                content = _quote_prefix(quote[:2000]) + content
            out.append({"role": "user", "content": content})
        elif role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": r["content"] or ""}
            if r["tool_calls_json"]:
                try:
                    calls = json.loads(r["tool_calls_json"])
                    msg["tool_calls"] = [
                        {
                            "function": {
                                "name": c.get("name", ""),
                                "arguments": c.get("arguments", {}),
                            },
                            **({"id": c["id"]} if c.get("id") else {}),
                        }
                        for c in calls
                    ]
                except json.JSONDecodeError:
                    pass
            out.append(msg)
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "content": r["content"],
                    "tool_name": r["tool_name"] or "",
                    **({"tool_call_id": r["tool_call_id"]} if r["tool_call_id"] else {}),
                }
            )
    # trim to history_max_messages (after system), never mid tool-run:
    # first kept message must be user or a plain assistant message.
    keep = settings.history_max_messages
    if len(out) > keep + 1:
        trimmed = [out[0]] + out[-(keep):]
        while len(trimmed) > 1:
            first = trimmed[1]
            ok_head = first["role"] == "user" or (
                first["role"] == "assistant" and "tool_calls" not in first
            )
            if ok_head:
                break
            trimmed.pop(1)
        out = trimmed
    return out