"""Scheduled prompts for the harness: every N minutes, every day at HH:MM, or weekly on a weekday at HH:MM (local time).

Inspired by DeepSeek Harness scheduled tasks: recurring work that runs through the same permissions and approvals as chat.

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
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def next_daily(at: str, after: float) -> float:
    """Next local timestamp strictly after `after` whose wall clock is `at` (HH:MM)."""
    h, m = (int(x) for x in DAILY_RE.match(at).groups())   # type: ignore[union-attr]
    lt = time.localtime(after)
    for extra_day in range(0, 3):
        cand = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + extra_day, h, m, 0, 0, 0, -1))
        if cand > after:
            return cand
    raise AssertionError("unreachable")


def next_weekly(weekday: str, at: str, after: float) -> float:
    """Next occurrence of weekday (mon..sun) at HH:MM after `after`."""
    target = WEEKDAYS.index(weekday.lower()[:3])
    h, m = (int(x) for x in DAILY_RE.match(at).groups())
    lt = time.localtime(after)
    # tm_wday: 0=Monday
    for extra in range(0, 14):
        cand_day = lt.tm_mday + extra
        cand = time.mktime((lt.tm_year, lt.tm_mon, cand_day, h, m, 0, 0, 0, -1))
        if cand > after and time.localtime(cand).tm_wday == target:
            return cand
    raise AssertionError("unreachable")


def next_run(s: dict, after: float) -> float:
    if s["kind"] == "interval":
        return after + s["every_minutes"] * 60
    if s["kind"] == "weekly":
        return next_weekly(s["weekday"], s["at"], after)
    return next_daily(s["at"], after)


def validate(data: dict) -> dict:
    """Validate a POST /schedules body. Raises ValueError with a readable message."""
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' (non-empty string) is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("prompt too long")
    every, at, weekly = data.get("every_minutes"), data.get("daily_at"), data.get("weekly")
    kinds = sum(x is not None for x in (every, at, weekly))
    if kinds != 1:
        raise ValueError("give exactly one of 'every_minutes', 'daily_at' or 'weekly'")
    if every is not None:
        if isinstance(every, bool) or not isinstance(every, (int, float)) or every < MIN_INTERVAL_MINUTES:
            raise ValueError(f"every_minutes must be a number >= {MIN_INTERVAL_MINUTES}")
        return {"prompt": prompt.strip(), "kind": "interval", "every_minutes": float(every)}
    if at is not None:
        if not isinstance(at, str) or not DAILY_RE.match(at.strip()):
            raise ValueError("daily_at must be 'HH:MM' (24h, local time)")
        return {"prompt": prompt.strip(), "kind": "daily", "at": at.strip()}
    # weekly: {"weekday": "fri", "at": "17:00"}
    if not isinstance(weekly, dict):
        raise ValueError("weekly must be an object {weekday, at}")
    wd = str(weekly.get("weekday") or "").lower()[:3]
    wat = str(weekly.get("at") or "").strip()
    if wd not in WEEKDAYS or not DAILY_RE.match(wat):
        raise ValueError("weekly.weekday must be mon..sun and at must be HH:MM")
    return {"prompt": prompt.strip(), "kind": "weekly", "weekday": wd, "at": wat}


def new(data: dict, now: float, name: str | None = None) -> dict[str, Any]:
    s = validate(data)
    s.update(id=uuid.uuid4().hex[:10], name=(name or s["prompt"][:60]), enabled=bool(data.get("enabled", True)),
             created=now, last_run=None, last_task=None, runs=0, skipped=0)
    s["next_run"] = next_run(s, now)
    return s


def describe(s: dict) -> str:
    if s["kind"] == "interval":
        return f"every {s['every_minutes']:g} min"
    if s["kind"] == "weekly":
        return f"weekly on {s['weekday']} at {s['at']}"
    return f"daily at {s['at']}"