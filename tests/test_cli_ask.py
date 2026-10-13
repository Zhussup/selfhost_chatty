"""The one-shot `ask` path through main(): argv/stdin source, exit codes,
image attach, error events, sessions/export views — the real app in-process.

Every ask passes --model explicitly: without it the CLI would resolve through
GET /api/models, whose upstream HTTP must never leak into the test suite.
"""

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from backend.app import app
from backend.config import settings
from backend.routes import chat as chat_route
from tests.base import BaseTestCase
from tests.test_images_api import PNG_B64, stream_factory, vision

from chatty_cli import __main__ as cli

ENV = {
    "CHATTY_URL": "http://testserver",
    # the client performs a real login, so this must be the real test password
    "CHATTY_PASSWORD": settings.auth_password,
}

TURN_ONE = [[
    {"message": {"role": "assistant", "content": "Hello!"}, "done": False},
    {"done": True, "done_reason": "stop", "prompt_eval_count": 2,
     "prompt_eval_cached_count": 0, "eval_count": 2, "model": "m"},
]]


def _run(argv, stdin_text=None):
    out, err = io.StringIO(), io.StringIO()
    transport = httpx.ASGITransport(app=app)
    patches = [
        mock.patch.dict(os.environ, dict(ENV), clear=True),
        mock.patch("sys.stdin", new=io.StringIO(stdin_text or "")),
    ]
    for p in patches:
        p.start()
    try:
        code = cli.main(argv, transport=transport, out=out, err=err)
    finally:
        for p in reversed(patches):
            p.stop()
    return code, out.getvalue(), err.getvalue()


class AskTests(BaseTestCase):
    def test_done_returns_zero_stdout_is_answer_only(self):
        with mock.patch.object(chat_route, "stream_chat", stream_factory(TURN_ONE)):
            code, out_v, err_v = _run(["ask", "hi", "--model", "m"])
        self.assertEqual(code, 0)
        self.assertEqual(out_v, "Hello!")            # nothing else on stdout
        self.assertIn("done: stop", err_v)           # footer lives on stderr
        self.assertIn("session ", err_v)

    def test_stdin_pipe_becomes_prompt(self):
        seen: list[dict] = []
        with mock.patch.object(chat_route, "stream_chat", stream_factory(TURN_ONE, seen)):
            code, out_v, _ = _run(["ask", "--model", "m"], stdin_text="explain me\n")
        self.assertEqual(code, 0)
        # seen captures the upstream payload, whose last message is the user's
        self.assertEqual(seen[0]["messages"][-1]["content"], "explain me")
        self.assertEqual(out_v, "Hello!")

    def test_422_unknown_mode_is_exit_one(self):
        code, out_v, err_v = _run(["ask", "hi", "--model", "m", "-m", "nope"])
        self.assertEqual(code, 1)
        self.assertEqual(out_v, "")
        self.assertIn("error:", err_v)

    def test_error_event_returns_one(self):
        # the probe says the model cannot see → an in-stream error event arrives;
        # main() maps it to exit 1 and stdout stays empty
        png = Path(tempfile.mkdtemp()) / "pixel.png"
        png.write_bytes(base64.b64decode(PNG_B64))
        with vision(False):
            code, out_v, err_v = _run(["ask", "look", "--model", "m", "--img", str(png)])
        self.assertEqual(code, 1)
        self.assertEqual(out_v, "")
        self.assertIn("vision_unsupported", err_v)

    def test_img_reads_files_base64_and_sends_name(self):
        seen: list[dict] = []
        png = Path(tempfile.mkdtemp()) / "pixel.png"
        png.write_bytes(base64.b64decode(PNG_B64))
        with vision(True), mock.patch.object(
            chat_route, "stream_chat", stream_factory(TURN_ONE, seen)
        ):
            code, _, _ = _run(["ask", "look", "--model", "m", "--img", str(png)])
        self.assertEqual(code, 0)
        # the raw bytes ride along into the upstream messages, b64-encoded
        self.assertIn(PNG_B64, json.dumps(seen[0]))

    def test_no_input_is_a_friendly_config_error(self):
        code, out_v, err_v = _run(["ask"])
        self.assertEqual(code, 2)
        self.assertEqual(out_v, "")
        self.assertIn("nothing to send", err_v)

    def test_interrupt_returns_130(self):
        class _Interrupting:
            def __init__(self, cfg, transport=None):
                pass

            async def resolve_model(self, flag=None):
                return "m"

            async def chat(self, payload, on_event=None):
                raise KeyboardInterrupt

        with mock.patch.object(cli, "Chatty", _Interrupting):
            with mock.patch.dict(os.environ, dict(ENV), clear=True):
                code = cli.main(["ask", "hi"], out=io.StringIO(), err=io.StringIO())
        self.assertEqual(code, 130)


class SessionsAndViewTests(BaseTestCase):
    def _turn(self):
        with mock.patch.object(chat_route, "stream_chat", stream_factory(TURN_ONE)):
            code, _, _ = _run(["ask", "make a session", "--model", "m"])
        self.assertEqual(code, 0)

    def test_sessions_lists_and_export_prints_by_number(self):
        self._turn()
        _, _, err_v = _run(["sessions"])     # listings are status → stderr
        self.assertIn("  1  ", err_v)
        self.assertIn("make a session", err_v)
        _, out_v, _ = _run(["export", "1"])
        self.assertIn("# make a session", out_v)

    def test_export_to_a_file(self):
        self._turn()
        dest = Path(tempfile.mkdtemp()) / "out.md"
        code, _, _ = _run(["export", "1", str(dest)])
        self.assertEqual(code, 0)
        self.assertIn("# make a session", dest.read_text(encoding="utf-8"))

    def test_export_unknown_id_is_exit_one(self):
        code, _, err_v = _run(["export", "no-such-id"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err_v)


if __name__ == "__main__":
    unittest.main()