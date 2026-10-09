"""Image attachments: vision gating, validation, persistence, serving, cascades."""

import base64
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from backend.app import app
from backend.config import settings
from backend.routes import chat as chat_route
from tests.base import BaseTestCase

# 1x1 PNG — small enough to inline, real enough for the magic-byte sniffer.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

DONE = {
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 5,
    "prompt_eval_cached_count": 0,
    "eval_count": 2,
}


def stream_factory(turns: list[list[dict]], seen: list[dict] | None = None):
    """stream_chat() replacement: scripted chunks per upstream call, optionally recording payloads."""
    schedule = iter(turns)

    def factory(payload):
        if seen is not None:
            seen.append(payload)
        chunks = next(schedule, [])

        async def gen():
            for c in chunks:
                yield c

        return gen()

    return factory


def login(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"password": settings.auth_password})
    assert resp.status_code == 200, resp.text


def events_of(resp) -> list[dict]:
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def vision(value):
    """Patch the capability probe the chat route gates on."""
    return mock.patch.object(chat_route.vision, "is_vision", mock.AsyncMock(return_value=value))


def turn(content: str = "ok") -> list[dict]:
    return [[{"message": {"role": "assistant", "content": content}, "done": False}, DONE]]


class ImageChatTests(BaseTestCase):
    """The turn itself: what gets accepted, refused and stored."""

    def send(self, client: TestClient, body: dict, turns=None, seen=None):
        turns = turns or turn()
        with mock.patch.object(chat_route, "stream_chat", stream_factory(turns, seen)):
            return client.post("/api/chat", json=body)

    def test_image_only_message_accepted(self):
        client = TestClient(app)
        login(client)
        with vision(True):
            resp = self.send(
                client,
                {
                    "model": "m",
                    "content": "",
                    "images": [{"data": PNG_B64, "name": "pixel.png", "width": 1, "height": 1}],
                    "use_tools": False,
                },
            )
        self.assertEqual([e["t"] for e in events_of(resp)], ["meta", "delta", "usage", "done"])

        row = chat_route.db.one("SELECT * FROM messages WHERE role='user'")
        self.assertEqual(row["content"], "")
        images = chat_route.db.q("SELECT * FROM message_images")
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["mime"], "image/png")
        self.assertEqual(images[0]["name"], "pixel.png")
        self.assertEqual((images[0]["width"], images[0]["height"]), (1, 1))
        self.assertEqual(bytes(images[0]["bytes"]), base64.b64decode(PNG_B64))
        # an image-only chat still gets a sensible title
        self.assertEqual(chat_route.db.one("SELECT title FROM sessions")["title"], "Photo")

    def test_empty_content_without_images_is_422(self):
        client = TestClient(app)
        login(client)
        resp = client.post("/api/chat", json={"model": "m", "content": "", "use_tools": False})
        self.assertEqual(resp.status_code, 422)

    def test_non_vision_model_is_refused_and_writes_nothing(self):
        client = TestClient(app)
        login(client)
        seen: list[dict] = []
        with vision(False):
            resp = self.send(
                client,
                {"model": "text-only", "content": "", "images": [{"data": PNG_B64}], "use_tools": False},
                seen=seen,
            )
        events = events_of(resp)
        self.assertEqual([e["t"] for e in events], ["error"])
        self.assertEqual(events[0]["code"], "vision_unsupported")
        self.assertEqual(seen, [])  # upstream was never called
        self.assertEqual(chat_route.db.q("SELECT id FROM sessions"), [])
        self.assertEqual(chat_route.db.q("SELECT id FROM messages"), [])
        self.assertEqual(chat_route.db.q("SELECT id FROM message_images"), [])

    def test_unknown_capability_fails_open(self):
        client = TestClient(app)
        login(client)
        with vision(None):
            resp = self.send(
                client,
                {"model": "m", "content": "look", "images": [{"data": PNG_B64}], "use_tools": False},
            )
        self.assertEqual(events_of(resp)[-1]["t"], "done")
        self.assertEqual(len(chat_route.db.q("SELECT id FROM message_images")), 1)

    def test_oversized_image_is_refused(self):
        client = TestClient(app)
        login(client)
        with vision(True), mock.patch.object(settings, "image_max_bytes", 10):
            resp = self.send(
                client,
                {"model": "m", "content": "x", "images": [{"data": PNG_B64}], "use_tools": False},
            )
        events = events_of(resp)
        self.assertEqual(events[0]["code"], "image_invalid")
        self.assertEqual(chat_route.db.q("SELECT id FROM message_images"), [])

    def test_too_many_images_is_refused(self):
        client = TestClient(app)
        login(client)
        body = {
            "model": "m",
            "content": "x",
            "images": [{"data": PNG_B64} for _ in range(settings.image_max_count + 1)],
            "use_tools": False,
        }
        with vision(True):
            resp = self.send(client, body)
        self.assertEqual(events_of(resp)[0]["code"], "image_invalid")

    def test_malformed_base64_is_refused(self):
        client = TestClient(app)
        login(client)
        with vision(True):
            resp = self.send(
                client,
                {"model": "m", "content": "x", "images": [{"data": "!!!not base64!!!"}], "use_tools": False},
            )
        self.assertEqual(events_of(resp)[0]["code"], "image_invalid")

    def test_payload_that_is_not_an_image_is_refused(self):
        client = TestClient(app)
        login(client)
        not_an_image = base64.b64encode(b"hello world, definitely not a photo").decode()
        with vision(True):
            resp = self.send(
                client,
                {"model": "m", "content": "x", "images": [{"data": not_an_image}], "use_tools": False},
            )
        self.assertEqual(events_of(resp)[0]["code"], "image_invalid")

    def test_backward_compat_plain_turn_has_no_images(self):
        client = TestClient(app)
        login(client)
        seen: list[dict] = []
        resp = self.send(client, {"model": "m", "content": "hi", "use_tools": False}, seen=seen)
        self.assertEqual(events_of(resp)[-1]["t"], "done")
        self.assertEqual(chat_route.db.q("SELECT id FROM message_images"), [])
        upstream_user = [m for m in seen[0]["messages"] if m["role"] == "user"][-1]
        self.assertNotIn("images", upstream_user)

    def test_images_reach_upstream(self):
        client = TestClient(app)
        login(client)
        seen: list[dict] = []
        with vision(True):
            self.send(
                client,
                {"model": "m", "content": "look", "images": [{"data": PNG_B64}], "use_tools": False},
                seen=seen,
            )
        upstream_user = [m for m in seen[0]["messages"] if m["role"] == "user"][-1]
        self.assertEqual(upstream_user["images"], [PNG_B64])  # normalized base64, no data: prefix

    def test_regenerate_resends_history_images(self):
        client = TestClient(app)
        login(client)
        with vision(True):
            first = self.send(
                client,
                {"model": "m", "content": "look", "images": [{"data": PNG_B64}], "use_tools": False},
            )
        session_id = events_of(first)[0]["session_id"]

        seen: list[dict] = []
        with vision(True):
            resp = self.send(
                client,
                {"model": "m", "session_id": session_id, "content": "look",
                 "regenerate": True, "use_tools": False},
                seen=seen,
            )
        self.assertEqual(events_of(resp)[-1]["t"], "done")
        upstream_user = [m for m in seen[0]["messages"] if m["role"] == "user"][-1]
        self.assertEqual(upstream_user["images"], [PNG_B64])


class ImageServingTests(BaseTestCase):
    """GET /api/images/{id}: auth, bytes, 404, and the cascades that clean up."""

    def seed(self, client: TestClient, content: str = "photo") -> tuple[str, str, list[str]]:
        with vision(True), mock.patch.object(chat_route, "stream_chat", stream_factory(turn())):
            resp = client.post(
                "/api/chat",
                json={"model": "m", "content": content, "images": [{"data": PNG_B64, "name": "p.png"}],
                      "use_tools": False},
            )
        events = events_of(resp)
        session_id = events[0]["session_id"]
        message_id = chat_route.db.one("SELECT id FROM messages WHERE role='user'")["id"]
        image_ids = [r["id"] for r in chat_route.db.q("SELECT id FROM message_images")]
        return session_id, message_id, image_ids

    def test_bytes_are_served_to_a_logged_in_client(self):
        client = TestClient(app)
        login(client)
        _, _, image_ids = self.seed(client)
        resp = client.get(f"/api/images/{image_ids[0]}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/png")
        self.assertEqual(resp.content, base64.b64decode(PNG_B64))

    def test_serving_requires_auth(self):
        client = TestClient(app)
        login(client)
        _, _, image_ids = self.seed(client)
        self.assertEqual(TestClient(app).get(f"/api/images/{image_ids[0]}").status_code, 401)

    def test_unknown_id_is_404(self):
        client = TestClient(app)
        login(client)
        self.assertEqual(client.get("/api/images/nope").status_code, 404)

    def test_session_payload_carries_image_metadata(self):
        client = TestClient(app)
        login(client)
        session_id, _, image_ids = self.seed(client)
        msgs = client.get(f"/api/sessions/{session_id}").json()["messages"]
        user = next(m for m in msgs if m["role"] == "user")
        self.assertEqual([i["id"] for i in user["images"]], image_ids)
        self.assertEqual(user["images"][0]["name"], "p.png")
        self.assertNotIn("bytes", user["images"][0])  # metadata only, never the payload

    def test_deleting_a_session_cascades_its_images(self):
        client = TestClient(app)
        login(client)
        session_id, _, _ = self.seed(client)
        self.assertEqual(client.delete(f"/api/sessions/{session_id}").status_code, 200)
        self.assertEqual(chat_route.db.q("SELECT id FROM message_images"), [])

    def test_edit_and_resend_keeps_the_prompt_images(self):
        client = TestClient(app)
        login(client)
        session_id, message_id, image_ids = self.seed(client, content="first")
        with mock.patch.object(chat_route, "stream_chat", stream_factory(turn())):
            resp = client.post(
                "/api/chat",
                json={"model": "m", "session_id": session_id, "content": "edited",
                      "edit_message_id": message_id, "use_tools": False},
            )
        self.assertEqual(events_of(resp)[-1]["t"], "done")
        row = chat_route.db.one("SELECT content FROM messages WHERE id=?", (message_id,))
        self.assertEqual(row["content"], "edited")
        # the stored attachments survive the text edit, exactly like the stored quote does
        kept = [r["id"] for r in chat_route.db.q("SELECT id FROM message_images")]
        self.assertEqual(kept, image_ids)

    def test_tail_truncation_cascades_the_dropped_images(self):
        client = TestClient(app)
        login(client)
        session_id, first_message_id, first_image_ids = self.seed(client, content="first")
        # a second image-bearing turn, which edit-and-resend will drop
        with vision(True), mock.patch.object(chat_route, "stream_chat", stream_factory(turn())):
            client.post(
                "/api/chat",
                json={"model": "m", "session_id": session_id, "content": "second",
                      "images": [{"data": PNG_B64}], "use_tools": False},
            )
        self.assertEqual(len(chat_route.db.q("SELECT id FROM message_images")), 2)

        with mock.patch.object(chat_route, "stream_chat", stream_factory(turn())):
            client.post(
                "/api/chat",
                json={"model": "m", "session_id": session_id, "content": "first again",
                      "edit_message_id": first_message_id, "use_tools": False},
            )
        remaining = [r["id"] for r in chat_route.db.q("SELECT id FROM message_images")]
        self.assertEqual(remaining, first_image_ids)

    def test_export_md_references_images_by_url(self):
        client = TestClient(app)
        login(client)
        session_id, _, image_ids = self.seed(client)
        body = client.get(f"/api/sessions/{session_id}/export.md").text
        self.assertIn(f"![p.png](/api/images/{image_ids[0]})", body)
        self.assertNotIn(PNG_B64, body)  # never inlined


if __name__ == "__main__":
    unittest.main()
