"""Tool-loop edge cases: 429 retry, nudged final answer, regenerate, cancel-save."""

import asyncio
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from backend.app import app
from backend.routes import chat as chat_route
from backend.schemas import ChatIn
from backend.config import settings
from tests.base import BaseTestCase, fresh_db
from tests.test_chat_loop import ndjson_factory


def login(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"password": settings.auth_password})
    assert resp.status_code == 200, resp.text


def run(client: TestClient, payload: dict):
    resp = client.post("/api/chat", json=payload)
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


class RateLimitRetryTests(BaseTestCase):
    def test_429_retries_then_succeeds(self):
        client = TestClient(app)
        login(client)
        attempts = []

        def factory(payload):
            attempts.append(payload)

            async def gen():
                if len(attempts) == 1:
                    from backend.ollama import OllamaRateLimitError
                    raise OllamaRateLimitError("429")
                yield {"message": {"role": "assistant", "content": "ok!"}, "done": False}
                yield {"done": True, "done_reason": "stop", "prompt_eval_count": 5, "eval_count": 3}

            return gen()

        with mock.patch.object(chat_route, "stream_chat", factory):
            events = run(client, {"model": "m", "content": "hi", "use_tools": False})
        kinds = [e["t"] for e in events]
        self.assertEqual(kinds, ["meta", "ping", "delta", "usage", "done"])
        self.assertEqual(len(attempts), 2)
        done = events[-1]
        self.assertEqual(done["prompt"], 5)
        self.assertEqual(done["completion"], 3)


class NudgedBudgetTests(BaseTestCase):
    TOOL_CALL_CHUNK = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "memory_list", "arguments": {}}}],
        },
        "done": False,
    }

    def test_budget_exhaustion_forces_answer(self):
        client = TestClient(app)
        login(client)
        done_chunk = {"done": True, "done_reason": "tool_calls", "prompt_eval_count": 10, "eval_count": 2}
        turns = [[self.TOOL_CALL_CHUNK, done_chunk] for _ in range(1, settings.tool_max_iter)]
        turns.append([  # iteration == max_iter -> nudged call without tools
            {"message": {"role": "assistant", "content": "Here is the answer."}, "done": False},
            {"done": True, "done_reason": "stop", "prompt_eval_count": 99, "eval_count": 7},
        ])
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(turns)):
            events = run(client, {"model": "m", "content": "loop me", "use_tools": True})
        done = events[-1]
        self.assertEqual(done["t"], "done")
        self.assertEqual(done["reason"], "tool_budget")   # nudged answer marks the exhausted budget
        self.assertEqual(done["prompt"], (settings.tool_max_iter - 1) * 10 + 99)
        self.assertEqual(done["tool_calls"], settings.tool_max_iter - 1)
        self.assertTrue(any(e["t"] == "delta" and "Here is the answer" in e["v"] for e in events))
        # nudged answer is persisted as the final assistant row
        msgs = chat_route.db.q("SELECT content FROM messages WHERE role='assistant' ORDER BY created_at")
        self.assertEqual(msgs[-1]["content"], "Here is the answer.")

    def test_nudged_call_has_no_tools(self):
        client = TestClient(app)
        login(client)
        seen_payloads = []

        def factory(payload):
            seen_payloads.append(payload)

            async def gen():
                if len(seen_payloads) == 1:
                    yield {"message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "calc", "arguments": {"expr": "1+1"}}}],
                    }, "done": False}
                    yield {"done": True, "prompt_eval_count": 1, "eval_count": 1}
                else:
                    yield {"message": {"content": "done"}, "done": False}
                    yield {"done": True, "done_reason": "stop", "prompt_eval_count": 2, "eval_count": 2}

            return gen()

        # budget of 2: iteration 1 = tool call, iteration 2 = nudged answer
        with mock.patch.object(settings, "tool_max_iter", 2), \
                mock.patch.object(chat_route, "stream_chat", factory):
            events = run(client, {"model": "m", "content": "go", "use_tools": True})
        self.assertEqual(events[-1]["t"], "done")
        self.assertEqual(events[-1]["reason"], "tool_budget")
        self.assertEqual(len(seen_payloads), 2)
        self.assertIn("tools", seen_payloads[0])
        self.assertNotIn("tools", seen_payloads[1])
        self.assertIn("Tool budget reached", seen_payloads[1]["messages"][-1]["content"])
        self.assertEqual(seen_payloads[1]["messages"][1]["content"], "go")  # history intact, nudge appended


class RegenerateTests(BaseTestCase):
    def test_regenerate_replaces_last_answer(self):
        client = TestClient(app)
        login(client)
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory([[
            {"message": {"role": "assistant", "content": "first answer"}, "done": False},
            {"done": True, "done_reason": "stop", "prompt_eval_count": 4, "eval_count": 2},
        ]])):
            run(client, {"model": "m", "content": "hi", "use_tools": False})
        sid = chat_route.db.q("SELECT id FROM sessions")[0]["id"]
        msgs = chat_route.db.q("SELECT role, content FROM messages WHERE session_id=? ORDER BY sort", (sid,))
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])

        with mock.patch.object(chat_route, "stream_chat", ndjson_factory([[
            {"message": {"role": "assistant", "content": "second answer"}, "done": False},
            {"done": True, "done_reason": "stop", "prompt_eval_count": 6, "eval_count": 2},
        ]])):
            events = run(client, {"session_id": sid, "model": "m", "content": "ignored",
                                  "use_tools": False, "regenerate": True})
        self.assertEqual(events[-1]["t"], "done")
        msgs = chat_route.db.q("SELECT role, content FROM messages WHERE session_id=? ORDER BY sort", (sid,))
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])   # old pair replaced
        self.assertEqual(msgs[1]["content"], "second answer")                # new answer, no duplicate question
        ok_rows = chat_route.db.q("SELECT COUNT(*) AS n FROM requests WHERE status='ok'")[0]["n"]
        self.assertEqual(ok_rows, 2)

    def test_quote_is_stored_and_survives_regenerate(self):
        client = TestClient(app)
        login(client)
        seen = []

        def factory(payload):
            seen.append(payload)

            async def gen():
                yield {"message": {"role": "assistant", "content": "ok"}, "done": False}
                yield {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}

            return gen()

        def user_quote(sid):
            return chat_route.db.q(
                "SELECT quote FROM messages WHERE role='user' AND session_id=?", (sid,)
            )[0]["quote"]

        with mock.patch.object(chat_route, "stream_chat", factory):
            run(client, {"model": "m", "content": "explain", "quote": "check this", "use_tools": False})
        sid = chat_route.db.q("SELECT id FROM sessions")[0]["id"]
        self.assertEqual(user_quote(sid), "check this")
        # the model sees the fragment as a blockquote ahead of the reply
        self.assertTrue(seen[0]["messages"][1]["content"].startswith("> check this\n\n"))

        # regenerate ignores the request's quote: no row is written, so the stored
        # user row keeps its own fragment and the rebuilt prompt is unchanged
        with mock.patch.object(chat_route, "stream_chat", factory):
            run(client, {"session_id": sid, "model": "m", "content": "ignored",
                         "quote": "should be ignored", "use_tools": False, "regenerate": True})
        self.assertEqual(user_quote(sid), "check this")
        self.assertTrue(seen[1]["messages"][1]["content"].startswith("> check this\n\n"))


class CancelSaveTests(unittest.TestCase):
    """Disconnect mid-stream: partial answer persists; no token ledger row."""

    def setUp(self):
        fresh_db()

    def test_partial_content_saved_on_cancel(self):
        release = asyncio.Event()

        def slow_stream(payload):
            async def gen():
                for w in ("word1 ", "word2 ", "word3 "):
                    yield {"message": {"role": "assistant", "content": w}, "done": False}
                await release.wait()   # hang: the model is still "generating"
            return gen()

        async def drive():
            got = []

            async def consume():
                try:
                    with mock.patch.object(chat_route, "stream_chat", slow_stream):
                        async for ev in chat_route._run_turn(_body("cancel me")):
                            got.append(json.loads(ev))
                except asyncio.CancelledError:
                    pass  # swallow at the consumer like an aborted fetch

            consumer = asyncio.create_task(consume())
            await asyncio.sleep(0.2)          # let the deltas flow
            consumer.cancel()                 # client disconnect
            await consumer
            await asyncio.sleep(0.05)         # let the except-handlers finish
            release.set()                     # unwind the hanging stream
            return got

        events = asyncio.run(drive())
        deltas = [e["v"] for e in events if e.get("t") == "delta"]
        self.assertEqual("".join(deltas), "word1 word2 word3 ")
        # partial answer is saved
        msgs = chat_route.db.q("SELECT content FROM messages WHERE role='assistant'")
        saved = "".join(m["content"] for m in msgs)
        self.assertIn("word1", saved)
        # no ok requests row: real tokens only for completed turns
        self.assertEqual(len(chat_route.db.q("SELECT * FROM requests")), 0)


def _body(content="hi", **kw):
    return ChatIn(model="m", content=content, **kw)


if __name__ == "__main__":
    unittest.main()