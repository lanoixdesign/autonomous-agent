"""Several API keys, by category, with limits that are never exceeded: the key router.

Config (`providers.yaml`, git-ignored; see providers.example.yaml): a list of keys. Each key names the
ENVIRONMENT VARIABLE that holds the secret (`key_env`), never the secret itself. Categories are free
strings (text, code, image, audio_tts, audio_stt, embeddings, ... add your own).

Routing: `acquire(category)` tries the keys of that category by `priority` (lower first) and returns
a lease on the first one that (a) has its env var set, (b) is not cooling down after a 429/5xx, and
(c) can take the request WITHOUT exceeding any limit: the request is checked and RESERVED up front
(requests, estimated tokens, estimated cost, images, audio minutes), so concurrent calls cannot
overshoot together. The caller then `commit()`s the real usage, or `fail(status)`s (429 / 5xx put the
key on cooldown and the caller moves on to the next key). If no key can serve the category,
`KeysExhausted` is raised with the reason for each key: no limit is ever exceeded.

Usage counters (per key: per minute, per day, per month, local time) are thread-safe and persisted
in `usage.json` (atomic rewrite), so limits survive restarts. Each limit hit is audit-logged once per
key, limit and period (`event: key_limit`).
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

KNOWN_CATEGORIES = ("text", "code", "image", "audio_tts", "audio_stt", "embeddings")
LIMIT_FIELDS = ("requests_per_minute", "requests_per_day", "tokens_per_day", "tokens_per_month",
                "cost_per_day", "cost_per_month", "images_per_day", "audio_minutes_per_day")
PRESETS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}
CHAT_CATEGORIES = ("text", "code")   # categories served by the chat-completions backend
MIN_COMPLETION = 16                   # a chat request needs at least this many completion tokens
COOLDOWN_429 = 60.0
COOLDOWN_ERROR = 30.0


class KeysExhausted(Exception):
    def __init__(self, category: str, reasons: dict[str, str]):
        self.category, self.reasons = category, reasons
        detail = "; ".join(f"{k}: {v}" for k, v in reasons.items()) or "no key configured for it"
        super().__init__(f"no API key can serve category '{category}' without exceeding a limit ({detail})")


def mask(secret: str | None) -> str:
    if not secret:
        return "(not set)"
    if len(secret) <= 12:
        return "****"
    return f"{secret[:4]}…{secret[-4:]}"


@dataclass
class KeyEntry:
    name: str
    categories: list[str]
    key_env: str | None = None          # None: no key needed (e.g. local Ollama)
    provider: str | None = None
    base_url: str | None = None
    models: dict[str, str] = field(default_factory=dict)   # category -> model ("*" = default)
    priority: int = 100
    limits: dict[str, float] = field(default_factory=dict)
    pricing: dict[str, float] = field(default_factory=dict)  # input_per_1m, output_per_1m, per_image, per_audio_minute
    # Keys entered in the Settings page: the secret comes from the local secret store (agent/userconfig.py),
    # read at call time, never from this object's fields (so it never ends up in a repr, a log or the audit).
    secret_fn: Callable[[], str | None] | None = field(default=None, repr=False, compare=False)
    source: str = "file"                 # "file" (providers.yaml) | "ui" (Settings page)

    def secret(self) -> str | None:
        if self.secret_fn is not None:
            return self.secret_fn() or None
        return os.environ.get(self.key_env) if self.key_env else None

    @property
    def needs_key(self) -> bool:
        return bool(self.key_env) or self.secret_fn is not None

    def available(self) -> bool:
        return not self.needs_key or bool(self.secret())

    def missing_reason(self) -> str:
        return f"environment variable {self.key_env} is not set" if self.key_env else "no key saved"

    def model_for(self, category: str) -> str | None:
        return self.models.get(category) or self.models.get("*")

    def cost(self, prompt_tokens: float = 0, completion_tokens: float = 0, images: float = 0,
             audio_minutes: float = 0) -> float:
        p = self.pricing
        return (prompt_tokens * p.get("input_per_1m", 0) / 1e6 + completion_tokens * p.get("output_per_1m", 0) / 1e6
                + images * p.get("per_image", 0) + audio_minutes * p.get("per_audio_minute", 0))


def parse(data: dict) -> tuple[list[KeyEntry], str]:
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list) or not data["keys"]:
        raise ValueError("keys file: a non-empty 'keys:' list is required")
    out, names = [], set()
    for i, k in enumerate(data["keys"]):
        if not isinstance(k, dict):
            raise ValueError(f"keys file: entry {i} must be a mapping")
        name = str(k.get("name") or f"key{i + 1}")
        if name in names:
            raise ValueError(f"keys file: duplicate name {name!r}")
        names.add(name)
        if "key" in k or "api_key" in k:
            raise ValueError(f"keys file: {name}: put the secret in an environment variable and use key_env")
        cats = k.get("categories") or ["text"]
        cats = [cats] if isinstance(cats, str) else [str(c) for c in cats]
        provider = k.get("provider")
        base = k.get("base_url") or PRESETS.get(str(provider or "").lower())
        models = k.get("models") or {}
        if isinstance(models, str):
            models = {"*": models}
        if k.get("model"):
            models = {"*": str(k["model"]), **models}
        limits = {}
        for f, v in (k.get("limits") or {}).items():
            if f not in LIMIT_FIELDS:
                raise ValueError(f"keys file: {name}: unknown limit {f!r} (known: {', '.join(LIMIT_FIELDS)})")
            if v is not None:
                limits[f] = float(v)
        if any(f.startswith("cost_") for f in limits) and not k.get("pricing"):
            raise ValueError(f"keys file: {name}: cost limits need 'pricing'")
        out.append(KeyEntry(name=name, categories=cats, key_env=k.get("key_env"), provider=provider,
                            base_url=base, models={str(a): str(b) for a, b in models.items()},
                            priority=int(k.get("priority", 100)), limits=limits,
                            pricing={a: float(b) for a, b in (k.get("pricing") or {}).items()}))
    return out, str(data.get("currency") or "")


def load_file(path: str | os.PathLike) -> tuple[list[KeyEntry], str]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return parse(json.loads(text))
    try:
        import yaml  # type: ignore
        return parse(yaml.safe_load(text))
    except ImportError:
        from . import miniyaml
        return parse(miniyaml.loads(text))


# ------------------------------------------------------------------------------- usage
def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _month(t: float) -> str:
    return time.strftime("%Y-%m", time.localtime(t))


COUNTERS = ("requests_day", "tokens_day", "tokens_month", "cost_day", "cost_month", "images_day", "audio_minutes_day")
# limit field -> (counter, amount key)
LIMIT_MAP = {
    "requests_per_day": ("requests_day", "requests"),
    "tokens_per_day": ("tokens_day", "tokens"),
    "tokens_per_month": ("tokens_month", "tokens"),
    "cost_per_day": ("cost_day", "cost"),
    "cost_per_month": ("cost_month", "cost"),
    "images_per_day": ("images_day", "images"),
    "audio_minutes_per_day": ("audio_minutes_day", "audio_minutes"),
}


class Lease:
    """One reserved request on one key. Call exactly one of commit() / fail() / release()."""

    def __init__(self, router: "KeyRouter", entry: KeyEntry, category: str, reserved: dict[str, float],
                 max_completion_tokens: int | None):
        self.router, self.entry, self.category, self.reserved = router, entry, category, reserved
        self.max_completion_tokens = max_completion_tokens
        self.done = False

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def api_key(self) -> str | None:
        return self.entry.secret()

    @property
    def base_url(self) -> str | None:
        return self.entry.base_url

    @property
    def model(self) -> str | None:
        return self.entry.model_for(self.category)

    def commit(self, prompt_tokens: int = 0, completion_tokens: int = 0, images: float = 0,
               audio_minutes: float = 0) -> None:
        self.router._finish(self, {"tokens": prompt_tokens + completion_tokens,
                                   "cost": self.entry.cost(prompt_tokens, completion_tokens, images, audio_minutes),
                                   "images": images, "audio_minutes": audio_minutes})

    def fail(self, status: int | None = None, retry_after: float | None = None) -> None:
        """The request failed. 429 / 5xx / network errors put the key on cooldown. The request stays
        counted (requests per minute / day); tokens, cost, images and audio are not charged."""
        cool = None
        if status == 429:
            cool = retry_after or COOLDOWN_429
        elif status is None or status >= 500:
            cool = COOLDOWN_ERROR
        self.router._finish(self, {"tokens": 0, "cost": 0, "images": 0, "audio_minutes": 0}, cooldown=cool, status=status)

    def release(self) -> None:
        """The request was not sent (or was rejected before any usage): only the request is counted."""
        self.router._finish(self, {"tokens": 0, "cost": 0, "images": 0, "audio_minutes": 0})

    def __enter__(self) -> "Lease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.done:
            if exc_type is None:
                self.commit(images=self.reserved.get("images", 0), audio_minutes=self.reserved.get("audio_minutes", 0))
            else:
                self.fail(getattr(exc, "status", None))


class KeyRouter:
    def __init__(self, entries: list[KeyEntry], usage_path: str | os.PathLike | None = None,
                 audit: Any = None, currency: str = "", clock: Callable[[], float] = time.time,
                 default_max_completion: int = 4096):
        self.entries = sorted(entries, key=lambda e: e.priority)
        self.usage_path = Path(usage_path) if usage_path else None
        self.audit, self.currency, self.clock = audit, currency, clock
        self.default_max_completion = default_max_completion
        self._lock = threading.Lock()
        self._usage: dict[str, dict] = {}
        self._pending: dict[str, dict[str, float]] = {e.name: {} for e in self.entries}
        self._logged: set[tuple] = set()
        self._load()

    @classmethod
    def from_file(cls, path: str | os.PathLike, usage_path: str | os.PathLike | None = None,
                  audit: Any = None) -> "KeyRouter":
        entries, currency = load_file(path)
        return cls(entries, usage_path, audit, currency)

    def replace_entries(self, entries: list[KeyEntry], currency: str | None = None) -> None:
        """Swap the key list while running (Settings page): usage counters are kept by key name, requests
        already in flight finish on the key they reserved."""
        with self._lock:
            self.entries = sorted(entries, key=lambda e: e.priority)
            for e in self.entries:
                self._pending.setdefault(e.name, {})
            if currency is not None:
                self.currency = currency

    # ---------------- persistence
    def _load(self) -> None:
        if self.usage_path and self.usage_path.is_file():
            try:
                data = json.loads(self.usage_path.read_text(encoding="utf-8"))
                self._usage = {k: v for k, v in data.get("keys", {}).items() if isinstance(v, dict)}
            except (ValueError, OSError):
                self._usage = {}

    def _save(self) -> None:
        if not self.usage_path:
            return
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.usage_path.with_name(self.usage_path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"keys": self._usage}, indent=1), encoding="utf-8")
        os.replace(tmp, self.usage_path)

    def _u(self, name: str, now: float) -> dict:
        """Usage record of one key, rolled over to the current day / month (call under lock)."""
        u = self._usage.setdefault(name, {})
        day, month = _day(now), _month(now)
        if u.get("day") != day:
            u.update(day=day, requests_day=0, tokens_day=0, cost_day=0.0, images_day=0, audio_minutes_day=0)
        if u.get("month") != month:
            u.update(month=month, tokens_month=0, cost_month=0.0)
        u["minute"] = [t for t in u.get("minute", []) if now - t < 60]
        for c in COUNTERS:
            u.setdefault(c, 0)
        return u

    # ---------------- routing
    def keys_for(self, category: str) -> list[KeyEntry]:
        return [e for e in self.entries if category in e.categories]

    def acquire(self, category: str, prompt_tokens: int = 0, max_completion_tokens: int | None = None,
                images: float = 0, audio_minutes: float = 0) -> Lease:
        """Reserve one request on the best key for `category`, or raise KeysExhausted."""
        reasons: dict[str, str] = {}
        with self._lock:
            now = self.clock()
            for e in self.keys_for(category):
                if not e.available():
                    reasons[e.name] = e.missing_reason()
                    continue
                cool = self._usage.get(e.name, {}).get("cooldown_until", 0)
                if cool > now:
                    reasons[e.name] = f"cooling down for {math.ceil(cool - now)}s after an error"
                    continue
                u, pend = self._u(e.name, now), self._pending[e.name]
                chat = category in CHAT_CATEGORIES
                completion = 0
                if chat:
                    completion = max_completion_tokens or self.default_max_completion
                    # shrink the completion budget to what the token / cost limits still allow
                    for f in ("tokens_per_day", "tokens_per_month"):
                        if f in e.limits:
                            left = e.limits[f] - u[LIMIT_MAP[f][0]] - pend.get("tokens", 0) - prompt_tokens
                            completion = min(completion, int(left))
                    out_price = e.pricing.get("output_per_1m", 0)
                    for f in ("cost_per_day", "cost_per_month"):
                        if f in e.limits and out_price > 0:
                            left = (e.limits[f] - u[LIMIT_MAP[f][0]] - pend.get("cost", 0)
                                    - e.cost(prompt_tokens, 0, images, audio_minutes))
                            completion = min(completion, int(left * 1e6 / out_price))
                amounts = {"requests": 1, "tokens": prompt_tokens + max(completion, 0),
                           "cost": e.cost(prompt_tokens, max(completion, 0), images, audio_minutes),
                           "images": images, "audio_minutes": audio_minutes}
                hit = None
                wanted = max_completion_tokens or self.default_max_completion
                if chat and completion < min(MIN_COMPLETION, wanted):
                    hit = "token or cost limit reached"
                else:
                    hit = self._would_exceed(e, u, pend, amounts)
                if hit:
                    reasons[e.name] = hit
                    self._log_limit(e, category, hit, now)
                    continue
                for k, v in amounts.items():
                    pend[k] = pend.get(k, 0) + v
                u["minute"].append(now)
                u["requests_day"] += 1
                self._save()
                return Lease(self, e, category, amounts, completion if chat else None)
        raise KeysExhausted(category, reasons)

    @staticmethod
    def _would_exceed(e: KeyEntry, u: dict, pend: dict, amounts: dict) -> str | None:
        """Name of the first limit this request would exceed (usage + in-flight + this request)."""
        lim = e.limits
        if "requests_per_minute" in lim and len(u["minute"]) + 1 > lim["requests_per_minute"]:
            return "requests_per_minute limit reached"
        for f, (counter, key) in LIMIT_MAP.items():
            if f in lim and u[counter] + pend.get(key, 0) * (key != "requests") + amounts.get(key, 0) > lim[f] + 1e-9:
                return f"{f} limit reached"
        return None

    def _log_limit(self, e: KeyEntry, category: str, reason: str, now: float) -> None:
        tag = (e.name, reason, _day(now) if "day" in reason or "minute" in reason else _month(now))
        if tag in self._logged:
            return
        self._logged.add(tag)
        if self.audit is not None:
            self.audit.record(event="key_limit", entry=e.name, category=category, reason=reason)

    def _finish(self, lease: Lease, used: dict[str, float], cooldown: float | None = None,
                status: int | None = None) -> None:
        with self._lock:
            if lease.done:
                return
            lease.done = True
            now = self.clock()
            name = lease.entry.name
            pend = self._pending.setdefault(name, {})
            for k, v in lease.reserved.items():
                pend[k] = max(0.0, pend.get(k, 0) - v)
            u = self._u(name, now)
            u["tokens_day"] += used.get("tokens", 0)
            u["tokens_month"] += used.get("tokens", 0)
            u["cost_day"] = round(u["cost_day"] + used.get("cost", 0), 8)
            u["cost_month"] = round(u["cost_month"] + used.get("cost", 0), 8)
            u["images_day"] += used.get("images", 0)
            u["audio_minutes_day"] += used.get("audio_minutes", 0)
            if cooldown:
                u["cooldown_until"] = now + cooldown   # persisted: survives a restart
            self._save()
        if cooldown and self.audit is not None:
            self.audit.record(event="key_error", entry=name, category=lease.category, status=status,
                              cooldown_s=round(cooldown, 1))

    # ---------------- reporting (keys are masked)
    def status(self) -> dict:
        with self._lock:
            now = self.clock()
            keys = []
            for e in self.entries:
                u = self._u(e.name, now)
                used = {"requests_per_minute": len(u["minute"])}
                used.update({f: u[c] for f, (c, _) in LIMIT_MAP.items()})
                limits = {f: {"limit": v, "used": round(used[f], 6), "remaining": round(max(0.0, v - used[f]), 6)}
                          for f, v in e.limits.items()}
                keys.append({"name": e.name, "provider": e.provider, "base_url": e.base_url,
                             "key": mask(e.secret()) if e.needs_key else "(no key)", "key_env": e.key_env,
                             "source": e.source,
                             "categories": e.categories, "priority": e.priority, "models": e.models,
                             "available": e.available(),
                             "cooldown_s": max(0, math.ceil(u.get("cooldown_until", 0) - now)),
                             "limits": limits, "used": {f: round(v, 6) for f, v in used.items()}})
            cats = sorted({c for e in self.entries for c in e.categories})
            return {"currency": self.currency, "keys": keys,
                    "categories": {c: [e.name for e in self.keys_for(c)] for c in cats}}
