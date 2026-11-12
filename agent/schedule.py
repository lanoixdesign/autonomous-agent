"""Scheduled prompts for the harness: every N minutes, or every day at HH:MM (local time).

A due schedule starts a NEW conversation through `Harness.submit`, so it goes through exactly the same
permissions, approvals, budgets, key limits and `max_tasks` as a message typed in the chat.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any

MIN_INTERVAL_MINUTES = 1
MAX_PROMPT_CHARS = 20_000
DAILY_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def next_daily(at: str, after: float) -> float:
    """Next local timestamp strictly after `after` whose wall clock is `at` (HH:MM)."""
    h, m = (int(x) for x in DAILY_RE.match(at).groups())   # type: ignore[union-attr]
    lt = time.localtime(after)
    for extra_day in range(0, 3):
        cand = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + extra_day, h, m, 0, 0, 0, -1))
        if cand > after:
            return cand
    raise AssertionError("unreachable")


def next_run(s: dict, after: float) -> float:
    if s["kind"] == "interval":
        return after + s["every_minutes"] * 60
    return next_daily(s["at"], after)


def validate(data: dict) -> dict:
    """Validate a POST /schedules body. Raises ValueError with a readable message."""
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' (non-empty string) is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("prompt too long")
    every, at = data.get("every_minutes"), data.get("daily_at")
    if (every is None) == (at is None):
        raise ValueError("give exactly one of 'every_minutes' (number) or 'daily_at' ('HH:MM')")
    if every is not None:
        if isinstance(every, bool) or not isinstance(every, (int, float)) or every < MIN_INTERVAL_MINUTES:
            raise ValueError(f"every_minutes must be a number >= {MIN_INTERVAL_MINUTES}")
        return {"prompt": prompt.strip(), "kind": "interval", "every_minutes": float(every)}
    if not isinstance(at, str) or not DAILY_RE.match(at.strip()):
        raise ValueError("daily_at must be 'HH:MM' (24h, local time)")
    return {"prompt": prompt.strip(), "kind": "daily", "at": at.strip()}


def new(data: dict, now: float, name: str | None = None) -> dict[str, Any]:
    s = validate(data)
    s.update(id=uuid.uuid4().hex[:10], name=(name or s["prompt"][:60]), enabled=bool(data.get("enabled", True)),
             created=now, last_run=None, last_task=None, runs=0, skipped=0)
    s["next_run"] = next_run(s, now)
    return s


def describe(s: dict) -> str:
    return f"every {s['every_minutes']:g} min" if s["kind"] == "interval" else f"daily at {s['at']}"
