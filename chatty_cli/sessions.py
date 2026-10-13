"""Pure helpers shared by the REPL and the one-shot commands — no I/O here."""


def resolve(ref: str, cache: list[dict]) -> str | None:
    '''"3" → the id at position 3 of the last listing; a bare id passes through.

    Numbers are only meaningful against what was actually shown, which is the
    caller's job to keep in `cache`.
    '''
    if ref.isdigit():
        idx = int(ref)
        if 1 <= idx <= len(cache):
            return str(cache[idx - 1].get("id"))
        return None
    return ref


def slug(title: str) -> str:
    """A session title → a filename part."""
    import re

    s = re.sub(r"\W+", "-", title.lower()).strip("-")
    return s or "chat"


def replay_lines(messages: list[dict], limit: int = 12) -> list[tuple[str, str]]:
    """Compact context for /open: one (role, text) line per message, newest last.

    thinking is omitted in v1 — the answer and the tool trail carry the story.
    """
    out: list[tuple[str, str]] = []
    for m in messages[-limit:]:
        role = m.get("role", "?")
        body = (m.get("content") or "").strip().replace("\n", " ")
        if role == "tool":
            ok = "ok" if not m.get("error") else "fail"
            out.append(("tool", f"{m.get('tool_name') or '?'} {ok} — {body}"))
        elif role == "assistant":
            model = m.get("model") or ""
            stamp = f" ·{model}" if model else ""
            if m.get("error"):
                body = f"[{m['error']}] {body}".strip()
            out.append(("bot", f"answer{stamp}: {body}"))
        elif role == "user":
            out.append(("you", f"{body}"))
        # system rows are plumbing, not a story — skipped
    return out