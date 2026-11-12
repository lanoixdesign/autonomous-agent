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

Parallel mode (`spawn_agents`, `max_parallel` > 1): children run concurrently in a thread pool ONLY
if they are read-only, i.e. `allowed_tools` is given and every one of those tools is in the `read`
or `network` category AND is already decided `allow` or `deny` by the policy (never `ask`). Such a
child cannot write, execute, spend, send, delegate, or wait for an approval. Any other batch runs
sequentially, exactly as before. (We chose this over isolated workspace copies + merge: simpler,
and nothing to merge since parallel children cannot write.)
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
    max_parallel: int = 3        # spawn_agents: read-only children run concurrently up to this many


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


def _left(parent: "Agent") -> tuple[int, int, int]:
    """What the parent has left, minus what running children already reserved (call under lock)."""
    b, st = parent.budget, parent.state
    return (b.max_steps - st.steps - st.reserved_steps,
            b.max_tool_calls - st.tool_calls - st.reserved_calls - 1,   # the spawn call itself counts
            b.max_tokens - st.tokens - st.reserved_tokens)


def spawn(parent: "Agent", task: str, max_steps: int | None = None,
          allowed_tools: list[str] | None = None, share: int = 1) -> str:
    """Run one sub-agent to completion and return its observation for the parent.

    `share` > 1 (parallel batch): the child may reserve at most 1/share of what is left."""
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
    parent.audit.record(event="spawn", agent=parent.agent_id, depth=parent.depth, child=child_id,
                        child_depth=depth, task=task, tools=sorted(allowed),
                        budget={"max_steps": budget.max_steps, "max_tool_calls": budget.max_tool_calls,
                                "max_tokens": budget.max_tokens})
    on_event = parent.on_event
    child = Agent(parent.llm, base, perms, parent.audit, parent.ctx, budget, confirm=parent.confirm,
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
    parent.audit.record(event="child_done", agent=child_id, depth=depth, parent=parent.agent_id,
                        stop_reason=res.stop_reason, steps=res.steps, tool_calls=res.tool_calls,
                        tokens=res.tokens, result=res.answer)
    return (f"[sub-agent {child_id}] stop={res.stop_reason} steps={res.steps} "
            f"tool_calls={res.tool_calls} tokens={res.tokens}\n{res.answer}")


def spawn_many(parent: "Agent", tasks: list[str], max_steps: int | None = None,
               allowed_tools: list[str] | None = None) -> list[str]:
    """Run several children; concurrently (up to max_parallel) only if they are read-only."""
    def one(task: str, share: int) -> str:
        try:
            return spawn(parent, str(task), max_steps, allowed_tools, share)
        except ToolError as e:
            return f"[sub-agent not started] {e}"

    workers = min(parent.swarm.max_parallel if parent.swarm else 1, len(tasks))
    if workers > 1 and parallel_safe(parent, allowed_tools):
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"agent-{parent.agent_id}") as ex:
            # at most `workers` children run at once: each may reserve 1/workers of what is left
            return list(ex.map(lambda t: one(t, workers), tasks))
    return [one(t, 1) for t in tasks]


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
             "They run in parallel only if allowed_tools is limited to read-only tools.", "delegate",
             params(["tasks"], tasks={"type": "array", "items": {"type": "string"}}, max_steps=steps_prop,
                    allowed_tools=tools_prop), _many),
    ]
