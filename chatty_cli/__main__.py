"""argparse entry point: chatty-cli ask|chat|sessions|export|models.

Bare `chatty-cli` on a terminal opens the REPL — the bash wrapper `chatty`
still owns starting and stopping the server.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__, sessions as sh
from .client import ApiError, Chatty
from .config import ConfigError, resolve
from .render import Renderer


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--url",
        help="server base url (default: CHATTY_URL, then .run/chatty.url, then localhost:8000)",
    )
    parent.add_argument(
        "--password",
        help="login password (prefer CHATTY_PASSWORD — argv lands in shell history)",
    )
    p = argparse.ArgumentParser(
        prog="chatty-cli",
        description="Terminal client for chatty: one-shot ask and a streaming REPL.",
    )
    p.add_argument("--version", action="version", version=f"chatty-cli {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="command")
    a = sub.add_parser("ask", parents=[parent], help="one question, one answer; stdin pipes work")
    a.add_argument("prompt", nargs="*", help="the question (or pipe text on stdin)")
    a.add_argument("-m", "--mode", help="mode id or alias (fact-check, teacher, tldr, code…)")
    a.add_argument("--model", help="model name; sessions via --session inherit their model")
    a.add_argument("--think", choices=["off", "low", "medium", "high"], help="reasoning depth")
    a.add_argument("--no-tools", action="store_true", help="send without tools")
    a.add_argument("--session", help="continue this session (id from a sessions listing)")
    a.add_argument(
        "--img", action="extend", nargs="+", default=[], help="attach image file paths"
    )
    sub.add_parser("chat", parents=[parent], help="interactive streaming REPL (/help inside)")
    s = sub.add_parser("sessions", parents=[parent], help="list recent conversations")
    s.add_argument("-n", type=int, default=12, help="how many to show")
    e = sub.add_parser("export", parents=[parent], help="conversation as markdown")
    e.add_argument("session", help="session id, or the number from chatty-cli sessions")
    e.add_argument("file", nargs="?", help="write here instead of stdout")
    sub.add_parser("models", parents=[parent], help="list available models")
    return p


async def _export(c: Chatty, r: Renderer, args) -> int:
    ref = args.session
    if ref.isdigit():
        page = await c.sessions()
        sid = sh.resolve(ref, page)
        if not sid:
            r.note(f"no conversation numbered {ref} — check chatty-cli sessions")
            return 1
    else:
        sid = ref
    text = await c.export_md(sid)
    if args.file:
        Path(args.file).write_text(text, encoding="utf-8")
        r.note(f"wrote {args.file}")
    else:
        r.out.write(text)
        r.out.flush()
    return 0


def _dispatch(args, cfg, r: Renderer, transport=None) -> int:
    c = Chatty(cfg, transport=transport)
    if args.cmd == "chat":
        from .repl import Repl

        return int(asyncio.run(Repl(c, r).run()) or 0)
    if args.cmd == "ask":
        from .ask import run

        return int(asyncio.run(run(c, r, args)))
    if args.cmd == "sessions":
        rows = asyncio.run(c.sessions())
        r.sessions_table(rows[: args.n])
        return 0
    if args.cmd == "models":
        r.models_list(asyncio.run(c.models()).get("models", []))
        return 0
    if args.cmd == "export":
        return asyncio.run(_export(c, r, args))
    return 2


def main(argv: list[str] | None = None, transport=None, out=None, err=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.cmd:
        if sys.stdin.isatty():
            args.cmd = "chat"
        else:
            print(
                '[chatty-cli] a command is needed — try: chatty-cli ask "…" | '
                "chatty-cli chat | chatty-cli --help",
                file=sys.stderr,
            )
            return 2
    try:
        cfg = resolve(getattr(args, "url", None), getattr(args, "password", None))
    except ConfigError as exc:
        print(f"[chatty-cli] {exc}", file=err or sys.stderr)
        return 2
    r = Renderer(cfg.tty, out=out, err=err)
    try:
        return _dispatch(args, cfg, r, transport=transport)
    except KeyboardInterrupt:
        r.note("interrupted")
        return 130
    except ConfigError as exc:           # e.g. `ask` ran with nothing to send
        r.note(str(exc))
        return 2
    except ApiError as exc:
        r.error(exc.code, exc.message)
        return 1


if __name__ == "__main__":
    sys.exit(main())