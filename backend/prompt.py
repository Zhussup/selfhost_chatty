"""History projection: DB message rows -> upstream messages list."""

import json
from typing import Any

from backend.config import settings


def system_prompt(notes: str = "") -> str:
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    parts = [
        f"Today is {today}.",
        "Reply in the language the user writes in.",
        "You have tools available. Use web_search for facts you are unsure about or that may be recent, "
        "and fetch_page to read a specific URL from search results. Use calc for any non-trivial arithmetic "
        "and python for computations or short scripts. Keep tool use purposeful — one search is usually enough.",
    ]
    if notes:
        parts.append(f"Long-term notes the user asked you to remember:\n{notes}")
    return "\n\n".join(parts)


def build_messages(rows: list, notes: str = "") -> list[dict[str, Any]]:
    """Rows ordered oldest->newest, already filtered to last N; system injected fresh at the top."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(notes)}]
    for r in rows:
        role = r["role"]
        if role == "system":
            continue
        if role == "user":
            out.append({"role": "user", "content": r["content"]})
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