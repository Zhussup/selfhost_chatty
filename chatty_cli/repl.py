"""Interactive REPL: streaming answers plus the SPA's slash grammar.

The mode list and its aliases are fetched, not hardcoded — the same registry
the web UI uses, so a new backend persona is usable from the terminal with no
CLI release. Ctrl+C during a turn cancels just that stream (the server keeps
the partial answer); at the prompt it clears the line, like any shell.
"""

import asyncio
import os
import re
import signal

from . import sessions as sh
from .client import ApiError, Chatty, read_images
from .render import Renderer

# verbatim port of frontend/src/modes.ts parseSlash: a token must start with a
# letter, so "/2" and "/usr/bin" stay plain messages
_SLASH = re.compile(r"^/([A-Za-z][A-Za-z0-9-]*)(?:\s+([\s\S]*))?$")

_BUILTINS = {
    "help", "exit", "quit", "new", "model", "think", "tools",
    "sessions", "open", "rm", "export", "img", "modes",
}

_THINK_LEVELS = ("off", "low", "medium", "high")


class Repl:
    """One instance per terminal session; asyncio.run() drives each turn."""

    def __init__(self, c: Chatty, r: Renderer, input_fn=None):
        self.c = c
        self.r = r
        self.input_fn = input_fn or input
        self.sid: str | None = None
        self.model: str | None = None
        self.mode = "assistant"
        self.think: str | None = None
        self.use_tools = True
        self.images: list[str] = []
        self.cache: list[dict] = []   # latest /sessions listing — /open and /rm resolve against it
        self._modes: list[dict] = []
        self.aliases: dict[str, str] = {}

    # ------------------------------------------------------------------- core

    async def _startup(self) -> None:
        self.model = await self.c.resolve_model(None)
        data = await self.c.modes()
        self._modes = data.get("modes", [])
        # id doubles as an alias of itself, like findMode in the SPA
        self.aliases = {
            a: m["id"]
            for m in self._modes
            for a in [m["id"], *m.get("aliases", [])]
        }

    async def run(self) -> int:
        try:
            import readline  # noqa: F401 — arrow keys + in-memory history

        except ImportError:
            pass
        await self._startup()
        self.r.note(
            f"model {self.model} — /modes personas, /help commands, Ctrl+D quits"
        )

        loop = asyncio.get_running_loop()
        turn_task: asyncio.Task | None = None

        def _sigint() -> None:
            # during a turn: cancel just the stream; at the prompt: restore the
            # default SIGINT so input() raises KeyboardInterrupt like any shell
            nonlocal turn_task
            if turn_task is not None and not turn_task.done():
                turn_task.cancel()
                return
            loop.remove_signal_handler(signal.SIGINT)
            os.kill(os.getpid(), signal.SIGINT)

        try:
            loop.add_signal_handler(signal.SIGINT, _sigint)
        except NotImplementedError:      # non-unix: Ctrl+C kills the REPL (fine)
            pass

        while True:
            try:
                line = self.input_fn("› ").strip()
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print()
                continue
            if not line:
                continue
            verdict = await self.handle(line)
            if verdict is True:
                return 0
            if isinstance(verdict, str):
                turn_task = asyncio.ensure_future(self.turn(verdict))
                try:
                    await turn_task
                except asyncio.CancelledError:
                    self.r.stopped()
                turn_task = None

    async def turn(self, text: str) -> None:
        """One streaming turn; images attach once, like the SPA composer."""
        payload: dict = {
            "model": self.model,
            "content": text,
            "use_tools": self.use_tools,
        }
        if self.sid:
            payload["session_id"] = self.sid
        if self.mode:
            payload["mode"] = self.mode
        if self.think:
            payload["think"] = self.think
        if self.images:
            payload["images"] = read_images(self.images)
            self.images = []
        try:
            summary = await self.c.chat(payload, on_event=self.r.event)
            self.sid = summary.get("session_id") or self.sid
        except ApiError as exc:
            self.r.error(exc.code, exc.message)

    # ---------------------------------------------------------------- dispatch

    async def handle(self, line: str):
        """True = quit, False = handled, str = the text to send."""
        stripped = line.strip()
        m = _SLASH.match(stripped)
        if m is None:
            return stripped          # plain text goes through as-is
        token, rest = m.group(1).lower(), (m.group(2) or "").strip()

        if token in self.aliases:
            return await self._mode(token, rest)
        if token in _BUILTINS:
            return await self._builtin(token, rest)
        # same spirit as the SPA: an unknown slash command is loud, not sent
        self.r.note(f"unknown command: /{token} — /help for commands, /modes for personas")
        return False

    async def _mode(self, token: str, rest: str):
        mode = next((m for m in self._modes if m["id"] == self.aliases[token]), None)
        if mode is None:
            self.r.note(f"Unknown mode: /{token}")
            return False
        if self.mode == mode["id"]:
            pass                     # re-picking the active persona is a no-op
        elif mode.get("warn") and not self._confirm(mode["warn"]):
            self.r.note("declined — mode unchanged, nothing sent")
            return False
        await self._adopt_mode(mode)
        return rest or False         # str = switch-and-send in one turn

    async def _adopt_mode(self, mode: dict, patch: bool = True) -> None:
        """Mirror the SPA's setMode: adopt think/use_tools the persona forces,
        persist at once when a session exists, and always send mode next turn."""
        self.mode = mode["id"]
        if mode.get("think"):
            self.think = mode["think"]
        if mode.get("tools") == "on":
            self.use_tools = True
        elif mode.get("tools") == "off":
            self.use_tools = False
        if patch and self.sid:
            try:
                await self.c.patch_session(self.sid, {"mode": self.mode})
            except ApiError as exc:
                self.r.error(exc.code, exc.message)

    def _confirm(self, warn: str) -> bool:
        self.r.warn(warn)
        try:
            ans = self.input_fn("switch? [y/N] ")
        except (KeyboardInterrupt, EOFError):
            print()
            return False
        return ans.strip().lower() in ("y", "yes")

    async def _builtin(self, token: str, rest: str):
        if token == "exit" or token == "quit":
            return True
        if token == "help":
            self.r.command_help()
            return False
        if token == "modes":
            self.r.modes_table(self._modes, current=self.mode)
            return False
        if token == "new":
            await self._cmd_new(rest)
            return False
        if token == "model":
            await self._cmd_model(rest)
            return False
        if token == "think":
            self._cmd_think(rest)
            return False
        if token == "tools":
            self._cmd_tools(rest)
            return False
        if token == "sessions":
            await self._cmd_sessions(rest)
            return False
        if token == "open":
            await self._cmd_open(rest)
            return False
        if token == "rm":
            await self._cmd_rm(rest)
            return False
        if token == "export":
            await self._cmd_export(rest)
            return False
        if token == "img":
            self._cmd_img(rest)
            return False
        self.r.note(f"unknown command: /{token}")     # unreachable — belt and braces
        return False

    # --------------------------------------------------------------- commands

    async def _cmd_new(self, title: str) -> None:
        if not title:
            self.sid = None
            self.r.note("next message starts a fresh conversation")
            return
        row = await self.c.create_session(
            {"title": title[:120], "model": self.model, "mode": self.mode}
        )
        self.sid = row.get("id")
        self.r.note(f"session {str(self.sid)[:8]} — {title[:40]}")

    async def _cmd_model(self, name: str) -> None:
        listing = (await self.c.models()).get("models") or []
        if not name:
            self.r.models_list(listing)
            if not listing:
                self.r.note("no models — check OLLAMA_API_KEY on the server")
            return
        names = {m.get("name") for m in listing}
        if name not in names:
            self.r.note(f"unknown model: {name} — /model lists the choices")
            return
        self.model = name
        self.r.note(f"model → {name}")

    def _cmd_think(self, raw: str) -> None:
        if not raw:
            self.r.note(f"think: {self.think or 'off'} — /think off|low|medium|high")
            return
        if raw not in _THINK_LEVELS:
            self.r.note(f"think: use one of {', '.join(_THINK_LEVELS)}")
            return
        self.think = None if raw == "off" else raw
        self.r.note(f"think → {self.think or 'off'}")

    def _cmd_tools(self, raw: str) -> None:
        if raw == "on":
            self.use_tools = True
        elif raw == "off":
            self.use_tools = False
        elif raw:
            self.r.note("tools: use on or off")
            return
        self.r.note(f"tools → {'on' if self.use_tools else 'off'}")

    async def _cmd_sessions(self, raw: str) -> None:
        n = int(raw) if raw.isdigit() else 12
        rows = await self.c.sessions()
        self.cache = rows[:n]
        self.r.sessions_table(self.cache)

    async def _cmd_open(self, ref: str) -> None:
        if not ref:
            self.r.note("open what? /open <n|id> — /sessions for the list")
            return
        sid = sh.resolve(ref, self.cache)
        try:
            row = await self.c.session(sid)
        except ApiError as exc:
            self.r.error(exc.code, exc.message)
            return
        self.sid = sid
        sess = row.get("session") or {}
        self.model = sess.get("model") or self.model
        mode = next((m for m in self._modes if m["id"] == sess.get("mode")), None)
        if mode:
            # the row already carries this mode — adopt it, don't re-PATCH it
            await self._adopt_mode(mode, patch=False)
        self.r.replay(sh.replay_lines(row.get("messages") or []))

    async def _cmd_rm(self, ref: str) -> None:
        if not ref:
            self.r.note("rm what? /rm <n|id> — /sessions for the list")
            return
        sid = sh.resolve(ref, self.cache)
        if not self._confirm(f"delete conversation {str(sid)[:8]}?"):
            self.r.note("kept")
            return
        await self.c.delete_session(sid)
        if self.sid == sid:
            self.sid = None
        self.r.note(f"deleted {str(sid)[:8]}")

    async def _cmd_export(self, raw: str) -> None:
        if not self.sid:
            self.r.note("nothing to export yet — this turn has no session")
            return
        from pathlib import Path

        title = ""
        try:
            title = (await self.c.session(self.sid)).get("session", {}).get("title") or ""
        except ApiError:
            pass
        target = raw or f"{sh.slug(title)}.md"
        text = await self.c.export_md(self.sid)
        Path(target).write_text(text, encoding="utf-8")
        self.r.note(f"wrote {target}")

    def _cmd_img(self, raw: str) -> None:
        if not raw:
            self.r.note(
                f"{len(self.images)} image(s) queued" if self.images
                else "img: pass file paths, or 'clear'"
            )
            return
        if raw.strip().lower() == "clear":
            self.images = []
            self.r.note("images cleared")
            return
        from pathlib import Path

        for p in raw.split():
            self.images.append(str(Path(p).expanduser()))
        self.r.note(f"{len(self.images)} image(s) queued for the next message")