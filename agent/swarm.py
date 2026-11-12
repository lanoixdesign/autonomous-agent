"""Multi-agent ("swarm") mode: an agent can launch sub-agents with `spawn_agent` / `spawn_agents`.

A sub-agent is a normal `Agent` run in-process, with the parent's LLM backend, workspace, memory,
skills, audit log, confirmation callback and cancel event. It can never do more than its parent:
  - permissions: the parent's own policy object, optionally narrowed to `allowed_tools`
    (anything else is denied). A child cannot loosen a rule, so send/spend stay as the parent has them;
  - tools: a subset of the parent's tools (unknown names are ignored, never added);
  - budget: reserved from what the parent has left (so concurrent children can never exceed it),
    and the child's real usage is deducted from the parent when it ends;
  - depth: root = 0; an agent at depth d may spawn only if d < max_depth (default 2);
  - count: at most max_children sub-agents per root run, across the whole tree (default 5).
Launching is its own risk category, `delegate` (default: ask). Every audit line carries `agent`
(e.g. "root", "root.1", "root.1.2") and `depth`; spawns add `event: spawn` / `event: child_done` lines.

Parallel mode (`spawn_agents`, `max_parallel` > 1), decided per batch:
  1. read-only children (`allowed_tools` given, only `read`/`network` tools already decided
     allow/deny, never `ask`) -> concurrent, in the shared workspace (they cannot change it);
  2. otherwise, if no child tool can need an approval, or the confirm callback can take concurrent
     approvals (the harness queue: `confirm.concurrent = True`) -> concurrent, each child in its own
     ISOLATED COPY of the parent workspace, merged back at the end (see isolation.py: files changed by
     one child are applied, conflicts are written as `<file>.conflict-<agent id>`, never overwritten);
  3. otherwise (terminal prompts) -> sequential in the shared workspace, so prompts never mix.
If the workspace is too large to copy, case 2 falls back to case 3.
"""
from __future__ import annotations

import dataclasses
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import isolation
from .permissions import Decision
from .tools import Registry, Tool, ToolContext, ToolError, params, s

if TYPE_CHECKING:  # pragma: no cover
    from .loop import Agent

SPAWN_TOOLS = ("spawn_agent", "spawn_agents")
PARALLEL_CATEGORIES = ("read", "network")


@dataclass
class SwarmConfig:
    max_depth: int = 2           # 0 disables sub-agents
    max_children: int = 5        # total sub-agents per root run (whole tree)
    child_max_steps: int = 6     # default step budget of one sub-agent (always capped by the parent)
    max_parallel: int = 3        # spawn_agents: children run concurrently up to this many
    isolate: bool = True         # allow parallel writing children in isolated workspace copies
    copy_limits: isolation.Limits = field(default_factory=isolation.Limits)


@dataclass
class SwarmState:
    """Shared by every agent of one tree. Thread-safe."""
    spawned: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def reserve_child(self, limit: int) -> int | None:
        """Atomically take one child slot; returns its number, or None if the limit is reached."""
        with self.lock:
            if self.spawned >= limit:
                return None
            self.spawned += 1
            return self.spawned

    def reset(self) -> None:
        with self.lock:
            self.spawned = 0


class RestrictedPermissions:
    """The parent's policy, narrowed to an allow-list of tools. Never wider than the parent."""

    def __init__(self, base: Any, allowed_tools: set[str]):
        self.base, self.allowed = base, set(allowed_tools)

    def decide(self, tool: str, category: str, subject_kind: str | None = None,
               subject: str | None = None) -> Decision:
        if tool not in self.allowed:
            return Decision("deny", f"tool '{tool}' not in this sub-agent's allowed_tools")
        return self.base.decide(tool, category, subject_kind, subject)

    def summary(self) -> str:
        return self.base.summary() + f"\n  sub-agent allowed_tools: {', '.join(sorted(self.allowed))}"

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


def _int(v: Any, name: str) -> int | None:
    if v is None or v == "":
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be an integer")
    if n < 1:
        raise ToolError(f"{name} must be >= 1")
    return n


def _tool_list(v: Any) -> list[str] | None:
    if v is None:
        return None
    if isinstance(v, str):
        v = [t.strip() for t in v.split(",") if t.strip()]
    if not isinstance(v, list):
        raise ToolError("allowed_tools must be a list of tool names")
    return [str(t) for t in v]


def parallel_safe(parent: "Agent", allowed_tools: list[str] | None) -> bool:
    """True if children limited to `allowed_tools` can run concurrently (see module docstring)."""
    if not allowed_tools:
        return False
    names = set(allowed_tools) & set(parent.registry.tools)
    if not names:
        return False
    for n in names:
        tool = parent.registry.get(n)
        if tool.category not in PARALLEL_CATEGORIES:
            return False
        if parent.permissions.decide(tool.name, tool.category).mode == "ask":
            return False
    return True


def child_tools(parent: "Agent", allowed_tools: list[str] | None) -> set[str]:
    names = set(parent.registry.tools)
    return names if allowed_tools is None else names & set(allowed_tools)


def may_ask(parent: "Agent", allowed_tools: list[str] | None) -> bool:
    """True if a child with these tools could hit an `ask` decision (subject rules never create one)."""
    for n in child_tools(parent, allowed_tools):
        tool = parent.registry.get(n)
        if parent.permissions.decide(tool.name, tool.category).mode == "ask":
            return True
    return False


def _left(parent: "Agent") -> tuple[int, int, int]:
    """What the parent has left, minus what running children already reserved (call under lock)."""
    b, st = parent.budget, parent.state
    return (b.max_steps - st.steps - st.reserved_steps,
            b.max_tool_calls - st.tool_calls - st.reserved_calls - 1,   # the spawn call itself counts
            b.max_tokens - st.tokens - st.reserved_tokens)


def spawn(parent: "Agent", task: str, max_steps: int | None = None,
          allowed_tools: list[str] | None = None, share: int = 1) -> str:
    """Run one sub-agent to completion and return its observation for the parent."""
    return run_child(parent, task, max_steps, allowed_tools, share)[1]


def run_child(parent: "Agent", task: str, max_steps: int | None = None,
              allowed_tools: list[str] | None = None, share: int = 1,
              workspace: Path | None = None) -> tuple[str, str]:
    """Run one sub-agent to completion; returns (child id, observation for the parent).

    `share` > 1 (parallel batch): the child may reserve at most 1/share of what is left.
    `workspace`: run the child in this directory (an isolated copy) instead of the parent's."""
    from .loop import Agent, Budget

    cfg, shared, st = parent.swarm, parent.swarm_state, parent.state
    if cfg is None or shared is None or st is None:
        raise ToolError("multi-agent mode is not enabled")
    if not str(task or "").strip():
        raise ToolError("task is empty")
    if parent.cancel is not None and parent.cancel.is_set():
        raise ToolError("cancelled")
    depth = parent.depth + 1
    if depth > cfg.max_depth:
        raise ToolError(f"max depth reached ({cfg.max_depth}); do the work yourself")

    b = parent.budget
    with parent.lock:
        left_steps, left_calls, left_tokens = (x // share for x in _left(parent))
        if left_steps < 1 or left_calls < 1 or left_tokens < 1:
            raise ToolError("not enough budget left for a sub-agent")
        budget = Budget(max_steps=min(max_steps or cfg.child_max_steps, left_steps),
                        max_tool_calls=left_calls, max_tokens=left_tokens, max_repeats=b.max_repeats)
        num = shared.reserve_child(cfg.max_children)
        if num is None:
            raise ToolError(f"max sub-agents per run reached ({cfg.max_children}); do the work yourself")
        st.reserved_steps += budget.max_steps
        st.reserved_calls += budget.max_tool_calls
        st.reserved_tokens += budget.max_tokens

    # Tools and permissions: a subset of the parent's, never more.
    parent_tools = set(parent.registry.tools)
    if allowed_tools is None:
        allowed = parent_tools
        perms = parent.permissions
    else:
        allowed = parent_tools & set(allowed_tools)
        perms = RestrictedPermissions(parent.permissions, allowed)
    base = Registry({n: t for n, t in parent.base_registry.tools.items() if n in allowed})

    child_id = f"{parent.agent_id}.{num}"
    ctx = parent.ctx if workspace is None else dataclasses.replace(parent.ctx, workspace=Path(workspace))
    parent.audit.record(event="spawn", agent=parent.agent_id, depth=parent.depth, child=child_id,
                        child_depth=depth, task=task, tools=sorted(allowed),
                        isolated=workspace is not None,
                        budget={"max_steps": budget.max_steps, "max_tool_calls": budget.max_tool_calls,
                                "max_tokens": budget.max_tokens})
    on_event = parent.on_event
    child = Agent(parent.llm, base, perms, parent.audit, ctx, budget, confirm=parent.confirm,
                  on_event=lambda kind, data: on_event(kind, {**data, "agent": child_id}),
                  stop_rule=parent.stop_rule, swarm=cfg, depth=depth, agent_id=child_id,
                  swarm_state=shared, allow_spawn=bool(allowed & set(SPAWN_TOOLS)), cancel=parent.cancel)
    try:
        res = child.run(task)
    finally:
        # Release the reservation and deduct the child's real usage from the parent's budget.
        cs = child.state
        with parent.lock:
            st.reserved_steps -= budget.max_steps
            st.reserved_calls -= budget.max_tool_calls
            st.reserved_tokens -= budget.max_tokens
            if cs is not None:
                st.steps += cs.steps
                st.tool_calls += cs.tool_calls
                st.tokens += cs.tokens
                st.cost += cs.cost
    parent.audit.record(event="child_done", agent=child_id, depth=depth, parent=parent.agent_id,
                        stop_reason=res.stop_reason, steps=res.steps, tool_calls=res.tool_calls,
                        tokens=res.tokens, cost=res.cost, result=res.answer)
    return child_id, (f"[sub-agent {child_id}] stop={res.stop_reason} steps={res.steps} "
                      f"tool_calls={res.tool_calls} tokens={res.tokens}\n{res.answer}")


def plan_batch(parent: "Agent", n: int, allowed_tools: list[str] | None) -> str:
    """'sequential' | 'parallel' (shared workspace, read-only) | 'isolated' (parallel, one copy each)."""
    cfg = parent.swarm
    if cfg is None or n < 2 or min(cfg.max_parallel, n) < 2:
        return "sequential"
    if parallel_safe(parent, allowed_tools):
        return "parallel"
    if not cfg.isolate:
        return "sequential"
    if may_ask(parent, allowed_tools) and not getattr(parent.confirm, "concurrent", False):
        return "sequential"   # terminal prompts must not interleave
    return "isolated"


def spawn_many(parent: "Agent", tasks: list[str], max_steps: int | None = None,
               allowed_tools: list[str] | None = None) -> list[str]:
    """Run several children (see the module docstring for when they run concurrently)."""
    mode = plan_batch(parent, len(tasks), allowed_tools)
    workers = min(parent.swarm.max_parallel, len(tasks)) if parent.swarm else 1

    def one(task: str, share: int, workspace: Path | None = None) -> tuple[str | None, str]:
        try:
            return run_child(parent, str(task), max_steps, allowed_tools, share, workspace)
        except ToolError as e:
            return None, f"[sub-agent not started] {e}"

    note = ""
    if mode == "isolated":
        cfg, src = parent.swarm, parent.ctx.workspace
        copies: list[Path] = []
        try:
            base = isolation.scan(src, cfg.copy_limits)
            for _ in tasks:
                copies.append(isolation.make_copy(src, base, cfg.copy_limits, prefix="agent-child-"))
        except (isolation.WorkspaceTooLarge, OSError) as e:
            for c in copies:
                shutil.rmtree(c, ignore_errors=True)
            mode, note = "sequential", f"[swarm] isolated copies not possible ({e}); ran sequentially\n\n"
        else:
            try:
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"agent-{parent.agent_id}") as ex:
                    results = list(ex.map(lambda tc: one(tc[0], workers, tc[1]), zip(tasks, copies)))
                done = [(cid, c) for (cid, _), c in zip(results, copies) if cid is not None]
                if parent.cancel is not None and parent.cancel.is_set():
                    parent.audit.record(event="merge", agent=parent.agent_id, depth=parent.depth,
                                        children=[cid for cid, _ in done], skipped="cancelled")
                    return [obs for _, obs in results] + ["[merge] skipped: task cancelled, no change applied"]
                report = isolation.merge(src, base, done, cfg.copy_limits)
                parent.audit.record(event="merge", agent=parent.agent_id, depth=parent.depth,
                                    children=[cid for cid, _ in done], applied=report.applied,
                                    conflicts=report.conflicts)
                return [obs for _, obs in results] + [report.text()]
            finally:
                for c in copies:
                    shutil.rmtree(c, ignore_errors=True)
    if mode == "parallel":
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"agent-{parent.agent_id}") as ex:
            # at most `workers` children run at once: each may reserve 1/workers of what is left
            return [obs for _, obs in ex.map(lambda t: one(t, workers), tasks)]
    out = [obs for _, obs in (one(t, 1) for t in tasks)]
    if note:
        out[0] = note + out[0]
    return out


def make_tools(agent: "Agent") -> list[Tool]:
    """Spawn tools bound to one agent (closures: the tool needs the agent, not only the context)."""

    def _one(ctx: ToolContext, a: dict) -> str:
        return spawn(agent, a["task"], _int(a.get("max_steps"), "max_steps"), _tool_list(a.get("allowed_tools")))

    def _many(ctx: ToolContext, a: dict) -> str:
        tasks = a["tasks"]
        if isinstance(tasks, str):
            tasks = [tasks]
        if not isinstance(tasks, list) or not tasks:
            raise ToolError("tasks must be a non-empty list")
        out = spawn_many(agent, tasks, _int(a.get("max_steps"), "max_steps"), _tool_list(a.get("allowed_tools")))
        return "\n\n".join(out)

    tools_prop = {"type": "array", "items": {"type": "string"},
                  "description": "optional: tools the sub-agent may use (subset of yours)"}
    steps_prop = {"type": "integer", "description": "optional: step budget (capped by what you have left)"}
    return [
        Tool("spawn_agent", "Launch a sub-agent on a self-contained task; returns its final answer. "
             "It uses your budget and never has more permissions than you.", "delegate",
             params(["task"], task=s("complete, self-contained instructions"), max_steps=steps_prop,
                    allowed_tools=tools_prop), _one),
        Tool("spawn_agents", "Launch several sub-agents (one per task); returns their answers in order. "
             "They may run in parallel (writers each in an isolated copy of the workspace, merged at the end; "
             "conflicting files are written as <file>.conflict-<agent id>).", "delegate",
             params(["tasks"], tasks={"type": "array", "items": {"type": "string"}}, max_steps=steps_prop,
                    allowed_tools=tools_prop), _many),
    ]
