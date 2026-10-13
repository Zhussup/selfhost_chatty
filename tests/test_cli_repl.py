"""REPL dispatch (against mocks) plus one real streaming turn (ASGITransport).

Mirrors the SPA's slash semantics: alias resolution, warn-confirm, switch-and-
send, adoption of the persona's think/tools, and the loud unknown-command rule.
"""

import asyncio
import io
import unittest
from unittest import mock

from backend.app import app
from backend.config import settings
from backend.routes import chat as chat_route

from chatty_cli.client import Chatty
from chatty_cli.config import Config
from chatty_cli.repl import Repl, _SLASH
from chatty_cli.render import Renderer
from tests.base import BaseTestCase
from tests.test_chat_loop import ndjson_factory

MODES = [
    {"id": "assistant", "title": "General help", "hint": "get things done",
     "tools": "auto", "think": None, "aliases": [], "warn": ""},
    {"id": "fact-check", "title": "Fact-check", "hint": "verdicts on claims",
     "tools": "on", "think": "high", "aliases": ["fact", "check"],
     "warn": "a claim-heavy message can spend the whole tool budget"},
    {"id": "text-only", "title": "Text only", "hint": "no lookups",
     "tools": "off", "think": "low", "aliases": ["text"], "warn": ""},
]


class _Feed:
    """input() replacement: a queue of lines, then EOF."""

    def __init__(self, lines: list[str]):
        self._it = iter(lines)
        self.log: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        try:
            line = next(self._it)
        except StopIteration:
            raise EOFError
        self.log.append(line)
        return line


def _repl(lines: list[str], client: mock.Mock) -> tuple[Repl, Renderer, _Feed]:
    out, err = io.StringIO(), io.StringIO()
    r = Renderer(tty=False, out=out, err=err)
    feed = _Feed(lines)
    repl = Repl(client, r, input_fn=feed)
    return repl, r, feed


def _client(**overrides) -> mock.Mock:
    c = mock.Mock()
    c.modes = mock.AsyncMock(return_value={"modes": MODES, "default": "assistant"})
    c.resolve_model = mock.AsyncMock(return_value="gpt-oss:120b")
    c.models = mock.AsyncMock(return_value={"models": [
        {"name": "m1", "vision": False, "capabilities": ["completion"]},
        {"name": "m2", "vision": True, "capabilities": ["completion", "vision"]},
    ]})
    c.models.return_value = c.models.return_value
    for name, value in overrides.items():
        setattr(c, name, value)
    return c


class SlashGrammarTests(unittest.TestCase):
    def test_regex_matches_like_parseSlash(self):
        self.assertIsNone(_SLASH.match("/2"))
        self.assertIsNone(_SLASH.match("/usr/bin/env"))
        self.assertEqual(_SLASH.match("/fact").groups(), ("fact", None))
        self.assertEqual(_SLASH.match("/fact is it true").groups(), ("fact", "is it true"))
        self.assertEqual(_SLASH.match("/MODE").groups(), ("MODE", None))


class DispatchTests(unittest.TestCase):
    """handle() against mocked API methods: state changes, nothing is sent."""

    def test_unknown_slash_sends_nothing(self):
        repl, r, _ = _repl([], _client())
        asyncio.run(repl._startup())
        verdict = asyncio.run(repl.handle("/boogey"))
        self.assertIs(verdict, False)
        self.assertIn("unknown command: /boogey", r.err.getvalue())
        repl.c.chat.assert_not_called()

    def test_plain_and_path_like_lines_pass_through(self):
        repl, _, _ = _repl([], _client())
        asyncio.run(repl._startup())
        self.assertEqual(asyncio.run(repl.handle("hello")), "hello")
        self.assertEqual(asyncio.run(repl.handle("/usr/bin/env")), "/usr/bin/env")

    def test_mode_alias_switch_adopts_think_and_tools(self):
        repl, _, feed = _repl([], _client())
        asyncio.run(repl._startup())
        feed._it = iter(["y"])                       # fact-check warns before switching
        self.assertIs(asyncio.run(repl.handle("/fact")), False)
        self.assertEqual(repl.mode, "fact-check")
        self.assertEqual(repl.think, "high")
        self.assertTrue(repl.use_tools)              # tools policy "on"

    def test_switch_off_mode_turns_tools_off(self):
        repl, _, _ = _repl([], _client())
        asyncio.run(repl._startup())
        asyncio.run(repl.handle("/text"))
        self.assertEqual(repl.mode, "text-only")
        self.assertFalse(repl.use_tools)
        self.assertEqual(repl.think, "low")

    def test_warn_confirm_declined_keeps_mode(self):
        repl, r, feed = _repl([], _client())
        asyncio.run(repl._startup())
        feed._it = iter(["n"])
        verdict = asyncio.run(repl.handle("/fact"))
        self.assertIs(verdict, False)
        self.assertEqual(repl.mode, "assistant")
        self.assertIn("tool budget", r.err.getvalue())

    def test_warn_confirm_accepted_switches(self):
        repl, _, feed = _repl([], _client())
        asyncio.run(repl._startup())
        feed._it = iter(["y"])
        self.assertIs(asyncio.run(repl.handle("/fact")), False)
        self.assertEqual(repl.mode, "fact-check")

    def test_switch_with_text_sends_one_turn(self):
        repl, _, feed = _repl([], _client())
        asyncio.run(repl._startup())
        feed._it = iter(["y"])
        text = asyncio.run(repl.handle("/fact is it true?"))
        self.assertEqual(text, "is it true?")
        self.assertEqual(repl.mode, "fact-check")

    def test_case_insensitive_aliases(self):
        repl, _, feed = _repl([], _client())
        asyncio.run(repl._startup())
        feed._it = iter(["y"])
        self.assertIs(asyncio.run(repl.handle("/FACT")), False)
        self.assertEqual(repl.mode, "fact-check")

    def test_think_and_tools_commands(self):
        repl, r, _ = _repl([], _client())
        asyncio.run(repl._startup())
        self.assertIs(asyncio.run(repl.handle("/think off")), False)
        self.assertIsNone(repl.think)
        self.assertIs(asyncio.run(repl.handle("/think bogus")), False)
        self.assertIn("off, low, medium, high", r.err.getvalue())
        asyncio.run(repl.handle("/think low"))
        self.assertEqual(repl.think, "low")
        asyncio.run(repl.handle("/tools off"))
        self.assertFalse(repl.use_tools)

    def test_model_lists_and_sets(self):
        repl, r, _ = _repl([], _client())
        asyncio.run(repl._startup())
        asyncio.run(repl.handle("/model"))
        self.assertIn("m1", r.err.getvalue())
        self.assertIn("vision", r.err.getvalue())
        asyncio.run(repl.handle("/model m2"))
        self.assertEqual(repl.model, "m2")
        asyncio.run(repl.handle("/model nope"))
        self.assertIn("unknown model: nope", r.err.getvalue())
        self.assertEqual(repl.model, "m2")

    def test_new_with_and_without_title(self):
        c = _client()
        c.create_session = mock.AsyncMock(return_value={"id": "abc123"})
        repl, r, _ = _repl([], c)
        asyncio.run(repl._startup())
        asyncio.run(repl.handle("/new Fresh"))
        self.assertEqual(repl.sid, "abc123")
        asyncio.run(repl.handle("/new"))
        self.assertIsNone(repl.sid)

    def test_sessions_numbering_then_open_and_rm(self):
        c = _client()
        c.sessions = mock.AsyncMock(return_value=[
            {"id": "s1" + "0" * 30, "title": "First", "mode": "assistant",
             "model": "m1", "updated_at": 0},
        ])
        c.session = mock.AsyncMock(return_value={
            "session": {"id": "s1" + "0" * 30, "title": "First", "model": "m1",
                        "mode": "text-only"},
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ho", "model": "m1"},
            ],
        })
        c.delete_session = mock.AsyncMock(return_value=None)
        repl, r, feed = _repl([], c)
        asyncio.run(repl._startup())
        asyncio.run(repl.handle("/sessions"))
        self.assertEqual(repl.cache[0]["id"], "s1" + "0" * 30)
        asyncio.run(repl.handle("/open 1"))
        self.assertEqual(repl.sid, "s1" + "0" * 30)
        self.assertEqual(repl.model, "m1")
        self.assertEqual(repl.mode, "text-only")      # the row's persona was adopted
        self.assertIn("you: hi", r.err.getvalue())
        self.assertIn("bot:", r.err.getvalue())
        feed._it = iter(["y"])
        asyncio.run(repl.handle("/rm 1"))
        c.delete_session.assert_awaited_once()
        self.assertIsNone(repl.sid)                   # deleting the open session resets

    def test_img_queue_and_clear(self):
        repl, r, _ = _repl([], _client())
        asyncio.run(repl._startup())
        asyncio.run(repl.handle("/img /tmp/a.png /tmp/b.jpg"))
        self.assertEqual(repl.images, ["/tmp/a.png", "/tmp/b.jpg"])
        asyncio.run(repl.handle("/img clear"))
        self.assertEqual(repl.images, [])

    def test_exit_and_help(self):
        repl, r, _ = _repl([], _client())
        asyncio.run(repl._startup())
        self.assertIs(asyncio.run(repl.handle("/help")), False)
        self.assertIn("/export", r.err.getvalue())
        self.assertIs(asyncio.run(repl.handle("/exit")), True)
        self.assertIs(asyncio.run(repl.handle("/quit")), True)

    def test_patch_fires_when_session_open(self):
        c = _client()
        c.patch_session = mock.AsyncMock(return_value=None)
        repl, _, feed = _repl([], c)
        asyncio.run(repl._startup())
        repl.sid = "sess1"
        feed._it = iter(["y"])                       # /fact warns; confirm it
        asyncio.run(repl.handle("/fact"))
        c.patch_session.assert_awaited_once_with("sess1", {"mode": "fact-check"})


class RealTurnTests(BaseTestCase):
    """One live streaming turn through run(), upstream fully scripted."""

    TURN = [[
        {"message": {"role": "assistant", "content": "Hi there"}, "done": False},
        {"done": True, "done_reason": "stop", "prompt_eval_count": 5,
         "prompt_eval_cached_count": 0, "eval_count": 2, "model": "m"},
    ]]

    def test_turn_streams_and_session_is_kept(self):
        import httpx

        cfg = Config(url="http://testserver", password=settings.auth_password, tty=False)
        c = Chatty(cfg, transport=httpx.ASGITransport(app=app))
        repl, r, feed = _repl(["/code hello", "/exit"], c)
        # /api/models would call the real upstream here — pin the model instead
        c.resolve_model = mock.AsyncMock(return_value="m")
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(self.TURN)):
            code = asyncio.run(repl.run())
        self.assertEqual(code, 0)
        self.assertTrue(repl.sid)                     # the session survived the turn
        self.assertIn("Hi there", r.out.getvalue())   # the answer is on stdout
        self.assertIn("stop ·", r.err.getvalue())     # and the footer on stderr
        # persona adoption: programmer forces auto tools + high think
        self.assertEqual(repl.mode, "programmer")
        self.assertEqual(repl.think, "high")


if __name__ == "__main__":
    unittest.main()