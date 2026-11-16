"""Everything configurable from the web UI (no terminal): settings, API keys, first-run wizard, restart / quit.

Files, all in the state folder (desktop app: ~/AutonomousAgent/data), written atomically with mode 0600:
  settings.json        language, demo mode, IDC, permissions per category, approval timeout, parallel tasks,
                       workspace folder, phone access. Saved values are applied at start; most of them also
                       apply immediately (see RESTART_KEYS for the ones that need the in-UI Restart button).
  providers-ui.json    API keys entered in the Settings page: provider, model, categories, priority, limits,
                       pricing. NO secret in this file.
  secrets.json         the secrets themselves (0600), unless the OS keychain is available (Python `keyring`
                       package installed and AGENT_KEYRING not 0): then they live in the keychain.
Secrets are read at call time by the key router. They are never sent back to the browser (only masked),
never written to the audit log, the conversation store or the console.

Who may change settings: requests coming straight from this computer. In remote / phone mode, only if
AGENT_REMOTE_SETTINGS=1, and then with authentication AND a CSRF token (agent/harness.py enforces it).
"""
from __future__ import annotations

import json
import os
import re
import secrets as _secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from . import USER_AGENT, __version__, i18n
from .keys import KNOWN_CATEGORIES, LIMIT_FIELDS, TASKS, KeyEntry, KeyRouter
from .permissions import CATEGORIES, MODES, YOLO_PROTECTED

SETTINGS_FILE = "settings.json"
PROVIDERS_FILE = "providers-ui.json"
SECRETS_FILE = "secrets.json"
USAGE_FILE = "usage-ui.json"
RESTART_CODE = 75                      # serve() returns this when the UI asked for a restart
RESTART_KEYS = ("workspace", "max_tasks", "remote")
TUNNELS = ("none", "tailscale", "cloudflared")
PRICING_FIELDS = ("input_per_1m", "output_per_1m", "per_image", "per_audio_minute")
MAX_SECRET = 500

PRESETS: dict[str, dict[str, Any]] = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "key": True,
             "prefix": "gsk_", "keys_url": "https://console.groq.com/keys"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key": True,
               "prefix": "sk-", "keys_url": "https://platform.openai.com/api-keys"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini", "key": True,
                   "prefix": "sk-or-", "keys_url": "https://openrouter.ai/keys"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3.1", "key": False, "prefix": "",
               "keys_url": "https://ollama.com/download"},
    "custom": {"base_url": "", "model": "", "key": True, "prefix": "", "keys_url": ""},
}

DEFAULTS: dict[str, Any] = {
    "version": 1, "setup_done": False, "lang": None, "demo": False, "idc": None, "permissions": {},
    "approval_timeout": None, "max_tasks": None, "workspace": None, "currency": "",
    "remote": {"enabled": False, "tunnel": "none", "public_url": ""},
    "ui_mode": "simple", "trace": "simple", "theme": "auto",
    "parallel": "auto",            # assistants at the same time: auto = one per working key, or 1..MAX_PARALLEL
}
MAX_PARALLEL = 8
MAX_BULK = 50                      # lines in one bulk paste
PROVIDER_LABELS = {"groq": "Groq", "openai": "OpenAI", "openrouter": "OpenRouter", "ollama": "Ollama",
                   "custom": "Custom"}
# Model strength, for the proposed task assignments (plain heuristics, the user can change everything)
FAST_WORDS = ("mini", "nano", "instant", "flash", "haiku", "small", "lite", "1b", "3b", "7b", "8b", "9b",
              "gemma", "free")
STRONG_WORDS = ("gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "o4", "claude", "sonnet", "opus", "70b", "72b",
                "120b", "235b", "405b", "large", "pro", "deepseek", "coder", "kimi", "grok")
VISION_WORDS = ("gpt-4o", "gpt-4.1", "gpt-5", "vision", "claude", "gemini", "llava", "pixtral", "-vl", "grok-4")


UI_MODES = ("simple", "expert")
TRACE_MODES = ("simple", "technical")
THEMES = ("auto", "light", "dark")      # auto = follow the system (prefers-color-scheme)


class SettingsError(ValueError):
    """A validation error with a stable `code` (+ params) so the pages can show it in the user's language;
    str(e) stays a plain English message for logs, the API and the CLI."""

    def __init__(self, code: str, message: str = "", **params: Any):
        super().__init__(message or code.replace("_", " "))
        self.code, self.params = code, {k: str(v) for k, v in params.items()}


# Recognisable key prefixes, most specific first (the wizard also does this in the browser).
KEY_PREFIXES = (("sk-or-", "openrouter"), ("gsk_", "groq"), ("sk-ant-", None), ("sk-", "openai"))


def detect_provider(secret: str | None) -> str | None:
    """Which provider a pasted key belongs to, from its prefix; None if unknown (or unsupported)."""
    s = (secret or "").strip()
    for prefix, provider in KEY_PREFIXES:
        if s.startswith(prefix):
            return provider
    return None


def write_private(path: Path, data: Any) -> None:
    """Atomic JSON write, readable by this user only (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def mask(secret: str | None) -> str:
    if not secret:
        return ""
    if len(secret) <= 12:
        return "••••"
    return f"{secret[:4]}••••{secret[-4:]}"


# ------------------------------------------------------------------------------------------ secrets
def _keyring_module():
    if os.environ.get("AGENT_KEYRING", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    try:
        import keyring  # type: ignore
        from keyring.backends import fail  # type: ignore
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001 - not installed / no backend: file fallback
        return None


class SecretStore:
    """API keys by id: OS keychain when available, else a 0600 JSON file. Never logged, never returned."""

    SERVICE = "autonomous-agent"

    def __init__(self, path: str | os.PathLike, use_keyring: bool | None = None):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._kr = _keyring_module() if use_keyring is not False else None
        self._cache: dict[str, str] | None = None

    @property
    def backend(self) -> str:
        return "keyring" if self._kr is not None else "file"

    def __repr__(self) -> str:
        return f"SecretStore({self.backend})"

    def _file(self) -> dict[str, str]:
        if self._cache is None:
            data = _read(self.path, {})
            self._cache = {k: v for k, v in (data.get("secrets") or {}).items() if isinstance(v, str)} \
                if isinstance(data, dict) else {}
        return self._cache

    def get(self, sid: str) -> str | None:
        with self._lock:
            if self._kr is not None:
                try:
                    v = self._kr.get_password(self.SERVICE, sid)
                    if v:
                        return v
                except Exception:  # noqa: BLE001
                    pass
            return self._file().get(sid)

    def set(self, sid: str, secret: str) -> None:
        with self._lock:
            files = dict(self._file())
            if self._kr is not None:
                try:
                    self._kr.set_password(self.SERVICE, sid, secret)
                    if files.pop(sid, None) is not None:
                        self._cache = files
                        write_private(self.path, {"secrets": files})
                    return
                except Exception:  # noqa: BLE001 - keychain refused: file fallback
                    pass
            files[sid] = secret
            self._cache = files
            write_private(self.path, {"secrets": files})

    def delete(self, sid: str) -> None:
        with self._lock:
            if self._kr is not None:
                try:
                    self._kr.delete_password(self.SERVICE, sid)
                except Exception:  # noqa: BLE001
                    pass
            files = dict(self._file())
            if files.pop(sid, None) is not None:
                self._cache = files
                write_private(self.path, {"secrets": files})

    def has(self, sid: str) -> bool:
        return bool(self.get(sid))


# ------------------------------------------------------------------------------------------ settings
class UserConfig:
    def __init__(self, state_dir: str | os.PathLike):
        self.dir = Path(state_dir)
        self.settings_path = self.dir / SETTINGS_FILE
        self.providers_path = self.dir / PROVIDERS_FILE
        self._lock = threading.RLock()
        raw = _read(self.settings_path, {})
        raw = raw if isinstance(raw, dict) else {}
        self.data: dict[str, Any] = {**json.loads(json.dumps(DEFAULTS)), **raw}
        self.data["remote"] = {**DEFAULTS["remote"], **(raw.get("remote") or {})}
        prov = _read(self.providers_path, {})
        self.providers: list[dict] = [p for p in (prov.get("providers") or []) if isinstance(p, dict)] \
            if isinstance(prov, dict) else []

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            v = self.data.get(key)
            return default if v is None else v

    def save(self) -> None:
        with self._lock:
            write_private(self.settings_path, self.data)

    def save_providers(self) -> None:
        with self._lock:
            write_private(self.providers_path, {"providers": self.providers})


def key_format_ok(provider: str, secret: str) -> bool:
    if not secret or len(secret) < 8 or len(secret) > MAX_SECRET or re.search(r"\s", secret):
        return False
    prefix = PRESETS.get(provider, {}).get("prefix") or ""
    return not prefix or secret.startswith(prefix)


def probe_key(base_url: str, secret: str | None, timeout: float = 8.0) -> dict:
    """Lightweight check, no tokens spent: GET <base_url>/models with the key."""
    req = urllib.request.Request(base_url.rstrip("/") + "/models", method="GET",
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                          **({"Authorization": f"Bearer {secret}"} if secret else {})})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(2_000_000)
            status = r.status
    except urllib.error.HTTPError as e:
        code = "invalid" if e.code in (401, 403) else ("no_models" if e.code == 404 else
                                                       ("rate_limited" if e.code == 429 else "error"))
        return {"ok": code in ("no_models", "rate_limited"), "code": code, "http_status": e.code,
                "ms": round((time.monotonic() - t0) * 1000)}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "code": "unreachable", "detail": type(e).__name__}
    n = None
    try:
        n = len(json.loads(body).get("data") or [])
    except (ValueError, AttributeError):
        pass
    return {"ok": True, "code": "ok", "http_status": status, "models": n, "ms": round((time.monotonic() - t0) * 1000)}


def _num(v: Any, name: str, lo: float = 0, hi: float | None = None, integer: bool = False) -> float | int:
    if isinstance(v, bool):
        raise SettingsError("num_required", f"{name}: a number is required", field=name)
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        raise SettingsError("num_required", f"{name}: a number is required", field=name) from None
    if x != x or x < lo or (hi is not None and x > hi):
        if hi is not None:
            raise SettingsError("num_range", f"{name}: must be between {lo:g} and {hi:g}", field=name, lo=f"{lo:g}", hi=f"{hi:g}")
        raise SettingsError("num_min", f"{name}: must be >= {lo:g}", field=name, lo=f"{lo:g}")
    return int(x) if integer else x


class AppControl:
    """Back end of the Settings page and the first-run wizard (called by the HTTP handler)."""

    def __init__(self, cfg: UserConfig, secrets: SecretStore, router: KeyRouter | None = None,
                 perms: Any = None, harness: Any = None, fallback: dict | None = None,
                 boot: dict | None = None, auth: Any = None, token_where: str | None = None,
                 prober: Callable[[str, str | None], dict] | None = None, home: str | None = None,
                 file_router: Any = None):
        self.cfg, self.secrets, self.perms, self.h = cfg, secrets, perms, harness
        self.router = router or KeyRouter([], cfg.dir / USAGE_FILE, currency=cfg.get("currency", ""))
        self.fallback = fallback or {"provider": "mock"}
        self.file_router = file_router
        self.boot = boot or {}
        self.auth, self.token_where = auth, token_where
        self.prober = prober or probe_key
        self.home = home
        self.stop_cb: Callable[[bool], None] | None = None
        self.csrf_secret = _secrets.token_bytes(32)
        self._lock = threading.RLock()
        self.reload_router()

    # ---------------------------------------------------------------- keys -> router
    def _needs_key(self, p: dict) -> bool:
        return bool(PRESETS.get(p.get("provider") or "custom", PRESETS["custom"])["key"]) or bool(p.get("has_key"))

    def entries(self) -> list[KeyEntry]:
        out = []
        for p in self.cfg.providers:
            if not p.get("enabled", True):
                continue
            pid = p["id"]
            out.append(KeyEntry(name=p["name"], categories=list(p.get("categories") or ["text"]),
                                provider=p.get("provider"), base_url=p.get("base_url") or None,
                                models={"*": p["model"]} if p.get("model") else {},
                                priority=int(p.get("priority", 100)), limits=dict(p.get("limits") or {}),
                                pricing=dict(p.get("pricing") or {}),
                                secret_fn=(lambda pid=pid: self.secrets.get(pid)) if self._needs_key(p) else None,
                                source="ui", tasks=[t for t in (p.get("tasks") or []) if t in TASKS]))
        return out

    def reload_router(self) -> None:
        self.router.replace_entries(self.entries(), self.cfg.get("currency", ""))

    def demo(self) -> bool:
        return bool(self.cfg.get("demo"))

    def backend_mode(self, category: str = "text") -> str:
        """demo (offline mock) | ui (keys from the Settings page) | fallback (.env / providers.yaml / mock)."""
        if self.demo():
            return "demo"
        if self.router.keys_for(category):
            return "ui"
        return "fallback"

    def effective_mode(self) -> str:
        m = self.backend_mode("text")
        if m == "fallback" and self.file_router is None and (self.fallback.get("provider") or "mock") == "mock":
            return "demo"
        return m

    def first_run(self) -> bool:
        return not self.cfg.get("setup_done") and self.effective_mode() == "demo" and not self.cfg.get("demo")

    # ---------------------------------------------------------------- views (no secret ever leaves)
    def providers_view(self) -> list[dict]:
        st = {k["name"]: k for k in self.router.status().get("keys", [])}
        out = []
        for p in sorted(self.cfg.providers, key=lambda p: int(p.get("priority", 100))):
            secret = self.secrets.get(p["id"]) if self._needs_key(p) else None
            s = st.get(p["name"], {})
            out.append({k: p.get(k) for k in ("id", "name", "provider", "base_url", "model", "categories", "priority",
                                               "limits", "pricing", "enabled", "created", "updated")}
                       | {"tasks": list(p.get("tasks") or []), "agents": s.get("agents", []),
                          "in_flight": s.get("in_flight", 0)}
                       | {"key": mask(secret), "has_key": bool(secret), "needs_key": self._needs_key(p),
                          "available": s.get("available", False) if p.get("enabled", True) else False,
                          "cooldown_s": s.get("cooldown_s", 0), "usage": s.get("limits", {}), "used": s.get("used", {})})
        return out

    def restart_needed(self) -> list[str]:
        out = []
        ws = self.cfg.get("workspace")
        if ws and self.boot.get("workspace") and str(Path(ws).expanduser()) != str(self.boot["workspace"]):
            out.append("workspace")
        mt = self.cfg.get("max_tasks")
        if mt and self.boot.get("max_tasks") and int(mt) != int(self.boot["max_tasks"]):
            out.append("max_tasks")
        r, b = self.cfg.get("remote") or {}, self.boot.get("remote") or {}
        if b and (bool(r.get("enabled")) != bool(b.get("enabled")) or
                  (r.get("enabled") and ((r.get("tunnel") or "none") != (b.get("tunnel") or "none")
                                         or (r.get("public_url") or "") != (b.get("public_url") or "")))):
            out.append("remote")
        return out

    def view(self) -> dict:
        h = self.h
        perms = self.perms
        idc = h.idc_config.as_dict() if h is not None else {}
        if h is not None:
            idc["enabled"] = bool(h.settings.get("idc"))
        return {
            "version": __version__, "lang": self.cfg.get("lang") or (h.lang if h is not None else "en"),
            "demo": self.demo(), "mode": self.effective_mode(), "first_run": self.first_run(),
            "setup_done": bool(self.cfg.get("setup_done")),
            "idc": idc,
            "permissions": {"defaults": dict(perms.defaults) if perms is not None else {},
                            "tools": dict(perms.tools) if perms is not None else {},
                            "protected": list(YOLO_PROTECTED), "categories": list(CATEGORIES), "modes": list(MODES)},
            "approval_timeout": h.approvals.timeout if h is not None else self.cfg.get("approval_timeout"),
            "max_tasks": {"saved": self.cfg.get("max_tasks"), "active": h.max_tasks if h is not None else None},
            "workspace": {"saved": self.cfg.get("workspace"), "active": self.boot.get("workspace")},
            "remote": {**(self.cfg.get("remote") or {}), "active": bool(self.auth is not None and self.auth.remote),
                       "public_url": (self.cfg.get("remote") or {}).get("public_url") or "",
                       "active_url": getattr(h, "public_url", None), "token_from_env": self.token_where == "AGENT_HARNESS_TOKEN",
                       "tunnels": list(TUNNELS)},
            "currency": self.cfg.get("currency", ""),
            "ui_mode": self.ui_mode(), "trace": self.trace_mode(), "theme": self.theme(),
            "parallel": {"saved": self.cfg.get("parallel", "auto"), "keys": self.router.usable("text"),
                         "effective": self.parallel_limit("text"), "max": MAX_PARALLEL},
            "tasks": list(TASKS),
            "restart_needed": self.restart_needed(),
            "storage": self.secrets.backend, "home": self.home or str(self.cfg.dir), "secrets_dir": str(self.cfg.dir),
            "presets": {k: dict(p) for k, p in PRESETS.items()},
            "key_prefixes": [[a, b] for a, b in KEY_PREFIXES],
            "categories": list(KNOWN_CATEGORIES), "limit_fields": list(LIMIT_FIELDS),
            "pricing_fields": list(PRICING_FIELDS),
            "fallback": {"provider": self.fallback.get("provider"), "file_keys": self.file_router is not None},
            "can_restart": self.stop_cb is not None,
        }

    def ui_mode(self) -> str:
        m = self.cfg.get("ui_mode")
        return m if m in UI_MODES else "simple"

    def theme(self) -> str:
        m = self.cfg.get("theme")
        return m if m in THEMES else "auto"

    def trace_mode(self) -> str:
        m = self.cfg.get("trace")
        return m if m in TRACE_MODES else "simple"

    def status(self) -> dict:
        return {"first_run": self.first_run(), "mode": self.effective_mode(), "demo": self.demo(),
                "restart_needed": self.restart_needed(), "lang": self.cfg.get("lang"), "version": __version__,
                "ui_mode": self.ui_mode(), "trace": self.trace_mode(), "theme": self.theme()}

    # ---------------------------------------------------------------- providers
    def _find(self, pid: str) -> dict:
        for p in self.cfg.providers:
            if p["id"] == pid:
                return p
        raise KeyError(pid)

    def _clean_provider(self, data: dict, old: dict | None) -> tuple[dict, str | None]:
        provider = str(data.get("provider") or (old or {}).get("provider") or "custom").lower()
        if provider not in PRESETS:
            raise SettingsError("bad_provider", f"provider must be one of {', '.join(PRESETS)}")
        pre = PRESETS[provider]
        name = str(data.get("name") or (old or {}).get("name") or provider).strip()[:60]
        if not re.fullmatch(r"[\w .@+-]{1,60}", name):
            raise SettingsError("bad_name", "name: letters, digits, spaces and . _ - @ + only")
        if any(p["name"] == name and p["id"] != (old or {}).get("id") for p in self.cfg.providers):
            raise SettingsError("name_taken", f"a key named {name!r} already exists", name=name)
        base = str(data.get("base_url") if data.get("base_url") is not None else (old or {}).get("base_url") or pre["base_url"] or "").strip()
        if not base:
            base = pre["base_url"] or ""
        if not re.match(r"^https?://[^\s/]+", base):
            raise SettingsError("bad_url", "base_url: an http(s) URL is required", field="base_url")
        model = str(data.get("model") if data.get("model") is not None else (old or {}).get("model") or pre["model"] or "").strip()[:200]
        if not model:
            model = pre["model"] or ""
        if not model:
            raise SettingsError("model_required", "model: required for a custom provider")
        cats = data.get("categories", (old or {}).get("categories") or ["text"])
        cats = [cats] if isinstance(cats, str) else cats
        if not isinstance(cats, list) or not cats:
            raise SettingsError("no_category", "categories: choose at least one")
        cats = [str(c).strip().lower() for c in cats if str(c).strip()]
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", c) for c in cats) or not cats:
            raise SettingsError("bad_category", "categories: lowercase words (text, code, image, audio_tts...)")
        limits = {}
        for f, v in (data.get("limits", (old or {}).get("limits")) or {}).items():
            if f not in LIMIT_FIELDS:
                raise SettingsError("unknown_field", f"unknown limit {f!r}", field=f)
            if v not in (None, ""):
                limits[f] = _num(v, f, 0)
        pricing = {}
        for f, v in (data.get("pricing", (old or {}).get("pricing")) or {}).items():
            if f not in PRICING_FIELDS:
                raise SettingsError("unknown_field", f"unknown price {f!r}", field=f)
            if v not in (None, ""):
                pricing[f] = _num(v, f, 0)
        if any(f.startswith("cost_") for f in limits) and not any(pricing.values()):
            raise SettingsError("cost_needs_price", "cost limits need a price (per 1M tokens)")
        prio = _num(data.get("priority", (old or {}).get("priority", (len(self.cfg.providers) + 1) * 10)),
                    "priority", 0, 100000, integer=True)
        secret = data.get("key")
        if secret is not None:
            if not isinstance(secret, str):
                raise SettingsError("bad_key", "key must be text")
            secret = secret.strip()
            if secret and (len(secret) > MAX_SECRET or re.search(r"\s", secret)):
                raise SettingsError("key_spaces", "key: no spaces, at most 500 characters")
        if pre["key"] and not secret and not (old and self.secrets.has(old["id"])):
            raise SettingsError("key_required", "key: required for this provider")
        tasks = data.get("tasks", (old or {}).get("tasks") or [])
        tasks = [tasks] if isinstance(tasks, str) else tasks
        if not isinstance(tasks, list) or any(t not in TASKS for t in tasks):
            raise SettingsError("bad_task", f"tasks: choose among {', '.join(TASKS)}", field="tasks")
        tasks = [t for t in TASKS if t in tasks]
        rec = {"name": name, "provider": provider, "base_url": base, "model": model, "categories": cats,
               "priority": prio, "limits": limits, "pricing": pricing, "tasks": tasks,
               "enabled": bool(data.get("enabled", (old or {}).get("enabled", True)))}
        return rec, (secret or None)

    def save_provider(self, data: dict, pid: str | None = None) -> dict:
        with self._lock:
            old = self._find(pid) if pid else None
            rec, secret = self._clean_provider(data, old)
            now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            if old is None:
                rec.update(id=uuid.uuid4().hex[:12], created=now)
                self.cfg.providers.append(rec)
                target = rec
            else:
                old.update(rec)
                target = old
            target["updated"] = now
            if secret:
                self.secrets.set(target["id"], secret)
            target["has_key"] = self.secrets.has(target["id"])
            self.cfg.providers.sort(key=lambda p: int(p.get("priority", 100)))
            self.cfg.save_providers()
            if self.cfg.get("demo") and target.get("enabled", True):
                self.cfg.data["demo"] = False        # a real key was added: leave demo mode
                self.cfg.save()
            self.reload_router()
        self._audit("settings_key_saved", key=target["name"], provider=target["provider"],
                    categories=target["categories"], new=old is None, key_changed=bool(secret))
        return next(v for v in self.providers_view() if v["id"] == target["id"])

    def delete_provider(self, pid: str) -> dict:
        with self._lock:
            p = self._find(pid)
            self.cfg.providers.remove(p)
            self.secrets.delete(pid)
            self.cfg.save_providers()
            self.reload_router()
        self._audit("settings_key_deleted", key=p["name"])
        return {"ok": True, "id": pid}

    def reorder(self, ids: list) -> list[dict]:
        with self._lock:
            known = [p["id"] for p in self.cfg.providers]
            if not isinstance(ids, list) or sorted(map(str, ids)) != sorted(known):
                raise SettingsError("bad_order", "ids: every key id, once, in the new order")
            for i, pid in enumerate(ids):
                self._find(str(pid))["priority"] = (i + 1) * 10
            self.cfg.providers.sort(key=lambda p: int(p.get("priority", 100)))
            self.cfg.save_providers()
            self.reload_router()
        self._audit("settings_key_order", order=[self._find(str(i))["name"] for i in ids])
        return self.providers_view()

    def test_provider(self, pid: str | None = None, data: dict | None = None) -> dict:
        """Lightweight check of a saved key (pid) or of a key typed in the form (data, not saved).
        Offline when AGENT_KEY_TEST=offline (tests, demos): only the key format is checked."""
        if pid:
            p = self._find(pid)
            provider, base, secret = p.get("provider") or "custom", p.get("base_url"), \
                (self.secrets.get(pid) if self._needs_key(p) else None)
        else:
            data = data or {}
            provider = str(data.get("provider") or "custom").lower()
            if provider not in PRESETS:
                raise SettingsError("bad_provider", f"provider must be one of {', '.join(PRESETS)}")
            base = str(data.get("base_url") or PRESETS[provider]["base_url"] or "")
            secret = str(data.get("key") or "").strip() or None
            if not secret and data.get("id"):
                secret = self.secrets.get(str(data["id"]))
        need = PRESETS.get(provider, PRESETS["custom"])["key"]
        if need and not secret:
            return {"ok": False, "code": "missing"}
        if secret and not key_format_ok(provider, secret):
            other = detect_provider(secret)
            if other and other != provider:
                return {"ok": False, "code": "wrong_provider", "detected": other}
            return {"ok": False, "code": "format"}
        if os.environ.get("AGENT_KEY_TEST", "").lower() == "offline":
            return {"ok": True, "code": "offline"}
        if not base or not re.match(r"^https?://", base):
            return {"ok": False, "code": "unreachable"}
        res = self.prober(base, secret)
        return {k: v for k, v in res.items() if k in ("ok", "code", "http_status", "models", "ms", "detail")}

    # ---------------------------------------------------------------- key pool (v0.7)
    def parallel_limit(self, category: str = "text", fallback: int = 3) -> int:
        """How many swarm assistants work at the same time: the saved number, or (auto) one per working
        key of the Settings page (at most MAX_PARALLEL); demo / no key: `fallback`."""
        v = self.cfg.get("parallel", "auto")
        if v != "auto":
            try:
                return max(1, min(MAX_PARALLEL, int(v)))
            except (TypeError, ValueError):
                pass
        if self.backend_mode(category) == "ui":
            n = self.router.usable(category)
            if n > 0:
                return min(MAX_PARALLEL, n)
        return max(1, fallback)

    def pool_view(self) -> dict:
        """Live key pool for the dashboard and the swarm graph: per key (masked) its agents and usage."""
        st = self.router.status()
        keys = [{"name": k["name"], "key": k["key"], "provider": k.get("provider"), "available": k.get("available"),
                 "tasks": k.get("tasks", []), "agents": k.get("agents", []), "in_flight": k.get("in_flight", 0),
                 "cooldown_s": k.get("cooldown_s", 0), "used": k.get("used", {}), "limits": k.get("limits", {})}
                for k in st.get("keys", [])]
        return {"keys": keys, "parallel": self.parallel_limit("text"), "mode": self.effective_mode()}

    @staticmethod
    def parse_bulk(text: Any) -> list[dict]:
        """One key per line, optionally "label: key" (or "label = key", "label key", "export NAME=key").
        Returns [{"line", "label", "key", "provider", "code"?}]; code set when the line cannot be used."""
        if not isinstance(text, str):
            raise SettingsError("bad_key", "keys: text expected")
        out: list[dict] = []
        seen: set[str] = set()
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.strip().strip("\ufeff").strip()
            if not line or line.startswith("#"):
                continue
            if len(out) >= MAX_BULK:
                over = {"line": n, "label": "", "key": "", "provider": None}
                over["code"] = "too_many"          # a per-line status (bulkc.*), not a request error
                out.append(over)
                break
            if line.lower().startswith("export "):
                line = line[7:].strip()
            m = re.match(r"^(.*?)[\s:=]*['\"]?([^\s'\":=]{8,})['\"]?[,;]?$", line)
            key = m.group(2) if m else ""
            label = (m.group(1) if m else line).strip().strip(":=-–—").strip().strip("'\"")[:60] if m else ""
            label = re.sub(r"[^\w .@+-]", "", label).strip()[:60]
            prov = detect_provider(key)
            low = label.lower()
            hinted = next((p for p in ("openrouter", "groq", "openai", "ollama") if p in low), None)
            if prov is None or (hinted == "openrouter" and prov == "openai"):
                prov = hinted if hinted in ("openrouter", "groq", "openai") else prov
            row = {"line": n, "label": label, "key": key, "provider": prov}
            if not key or len(key) > MAX_SECRET:
                row["code"] = "format"
            elif prov is None:
                row["code"] = "unknown_provider"
            elif key in seen:
                row["code"] = "duplicate"
            seen.add(key)
            out.append(row)
        return out

    def _unique_name(self, label: str, provider: str, taken: set[str]) -> str:
        base = label if label and re.fullmatch(r"[\w .@+-]{1,60}", label) else PROVIDER_LABELS.get(provider, provider)
        if re.fullmatch(r"(?i)(export )?[A-Z0-9_]*(API_?KEY|TOKEN|KEY)[A-Z0-9_]*", base or ""):
            base = PROVIDER_LABELS.get(provider, provider)       # GROQ_API_KEY=... -> "Groq"
        name, i = base[:60], 2
        while name in taken:
            name = f"{base[:55]} {i}"
            i += 1
        taken.add(name)
        return name

    def bulk_add(self, text: Any, save: bool = True) -> dict:
        """Paste many keys at once: parse, detect the provider, test them all at the same time, save the
        working ones. Returns one line per key (masked, never the secret) and a proposed task assignment."""
        rows = self.parse_bulk(text)
        if not rows:
            raise SettingsError("nothing", "no key found: paste one key per line")
        existing: set[str] = set()
        for p in self.cfg.providers:
            sec = self.secrets.get(p["id"]) if self._needs_key(p) else None
            if sec:
                existing.add(sec)
        todo = []
        for r in rows:
            if "code" not in r and r["key"] in existing:
                r["code"] = "already_saved"
            if "code" not in r and not key_format_ok(r["provider"], r["key"]):
                r["code"] = "format"
            if "code" not in r:
                todo.append(r)

        def test(r: dict) -> dict:
            try:
                return self.test_provider(data={"provider": r["provider"], "key": r["key"]})
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "code": "error", "detail": type(e).__name__}
        if todo:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(8, len(todo)), thread_name_prefix="keytest") as ex:
                for r, res in zip(todo, ex.map(test, todo)):
                    r["ok"], r["code"] = bool(res.get("ok")), res.get("code") or ("ok" if res.get("ok") else "error")
                    if res.get("http_status"):
                        r["http_status"] = res["http_status"]
        saved = []
        if save:
            with self._lock:
                taken = {p["name"] for p in self.cfg.providers}
                for r in rows:
                    if not r.get("ok"):
                        continue
                    name = self._unique_name(r["label"], r["provider"], taken)
                    try:
                        v = self.save_provider({"provider": r["provider"], "key": r["key"], "name": name})
                    except SettingsError as e:
                        r["ok"], r["code"] = False, e.code
                        continue
                    r["id"], r["name"] = v["id"], v["name"]
                    saved.append(v["id"])
        out = []
        for r in rows:
            out.append({"line": r["line"], "label": r.get("label", ""), "provider": r.get("provider"),
                        "key": mask(r.get("key")) if r.get("key") else "", "ok": bool(r.get("ok")),
                        "code": r.get("code", "error"), "id": r.get("id"), "name": r.get("name"),
                        **({"http_status": r["http_status"]} if r.get("http_status") else {})})
        self._audit("settings_keys_bulk", lines=len(rows), saved=len(saved),
                    failed=sum(1 for r in out if not r["ok"]))
        return {"results": out, "saved": len(saved), "failed": sum(1 for r in out if not r["ok"]),
                "proposal": self.propose_tasks() if saved else [], "providers": self.providers_view(),
                "parallel": self.parallel_limit("text")}

    @staticmethod
    def key_class(provider: str | None, model: str | None) -> tuple[int, bool]:
        """(strength 0 fast/free, 1 fast paid, 2 strong; vision?) from the provider and the model name."""
        m = (model or "").lower()
        free = provider in ("groq", "ollama") or ":free" in m
        vision = (not free) and any(w in m for w in VISION_WORDS)
        if free:
            return 0, vision
        fast = any(w in re.split(r"[/:]", m)[-1] for w in FAST_WORDS)
        strong = any(w in m for w in STRONG_WORDS)
        return (2 if strong and not fast else 1), vision

    def propose_tasks(self) -> list[dict]:
        """Sensible task types for every enabled key (not saved): fast / free keys for research and
        summaries, stronger models for writing and code; with keys of one kind, the jobs are spread."""
        provs = [p for p in self.cfg.providers if p.get("enabled", True)]
        if not provs:
            return []
        cls = {p["id"]: self.key_class(p.get("provider"), p.get("model")) for p in provs}
        lo, hi = min(c[0] for c in cls.values()), max(c[0] for c in cls.values())
        plan: dict[str, list[str]] = {p["id"]: [] for p in provs}
        why: dict[str, str] = {}
        if lo != hi:
            for p in provs:
                s = cls[p["id"]][0]
                if s == lo:
                    plan[p["id"]] += ["research", "analysis"]
                    why[p["id"]] = "fast_free" if s == 0 else "fast"
                elif s == hi:
                    plan[p["id"]] += ["writing", "code", "general"]
                    why[p["id"]] = "strong"
                else:
                    plan[p["id"]] += ["analysis", "general"]
                    why[p["id"]] = "middle"
        else:
            groups = ["research", "writing", "code", "analysis"]
            n = len(provs)
            for j, g in enumerate(groups):
                plan[provs[j % n]["id"]].append(g)
            for i, p in enumerate(provs):
                if i >= len(groups) or i == 0:
                    plan[p["id"]].append("general")
                why[p["id"]] = "only" if n == 1 else "spread"
        for p in provs:
            if cls[p["id"]][1]:
                plan[p["id"]].append("vision")
        out = []
        for p in provs:
            secret = self.secrets.get(p["id"]) if self._needs_key(p) else None
            out.append({"id": p["id"], "name": p["name"], "provider": p.get("provider"), "model": p.get("model"),
                        "key": mask(secret), "current": list(p.get("tasks") or []),
                        "tasks": [t for t in TASKS if t in plan[p["id"]]], "why": why.get(p["id"], "spread"),
                        "strength": cls[p["id"]][0]})
        return out

    def set_tasks(self, assign: Any) -> list[dict]:
        """{id: [tasks]} or {id: {"tasks": [...], "model": "..."}}: the user accepted / adjusted the proposal."""
        if not isinstance(assign, dict) or not assign:
            raise SettingsError("bad_object", "assign: {key id: [task types]}", field="assign")
        clean: dict[str, tuple[list[str], str | None]] = {}
        for pid, v in assign.items():
            try:
                self._find(str(pid))
            except KeyError:
                raise SettingsError("unknown_key", f"unknown key id {pid!r}", field=str(pid)) from None
            model = None
            if isinstance(v, dict):
                model = v.get("model")
                v = v.get("tasks", [])
            v = [v] if isinstance(v, str) else v
            if not isinstance(v, list) or any(t not in TASKS for t in v):
                raise SettingsError("bad_task", f"tasks: choose among {', '.join(TASKS)}", field="tasks")
            if model is not None:
                model = str(model).strip()[:200]
                if model and re.search(r"\s", model):
                    raise SettingsError("bad_model", "model: no spaces", field="model")
            clean[str(pid)] = ([t for t in TASKS if t in v], model or None)
        with self._lock:
            for pid, (tasks, model) in clean.items():
                p = self._find(pid)
                p["tasks"] = tasks
                if model:
                    p["model"] = model
                p["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            self.cfg.save_providers()
            self.reload_router()
        self._audit("settings_key_tasks", keys={self._find(pid)["name"]: t for pid, (t, _) in clean.items()})
        return self.providers_view()

    # ---------------------------------------------------------------- settings
    def update(self, data: dict) -> dict:
        if not isinstance(data, dict) or not data:
            raise SettingsError("nothing", "nothing to change")
        h, cfg = self.h, self.cfg
        changes: dict[str, Any] = {}
        # validate everything first, then apply
        if "lang" in data:
            if data["lang"] not in i18n.LANGS:
                raise SettingsError("bad_choice", "lang must be en or fr", field="lang")
            changes["lang"] = data["lang"]
        if "demo" in data:
            if not isinstance(data["demo"], bool):
                raise SettingsError("bad_bool", "demo must be true or false", field="demo")
            changes["demo"] = data["demo"]
        for k, allowed in (("ui_mode", UI_MODES), ("trace", TRACE_MODES), ("theme", THEMES)):
            if k in data:
                if data[k] not in allowed:
                    raise SettingsError("bad_choice", f"{k} must be one of {', '.join(allowed)}", field=k)
                changes[k] = data[k]
        if "parallel" in data:
            v = data["parallel"]
            changes["parallel"] = "auto" if v in ("auto", None, "") else _num(v, "parallel", 1, MAX_PARALLEL, integer=True)
        if "currency" in data:
            cur = str(data["currency"] or "").strip()[:8]
            if cur and not re.fullmatch(r"[A-Za-z€$£¥ ]{1,8}", cur):
                raise SettingsError("bad_currency", "currency: up to 8 letters")
            changes["currency"] = cur
        if "approval_timeout" in data:
            changes["approval_timeout"] = _num(data["approval_timeout"], "approval_timeout", 10, 3600, integer=True)
        if "max_tasks" in data:
            changes["max_tasks"] = _num(data["max_tasks"], "max_tasks", 1, 16, integer=True)
        if "workspace" in data:
            ws = str(data["workspace"] or "").strip()
            if ws:
                p = Path(ws).expanduser()
                if not p.is_absolute():
                    raise SettingsError("ws_absolute", "workspace: a full folder path is required (e.g. /Users/me/AgentWork)")
                p = p.resolve()
                if p == Path(p.anchor) or p == Path.home().resolve():
                    raise SettingsError("ws_too_wide", "workspace: choose a dedicated folder, not the disk root or your whole home folder")
                if p.exists() and not p.is_dir():
                    raise SettingsError("ws_is_file", "workspace: this path is a file")
                ws = str(p)
            changes["workspace"] = ws or None
        if "permissions" in data:
            pd = data["permissions"]
            if not isinstance(pd, dict):
                raise SettingsError("bad_object", "permissions: {category: mode}", field="permissions")
            for c, m in pd.items():
                if c not in CATEGORIES:
                    raise SettingsError("unknown_field", f"permissions: unknown category {c!r}", field=str(c))
                if m not in MODES:
                    raise SettingsError("bad_choice", f"permissions: invalid mode {m!r}", field=str(c))
                if c in YOLO_PROTECTED and m == "allow":
                    raise SettingsError("perm_protected", f"permissions: '{c}' can never be approved automatically (ask or deny only)", field=c)
            changes["permissions"] = dict(pd)
        if "idc" in data:
            from .idc import IDCConfig
            d = data["idc"]
            if not isinstance(d, dict):
                raise SettingsError("bad_object", "idc: settings object expected", field="idc")
            base = (h.idc_config.as_dict() if h is not None else IDCConfig().as_dict())
            types = {k: type(v) for k, v in base.items()}
            new = dict(base)
            for k, v in d.items():
                if k not in types:
                    raise SettingsError("unknown_field", f"idc: unknown setting {k!r}", field=str(k))
                if types[k] is bool:
                    if not isinstance(v, bool):
                        raise SettingsError("bad_bool", f"idc: {k} must be true or false", field=k)
                    new[k] = v
                else:
                    new[k] = _num(v, f"idc.{k}", 0, 1e9, integer=types[k] is int)
            changes["idc"] = IDCConfig(**new).validate()
        if "remote" in data:
            r = data["remote"]
            if not isinstance(r, dict):
                raise SettingsError("bad_object", "remote: settings object expected", field="remote")
            cur = dict(cfg.get("remote") or {})
            if "enabled" in r:
                if not isinstance(r["enabled"], bool):
                    raise SettingsError("bad_bool", "remote.enabled must be true or false", field="remote.enabled")
                cur["enabled"] = r["enabled"]
            if "tunnel" in r:
                if r["tunnel"] not in TUNNELS:
                    raise SettingsError("bad_choice", f"remote.tunnel must be one of {', '.join(TUNNELS)}", field="remote.tunnel")
                cur["tunnel"] = r["tunnel"]
            if "public_url" in r:
                u = str(r["public_url"] or "").strip()
                if u and not re.match(r"^https?://[^\s/]+", u):
                    raise SettingsError("bad_url", "remote.public_url: an http(s) address", field="remote.public_url")
                cur["public_url"] = u
            changes["remote"] = cur
        # apply
        with self._lock:
            for k, v in changes.items():
                if k == "idc":
                    cfg.data["idc"] = v.as_dict()
                    if h is not None:
                        h.idc_config = v
                        h.update_settings({"idc": bool(v.enabled)})
                elif k == "permissions":
                    merged = {**(cfg.get("permissions") or {}), **v}
                    cfg.data["permissions"] = merged
                    if self.perms is not None:
                        self.perms.defaults.update(v)
                else:
                    cfg.data[k] = v
                if k == "lang" and h is not None:
                    h.lang = v
                if k == "approval_timeout" and h is not None:
                    h.approvals.timeout = float(v)
                if k == "currency":
                    self.router.currency = v
            cfg.save()
        self._audit("settings_changed", fields=sorted(changes))
        return self.view()

    def setup(self, data: dict) -> dict:
        upd = {k: data[k] for k in ("lang", "demo") if k in data}
        if upd:
            self.update(upd)
        if data.get("done"):
            self.cfg.data["setup_done"] = True
            self.cfg.save()
        return self.status()

    def new_token(self) -> dict:
        if self.token_where == "AGENT_HARNESS_TOKEN":
            raise SettingsError("token_env", "the token comes from AGENT_HARNESS_TOKEN: change it there")
        from . import remote
        tok = remote.rotate_token(self.cfg.dir)
        n = 0
        if self.auth is not None and self.auth.remote:
            self.auth.token = tok
            n = self.auth.revoke_all()
        self._audit("remote_token_rotated", sessions_signed_out=n)
        return {"token": tok, "active": bool(self.auth is not None and self.auth.remote), "sessions_signed_out": n}

    def request_stop(self, restart: bool) -> bool:
        if self.stop_cb is None:
            return False
        self._audit("app_restart" if restart else "app_quit")
        cb = self.stop_cb
        threading.Timer(0.3, cb, args=(restart,)).start()
        return True

    def _audit(self, event: str, **kw: Any) -> None:
        if self.h is not None:
            try:
                self.h._audit(None, event=event, agent="user", **kw)
            except Exception:  # noqa: BLE001
                pass


# ------------------------------------------------------------------------------------------ startup
def apply_startup(args: Any, cfg: UserConfig, defaults: dict) -> None:
    """Saved UI settings -> serve() arguments. Flags given on the command line win (`defaults` holds the
    argparse defaults, a value different from its default was typed by the user)."""
    if cfg.get("lang") and not getattr(args, "_lang_explicit", False):
        args.lang = cfg.get("lang")
    for k in ("approval_timeout", "max_tasks"):
        if cfg.get(k) and getattr(args, k, None) == defaults.get(k):
            setattr(args, k, cfg.get(k))
    if cfg.get("workspace") and getattr(args, "state_dir", None):
        args.workspace = cfg.get("workspace")


def apply_permissions(perms: Any, cfg: UserConfig) -> None:
    for c, m in (cfg.get("permissions") or {}).items():
        if c in CATEGORIES and m in MODES and not (c in YOLO_PROTECTED and m == "allow"):
            perms.defaults[c] = m


def apply_idc(idc_cfg: Any, cfg: UserConfig, explicit: bool) -> Any:
    saved = cfg.get("idc")
    if not isinstance(saved, dict):
        return idc_cfg
    from .idc import IDCConfig
    base = idc_cfg.as_dict()
    for k, v in saved.items():
        if k in base and not (k == "enabled" and explicit):
            base[k] = v
    try:
        return IDCConfig(**base).validate()
    except (TypeError, ValueError):
        return idc_cfg
