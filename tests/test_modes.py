"""Chat modes: registry integrity, the /api/modes payload, and the DB column."""

import json
import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from backend import db
from backend.app import app
from backend.config import settings
from backend.modes import DEFAULT_MODE_ID, MODES, get_mode, soft_rules
from backend.routes import chat as chat_route
from tests.base import BaseTestCase
from tests.test_chat_loop import login, ndjson_factory


class RegistryTests(BaseTestCase):
    def test_ids_unique_and_well_formed(self):
        ids = [m.id for m in MODES.values()]
        self.assertEqual(len(ids), len(set(ids)))
        for mode_id in ids:
            self.assertRegex(mode_id, re.compile(r"^[a-z][a-z0-9-]*$"))
        self.assertIn(DEFAULT_MODE_ID, MODES)

    def test_every_mode_is_filled_in(self):
        for m in MODES.values():
            self.assertTrue(m.title.strip(), m.id)
            self.assertTrue(m.hint.strip(), m.id)
            self.assertTrue(m.icon.strip(), m.id)
            self.assertIn(m.tools, ("auto", "on", "off"), m.id)
            self.assertIn(m.think, (None, "low", "medium", "high"), m.id)
            # assistant is the bare base prompt; every other mode must say something
            if m.id != DEFAULT_MODE_ID:
                self.assertTrue(m.block.strip(), m.id)

    def test_sixteen_modes(self):
        self.assertEqual(len(MODES), 16)

    def test_get_mode_falls_back_never_raises(self):
        self.assertIs(get_mode(None), MODES[DEFAULT_MODE_ID])
        self.assertIs(get_mode("nope"), MODES[DEFAULT_MODE_ID])
        self.assertIs(get_mode(""), MODES[DEFAULT_MODE_ID])
        self.assertIs(get_mode("teacher"), MODES["teacher"])

    def test_aliases_do_not_collide_with_ids(self):
        # The UI resolves a slash token case-insensitively against id+aliases, so
        # the collision guarantee has to hold after lowercasing.
        tokens: list[str] = []
        for m in MODES.values():
            self.assertEqual(m.id, m.id.lower(), m.id)
            for alias in m.aliases:
                self.assertEqual(alias, alias.strip().lower(), f"{m.id}: {alias!r}")
            tokens += [m.id, *m.aliases]
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_only_translator_overrides_the_language_rule(self):
        overriding = [m.id for m in MODES.values() if "language" in m.overrides]
        self.assertEqual(overriding, ["translator"])
        self.assertIn("Reply in the language", " ".join(soft_rules(MODES["teacher"])))
        self.assertNotIn("Reply in the language", " ".join(soft_rules(MODES["translator"])))

    def test_tool_rule_follows_the_policy(self):
        # off: no tools paragraph at all — a mode without tools must not be told to search
        self.assertNotIn("You have tools available", " ".join(soft_rules(MODES["editor"])))
        self.assertNotIn("must use your tools", " ".join(soft_rules(MODES["editor"])))
        # on: the firmer wording
        self.assertIn("must use your tools", " ".join(soft_rules(MODES["fact-check"])))
        # auto: the original paragraph, unchanged
        self.assertIn("You have tools available", " ".join(soft_rules(MODES["assistant"])))
        self.assertIn("You have tools available", " ".join(soft_rules(None)))

    def test_fact_check_requires_tools_and_warns(self):
        fc = MODES["fact-check"]
        self.assertEqual(fc.tools, "on")
        self.assertTrue(fc.warn)
        self.assertIn("{max_iter}", fc.warn)


class ModesEndpointTests(BaseTestCase):
    def test_requires_login(self):
        self.assertEqual(TestClient(app).get("/api/modes").status_code, 401)

    def test_payload_shape(self):
        client = TestClient(app)
        login(client)
        r = client.get("/api/modes")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["default"], DEFAULT_MODE_ID)
        self.assertEqual(len(body["modes"]), 16)
        for m in body["modes"]:
            self.assertEqual(
                set(m), {"id", "title", "hint", "icon", "tools", "think", "aliases", "warn"}
            )

    def test_warning_quotes_the_live_tool_budget(self):
        client = TestClient(app)
        login(client)
        with mock.patch.object(settings, "tool_max_iter", 3):
            body = client.get("/api/modes").json()
        fc = next(m for m in body["modes"] if m["id"] == "fact-check")
        self.assertIn("3 tool iterations", fc["warn"])
        # and nobody else carries a warning
        self.assertEqual([m["id"] for m in body["modes"] if m["warn"]], ["fact-check"])


class SessionModeColumnTests(BaseTestCase):
    def test_migration_added_the_column(self):
        cols = [r["name"] for r in db.q("PRAGMA table_info(sessions)")]
        self.assertIn("mode", cols)

    def test_default_is_assistant(self):
        # a row written without the column (as older code did) still reads back
        now = db.now()
        db.qx(
            "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?,?,?,?,?)",
            ("legacy", "old chat", "m", now, now),
        )
        self.assertEqual(db.one("SELECT mode FROM sessions WHERE id=?", ("legacy",))["mode"], "assistant")


class ModeSessionTests(BaseTestCase):
    """The mode rides on the session: sent with a turn, patchable on its own."""

    def turn(self, client, content: str, sid: str | None = None, mode: str | None = None):
        payload = {"model": "m", "content": content, "think": None, "use_tools": False}
        if sid:
            payload["session_id"] = sid
        if mode:
            payload["mode"] = mode
        turns = [[
            {"message": {"role": "assistant", "content": "answer"}, "done": False},
            {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1},
        ]]
        with mock.patch.object(chat_route, "stream_chat", ndjson_factory(turns)):
            resp = client.post("/api/chat", json=payload)
        events = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
        return events[0]["session_id"]

    def test_mode_sent_with_a_turn_persists(self):
        client = TestClient(app)
        login(client)
        sid = self.turn(client, "teach me", mode="teacher")
        self.assertEqual(db.one("SELECT mode FROM sessions WHERE id=?", (sid,))["mode"], "teacher")
        self.assertEqual(client.get(f"/api/sessions/{sid}").json()["session"]["mode"], "teacher")
        listed = [s for s in client.get("/api/sessions").json() if s["id"] == sid][0]
        self.assertEqual(listed["mode"], "teacher")

    def test_a_turn_without_a_mode_keeps_the_session_mode(self):
        client = TestClient(app)
        login(client)
        sid = self.turn(client, "one", mode="teacher")
        self.turn(client, "two", sid)  # no mode field — an older client
        self.assertEqual(db.one("SELECT mode FROM sessions WHERE id=?", (sid,))["mode"], "teacher")

    def test_new_session_defaults_to_assistant(self):
        client = TestClient(app)
        login(client)
        sid = self.turn(client, "hi")
        self.assertEqual(db.one("SELECT mode FROM sessions WHERE id=?", (sid,))["mode"], "assistant")

    def test_unknown_mode_is_rejected(self):
        client = TestClient(app)
        login(client)
        r = client.post("/api/chat", json={"model": "m", "content": "hi", "mode": "wizard"})
        self.assertEqual(r.status_code, 422)

    def test_patch_mode_alone_leaves_the_title(self):
        client = TestClient(app)
        login(client)
        sid = client.post("/api/sessions", json={"title": "keep me"}).json()["id"]
        self.assertEqual(client.patch(f"/api/sessions/{sid}", json={"mode": "editor"}).status_code, 200)
        row = db.one("SELECT title, mode FROM sessions WHERE id=?", (sid,))
        self.assertEqual((row["title"], row["mode"]), ("keep me", "editor"))

    def test_patch_title_alone_leaves_the_mode(self):
        client = TestClient(app)
        login(client)
        sid = client.post("/api/sessions", json={"mode": "editor"}).json()["id"]
        client.patch(f"/api/sessions/{sid}", json={"title": "renamed"})
        row = db.one("SELECT title, mode FROM sessions WHERE id=?", (sid,))
        self.assertEqual((row["title"], row["mode"]), ("renamed", "editor"))

    def test_patch_rejects_an_unknown_mode(self):
        client = TestClient(app)
        login(client)
        sid = client.post("/api/sessions").json()["id"]
        self.assertEqual(client.patch(f"/api/sessions/{sid}", json={"mode": "wizard"}).status_code, 422)

    def test_create_session_accepts_a_mode(self):
        client = TestClient(app)
        login(client)
        sid = client.post("/api/sessions", json={"mode": "planner"}).json()["id"]
        self.assertEqual(db.one("SELECT mode FROM sessions WHERE id=?", (sid,))["mode"], "planner")

    def test_unknown_mode_in_create_falls_back(self):
        # the POST body is a raw dict, not SessionPatch: it normalises instead
        client = TestClient(app)
        login(client)
        sid = client.post("/api/sessions", json={"mode": "wizard"}).json()["id"]
        self.assertEqual(db.one("SELECT mode FROM sessions WHERE id=?", (sid,))["mode"], "assistant")


def _gen(chunks: list[dict]):
    """A stream_chat() replacement yielding one scripted chunk set."""

    async def gen():
        for c in chunks:
            yield c

    return gen()


class ToolPolicyTests(BaseTestCase):
    """The mode pins tool use on or off, over the user's own toggle."""

    def capture(self, turns: list[dict], payload: dict) -> list[dict]:
        """Run one logged-in turn and return the upstream payloads the route built."""
        seen: list[dict] = []

        def factory(up):
            seen.append(up)
            return _gen(turns)

        client = TestClient(app)
        login(client)
        with mock.patch.object(chat_route, "stream_chat", factory):
            client.post("/api/chat", json=payload)
        return seen

    def test_tools_off_mode_suppresses_them_despite_the_toggle(self):
        seen = self.capture(
            [
                {"message": {"role": "assistant", "content": "plain"}, "done": False},
                {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1},
            ],
            {"model": "m", "content": "hi", "think": None, "use_tools": True, "mode": "editor"},
        )
        self.assertNotIn("tools", seen[0])

    def test_tools_on_mode_attaches_them_despite_the_toggle(self):
        seen = self.capture(
            [
                {"message": {"role": "assistant", "content": "checked"}, "done": False},
                {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1},
            ],
            {"model": "m", "content": "hi", "think": None, "use_tools": False, "mode": "fact-check"},
        )
        self.assertIn("tools", seen[0])

    def test_auto_mode_honours_the_toggle(self):
        seen = self.capture(
            [
                {"message": {"role": "assistant", "content": "plain"}, "done": False},
                {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1},
            ],
            {"model": "m", "content": "hi", "think": None, "use_tools": False, "mode": "teacher"},
        )
        self.assertNotIn("tools", seen[0])

    def test_forced_mode_reasks_once_when_the_model_stays_silent(self):
        client = TestClient(app)
        login(client)
        turns = [
            # iteration 1: nothing at all — no prose, no tool call
            [{"message": {"role": "assistant", "content": ""}, "done": False},
             {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}],
            # iteration 2: the model takes the hint and searches
            [{"message": {"role": "assistant", "content": "",
                          "tool_calls": [{"function": {"name": "calc", "arguments": {"expr": "1+1"}}}]},
              "done": False},
             {"done": True, "done_reason": "tool_calls", "prompt_eval_count": 2, "eval_count": 2}],
            # iteration 3: the answer
            [{"message": {"role": "assistant", "content": "verified"}, "done": False},
             {"done": True, "done_reason": "stop", "prompt_eval_count": 3, "eval_count": 3}],
        ]
        seen: list[dict] = []

        def factory(up):
            seen.append(up)
            return _gen(turns[len(seen) - 1])

        with mock.patch.object(chat_route, "stream_chat", factory):
            resp = client.post(
                "/api/chat",
                json={"model": "m", "content": "check this", "think": None,
                      "use_tools": False, "mode": "fact-check"},
            )
        events = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
        self.assertEqual(events[-1]["t"], "done")
        self.assertIn("tools", seen[1], "the re-ask keeps tools attached")
        self.assertIn("have not used any tool", seen[1]["messages"][-1]["content"])
        # exactly one re-ask, then it proceeded to the tool call
        self.assertEqual(len(seen), 3)

    def test_auto_mode_never_reasks(self):
        client = TestClient(app)
        login(client)
        turns = [
            [{"message": {"role": "assistant", "content": ""}, "done": False},
             {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}],
        ]
        seen: list[dict] = []

        def factory(up):
            seen.append(up)
            return _gen(turns[0])

        with mock.patch.object(chat_route, "stream_chat", factory):
            client.post(
                "/api/chat",
                json={"model": "m", "content": "hi", "think": None, "use_tools": True,
                      "mode": "teacher"},
            )
        self.assertEqual(len(seen), 1, "a silent answer from an auto mode is final")


class SystemPromptModeTests(BaseTestCase):
    """The mode block reaches the model; the base rules arrange around it."""

    def sys_prompt(self, mode_id: str) -> str:
        from backend.modes import get_mode
        from backend.prompt import build_messages

        out = build_messages([{"role": "user", "content": "hi"}], mode=get_mode(mode_id))
        return out[0]["content"]

    def test_default_matches_the_old_prompt(self):
        content = self.sys_prompt("assistant")
        self.assertIn("Today is", content)
        self.assertIn("Reply in the language", content)
        self.assertIn("You have tools available", content)

    def test_mode_block_comes_after_the_base_rules(self):
        content = self.sys_prompt("teacher")
        self.assertLess(content.index("Reply in the language"), content.index("Teach rather than"))
        self.assertIn("Teach rather than", content)

    def test_translator_replaces_the_language_rule(self):
        content = self.sys_prompt("translator")
        self.assertNotIn("Reply in the language", content)
        self.assertIn("Translate the user's text", content)

    def test_tool_less_mode_drops_the_tools_paragraph(self):
        self.assertNotIn("You have tools available", self.sys_prompt("editor"))

    def test_notes_stay_last(self):
        from backend.modes import get_mode
        from backend.prompt import build_messages

        out = build_messages(
            [{"role": "user", "content": "hi"}], notes="likes dark mode", mode=get_mode("teacher")
        )
        content = out[0]["content"]
        self.assertIn("likes dark mode", content)
        self.assertLess(content.index("Teach rather than"), content.index("likes dark mode"))


if __name__ == "__main__":
    unittest.main()
