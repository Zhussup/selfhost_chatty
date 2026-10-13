"""Renderer output policy: stdout = raw deltas only; everything else to stderr.

The piped form must stay byte-exact for pipes (`| md > notes.md`); the tty
form must never swallow model or server texts as rich markup. Note: with a
StringIO sink rich strips ANSI (no terminal detected), so color is asserted
only where the renderer emits manual escapes (the thinking dim).
"""

import io
import os
import unittest
from unittest import mock

from chatty_cli.render import Renderer

STREAM = [
    {"t": "meta", "session_id": "abc123def", "message_id": "m1"},
    {"t": "thinking", "v": "hmm "},
    {"t": "thinking", "v": "deep"},
    {"t": "assistant_tool_calls", "iter": 1,
     "calls": [{"id": "c0", "name": "web_search", "arguments": {"q": "x"}}]},
    {"t": "delta", "v": "a [b] *c* "},
    {"t": "delta", "v": " tail\nline2"},
    {"t": "tool_result", "id": "c0", "name": "web_search", "ok": True, "ms": 12,
     "result": "found\nthings"},
    {"t": "usage", "iter": 1, "prompt": 100, "cached": 9, "completion": 30},
    {"t": "done", "message_id": "m1", "reason": "stop", "prompt": 100,
     "completion": 30, "tool_calls": 1, "ms": 4200},
]


def _feed(tty: bool):
    out, err = io.StringIO(), io.StringIO()
    r = Renderer(tty=tty, out=out, err=err)
    for ev in STREAM:
        r.event(ev)
    return out.getvalue(), err.getvalue(), r


class PipedModeTests(unittest.TestCase):
    def test_stdout_receives_deltas_only(self):
        out_v, err_v, _ = _feed(tty=False)
        self.assertEqual(out_v, "a [b] *c*  tail\nline2")
        self.assertIn("thinking", err_v)
        self.assertIn("web_search", err_v)
        self.assertIn("done: stop", err_v)
        self.assertIn("abc123de", err_v)          # session id8 in the footer
        self.assertNotIn("100", out_v)            # usage never leaks into stdout

    def test_thinking_is_one_stderr_note(self):
        _, err_v, _ = _feed(tty=False)
        self.assertEqual(err_v.count("thinking"), 1)

    def test_provenance_free_and_plain(self):
        out_v, err_v, _ = _feed(tty=False)
        self.assertNotIn("\x1b", out_v + err_v)   # no ANSI escapes in a pipe

    def test_note_and_error_routes_to_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        r = Renderer(tty=False, out=out, err=err)
        r.note("hello")
        r.error("ollama_upstream", "boom")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("hello", err.getvalue())
        self.assertIn("boom", err.getvalue())


class TtyModeTests(unittest.TestCase):
    def test_markup_in_answer_and_messages_is_literal(self):
        out_v, err_v, _ = _feed(tty=True)
        self.assertIn("a [b] *c*", out_v)         # rich must not eat it
        self.assertEqual(out_v, "a [b] *c*  tail\nline2")
        out, err = io.StringIO(), io.StringIO()
        r = Renderer(tty=True, out=out, err=err)
        r.error("http", "[section] vanished?")
        self.assertIn("[section] vanished?", err.getvalue())

    def test_thinking_streams_with_manual_dim_ansi(self):
        out, err = io.StringIO(), io.StringIO()
        r = Renderer(tty=True, out=out, err=err)
        r.thinking("hm")
        self.assertIn("\x1b[2m", err.getvalue())  # manual escape, not rich
        r.delta("answer")
        self.assertIn("hm", err.getvalue())
        r.delta("…")
        # the dim run closed before the answer arrived
        self.assertIn("\x1b[22m", err.getvalue())

    def test_tool_and_footer_on_stderr(self):
        out_v, err_v, _ = _feed(tty=True)
        self.assertEqual(out_v, "a [b] *c*  tail\nline2")
        self.assertIn("⌘ web_search", err_v)
        self.assertIn("✓ web_search", err_v)
        self.assertIn("— stop", err_v)

    def test_no_color_env_kills_ansi(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            out, err = io.StringIO(), io.StringIO()
            r = Renderer(tty=True, out=out, err=err)
            self.assertFalse(r.tty)


class ReplayAndTablesTests(unittest.TestCase):
    def test_replay_marks_bot_and_tool(self):
        out, err = io.StringIO(), io.StringIO()
        r = Renderer(tty=False, out=out, err=err)
        r.replay([("you", "hi"), ("bot", "answer: hello"), ("tool", "calc ok")])
        v = err.getvalue()
        self.assertIn("  you: hi", v)
        self.assertIn("bot: answer: hello", v)
        self.assertIn("tool: calc ok", v)

    def test_sessions_table_numbering(self):
        out, err = io.StringIO(), io.StringIO()
        r = Renderer(tty=False, out=out, err=err)
        r.sessions_table([{"id": "a" * 32, "title": "First", "mode": "assistant",
                           "model": "m", "updated_at": None}])
        v = err.getvalue()
        self.assertIn("  1  ", v)
        self.assertIn("First", v)

    def test_modes_table_marks_current(self):
        out, err = io.StringIO(), io.StringIO()
        r = Renderer(tty=False, out=out, err=err)
        r.modes_table([{"id": "assistant", "title": "t", "hint": "h", "aliases": []},
                       {"id": "fact-check", "title": "f", "hint": "", "aliases": ["fact"]}],
                      current="assistant")
        v = err.getvalue()
        self.assertIn("› assistant", v)
        self.assertIn("[fact]", v)


if __name__ == "__main__":
    unittest.main()