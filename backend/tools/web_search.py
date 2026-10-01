"""Web search (ddgs metasearch, no API key) + single-page fetching (trafilatura)."""

from typing import Any

import httpx
import trafilatura
from ddgs import DDGS
from ddgs.exceptions import DDGSException


def web_search(query: str, max_results: int = 5, backend: str = "auto") -> str:
    max_results = max(1, min(int(max_results or 5), 8))
    try:
        with DDGS(timeout=10) as ddgs:
            raw: list[dict[str, Any]] = list(ddgs.text(query, max_results=max_results, backend=backend))
    except DDGSException:
        return "search failed (rate limited or unavailable) — try different wording"
    if not raw:
        return "no results found"
    out = []
    for i, r in enumerate(raw, 1):
        title = r.get("title") or "(untitled)"
        href = r.get("href") or r.get("url") or ""
        body = r.get("body") or r.get("snippet") or r.get("content") or ""
        out.append(f"{i}. {title}\n   {href}\n   {body.strip()}")
    return "\n\n".join(out)


def fetch_page(url: str, max_chars: int = 20000) -> str:
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http(s)://"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = httpx.get(url, timeout=15, headers=headers, follow_redirects=True)
    except httpx.HTTPError as exc:
        return f"error fetching page: {exc.__class__.__name__}"
    if resp.status_code >= 400:
        return f"error: page returned HTTP {resp.status_code}"
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype and "xml" not in ctype and ctype:
        snippet = resp.text[: max(0, max_chars)]
        return f"(non-HTML page, content-type {ctype.split(';')[0]})\n{snippet}"
    html = resp.content[:3_000_000]
    text = trafilatura.extract(html, output_format="markdown", include_links=False, url=url)
    if not text:
        text = trafilatura.extract(html, output_format="txt", url=url)
    if not text:
        return "error: could not extract readable text from this page"
    return text[: max(0, max_chars)]