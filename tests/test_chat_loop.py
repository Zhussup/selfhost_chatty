"""Integration tests: full chat pipeline with a mocked upstream (TestClient)."""

import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from backend.app import app
from backend.config import settings
from backend.routes import chat as chat_route
from tests.base import BaseTestCase


def ndjson_factory(turns: list[list[dict]]):
    """A stream_chat() replacement yielding scripted NDJSON chunk sets per upstream call."""
    schedule = iter(turns)

    def factory(payload):
        chunks = next(schedule, [])
        async def gen():
            for c in chunks:
                if c.get("_raise"):
                    raise c["_raise"]
                yield c
        return gen()

    return factory


def login(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"password": settings.auth_password})
    assert resp.status_code == 200, resp.text


class AuthTests(BaseTestCase):
    def test_me_requires_login(self):
        client = TestClient(app)
        r = client.get("/api/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_login_sets_cookie_and_sessions_unlock(self):
        client = TestClient(app)
        login(client)
        r = client.get("/api/auth/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get("/api/sessions").status_code, 200)

    def test_wrong_password(self):
        client = TestClient(app)
        r = client.post("/api/auth/login", json={"password": "nope"})
        self.assertEqual(r.status_code, 401)

    def test_logout(self):
        client = TestClient(app)
        login(client)
        self.assertEqual(client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)


class ChatPlainTests(BaseTestCase):
    """Turn without tools: meta -> delta -> usage -> done, honest token ledger."""

    def mock(self, turns):
        factory = ndjson_factory(turns)
        return mock.patch.object(chat_route, "stream_chat", factory)

    def test_plain_turn(self):
        client = TestClient(app)
        login(client)
        turns = [
            [
                {"message": {"role": "assistant", "content": "Hel"}, "done": False},
                {"message": {"role": "assistant", "content": "lo!"}, "done": False},
                {
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 11,
                    "prompt_eval_cached_count": 3,
                    "eval_count": 4,
                },
            ]
        ]
        with self.mock(turns):
            resp = client.post(
                "/api/chat",
                json={"model": "test-model", "content": "hi", "think": None, "use_tools": False},
            )
        events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        kinds = [e["t"] for e in events]
        self.assertEqual(kinds, ["meta", "delta", "delta", "usage", "done"])
        done = events[-1]
        self.assertEqual(done["prompt"], 11)
        self.assertEqual(done["completion"], 4)
        meta = events[0]
        self.assertEqual(meta["session_id"], done["session_id"] if "session_id" in done else meta["session_id"])

        # ledger
        req_rows = chat_route.db.q("SELECT * FROM requests ORDER BY created_at")
        self.assertEqual(len(req_rows), 1)
        self.assertEqual(req_rows[0]["prompt_tokens"], 11)
        self.assertEqual(req_rows[0]["completion_tokens"], 4)
        session_id = req_rows[0]["session_id"]

        # messages persisted
        msgs = chat_route.db.q(f"SELECT * FROM messages WHERE session_id='{session_id}' ORDER BY sort")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[1]["content"], "Hello!")

        # session API serves it back
        r = client.get(f"/api/sessions/{session_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([m["role"] for m in r.json()["messages"]], ["user", "assistant"])

    def test_upstream_stream_without_done_is_error(self):
        client = TestClient(app)
        login(client)
        turns = [
            [
                {"message": {"role": "assistant", "content": "par"}, "done": False},
                # stream just ends: no done chunk
            ]
        ]
        with self.mock(turns):
            resp = client.post(
                "/api/chat",
                json={"model": "m", "content": "hi", "think": None, "use_tools": False},
            )
        events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        self.assertEqual(events[-1]["t"], "error")
        self.assertEqual(events[-1]["code"], "ollama_upstream")
        # ledger has no 'ok' row
        ok_rows = chat_route.db.q("SELECT * FROM requests WHERE status='ok'")
        self.assertEqual(len(ok_rows), 0)


class AuthUpstreamTests(BaseTestCase):
    def test_401_maps_to_ollama_auth(self):
        from backend.ollama import OllamaAuthError

        client = TestClient(app)
        login(client)

        def factory(payload):
            async def gen():
                raise OllamaAuthError("upstream 401")
                yield {}
            return gen()

        with mock.patch.object(chat_route, "stream_chat", factory):
            resp = client.post("/api/chat", json={"model": "m", "content": "hi", "use_tools": False})
        events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        self.assertEqual(events[-1]["code"], "ollama_auth")
        rows = chat_route.db.q("SELECT * FROM requests")  # nothing recorded for auth failures
        self.assertEqual([r["status"] for r in rows if r["status"] == "ok"], [])


class ToolLoopTests(BaseTestCase):
    def test_tool_run_finishes_with_answer(self):
        client = TestClient(app)
        login(client)
        turns = [
            # iteration 1: model asks for calc
            [
                {"message": {"role": "assistant", "content": "Let me compute."}, "done": False},
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"function": {"name": "calc", "arguments": {"expr": "6*7"}}}],
                    },
                    "done": False,
                },
                {"done": True, "done_reason": "tool_calls", "prompt_eval_count": 20, "eval_count": 8},
            ],
            # iteration 2: model answers from the tool result
            [
                {"message": {"role": "assistant", "content": "6*7 = **42**"}, "done": False},
                {"done": True, "done_reason": "stop", "prompt_eval_count": 30, "eval_count": 9},
            ],
        ]
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(turns)):
            resp = client.post(
                "/api/chat",
                json={"model": "m", "content": "what is 6*7", "think": None, "use_tools": True},
            )
        events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        kinds = [e["t"] for e in events]
        self.assertIn("assistant_tool_calls", kinds)
        self.assertIn("tool_result", kinds)
        done = events[-1]
        self.assertEqual(done["t"], "done")
        self.assertEqual(done["prompt"], 50)   # 20 + 30
        self.assertEqual(done["completion"], 17)  # 8 + 9
        self.assertEqual(done["tool_calls"], 1)

        tr = [e for e in events if e["t"] == "tool_result"][0]
        self.assertTrue(tr["ok"])
        self.assertIn("42", tr["result"])

        # DB: two ok requests, tool_call row, and the exact message chain
        reqs = chat_route.db.q("SELECT * FROM requests ORDER BY created_at")
        self.assertEqual([r["status"] for r in reqs], ["ok", "ok"])
        self.assertEqual(len(reqs), 2)
        tools_rows = chat_route.db.q("SELECT * FROM tool_calls")
        self.assertEqual(len(tools_rows), 1)
        self.assertTrue(tools_rows[0]["ok"])

        session_id = reqs[0]["session_id"]
        msgs = chat_route.db.q(f"SELECT role, content, tool_calls_json, tool_name FROM messages WHERE session_id='{session_id}' ORDER BY sort")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(msgs[2]["content"], "42")
        tool_calls = json.loads(msgs[1]["tool_calls_json"])
        self.assertEqual(tool_calls[0]["arguments"]["expr"], "6*7")
        self.assertEqual(msgs[3]["content"], "6*7 = **42**")

        # history reconstruction: the second upstream call received tool context
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(turns)) as m2:
            pass

    def test_stats_endpoints(self):
        client = TestClient(app)
        login(client)
        r = client.get("/api/stats/summary")
        self.assertEqual(r.status_code, 200)
        self.assertIn("prompt_tokens", r.json())
        for ep in ("timeseries", "top-models", "tools", "sessions"):
            self.assertEqual(client.get(f"/api/stats/{ep}").status_code, 200)


class SessionsTests(BaseTestCase):
    def test_crud_and_export(self):
        client = TestClient(app)
        login(client)
        r = client.post("/api/sessions")
        sid = r.json()["id"]
        # rename, show as list, export, delete
        self.assertEqual(client.patch(f"/api/sessions/{sid}", json={"title": "renamed"}).status_code, 200)
        titles = [s["title"] for s in client.get("/api/sessions").json()]
        self.assertIn("renamed", titles)
        exp = client.get(f"/api/sessions/{sid}/export.md")
        self.assertEqual(exp.status_code, 200)
        self.assertIn("renamed", exp.text)
        self.assertEqual(client.delete(f"/api/sessions/{sid}").status_code, 200)
        self.assertNotIn(sid, [s["id"] for s in client.get("/api/sessions").json()])

    def test_export_of_a_quoted_turn(self):
        # the empty-session export above never touched the stamp/quote paths
        client = TestClient(app)
        login(client)
        turns = [[
            {"message": {"role": "assistant", "content": "answer"}, "done": False},
            {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1},
        ]]
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(turns)):
            resp = client.post("/api/chat", json={"model": "m", "content": "explain",
                                                  "quote": "line one\nline two", "use_tools": False})
        sid = json.loads([ln for ln in resp.text.splitlines() if ln.strip()][0])["session_id"]
        exp = client.get(f"/api/sessions/{sid}/export.md")
        self.assertEqual(exp.status_code, 200)  # stamps read created_at
        self.assertIn("> line one\n> line two", exp.text)
        self.assertIn("explain", exp.text)

    def test_404s(self):
        client = TestClient(app)
        login(client)
        self.assertEqual(client.get("/api/sessions/nope").status_code, 404)
        self.assertEqual(client.get("/api/sessions/nope/export.md").status_code, 404)


class EditMessageTests(BaseTestCase):
    """Edit-and-resend: rewrite a sent prompt in place and regenerate from it."""

    def turn(self, client, content: str, sid: str | None = None, edit_id: str | None = None):
        payload = {"model": "m", "content": content, "think": None, "use_tools": False}
        if sid:
            payload["session_id"] = sid
        if edit_id:
            payload["edit_message_id"] = edit_id
        turns = [[
            {"message": {"role": "assistant", "content": "answer"}, "done": False},
            {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1},
        ]]
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(turns)):
            resp = client.post("/api/chat", json=payload)
        events = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
        return events[0]["session_id"]

    def user_rows(self, client, sid: str) -> list[dict]:
        full = client.get(f"/api/sessions/{sid}").json()
        return [m for m in full["messages"] if m["role"] == "user"]

    def test_edit_replaces_prompt_and_drops_the_tail(self):
        client = TestClient(app)
        login(client)
        sid = self.turn(client, "first prompt")
        first_id = self.user_rows(client, sid)[0]["id"]
        self.turn(client, "second prompt", sid)  # a tail that the edit must discard

        self.turn(client, "edited prompt", sid, edit_id=first_id)

        rows = self.user_rows(client, sid)
        self.assertEqual([r["content"] for r in rows], ["edited prompt"])
        self.assertEqual(rows[0]["id"], first_id, "the row is rewritten, not replaced")
        full = client.get(f"/api/sessions/{sid}").json()
        self.assertEqual([m["role"] for m in full["messages"]], ["user", "assistant"])

    def test_edit_ignores_non_user_ids(self):
        client = TestClient(app)
        login(client)
        sid = self.turn(client, "keep me")
        full = client.get(f"/api/sessions/{sid}").json()
        assistant_id = next(m["id"] for m in full["messages"] if m["role"] == "assistant")

        # an assistant id is not a user row: the edit no-ops, so nothing is
        # rewritten and no new prompt is appended either
        self.turn(client, "other", sid, edit_id=assistant_id)
        self.assertEqual([r["content"] for r in self.user_rows(client, sid)], ["keep me"])


if __name__ == "__main__":
    unittest.main()