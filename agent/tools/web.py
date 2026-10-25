"""Network tools: fetch a URL as text, and an optional best-effort web search."""
from __future__ import annotations

import html
import os
import re
import urllib.parse
import urllib.request

from .. import USER_AGENT
from . import Tool, ToolContext, ToolError, params, s

TAG = re.compile(r"<(script|style)[\s\S]*?</\1>|<[^>]+>", re.I)


def html_to_text(raw: str) -> str:
    text = TAG.sub(" ", raw)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def _get(url: str, timeout: int = 20) -> tuple[str, str]:
    if not url.startswith(("http://", "https://")):
        raise ToolError("only http(s) URLs are allowed")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,text/plain,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"fetch failed: {e}")
    return ctype, body


def _fetch(ctx: ToolContext, a: dict) -> str:
    ctype, body = _get(a["url"])
    text = html_to_text(body) if "html" in ctype else body
    n = int(a.get("max_chars") or ctx.max_output)
    return text[:n] + ("\n... (truncated)" if len(text) > n else "")


def _search_base(_args: dict | None = None) -> str:
    return os.environ.get("AGENT_SEARCH_URL", "https://html.duckduckgo.com/html/")


def _search(ctx: ToolContext, a: dict) -> str:
    base = _search_base()
    url = base + ("&" if "?" in base else "?") + urllib.parse.urlencode({"q": a["query"]})
    _, body = _get(url)
    results = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        href = html.unescape(m.group(1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
        results.append(f"- {html_to_text(m.group(2))} — {q[0] if q else href}")
        if len(results) >= int(a.get("limit") or 8):
            break
    return "\n".join(results) or "no results (search endpoint may block automated requests; use web_fetch on a known URL)"


TOOLS = [
    Tool("web_fetch", "Fetch a web page or API URL and return its text.", "network",
         params(["url"], url=s("http(s) URL"), max_chars={"type": "integer"}), _fetch, "url", "url"),
    Tool("web_search", "Best-effort web search (DuckDuckGo HTML by default, AGENT_SEARCH_URL to change).", "network",
         params(["query"], query=s("search query"), limit={"type": "integer"}), _search, "url", _search_base),
]
