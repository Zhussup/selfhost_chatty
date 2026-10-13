"""Everything the CLI prints. The rule: stdout carries answers — raw deltas
only, byte-exact for pipes; every status line (thinking, tools, footers,
tables) goes to stderr. A terminal gets rich styling; a pipe gets plain text."""

import os
import sys
from typing import IO, TextIO

from rich.console import Console
from rich.table import Table
from rich.text import Text

_DIM = "dim"
_ANSI_DIM = "\x1b[2m"
_ANSI_RESET_DIM = "\x1b[22m"


def _ago(ts: int | float | None) -> str:
    """unix seconds → 'now / 5m / 2h / 3d / 12d'."""
    if not ts:
        return "?"
    import time

    d = max(0, int(time.time() - ts))
    for step, unit in ((60, "s"), (3600, "m"), (86400, "h"), (86400 * 30, "d")):
        if d < step:
            return f"{d // ((step // 60) or step)}{unit}"
    return f"{d // 86400}d"


def _human_i(n: int | float | None) -> str:
    return f"{n or 0:,}"


class Renderer:
    """One renderer per run (or per REPL); state is only the streaming sidebar
    (thinking, last session id) — everything else is per-event."""

    def __init__(self, tty: bool, out: TextIO | None = None, err: TextIO | None = None):
        self.out: IO = out or sys.stdout
        self.err: IO = err or sys.stderr
        self.tty = tty and not os.environ.get("NO_COLOR")
        self._sid: str | None = None
        self._in_think = False
        self._think_noted = False
        if self.tty:
            # markup=False everywhere: model output contains '[' and '*' freely,
            # and neither answers nor server texts must be parsed as rich markup.
            self._con = Console(
                file=self.out, markup=False, highlight=False, quiet=True
            )
            self._err = Console(file=self.err, markup=False, highlight=False)
        else:
            self._con = None
            self._err = None

    # ------------------------------------------------------------------ stream

    def event(self, ev: dict) -> None:
        """The single entry point from the event stream; unknown `t` is noise."""
        t = ev.get("t")
        if t == "delta":
            self.delta(ev.get("v", ""))
        elif t == "thinking":
            self.thinking(ev.get("v", ""))
        elif t == "assistant_tool_calls":
            self.tool_calls(ev)
        elif t == "tool_result":
            self.tool_result(ev)
        elif t == "meta":
            self._sid = ev.get("session_id")
        elif t == "done":
            self.footer(ev)
        # usage folds into the done footer; ping is a keepalive: both stay silent

    def delta(self, text: str) -> None:
        """Raw answer chunk — the pipable path, flushed per chunk."""
        self._leave_think()          # thinking ends where the answer begins
        self.out.write(text)
        self.out.flush()

    def thinking(self, v: str) -> None:
        """Streamed reasoning: dim italic in a terminal, one stderr note in a pipe."""
        if self.tty:
            if not self._in_think:
                self._in_think = True
                self.err.write(_ANSI_DIM)
            self.err.write(v)
            self.err.flush()
        elif not self._think_noted:
            self._think_noted = True
            print("[chatty-cli] thinking…", file=self.err)

    def _leave_think(self) -> None:
        if self._in_think:
            self._in_think = False
            self.err.write(_ANSI_RESET_DIM + "\n")
            self.err.flush()

    def tool_calls(self, ev: dict) -> None:
        self._leave_think()
        names = [c.get("name", "?") for c in ev.get("calls", ())]
        line = f"⌘ {', '.join(names)}" if names else "⌘"
        if self.tty:
            self._err.print(line, style=_DIM)
        else:
            print(f"[chatty-cli] tool: {', '.join(names)}", file=self.err)

    def tool_result(self, ev: dict) -> None:
        self._leave_think()
        head = "✓" if ev.get("ok") else "✗"
        preview = (ev.get("result") or "").strip().replace("\n", " ")[:80]
        line = f"{head} {ev.get('name', '?')} {ev.get('ms', 0)}ms — {preview or '(empty)'}"
        if self.tty:
            self._err.print(line, style=_DIM)
        else:
            print(f"[chatty-cli] {line}", file=self.err)

    def footer(self, ev: dict) -> None:
        self._leave_think()
        secs = (ev.get("ms") or 0) / 1000
        tok = _human_i((ev.get("prompt") or 0) + (ev.get("completion") or 0))
        parts = [ev.get("reason") or "done", f"{secs:.1f}s", f"{tok} tok"]
        if self._sid:
            parts.append(f"session {(self._sid or '')[:8]}")
        line = "— " + " · ".join(parts)
        if self.tty:
            self._err.print(line, style=_DIM)
        else:
            print(f"[chatty-cli] done: {' · '.join(parts)}", file=self.err)

    # ----------------------------------------------------------------- status

    def note(self, text: str) -> None:
        self._leave_think()
        if self.tty:
            self._err.print(text, style=_DIM)
        else:
            print(f"[chatty-cli] {text}", file=self.err)

    def warn(self, text: str) -> None:
        self._leave_think()
        line = f"! {text}"
        if self.tty:
            self._err.print(line, style="yellow")
        else:
            print(f"[chatty-cli] {line}", file=self.err)

    def stopped(self) -> None:
        """Ctrl+C mid-stream: the server keeps whatever already arrived."""
        self._leave_think()
        if self.tty:
            self._err.print("— stopped · partial answer saved", style=_DIM)
        else:
            print("[chatty-cli] stopped, partial answer saved", file=self.err)

    def error(self, code: str, message: str) -> None:
        self._leave_think()
        if code == "rate_limited":
            message = "another turn is already running — wait a moment"
        tail = f" [{code}]" if code and code != "http" else ""
        line = f"error: {message}{tail}"
        if self.tty:
            self._err.print(line, style="bold red")
        else:
            print(f"[chatty-cli] {line}", file=self.err)

    # ------------------------------------------------------------ REPL panels

    def command_help(self) -> None:
        lines = [
            "commands",
            "  /modes             list personas",
            "  /<persona> [text]  switch mode; with text — switch and send in one turn",
            "  /model [name]      show or set the model",
            "  /think off|low|medium|high    reasoning depth",
            "  /tools on|off      tool calling",
            "  /new [title]       start a fresh conversation",
            "  /sessions [n]      recent conversations",
            "  /open <n|id>       continue one — replays a short context",
            "  /rm <n|id>         delete one",
            "  /export [file]     current conversation as markdown (default: <slug>.md)",
            "  /img <paths…>      attach photos to the next message; /img clear reset",
            "  /exit              quit (Ctrl+D also)",
        ]
        block = "\n".join(lines)
        if self.tty:
            self._err.print(block, style=_DIM)
        else:
            print(block, file=self.err)

    def _panel_line(self, left: str, mid: str, right: str) -> None:
        """One table-ish line on stderr: dim frame, bright middle."""
        if self.tty:
            self._err.print(Text(left, style=_DIM) + Text(mid) + Text(right, style=_DIM))
        else:
            print(f"{left}{mid}{right}", file=self.err)

    def sessions_table(self, rows: list[dict]) -> None:
        if not rows:
            self.note("no conversations yet — say something first")
            return
        for i, s in enumerate(rows):
            left = f"{i + 1:>3}  {str(s.get('id', ''))[:8]}  {_ago(s.get('updated_at')):<5} "
            mid = str(s.get("title", ""))
            right = f"  · {s.get('mode', '?')} · {s.get('model', '?')}"
            self._panel_line(left, mid, right)

    def modes_table(self, modes: list[dict], current: str | None = None) -> None:
        for m in modes:
            mark = "› " if m.get("id") == current else "  "
            aliases = ",".join(m.get("aliases", []))
            left = f"{mark}{m.get('id', '?'):<16}"
            mid = f" {m.get('title', '')}"
            extra = f" — {m.get('hint', '')}" if m.get("hint") else ""
            right = (f"  [{aliases}]{extra}" if aliases else extra)
            self._panel_line(left, mid, right)

    def models_list(self, models: list[dict]) -> None:
        for m in models:
            caps = ",".join(m.get("capabilities") or [])
            mark = " 📷" if m.get("vision") else ""
            left = "  "
            mid = m.get("name", "?")
            right = f"{mark}  {caps}" if caps else mark
            self._panel_line(left, mid, right)

    def replay(self, lines: list[tuple[str, str]]) -> None:
        """Short context after /open: you-lines plain, bot and tool dim."""
        for role, text in lines:
            if self.tty:
                style = _DIM if role in ("bot", "tool") else None
                self._err.print(
                    f"{role:>5}: {text}", style=style, markup=False, highlight=False
                )
            else:
                print(f"{role:>5}: {text}", file=self.err)