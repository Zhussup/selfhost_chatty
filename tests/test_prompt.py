"""History projection tests."""

from backend import db
from backend.prompt import build_messages
from tests.base import BaseTestCase


def add(msgs, sid="sess") -> None:
    now = db.now()
    db.qx("INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?,?,?,?,?)", (sid, "t", "m", now, now))
    for i, m in enumerate(msgs, 1):
        db.qx(
            "INSERT INTO messages (id, session_id, role, sort, content, thinking, tool_calls_json, tool_call_id, tool_name, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"m{i}-{sid}", sid, m["role"], i, m.get("content", ""), m.get("thinking", ""),
             m.get("tool_calls_json"), m.get("tool_call_id"), m.get("tool_name"), now + i),
        )


def get_rows(sid="sess"):
    return db.q("SELECT * FROM messages WHERE session_id=? ORDER BY sort", (sid,))


class PromptTests(BaseTestCase):
    def test_system_first_and_language(self):
        add([{"role": "user", "content": "привет"}])
        out = build_messages(list(get_rows()))
        self.assertEqual(out[0]["role"], "system")
        self.assertIn("Reply in the language", out[0]["content"])
        self.assertEqual(out[1], {"role": "user", "content": "привет"})

    def test_notes_included(self):
        add([{"role": "user", "content": "hi"}])
        out = build_messages(list(get_rows()), notes="likes dark mode")
        self.assertIn("likes dark mode", out[0]["content"])
        self.assertNotIn("likes dark mode", str(out[1:]))

    def test_thinking_not_resent(self):
        add([
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls_json": '[{"id":"c1","name":"calc","arguments":{"expr":"1+1"}}]'},
            {"role": "tool", "content": "2", "tool_call_id": "c1", "tool_name": "calc"},
            {"role": "assistant", "content": "2", "thinking": "secret reasoning"},
        ])
        out = build_messages(list(get_rows()))
        self.assertEqual(out[2]["role"], "assistant")
        self.assertEqual(out[2]["tool_calls"][0]["function"]["name"], "calc")
        self.assertEqual(out[2]["tool_calls"][0]["function"]["arguments"], {"expr": "1+1"})
        self.assertEqual(out[3]["role"], "tool")
        self.assertEqual(out[3]["tool_name"], "calc")
        self.assertEqual(out[4]["content"], "2")
        blob = str(out)
        self.assertNotIn("secret reasoning", blob)

    def test_trim_never_breaks_tool_run(self):
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(1, 50)]
        msgs.append({"role": "user", "content": "final"})
        add(msgs)
        out = build_messages(list(get_rows()))
        self.assertLessEqual(len(out), 41)

        # tool chain at the boundary is kept intact (its own session to avoid sort collisions)
        base = [{"role": "user", "content": f"msg {i}"} for i in range(1, 48)]
        base += [
            {"role": "user", "content": "trigger"},
            {"role": "assistant", "content": "", "tool_calls_json": '[{"id":"c9","name":"calc","arguments":{}}]'},
            {"role": "tool", "content": "x", "tool_call_id": "c9", "tool_name": "calc"},
        ]
        add(base, sid="sess2")
        out = build_messages(list(get_rows("sess2")))
        # either the chain start is inside the window, or all of it dropped — never an orphaned tail
        roles = [m["role"] for m in out[1:]]
        if "tool" in roles:
            self.assertIn("assistant", roles)
            # the first non-system message never leaves an orphaned tool/chain end
            self.assertNotEqual(roles[0], "tool")