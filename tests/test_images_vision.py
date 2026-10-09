"""Vision support plumbing: prompt projection, upstream capabilities, the model list."""

import asyncio
import json
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from backend import ollama, vision
from backend.app import app
from backend.config import settings
from backend.prompt import build_messages
from backend.routes import models as models_route
from tests.base import BaseTestCase
from tests.test_prompt import add, get_rows


class PromptImageTests(BaseTestCase):
    def test_user_row_with_images_projects_an_images_array(self):
        add([{"role": "user", "content": "look at this"}])
        rows = list(get_rows())
        out = build_messages(rows, "", None, images={rows[0]["id"]: ["AAA", "BBB"]})
        self.assertEqual(out[1]["images"], ["AAA", "BBB"])
        self.assertEqual(out[1]["content"], "look at this")

    def test_rows_without_attachments_get_no_images_key(self):
        add([{"role": "user", "content": "hi"}])
        out = build_messages(list(get_rows()), "", None, images={})
        self.assertNotIn("images", out[1])

    def test_hand_built_rows_without_ids_are_unaffected(self):
        # tests/test_prompt.py builds plain dicts; a missing id must not explode
        out = build_messages([{"role": "user", "content": "hi"}], "", None, images={"x": ["AAA"]})
        self.assertEqual(out[1], {"role": "user", "content": "hi"})

    def test_images_survive_the_history_trim(self):
        msgs = []
        for i in range(5):
            msgs.append({"role": "user", "content": f"q{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        add(msgs)
        rows = list(get_rows())
        # the newest user row is the one the trim keeps
        self.assertEqual(rows[-2]["role"], "user")
        with mock.patch.object(settings, "history_max_messages", 2):
            out = build_messages(rows, "", None, images={rows[-2]["id"]: ["AAA"]})
        # the surviving user row keeps its images; the dropped ones simply vanish
        kept = [m for m in out if m["role"] == "user" and m.get("images")]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["content"], "q4")


class ModelCapabilitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._key = settings.ollama_api_key
        settings.ollama_api_key = "test-key"

    def tearDown(self) -> None:
        ollama.INJECT_TRANSPORT = None
        settings.ollama_api_key = self._key

    def _caps(self, response: httpx.Response):
        ollama.INJECT_TRANSPORT = httpx.MockTransport(lambda request: response)
        return asyncio.run(ollama.model_capabilities("m"))

    def test_parses_capabilities(self):
        self.assertEqual(
            self._caps(httpx.Response(200, json={"capabilities": ["completion", "vision"]})),
            ["completion", "vision"],
        )

    def test_upstream_error_returns_empty(self):
        self.assertEqual(self._caps(httpx.Response(500, json={"error": "nope"})), [])

    def test_missing_field_returns_empty(self):
        self.assertEqual(self._caps(httpx.Response(200, json={"details": {}})), [])


class VisionCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        vision.forget_all()
        self._key = settings.ollama_api_key
        settings.ollama_api_key = "test-key"
        self.probes = 0

    def tearDown(self) -> None:
        ollama.INJECT_TRANSPORT = None
        vision.forget_all()
        settings.ollama_api_key = self._key

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.probes += 1
        return httpx.Response(200, json={"capabilities": ["completion", "vision"]})

    def test_is_vision_reads_the_cache_after_the_first_probe(self):
        ollama.INJECT_TRANSPORT = httpx.MockTransport(self._handler)
        self.assertIs(asyncio.run(vision.is_vision("m")), True)
        self.assertIs(asyncio.run(vision.is_vision("m")), True)
        self.assertEqual(self.probes, 1)

    def test_probe_failure_is_unknown_not_false(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        ollama.INJECT_TRANSPORT = httpx.MockTransport(handler)
        self.assertIsNone(asyncio.run(vision.is_vision("m")))


class ModelsRouteVisionTests(BaseTestCase):
    """GET /api/models must carry the vision flag the composer gates on."""

    def setUp(self) -> None:
        super().setUp()
        models_route._cache = []
        models_route._cache_at = 0.0
        vision.forget_all()
        self._key = settings.ollama_api_key
        settings.ollama_api_key = "test-key"
        self.probes = 0

    def tearDown(self) -> None:
        ollama.INJECT_TRANSPORT = None
        vision.forget_all()
        settings.ollama_api_key = self._key

    def _handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "vision-model"}, {"name": "plain-model"}]},
            )
        self.probes += 1
        wanted = json.loads(request.content)["model"]
        caps = ["completion", "vision"] if wanted == "vision-model" else ["completion", "tools"]
        return httpx.Response(200, json={"capabilities": caps})

    def test_models_carry_vision_and_capabilities(self):
        client = TestClient(app)
        client.post("/api/auth/login", json={"password": settings.auth_password})
        ollama.INJECT_TRANSPORT = httpx.MockTransport(self._handler)
        by_name = {m["name"]: m for m in client.get("/api/models").json()["models"]}
        self.assertIs(by_name["vision-model"]["vision"], True)
        self.assertIs(by_name["plain-model"]["vision"], False)
        self.assertEqual(by_name["vision-model"]["capabilities"], ["completion", "vision"])
        self.assertEqual(self.probes, 2)

        # a second request inside the TTL serves the cache and probes nothing new
        client.get("/api/models")
        self.assertEqual(self.probes, 2)


if __name__ == "__main__":
    unittest.main()
