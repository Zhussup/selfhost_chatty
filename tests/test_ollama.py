"""ollama.py parser tests (httpx.MockTransport) + error mapping."""

import asyncio
import json
import unittest

import httpx

from backend import ollama
from backend.config import settings


def transport_with(responses: list[httpx.Response]) -> httpx.MockTransport:
    # each queued response pops once per client.stream call
    queue = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return next(queue)
        except StopIteration:
            raise AssertionError("unexpected extra upstream request") from None

    return httpx.MockTransport(handler)


def _collect(payload: dict, responses: list[httpx.Response]):
    ollama.INJECT_TRANSPORT = transport_with(responses)
    try:
        chunks = asyncio.run(_drain(payload))
        return chunks
    finally:
        ollama.INJECT_TRANSPORT = None


async def _drain(payload: dict):
    out = []
    async for chunk in ollama.stream_chat(payload):
        out.append(chunk)
    return out


class StreamChatTests(unittest.TestCase):
    def setUp(self):
        self._key = settings.ollama_api_key
        settings.ollama_api_key = "test-key"  # bypass "not set" guard

    def tearDown(self):
        settings.ollama_api_key = self._key

    def test_ndjson_parsing(self):
        lines = [
            {"message": {"role": "assistant", "content": "hel"}, "done": False},
            {"message": {"role": "assistant", "content": "lo"}, "done": False},
            {"done": True, "done_reason": "stop"},
        ]
        body = ("\n".join(json.dumps(l) for l in lines) + "\n").encode()
        chunks = _collect({"model": "m", "messages": [], "stream": True},
                          [httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"})])
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[1]["message"]["content"], "lo")
        self.assertTrue(chunks[2]["done"])

    def test_http_errors_map(self):
        with self.assertRaises(ollama.OllamaAuthError):
            _collect({"messages": []}, [httpx.Response(401, content=b'{"error":"bad key"}')])
        with self.assertRaises(ollama.OllamaRateLimitError):
            _collect({"messages": []}, [httpx.Response(429, content=b'{}')])

    def test_error_chunk_from_upstream(self):
        # mid-stream error object (Ollama emits {"error": ...} without done)
        body = json.dumps({"error": "model is overloaded"}).encode()
        with self.assertRaises(ollama.OllamaUpstreamError) as ctx:
            _collect({"messages": []}, [httpx.Response(200, content=body)])
        self.assertIn("overloaded", str(ctx.exception))

    def test_list_models(self):
        tags = {"models": [
            {"name": "gpt-oss:120b", "size": 65000000000, "modified_at": "2025-01-01", "details": {"family": "gptoss"}},
            {"name": "qwen3.5:397b", "size": 800, "modified_at": "", "details": {"family": "qwen"}},
        ]}
        ollama.INJECT_TRANSPORT = transport_with([httpx.Response(200, json=tags)])
        try:
            models = asyncio.run(ollama.list_models())
        finally:
            ollama.INJECT_TRANSPORT = None
        self.assertEqual([m["name"] for m in models], ["gpt-oss:120b", "qwen3.5:397b"])


class NormalizeCallTests(unittest.TestCase):
    def test_dict_arguments(self):
        c = ollama._normalize_call({"function": {"name": "calc", "arguments": {"expr": "1"}}}, 0, 1)
        self.assertEqual(c, {"id": "iter1call0", "name": "calc", "arguments": {"expr": "1"}})

    def test_string_arguments(self):
        c = ollama._normalize_call({"function": {"name": "x", "arguments": '{"q": "hi"}'}}, 1, 2)
        self.assertEqual(c["arguments"], {"q": "hi"})
        self.assertEqual(c["id"], "iter2call1")

    def test_broken_arguments(self):
        c = ollama._normalize_call({"function": {"name": "x", "arguments": "not json"}}, 0, 3)
        self.assertEqual(c["arguments"], {"_raw": "not json"})


if __name__ == "__main__":
    unittest.main()