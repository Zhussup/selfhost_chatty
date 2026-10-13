"""HTTP transport for the chatty backend: login, streaming chat, sessions, modes, models.

Async core, because the in-process test transport (httpx.ASGITransport) exists only
for the async interface, and the REPL blocks on input() between turns anyway. One
`asyncio.run()` per CLI operation; the cookie jar is plain data and survives the
event loop being torn down between turns.
"""

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .config import Config, ConfigError

# The default read timeout (5 s) would kill the stream during long tool
# executions — give every segment explicit headroom.
_TIMEOUT = httpx.Timeout(connect=5, read=180, write=60, pool=5)


class ApiError(Exception):
    """A non-200 reply, an error event inside the stream, or a failed login."""

    def __init__(self, status: int = 0, code: str = "", message: str = ""):
        self.status = status
        self.code = code or ("http" if status else "api")
        self.message = message or (f"http {status}" if status else "unknown error")
        super().__init__(self.message)


class Chatty:
    """One server + one cookie jar. Auth is a stateless signed cookie, so an
    instance is just base url + shc_auth — no server-side session to track."""

    def __init__(self, cfg: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self._transport = transport
        self._cookies = httpx.Cookies()

    def _client(self) -> httpx.AsyncClient:
        kw: dict[str, Any] = {
            "base_url": self.cfg.url,
            "cookies": self._cookies,
            "timeout": _TIMEOUT,
        }
        if self._transport is not None:
            kw["transport"] = self._transport
        return httpx.AsyncClient(**kw)

    async def _ensure_login(self) -> None:
        if self._cookies.get("shc_auth"):
            return
        async with self._client() as client:
            resp = await client.post(
                "/api/auth/login", json={"password": self.cfg.password}
            )
            # Fresh client per call: cookies live here, the loop dies after.
            self._cookies = client.cookies
        if resp.status_code != 200:
            # 0.7 s wrong-password delay is server-side; one clear message is enough.
            raise ApiError(resp.status_code, "login", "login failed — wrong password?")

    async def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        await self._ensure_login()
        async with self._client() as client:
            resp = await client.request(method, path, **kw)
            self._cookies = client.cookies
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, "http", _detail(resp))
        return resp

    async def chat(
        self,
        payload: dict[str, Any],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Stream one turn; feed every line to on_event and return the summary.

        Unknown event types pass through untouched (frontend contract): the
        caller decides what to ignore, so an old CLI keeps working when the
        backend grows new events.
        """
        await self._ensure_login()
        summary: dict[str, Any] = {}
        async with self._client() as client:
            async with client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise ApiError(*_status_error(resp.status_code, body))
                self._cookies = client.cookies
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("t") == "error":
                        raise ApiError(
                            200, ev.get("code", "error"), ev.get("message", "")
                        )
                    if ev.get("t") == "meta":
                        summary["session_id"] = ev.get("session_id")
                        summary["message_id"] = ev.get("message_id")
                    elif ev.get("t") == "done":
                        summary.update(
                            message_id=ev.get("message_id") or summary.get("message_id"),
                            reason=ev.get("reason"),
                            prompt=ev.get("prompt", 0),
                            completion=ev.get("completion", 0),
                            tool_calls=ev.get("tool_calls", 0),
                            ms=ev.get("ms", 0),
                        )
                    if on_event:
                        on_event(ev)
        return summary

    async def sessions(self) -> list[dict[str, Any]]:
        return (await self._call("GET", "/api/sessions")).json()

    async def session(self, sid: str) -> dict[str, Any]:
        return (await self._call("GET", f"/api/sessions/{sid}")).json()

    async def create_session(self, body: dict[str, Any]) -> dict[str, Any]:
        return (await self._call("POST", "/api/sessions", json=body)).json()

    async def patch_session(self, sid: str, body: dict[str, Any]) -> None:
        await self._call("PATCH", f"/api/sessions/{sid}", json=body)

    async def delete_session(self, sid: str) -> None:
        await self._call("DELETE", f"/api/sessions/{sid}")

    async def export_md(self, sid: str) -> str:
        return (await self._call("GET", f"/api/sessions/{sid}/export.md")).text

    async def modes(self) -> dict[str, Any]:
        return (await self._call("GET", "/api/modes")).json()

    async def models(self) -> dict[str, dict[str, Any]]:
        return (await self._call("GET", "/api/models")).json()

    async def default_model(self) -> str | None:
        data = (await self._call("GET", "/healthz")).json()
        return data.get("model_default") or None

    async def resolve_model(self, flag: str | None = None) -> str:
        """--model > server default (healthz) > first listed model."""
        if flag:
            return flag
        default = await self.default_model()
        if default:
            return default
        listing = (await self.models()).get("models") or []
        if listing:
            return listing[0]["name"]
        raise ApiError(
            0, "no_models", "no models available — check OLLAMA_API_KEY on the server"
        )


def read_images(paths: list[str]) -> list[dict[str, str]]:
    """Local files → ImageIn dicts. Nothing about the format is guessed here —
    the server sniffs magic bytes and reports image_invalid on its own terms."""
    images: list[dict[str, str]] = []
    for raw in paths:
        path = Path(raw).expanduser()
        try:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise ConfigError(f"cannot read image {raw}: {exc.strerror}") from exc
        images.append({"data": data, "name": path.name})
    return images


def _detail(resp: httpx.Response) -> str:
    """The `detail` field of a JSON error body, or a text fallback."""
    try:
        data = resp.json()
    except ValueError:
        data = None
    if isinstance(data, dict) and "detail" in data:
        d = data["detail"]
        return d if isinstance(d, str) else json.dumps(d)[:200]
    return (resp.text or "").strip()[:200] or f"http {resp.status_code}"


def _status_error(status: int, body: str) -> tuple[int, str, str]:
    """Decode the one-line NDJSON or JSON body that came with a non-200 chat reply."""
    code, message = "http", ""
    try:
        first = json.loads(body.splitlines()[0] or "{}")
    except ValueError:
        first = None
    if isinstance(first, dict):
        if first.get("t") == "error":
            code = first.get("code", "http")
            message = first.get("message", "")
        elif "detail" in first:
            d = first["detail"]
            message = d if isinstance(d, str) else json.dumps(d)[:200]
    if not message:
        message = body.strip()[:200] or f"http {status}"
    return status, code, message