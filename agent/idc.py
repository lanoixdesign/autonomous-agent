"""IDC — Irreversible Decision Collapse (Effondrement Décisionnel Irréversible). OPTIONAL, OFF by default.

The author's model (a hypothesis, not a validated result): an agent with no finitude can deliberate
forever, waste compute, hesitate, and invent answers because inventing costs no more than saying
"I don't know". IDC gives the agent finitude through three pillars:

1. A decreasing resource — "vitality". Every model call, every tool call and every 1000 tokens cost
   vitality. Vitality at 0 is "cognitive death": the agent may not think any more.
2. Append-only commitments. `idc_commit` records a fact, a decision, an answer or "I don't know".
   Entries are never edited or deleted; revising one adds a new entry that points to the old one and
   costs `revise_cost` (or is forbidden with `allow_revise: false`).
3. A stopping rule — collapse. When vitality falls to `collapse_threshold`, or when `stall_limit`
   tool calls in a row bring no new information (same observation as before, error, refusal), the
   agent must answer NOW, without tools ("good enough now" rather than an illusory optimum).

Hallucination hypothesis, made concrete: a commitment is "supported" when every evidence quote it
gives appears in what the agent actually observed this turn (user message, tool results). A supported
commitment costs `commit_cost`, an "I don't know" costs `unknown_cost` (the cheapest), an
unsupported claim costs `unsupported_cost` (the most expensive). If vitality runs out, the answer is
the last SUPPORTED answer commitment, otherwise an explicit "I don't know" listing what is known.

This module only measures and enforces budgets and records; it does not make a model truthful.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Callable

from . import i18n

KINDS = ("fact", "decision", "answer", "unknown")
TOOL_NAME = "idc_commit"
STOP_REASONS = ("idc_collapse", "idc_exhausted")


@dataclass
class IDCConfig:
    enabled: bool = False
    vitality: float = 100.0          # initial vitality per user turn (root agent)
    step_cost: float = 4.0           # per model call
    tool_cost: float = 3.0           # per tool call (commitments are charged separately)
    token_cost: float = 0.5          # per 1000 tokens (prompt + completion)
    collapse_threshold: float = 20.0  # at or below: forced collapse (final answer without tools)
    stall_limit: int = 3             # tool calls in a row without new information -> collapse
    commit_cost: float = 1.0         # supported commitment (fact / decision / answer)
    unknown_cost: float = 0.5        # "I don't know": the cheapest commitment
    unsupported_cost: float = 15.0   # claim whose evidence was not observed: the most expensive
    revise_cost: float = 25.0        # revising an earlier commitment (added to the commitment cost)
    allow_revise: bool = True        # false: commitments can never be revised
    child_share: float = 0.5         # a sub-agent gets at most this fraction of the vitality left

    def validate(self) -> "IDCConfig":
        def check(ok: bool, msg: str) -> None:
            if not ok:
                raise ValueError("idc: " + msg)
        check(self.vitality > 0, "vitality must be > 0")
        for f in ("step_cost", "tool_cost", "token_cost", "commit_cost", "unknown_cost", "unsupported_cost",
                  "revise_cost", "collapse_threshold"):
            check(getattr(self, f) >= 0, f"{f} must be >= 0")
        check(self.collapse_threshold < self.vitality, "collapse_threshold must be < vitality")
        check(self.stall_limit >= 1, "stall_limit must be >= 1")
        check(0 < self.child_share <= 1, "child_share must be in (0, 1]")
        check(self.unknown_cost < self.unsupported_cost,
              "unknown_cost must be lower than unsupported_cost (saying 'I don't know' must be cheaper)")
        return self

    @classmethod
    def from_sources(cls, data: dict | None = None, env: dict | None = None,
                     enabled: bool | None = None) -> "IDCConfig":
        """Defaults < `idc:` section of the permissions file < AGENT_IDC_* env vars < CLI `enabled`."""
        env = os.environ if env is None else env
        cfg = cls()
        types = {f.name: f.type for f in fields(cls)}
        for name, value in (data or {}).items():
            if name not in types:
                raise ValueError(f"idc: unknown setting {name!r}")
            setattr(cfg, name, _coerce(name, value, cfg))
        for name in types:
            var = "AGENT_IDC" if name == "enabled" else "AGENT_IDC_" + name.upper()
            if env.get(var, "").strip():
                setattr(cfg, name, _coerce(name, env[var], cfg))
        if enabled is not None:
            cfg.enabled = enabled
        return cfg.validate()

    def as_dict(self) -> dict:
        return asdict(self)


def _coerce(name: str, value: Any, cfg: IDCConfig) -> Any:
    current = getattr(cfg, name)
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        v = str(value).strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off", ""):
            return False
        raise ValueError(f"idc: {name} must be true or false")
    try:
        return int(value) if isinstance(current, int) else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"idc: {name} must be a number") from None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


class CommitError(Exception):
    """A refused commitment (the message goes back to the model)."""


class IDC:
    """Per-agent controller. Vitality is per user turn; commitments last for the whole conversation."""

    def __init__(self, cfg: IDCConfig, vitality: float | None = None, agent_id: str = "root",
                 lang: str = "en", on_change: Callable[[dict], None] | None = None,
                 corpus: list[str] | None = None):
        self.cfg = cfg
        self.agent_id = agent_id
        self.lang = i18n.normalize(lang)
        self.max = float(cfg.vitality if vitality is None else vitality)
        self.spent = 0.0
        self.reserved = 0.0
        self.stall = 0
        self.collapsed: str | None = None
        self.on_change = on_change or (lambda data: None)
        self._commitments: list[dict] = []
        self._seen: set[str] = set()
        self._corpus: list[str] = list(corpus or [])
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- vitality
    @property
    def vitality(self) -> float:
        with self._lock:
            return round(self.max - self.spent - self.reserved, 4)

    @property
    def threshold(self) -> float:
        """The collapse threshold scales with this agent's budget (a sub-agent has a smaller one)."""
        return round(self.cfg.collapse_threshold * self.max / self.cfg.vitality, 4)

    def start_turn(self, user_text: str) -> None:
        with self._lock:
            self.spent = self.reserved = 0.0
            self.stall = 0
            self.collapsed = None
            self._seen = set()
            self._corpus = [user_text or ""]
        self._emit()

    def charge(self, amount: float) -> None:
        with self._lock:
            self.spent += max(0.0, float(amount))
        self._emit()

    def on_step(self, tokens: int) -> None:
        self.charge(self.cfg.step_cost + self.cfg.token_cost * max(0, tokens) / 1000.0)

    def on_tool(self, observation: str) -> bool:
        """Charge a tool call; returns True when the observation brought new information."""
        obs = str(observation or "")
        h = hashlib.sha256(_norm(obs).encode()).hexdigest()
        with self._lock:
            new = h not in self._seen and not obs.startswith(("ERROR", "DENIED"))
            self._seen.add(h)
            self.stall = 0 if new else self.stall + 1
            self._corpus.append(obs)
            self.spent += self.cfg.tool_cost
        self._emit()
        return new

    def should_collapse(self) -> str | None:
        """None, or why the agent must stop deliberating: exhausted | low_vitality | no_new_information."""
        v = self.vitality
        if v <= 0:
            return "exhausted"
        if v <= self.threshold:
            return "low_vitality"
        if self.stall >= self.cfg.stall_limit:
            return "no_new_information"
        return None

    def mark_collapse(self, why: str) -> None:
        with self._lock:
            self.collapsed = why
        self._emit(collapse=why)

    # ---------------------------------------------------------------- sub-agents
    def child(self, agent_id: str, share: int = 1) -> tuple["IDC", float]:
        """A controller for a sub-agent with a slice of the vitality left (reserved until settle_child)."""
        with self._lock:
            left = max(0.0, self.max - self.spent - self.reserved)
            slice_ = round(left * self.cfg.child_share / max(1, share), 4)
            self.reserved += slice_
            corpus = list(self._corpus)
        # what the parent observed counts as evidence for the child too
        kid = IDC(self.cfg, vitality=slice_, agent_id=agent_id, lang=self.lang, corpus=corpus)
        kid._inherited = len(corpus)
        self._emit()
        return kid, slice_

    def settle_child(self, kid: "IDC", slice_: float) -> None:
        """Release the reservation and charge what the child really spent (never more than its slice)."""
        with self._lock:
            self.reserved -= slice_
            self.spent += min(kid.spent, slice_)
            self._corpus.extend(kid._corpus[getattr(kid, "_inherited", 0):])   # its observations are evidence too
        self._emit()

    # ---------------------------------------------------------------- commitments (append-only)
    @property
    def commitments(self) -> list[dict]:
        """A copy: changing it changes nothing. There is no way to edit or delete an entry."""
        with self._lock:
            return copy.deepcopy(self._commitments)

    def supported(self, evidence: list[str]) -> bool:
        if not evidence:
            return False
        corpus = _norm("\n".join(self._corpus))
        return all(_norm(e) and _norm(e) in corpus for e in evidence)

    def commit(self, args: dict) -> dict:
        kind = str(args.get("kind") or "").strip().lower()
        text = str(args.get("text") or "").strip()
        evidence = args.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = [str(e) for e in evidence if str(e).strip()][:10]
        revises = args.get("revises")
        if kind not in KINDS:
            raise CommitError(f"kind must be one of {', '.join(KINDS)}")
        if not text:
            raise CommitError("text is required")
        with self._lock:
            if revises:
                ids = {c["id"] for c in self._commitments}
                if revises not in ids:
                    raise CommitError(f"unknown commitment {revises!r}")
                if not self.cfg.allow_revise:
                    raise CommitError("commitments are irreversible here (allow_revise: false); "
                                      "add a new commitment or say what you do not know")
            supported = kind == "unknown" or self.supported(evidence)
            cost = (self.cfg.unknown_cost if kind == "unknown"
                    else self.cfg.commit_cost if supported else self.cfg.unsupported_cost)
            if revises:
                cost += self.cfg.revise_cost
            entry = {"id": f"{self.agent_id}:c{len(self._commitments) + 1}", "agent": self.agent_id,
                     "kind": kind, "text": text[:2000], "evidence": evidence, "supported": supported,
                     "revises": revises or None, "cost": round(cost, 4),
                     "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            self._commitments.append(entry)
            self.spent += cost
        self._emit(commit=dict(entry))
        return dict(entry)

    def record_final(self, text: str) -> None:
        """The final answer is also written down (free): the conversation's append-only record."""
        with self._lock:
            entry = {"id": f"{self.agent_id}:c{len(self._commitments) + 1}", "agent": self.agent_id,
                     "kind": "final", "text": str(text or "")[:2000], "evidence": [], "supported": None,
                     "revises": None, "cost": 0.0, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            self._commitments.append(entry)
        self._emit(commit=dict(entry))

    def restore(self, entries: list[dict]) -> None:
        """Reload commitments saved by the harness (after a restart). Only before anything was added."""
        with self._lock:
            if not self._commitments:
                self._commitments = [dict(e) for e in entries if isinstance(e, dict) and e.get("id")]

    def fallback_answer(self) -> str:
        """Used when vitality is gone: the last supported answer, else an explicit 'I don't know'."""
        with self._lock:
            revised = {c["revises"] for c in self._commitments if c.get("revises")}
            live = [c for c in self._commitments if c["id"] not in revised]
        answers = [c for c in live if c["kind"] == "answer" and c["supported"]]
        if answers:
            return i18n.t(self.lang, "idc.fallbackAnswer", text=answers[-1]["text"])
        known = [c["text"] for c in live if c["kind"] in ("fact", "decision") and c["supported"]]
        unverified = [c["text"] for c in live if c["kind"] in ("fact", "decision", "answer") and not c["supported"]]
        out = i18n.t(self.lang, "idc.dontKnow")
        if known:
            out += "\n" + i18n.t(self.lang, "idc.known") + "\n" + "\n".join("- " + k for k in known)
        if unverified:
            out += "\n" + i18n.t(self.lang, "idc.unverified") + "\n" + "\n".join("- " + k for k in unverified)
        return out

    # ---------------------------------------------------------------- reporting
    def snapshot(self) -> dict:
        with self._lock:
            return {"agent": self.agent_id, "vitality": round(max(0.0, self.max - self.spent - self.reserved), 2),
                    "max": round(self.max, 2), "spent": round(self.spent, 2), "reserved": round(self.reserved, 2),
                    "threshold": round(self.threshold, 2), "stall": self.stall, "collapsed": self.collapsed,
                    "commitments": len(self._commitments)}

    def _emit(self, **extra: Any) -> None:
        self.on_change({**self.snapshot(), **extra})


def tool_schema() -> dict:
    return {"type": "function", "function": {
        "name": TOOL_NAME,
        "description": ("[idc] Record a commitment in the append-only log. kind: fact | decision | answer | "
                        "unknown. Give `evidence`: short exact quotes from what you observed (tool results, the "
                        "user's message). Supported commitments are cheap, 'unknown' is the cheapest, "
                        "claims without observed evidence are expensive. Entries can never be edited; "
                        "`revises` (an earlier id) adds a correction at a high cost."),
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "text": {"type": "string", "description": "the commitment"},
            "evidence": {"type": "array", "items": {"type": "string"},
                         "description": "exact quotes from observations that support it"},
            "revises": {"type": "string", "description": "id of an earlier commitment this one corrects"}},
            "required": ["kind", "text"]}}}


def system_rules(ctrl: IDC) -> str:
    c = ctrl.cfg
    return (
        "\nIDC mode is ON (finite deliberation). Rules:\n"
        f"- You have a vitality budget of {ctrl.max:g} per user message. Each model call costs {c.step_cost:g} (+{c.token_cost:g} per "
        f"1000 tokens), each tool call {c.tool_cost:g}. At {ctrl.threshold:g} or after {c.stall_limit} tool "
        "calls without new information you must answer immediately, without tools. At 0 you cannot think any more.\n"
        "- Prefer a good-enough answer now over an illusory perfect one later.\n"
        f"- Record important facts, decisions and your answer with {TOOL_NAME}, quoting the exact evidence you "
        "observed. Commitments are append-only: you cannot erase them; correcting one is costly"
        f"{'' if c.allow_revise else ' and forbidden here'}.\n"
        f"- Saying you do not know costs {c.unknown_cost:g}; a claim without observed evidence costs "
        f"{c.unsupported_cost:g}. Under uncertainty, say clearly what you do not know instead of guessing.\n")


def collapse_message(ctrl: IDC, why: str) -> str:
    return ("[IDC controller] Collapse now (" + why + f", vitality {ctrl.vitality:g}). Give your final answer "
            "immediately, without calling any tool. Use only what you observed; if it is not enough, say "
            "plainly that you do not know and list what you do know.")
