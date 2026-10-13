"""One-shot `ask`: prompt from argv or stdin, answer on stdout, exit code says why.

The piped form (`cat notes.md | chatty-cli ask -m tldr`) is the reason stdout
stays answer-only — everything else is stderr.
"""

import sys

from .client import Chatty, read_images
from .config import ConfigError


def piped_text() -> str:
    """Piped stdin becomes the prompt; a terminal stdin means argv had the text."""
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read().strip()


async def run(c: Chatty, r, args) -> int:
    content = " ".join(args.prompt).strip() or piped_text()
    if not content and not args.img:
        raise ConfigError(
            'nothing to send — give a prompt, pipe text on stdin, or pass --img files'
        )

    sid = args.session
    model = args.model
    if sid:
        # 404 here is a loud, useful error ("no such session") — keep it;
        # otherwise a typo would quietly start a fresh conversation.
        row = await c.session(sid)
        model = model or (row.get("session") or {}).get("model") or None

    if not model:
        model = await c.resolve_model(None)

    payload: dict = {
        "model": model,
        "content": content,
        "use_tools": not args.no_tools,
    }
    if sid:
        payload["session_id"] = sid
    if args.mode:
        payload["mode"] = args.mode
    if args.think and args.think != "off":
        payload["think"] = args.think
    if args.img:
        payload["images"] = read_images(args.img)

    await c.chat(payload, on_event=r.event)
    # the done footer (reason · time · tokens · session id) already came from
    # the stream via r.event; the exit code is the machine-readable part
    return 0