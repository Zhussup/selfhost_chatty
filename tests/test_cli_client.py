"""chatty_cli.client against the real app (ASGITransport) and against canned
NDJSON (MockTransport): login/cookie replay, event protocol, error mapping,
session CRUD, the 409 busy path — reusing the existing upstream-stub patterns.
"""

import asyncio
import json
import unittest
from unittest import mock

import httpx

from backend.app import app
from backend.config import settings
from backend.routes import chat as chat_route

from chatty_cli.client import ApiError, Chatty
from chatty_cli.config import Config
from tests.base import BaseTestCase
from tests.test_chat_loop import ndjson_factory

TURN = [
    [
        {"message": {"role": "assistant", "content": "Hel"}, "done": False},
        {"message": {"role": "assistant", "content": "lo!"}, "done": False},
        {
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 11,
            "prompt_eval_cached_count": 3,
            "eval_count": 4,
            "model": "m",
        },
    ]
]


def _asgi(password=None) -> Chatty:
    cfg = Config(
        url="http://testserver",
        password=password or settings.auth_password,
        tty=False,
    )
    return Chatty(cfg, transport=httpx.ASGITransport(app=app))


def _canned(ev_lines: list[dict], status: int = 200) -> Chatty:
    """A client whose /api/chat returns a scripted NDJSON body (no server)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(
                200, json={"ok": True},
                headers={"set-cookie": "shc_auth=fake-token; Path=/"},
            )
        body = "\n".join(json.dumps(e, ensure_ascii=False) for e in ev_lines)
        return httpx.Response(
            status, content=body.encode(),
            headers={"content-type": "application/x-ndjson"},
        )

    return Chatty(Config(url="http://testserver", password="x", tty=False),
                  transport=httpx.MockTransport(handler))


class LoginTests(BaseTestCase):
    def test_login_sets_cookie_that_replays(self):
        c = _asgi()
        self.assertEqual(asyncio.run(c.sessions()), [])
        # a fresh AsyncClient is built per call — the jar must carry shc_auth
        self.assertTrue(c._cookies.get("shc_auth"))

    def test_wrong_password_raises_api_error(self):
        with self.assertRaises(ApiError) as cm:
            asyncio.run(_asgi(password="nope").sessions())
        self.assertEqual(cm.exception.status, 401)


class StreamProtocolTests(BaseTestCase):
    def test_event_order_and_summary(self):
        c = _asgi()
        kinds: list[str] = []
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(TURN)):
            summary = asyncio.run(
                c.chat({"model": "m", "content": "hi", "use_tools": False},
                       on_event=lambda ev: kinds.append(ev.get("t")))
            )
        self.assertEqual(kinds, ["meta", "delta", "delta", "usage", "done"])
        self.assertEqual(summary["reason"], "stop")
        self.assertEqual(summary["prompt"], 11)
        self.assertEqual(summary["completion"], 4)
        self.assertTrue(summary["session_id"])

    def test_error_event_raises_with_code(self):
        c = _canned([
            {"t": "meta", "session_id": "s", "message_id": "m"},
            {"t": "error", "code": "ollama_upstream", "message": "upstream exploded"},
        ])
        with self.assertRaises(ApiError) as cm:
            asyncio.run(c.chat({"model": "m", "content": "hi"}))
        self.assertEqual(cm.exception.code, "ollama_upstream")
        self.assertEqual(cm.exception.message, "upstream exploded")

    def test_unknown_event_type_passes_through_ignored(self):
        c = _canned([
            {"t": "meta", "session_id": "s", "message_id": "m"},
            {"t": "totally_future", "v": 1},
            {"t": "delta", "v": "ok"},
            {"t": "done", "reason": "stop", "prompt": 1, "completion": 2},
        ])
        seen: list[str] = []
        summary = asyncio.run(
            c.chat({"model": "m", "content": "hi"}, on_event=lambda ev: seen.append(ev["t"]))
        )
        self.assertIn("totally_future", seen)     # pass-through, not a crash
        self.assertEqual(summary["reason"], "stop")

    def test_409_body_maps_to_rate_limited(self):
        c = _canned(
            [{"t": "error", "code": "rate_limited", "message": "busy"}], status=409
        )
        with self.assertRaises(ApiError) as cm:
            asyncio.run(c.chat({"model": "m", "content": "hi"}))
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.code, "rate_limited")

    def test_409_when_both_slots_busy_real_route(self):
        """One holder is not enough: Semaphore(2).locked() needs both taken."""
        c = _asgi()

        async def busy():
            await chat_route._slot.acquire()
            await chat_route._slot.acquire()
            try:
                await c.chat({"model": "m", "content": "hi", "use_tools": False})
            finally:
                chat_route._slot.release()
                chat_route._slot.release()

        with self.assertRaises(ApiError) as cm:
            asyncio.run(busy())
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.code, "rate_limited")

    def test_422_unknown_mode(self):
        c = _asgi()
        with self.assertRaises(ApiError) as cm:
            asyncio.run(
                c.chat({"model": "m", "content": "hi", "mode": "nope", "use_tools": False})
            )
        self.assertEqual(cm.exception.status, 422)


class SessionsCrudTests(BaseTestCase):
    def test_create_patch_list_export_delete(self):
        c = _asgi()
        row = asyncio.run(c.create_session({"title": "CLI row"}))
        sid = row["id"]
        listed = asyncio.run(c.sessions())
        self.assertIn(sid, [s["id"] for s in listed])
        asyncio.run(c.patch_session(sid, {"title": "CLI row 2"}))
        md = asyncio.run(c.export_md(sid))
        self.assertIn("# CLI row 2", md)
        asyncio.run(c.delete_session(sid))
        with self.assertRaises(ApiError) as cm:
            asyncio.run(c.session(sid))
        self.assertEqual(cm.exception.status, 404)

    def test_session_returns_messages_payload(self):
        c = _asgi()
        row = asyncio.run(c.create_session({"title": "hist"}))
        data = asyncio.run(c.session(row["id"]))
        self.assertIn("session", data)
        self.assertIn("messages", data)


if __name__ == "__main__":
    unittest.main()