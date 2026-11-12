"""Multi-agent ("swarm") mode: an agent can launch sub-agents with `spawn_agent` / `spawn_agents`.

A sub-agent is a normal `Agent` run in-process, sequentially, with the parent's LLM backend,
workspace, memory, skills, audit log and confirmation callback. It can never do more than its parent:
  - permissions: the parent's own policy object, optionally narrowed to `allowed_tools`
    (anything else is denied). A child cannot loosen a rule, so send/spend stay as the parent has them;
  - tools: a subset of the parent's tools (unknown names are ignored, never added);
  - budget: capped by what the parent has left, and the child's usage is deducted from the parent;
  - depth: root = 0; an agent at depth d may spawn only if d < max_depth (default 2);
  - count: at most max_children sub-agents per root run, across the whole tree (default 5).
Launching is its own risk category, `delegate` (default: ask). Every audit line carries `agent`
(e.g. "root", "root.1", "root.1.2") and `depth`; spawns add `event: spawn` / `event: child_done` lines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .permissions import Decision
from .tools import Registry, Tool, ToolContext, ToolError, params, s

if TYPE_CHECKING:  # pragma: no cover
    from .loop import Agent

SPAWN_TOOLS = ("spawn_agent", "spawn_agents")


@dataclass
class SwarmConfig:
    max_depth: int = 2           # 0 disables sub-agents
    max_children: int = 5        # total sub-agents per root run (whole tree)
    child_max_steps: int = 6     # default step budget of one sub-agent (always capped by the parent)


@dataclass
class SwarmState:
    """Shared by every agent of one tree."""
    spawned: int = 0


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


def spawn(parent: "Agent", task: str, max_steps: int | None = None,
          allowed_tools: list[str] | None = None) -> str:
    """Run one sub-agent to completion and return its observation for the parent."""
    from .loop import Agent, Budget

    cfg, shared, st = parent.swarm, parent.swarm_state, parent.state
    if cfg is None or shared is None or st is None:
        raise ToolError("multi-agent mode is not enabled")
    if not str(task or "").strip():
        raise ToolError("task is empty")
    depth = parent.depth + 1
    if depth > cfg.max_depth:
        raise ToolError(f"max depth reached ({cfg.max_depth}); do the work yourself")
    if shared.spawned >= cfg.max_children:
        raise ToolError(f"max sub-agents per run reached ({cfg.max_children}); do the work yourself")

    b = parent.budget
    left_steps = b.max_steps - st.steps
    left_calls = b.max_tool_calls - st.tool_calls - 1   # the spawn call itself counts
    left_tokens = b.max_tokens - st.tokens
    if left_steps < 1 or left_calls < 1 or left_tokens < 1:
        raise ToolError("not enough budget left for a sub-agent")
    budget = Budget(max_steps=min(max_steps or cfg.child_max_steps, left_steps),
                    max_tool_calls=left_calls, max_tokens=left_tokens, max_repeats=b.max_repeats)

    # Tools and permissions: a subset of the parent's, never more.
    parent_tools = set(parent.registry.tools)
    if allowed_tools is None:
        allowed = parent_tools
        perms = parent.permissions
    else:
        allowed = parent_tools & set(allowed_tools)
        perms = RestrictedPermissions(parent.permissions, allowed)
    base = Registry({n: t for n, t in parent.base_registry.tools.items() if n in allowed})

    shared.spawned += 1
    child_id = f"{parent.agent_id}.{shared.spawned}"
    parent.audit.record(event="spawn", agent=parent.agent_id, depth=parent.depth, child=child_id,
                        child_depth=depth, task=task, tools=sorted(allowed),
                        budget={"max_steps": budget.max_steps, "max_tool_calls": budget.max_tool_calls,
                                "max_tokens": budget.max_tokens})
    on_event = parent.on_event
    child = Agent(parent.llm, base, perms, parent.audit, parent.ctx, budget, confirm=parent.confirm,
                  on_event=lambda kind, data: on_event(kind, {**data, "agent": child_id}),
                  stop_rule=parent.stop_rule, swarm=cfg, depth=depth, agent_id=child_id,
                  swarm_state=shared, allow_spawn=bool(allowed & set(SPAWN_TOOLS)))
    res = child.run(task)
    # Deduct the child's usage from the parent's budget.
    st.steps += res.steps
    st.tool_calls += res.tool_calls
    st.tokens += res.tokens
    parent.audit.record(event="child_done", agent=child_id, depth=depth, parent=parent.agent_id,
                        stop_reason=res.stop_reason, steps=res.steps, tool_calls=res.tool_calls,
                        tokens=res.tokens, result=res.answer)
    return (f"[sub-agent {child_id}] stop={res.stop_reason} steps={res.steps} "
            f"tool_calls={res.tool_calls} tokens={res.tokens}\n{res.answer}")


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
        tools = _tool_list(a.get("allowed_tools"))
        steps = _int(a.get("max_steps"), "max_steps")
        out = []
        for t in tasks:
            try:
                out.append(spawn(agent, str(t), steps, tools))
            except ToolError as e:
                out.append(f"[sub-agent not started] {e}")
        return "\n\n".join(out)

    tools_prop = {"type": "array", "items": {"type": "string"},
                  "description": "optional: tools the sub-agent may use (subset of yours)"}
    steps_prop = {"type": "integer", "description": "optional: step budget (capped by what you have left)"}
    return [
        Tool("spawn_agent", "Launch a sub-agent on a self-contained task; returns its final answer. "
             "It uses your budget and never has more permissions than you.", "delegate",
             params(["task"], task=s("complete, self-contained instructions"), max_steps=steps_prop,
                    allowed_tools=tools_prop), _one),
        Tool("spawn_agents", "Launch several sub-agents one after the other (one per task); returns "
             "their answers in order.", "delegate",
             params(["tasks"], tasks={"type": "array", "items": {"type": "string"}}, max_steps=steps_prop,
                    allowed_tools=tools_prop), _many),
    ]
