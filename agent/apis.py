"""Business API connector (v0.9): the user adds an API in the Connect tab (name, base URL, an auth header
whose value is stored like an API key — never shown again, never given to the model — and an optional
OpenAPI URL). The agent gets tools to call it, each with a risk category, so approvals still apply:

  api_list  (read)     the APIs and their endpoints (from the OpenAPI document when given)
  api_get   (network)  GET; asks every time unless the user ticked "reads without asking" for that API
  api_send  (send)     POST / PUT / PATCH / DELETE (asks unless the permissions say otherwise)
  api_pay   (spend)    the same, for an API the user marked "can spend money" (always asked; blocked
                       while the "spend" category is set to deny, the default)

Requests only go to the API's own base URL (same scheme, host, port, path prefix)."""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .tools import Tool, ToolContext, ToolError, params, s

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")
HEADER_RE = re.compile(r"^[A-Za-z0-9-]{1,60}$")
SEND_METHODS = ("POST", "PUT", "PATCH", "DELETE")
MAX_BODY = 64 * 1024
MAX_SPEC = 2 * 1024 * 1024
TIMEOUT = 20.0


class ApiError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _mask(v: str | None) -> str:
    from .keys import mask
    return mask(v)


def _key(name: str) -> str:
    return name.strip().lower()


class ApiRegistry:
    """apis.json (no secret in it) + the auth header values in the app's SecretStore ("api:<id>")."""

    def __init__(self, directory: str | Path, secrets: Any, perms: Any = None, fetch: Any = None):
        self.path = Path(directory) / "apis.json"
        self.secrets, self.perms = secrets, perms
        self._fetch = fetch or _http
        self._lock = threading.RLock()
        self.items: list[dict] = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [a for a in data.get("apis", []) if isinstance(a, dict) and a.get("id")]
        except (OSError, ValueError):
            self.items = []
        self._sync_perms()

    # -- storage
    def _save(self) -> None:
        from .userconfig import write_private
        write_private(self.path, {"version": 1, "apis": self.items})
        self._sync_perms()

    def _sync_perms(self) -> None:
        if self.perms is not None:
            self.perms.api_auto_get = {_key(a["name"]) for a in self.items if a.get("auto_get")}

    def find(self, name_or_id: str) -> dict:
        k = _key(str(name_or_id or ""))
        for a in self.items:
            if a["id"] == name_or_id or _key(a["name"]) == k:
                return a
        raise KeyError(name_or_id)

    def secret(self, a: dict) -> str | None:
        return self.secrets.get("api:" + a["id"]) if self.secrets is not None else None

    def view(self) -> list[dict]:
        """For the page: the header value only masked."""
        out = []
        for a in self.items:
            sec = self.secret(a)
            out.append({**{k: a.get(k) for k in ("id", "name", "base_url", "auth_header", "openapi_url",
                                                  "auto_get", "spends", "description")},
                        "auth_set": bool(sec), "auth_mask": _mask(sec) if sec else None,
                        "endpoints": len(a.get("endpoints") or [])})
        return out

    # -- changes (Connect tab)
    def save(self, data: dict, api_id: str | None = None) -> dict:
        name = str(data.get("name") or "").strip()
        base = str(data.get("base_url") or "").strip()
        header = str(data.get("auth_header") or "Authorization").strip() or "Authorization"
        spec = str(data.get("openapi_url") or "").strip()
        with self._lock:
            old = self.find(api_id) if api_id else None
            if not NAME_RE.match(name):
                raise ApiError("bad_name", "name: letters, digits, space, _ . - (max 40)")
            if any(_key(a["name"]) == _key(name) and a is not old for a in self.items):
                raise ApiError("duplicate", "an API with this name already exists")
            u = urllib.parse.urlparse(base)
            if u.scheme not in ("http", "https") or not u.hostname or u.query or u.fragment:
                raise ApiError("bad_url", "base URL: http(s)://host[/path], without ?query")
            if not HEADER_RE.match(header):
                raise ApiError("bad_header", "auth header name: letters, digits and - only")
            if spec and urllib.parse.urlparse(spec).scheme not in ("http", "https"):
                raise ApiError("bad_url", "OpenAPI URL: http(s)://...")
            a = old if old is not None else {"id": uuid.uuid4().hex[:10]}
            a.update(name=name, base_url=base.rstrip("/"), auth_header=header, openapi_url=spec or None,
                     auto_get=bool(data.get("auto_get")), spends=bool(data.get("spends")),
                     description=str(data.get("description") or "").strip()[:300] or None)
            secret = data.get("auth_value")
            if isinstance(secret, str) and secret.strip():
                self.secrets.set("api:" + a["id"], secret.strip())
            elif data.get("auth_clear"):
                self.secrets.delete("api:" + a["id"])
            if old is None:
                self.items.append(a)
            self._save()
        if spec and (old is None or old.get("openapi_url") != spec or data.get("refresh_spec")):
            self.load_spec(a)
        return next(v for v in self.view() if v["id"] == a["id"])

    def delete(self, api_id: str) -> dict:
        with self._lock:
            a = self.find(api_id)
            self.items.remove(a)
            self.secrets.delete("api:" + a["id"])
            self._save()
        return {"ok": True, "id": a["id"]}

    def load_spec(self, a: dict) -> int:
        """Read the OpenAPI (JSON) document once and keep a short list of endpoints. Errors are kept, not raised."""
        try:
            status, text = self._fetch("GET", a["openapi_url"], {}, None, MAX_SPEC)
            if status >= 400:
                raise ValueError(f"HTTP {status}")
            a["endpoints"] = endpoints(json.loads(text))
            a["spec_error"] = None
            if not a.get("description"):
                a["description"] = None
        except (ValueError, OSError, urllib.error.URLError) as e:
            a["endpoints"], a["spec_error"] = [], str(e)[:200]
        with self._lock:
            self._save()
        return len(a["endpoints"])

    # -- calls (tools)
    def url_for(self, a: dict, path: str, query: Any = None) -> str:
        path = str(path or "/").strip()
        if re.match(r"^[a-z][a-z0-9+.-]*:", path, re.I) or path.startswith("//"):
            raise ToolError("give a path of this API (e.g. /customers), not a full URL")
        base = urllib.parse.urlparse(a["base_url"] + "/")
        full = urllib.parse.urljoin(a["base_url"] + "/", path.lstrip("/"))
        u = urllib.parse.urlparse(full)
        norm = urllib.parse.urlparse(urllib.parse.urljoin(full, "."))   # resolves ../
        if (u.scheme, u.netloc) != (base.scheme, base.netloc) or not (norm.path + "/").startswith(base.path) \
                or "/../" in "/" + path + "/":
            raise ToolError("this path leaves the API's base URL")
        if isinstance(query, dict) and query:
            full += ("&" if u.query else "?") + urllib.parse.urlencode({str(k): str(v) for k, v in query.items()})
        return full

    def call(self, name: str, method: str, path: str, query: Any = None, body: Any = None,
             max_output: int = 12000) -> str:
        try:
            a = self.find(name)
        except KeyError:
            raise ToolError(f"unknown API {name!r}; use api_list to see the APIs the user added")
        url = self.url_for(a, path, query)
        secret = self.secret(a)
        headers = {"Accept": "application/json, text/plain;q=0.9, */*;q=0.5", "User-Agent": "autonomous-agent"}
        if secret:
            headers[a.get("auth_header") or "Authorization"] = secret
        data = None
        if body is not None and method in SEND_METHODS:
            data = (json.dumps(body) if not isinstance(body, str) else body).encode("utf-8")
            if len(data) > MAX_BODY:
                raise ToolError("request body too large (64 KB max)")
            headers["Content-Type"] = "application/json"
        try:
            status, text = self._fetch(method, url, headers, data, 1024 * 1024)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ToolError(f"cannot reach {a['name']}: {_clean(str(e), secret)}")
        text = _clean(text, secret)
        if len(text) > max_output:
            text = text[:max_output] + f"\n... ({len(text) - max_output} chars truncated)"
        return f"HTTP {status} {method} {urllib.parse.urlparse(url).path}\n{text}"


def _clean(text: str, secret: str | None) -> str:
    from .redact import redact
    out = str(text)
    if secret:
        out = out.replace(secret, "***REDACTED***")
        if " " in secret:                                   # "Bearer abc": the token alone too
            out = out.replace(secret.split(" ", 1)[1], "***REDACTED***")
    return redact(out)


def _http(method: str, url: str, headers: dict, data: bytes | None, limit: int) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        from .netguard import open_url          # v0.9.3: never follow a redirect to another host with the key
        with open_url(req, TIMEOUT, ssrf=False, same_origin_redirects=True) as r:
            return r.status, r.read(limit).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(limit).decode("utf-8", "replace")


def endpoints(spec: dict, limit: int = 60) -> list[str]:
    """OpenAPI 3 / Swagger 2 -> ["GET /customers — List customers", ...]"""
    out = []
    for path, ops in (spec.get("paths") or {}).items():
        if not isinstance(ops, dict):
            continue
        for m, op in ops.items():
            if m.upper() in ("GET",) + SEND_METHODS and isinstance(op, dict):
                what = str(op.get("summary") or op.get("operationId") or op.get("description") or "")[:80]
                out.append(f"{m.upper()} {path}" + (f" — {what}" if what else ""))
                if len(out) >= limit:
                    return out
    return out


# ------------------------------------------------------------------------------------------------ tools
def _reg(ctx: ToolContext) -> ApiRegistry:
    reg = getattr(ctx, "apis", None)
    if reg is None or not reg.items:
        raise ToolError("no business API added yet: the user can add one in the Connect tab (Connexion)")
    return reg


def _list(ctx: ToolContext, a: dict) -> str:
    reg = _reg(ctx)
    lines = []
    for x in reg.items:
        mode = "reads without asking" if x.get("auto_get") else "reads need approval"
        lines.append(f"- {x['name']}: {x['base_url']} ({mode}{'; can spend money: use api_pay' if x.get('spends') else ''})"
                     + (f"\n  {x['description']}" if x.get("description") else ""))
        for e in (x.get("endpoints") or [])[:40]:
            lines.append(f"    {e}")
    return "\n".join(lines)


def _get(ctx: ToolContext, a: dict) -> str:
    from .netguard import untrusted
    out = _reg(ctx).call(a.get("api"), "GET", a.get("path") or "/", a.get("query"), None, ctx.max_output)
    return untrusted(f"api {a.get('api')} GET {str(a.get('path') or '/')[:120]}", out)


def _method(a: dict) -> str:
    m = str(a.get("method") or "POST").upper()
    if m not in SEND_METHODS:
        raise ToolError("method must be POST, PUT, PATCH or DELETE (use api_get to read)")
    return m


def _send(ctx: ToolContext, a: dict) -> str:
    reg = _reg(ctx)
    try:
        if reg.find(a.get("api")).get("spends"):
            raise ToolError("this API can spend money: use api_pay (the user is always asked)")
    except KeyError:
        pass
    return reg.call(a.get("api"), _method(a), a.get("path") or "/", a.get("query"), a.get("body"), ctx.max_output)


def _pay(ctx: ToolContext, a: dict) -> str:
    reg = _reg(ctx)
    try:
        if not reg.find(a.get("api")).get("spends"):
            raise ToolError("this API is not marked as able to spend money: use api_send")
    except KeyError:
        pass
    return reg.call(a.get("api"), _method(a), a.get("path") or "/", a.get("query"), a.get("body"), ctx.max_output)


def _api_name(a: dict) -> str:
    return _key(str(a.get("api") or ""))


_q = {"type": ["object", "null"], "description": "optional query parameters"}
_b = {"type": ["object", "array", "string", "null"], "description": "optional JSON body"}
TOOLS = [
    Tool("api_list", "List the business APIs the user added (name, base URL, endpoints).", "read", params([]), _list),
    Tool("api_get", "Read from a business API the user added: GET <path> (e.g. /customers?city=Paris).", "network",
         params(["api", "path"], api=s("API name (see api_list)"), path=s("path, e.g. /customers"), query=_q),
         _get, "api_get", _api_name),
    Tool("api_send", "Change data in a business API the user added: POST/PUT/PATCH/DELETE <path> with a JSON body.",
         "send", params(["api", "method", "path"], api=s("API name"), method=s("POST, PUT, PATCH or DELETE"),
                        path=s("path"), query=_q, body=_b), _send, "api", _api_name),
    Tool("api_pay", "Call an API the user marked as able to spend money (payments, orders). Always asked (blocked if spending is off).", "spend",
         params(["api", "method", "path"], api=s("API name"), method=s("POST, PUT, PATCH or DELETE"),
                path=s("path"), query=_q, body=_b), _pay, "api_pay", _api_name),
]
