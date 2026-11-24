"""v0.9.11: "my AI on my computer" with Ollama — check the address, list the installed models, tool support.

The chat itself goes through Ollama's OpenAI-compatible endpoint (<address>/v1/chat/completions, with tools),
like every other provider. This module only does the small checks the welcome screen needs (no tokens spent).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

DEFAULT_ADDRESS = "http://localhost:11434"
RECOMMENDED = "qwen2.5:7b"          # small, good at tool calling, runs on an 8 GB GPU
MAX_MODELS = 30
MAX_SHOW = 12                       # /api/show calls (tool support) per check

Opener = Callable[..., Any]


def root(address: str | None) -> str:
    """'localhost:11434/v1/' -> 'http://localhost:11434' (what /api/* lives under)."""
    a = str(address or "").strip() or DEFAULT_ADDRESS
    if not re.match(r"^[a-z][a-z0-9+.-]*://", a, re.I):
        a = "http://" + a
    a = a.rstrip("/")
    for tail in ("/v1", "/api"):
        if a.lower().endswith(tail):
            a = a[: -len(tail)]
    return a.rstrip("/")


def chat_url(address: str | None) -> str:
    """The base URL saved for the key: the OpenAI-compatible one."""
    return root(address) + "/v1"


def _get(opener: Opener, url: str, timeout: float, body: dict | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"} if data else {})
    with opener(req, timeout=timeout) as r:
        return json.loads(r.read(2_000_000).decode("utf-8", "replace") or "null")


def tool_support(info: Any) -> bool | None:
    """From /api/show: True / False, or None when this Ollama is too old to say."""
    caps = info.get("capabilities") if isinstance(info, dict) else None
    if isinstance(caps, list):
        return "tools" in caps
    tpl = info.get("template") if isinstance(info, dict) else None
    if isinstance(tpl, str) and tpl:
        return ".Tools" in tpl
    return None


def check(address: str | None, timeout: float = 5.0, opener: Opener | None = None) -> dict:
    """{"ok", "code", "address", "base_url", "models": [{"name", "size", "tools"}], "recommended", "has_recommended"}.
    code: ok | no_models | unreachable | not_ollama | bad_url."""
    opener = opener or urllib.request.urlopen
    base = root(address)
    out: dict[str, Any] = {"ok": False, "address": base, "base_url": base + "/v1", "models": [],
                           "recommended": RECOMMENDED, "has_recommended": False}
    if not re.match(r"^https?://[^/\s]+$", base, re.I):
        return {**out, "code": "bad_url"}
    try:
        tags = _get(opener, base + "/api/tags", timeout)
    except urllib.error.HTTPError as e:
        return {**out, "code": "not_ollama", "http_status": e.code}
    except (urllib.error.URLError, OSError, TimeoutError):
        return {**out, "code": "unreachable"}
    except ValueError:
        return {**out, "code": "not_ollama"}
    if not isinstance(tags, dict) or not isinstance(tags.get("models"), list):
        return {**out, "code": "not_ollama"}
    models = []
    for m in tags["models"][:MAX_MODELS]:
        name = str((m or {}).get("name") or (m or {}).get("model") or "").strip()
        if name:
            models.append({"name": name[:120], "size": (m or {}).get("size"), "tools": None})
    for m in models[:MAX_SHOW]:
        try:
            m["tools"] = tool_support(_get(opener, base + "/api/show", timeout, {"model": m["name"]}))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            pass
    names = [m["name"] for m in models]
    out.update(models=models, has_recommended=RECOMMENDED in names or RECOMMENDED + ":latest" in names)
    return {**out, "ok": bool(models), "code": "ok" if models else "no_models"}


def is_local(base_url: str | None) -> bool:
    return bool(base_url) and ":11434" in str(base_url)
