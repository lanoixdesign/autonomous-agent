"""Self-evaluation loop (v0.9): after a draft final answer, a Critic checks it against the request
(criteria asked for, correctness against what was actually done, language) and, if it is not good enough,
the agent revises it. At most `rounds` reviews per turn; a Critic that cannot be read never blocks."""
from __future__ import annotations

import json
import re
from typing import Any

CRITIC_PROMPT = """You are the Critic of a small team of AI assistants. You do not do the task: you check a DRAFT
final answer before it is sent to the user. Check, in order:
1. Criteria: does it do everything the request asked (number of sentences/lines, files to create, format...)?
2. Correctness: is it consistent with the actions and tool results listed (no invented files or facts)?
3. Language: is it written in {language}, the language of the request?
Be pragmatic: small style issues are fine. Reply with ONLY one JSON object, no other text:
{{"verdict": "ok" or "revise", "score": 0-10, "issues": ["short, concrete problem", ...]}}
"issues" must be empty when the verdict is "ok"; write them in {language}."""

REVISE = ("[Critic] The draft answer was reviewed and is not good enough yet:\n{issues}\n"
          "Fix these points (use tools if something is missing), then give the complete corrected final answer, "
          "in {language}, without mentioning this review.")

LANG_NAME = {"fr": "French", "en": "English"}


def language_name(lang: str | None) -> str:
    return LANG_NAME.get(lang or "", "the same language as the request")


def build_messages(request: str, draft: str, actions: list[str], lang: str | None) -> list[dict]:
    acts = "\n".join(f"- {a}" for a in actions[-30:]) or "- (no tool used)"
    return [{"role": "system", "content": CRITIC_PROMPT.format(language=language_name(lang))},
            {"role": "user", "content": f"REQUEST:\n{request[:6000]}\n\nACTIONS AND RESULTS (this turn):\n{acts[:5000]}"
                                        f"\n\nDRAFT ANSWER:\n{draft[:8000]}"}]


def parse(text: str | None) -> dict:
    """The Critic's verdict -> {"ok", "score", "issues", "readable"}; unreadable = ok (never blocks)."""
    s = str(text or "").strip()
    m = re.search(r"\{.*\}", s, re.S)
    data: Any = None
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = None
    if not isinstance(data, dict):
        low = s.lower()
        bad = bool(re.search(r"\brevise\b|\bà revoir\b", low))
        return {"ok": not bad, "score": None, "issues": [s[:300]] if bad else [], "readable": False}
    verdict = str(data.get("verdict") or "").lower()
    issues = [str(i)[:300] for i in (data.get("issues") or []) if str(i).strip()][:8]
    score = data.get("score")
    try:
        score = max(0.0, min(10.0, float(score))) if score is not None else None
    except (TypeError, ValueError):
        score = None
    ok = verdict != "revise"
    if not ok and not issues:
        issues = ["(no detail)"]
    return {"ok": bool(ok), "score": score, "issues": issues if not ok else [], "readable": True}


def revise_message(issues: list[str], lang: str | None) -> dict:
    return {"role": "user", "content": REVISE.format(issues="\n".join(f"- {i}" for i in issues),
                                                     language=language_name(lang))}
