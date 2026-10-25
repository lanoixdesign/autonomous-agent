"""Command line: python -m agent chat | run "task" | memory | skills | permissions | audit."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .audit import AuditLog
from .llm import LLMError, make_llm
from .loop import Agent, Budget
from .memory import Memory
from .permissions import CATEGORIES, Permissions
from .skills import SkillLibrary
from .tools import ToolContext, default_registry

REPO_SKILLS = Path(__file__).resolve().parent.parent / "skills"


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines; never overrides variables already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def make_confirm(interactive: bool):
    always: set[str] = set()

    def confirm(tool: str, category: str, args: dict, reason: str) -> bool:
        if tool in always:
            return True
        if not interactive:
            print(f"  ! {tool} [{category}] needs confirmation but there is no terminal -> refused", file=sys.stderr)
            return False
        shown = json.dumps(args, ensure_ascii=False)
        if len(shown) > 600:
            shown = shown[:600] + "..."
        print(f"\n  ? {tool} [{category}] {shown}\n    ({reason})", file=sys.stderr)
        while True:
            try:
                ans = input("    allow? [y]es / [n]o / [a]lways this session: ").strip().lower()
            except EOFError:
                return False
            if ans in ("y", "yes", "o", "oui"):
                return True
            if ans in ("a", "always", "toujours"):
                always.add(tool)
                return True
            if ans in ("", "n", "no", "non"):
                return False

    return confirm


def printer(kind: str, data: dict) -> None:
    if kind == "tool":
        args = json.dumps(data["args"], ensure_ascii=False)
        print(f"  -> {data['name']} [{data['category']}] {args[:160]} : {data['decision']}", file=sys.stderr)
    elif kind == "assistant" and not data["final"]:
        print(f"  .. {data['content'][:300]}", file=sys.stderr)
    elif kind == "stop":
        print(f"  [stop: {data['reason']}]", file=sys.stderr)


def build(args) -> tuple[Agent, Permissions]:
    ws = Path(args.workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    state = Path(args.state_dir).resolve() if args.state_dir else ws / ".agent"
    perm_path = args.permissions
    if perm_path is None:
        for cand in (Path.cwd() / "permissions.yaml", ws / "permissions.yaml"):
            if cand.is_file():
                perm_path = cand
                break
    perms = Permissions.load(perm_path, yolo=args.yolo)
    mem = Memory(state / "memory")
    skills = SkillLibrary([ws / "skills", state / "skills", REPO_SKILLS])
    ctx = ToolContext(workspace=ws, memory=mem, skills=skills)
    llm = make_llm(args.provider, args.model)
    registry = default_registry(enable_web=not args.offline, enable_github=not args.offline)
    budget = Budget(max_steps=args.max_steps, max_tool_calls=args.max_tool_calls, max_tokens=args.max_tokens)
    agent = Agent(llm, registry, perms, AuditLog(state / "audit.jsonl"), ctx, budget,
                  confirm=make_confirm(sys.stdin.isatty()), on_event=None if args.quiet else printer)
    return agent, perms


def common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace", "-w", default=".", help="directory the agent may work in (default: .)")
    p.add_argument("--permissions", "-p", default=None, help="permissions.yaml/.json (default: ./permissions.yaml if present, else safe defaults)")
    p.add_argument("--model", "-m", default=None, help="model name (default: AGENT_MODEL or provider default)")
    p.add_argument("--provider", default=None, help="groq|openai|openrouter|ollama|custom|mock (default: AGENT_PROVIDER or mock)")
    p.add_argument("--state-dir", default=None, help="memory + audit directory (default: <workspace>/.agent)")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--max-tool-calls", type=int, default=24)
    p.add_argument("--max-tokens", type=int, default=60000)
    p.add_argument("--yolo", action="store_true", help="turn 'ask' into 'allow' EXCEPT for send and spend")
    p.add_argument("--offline", action="store_true", help="do not register network tools (web, GitHub)")
    p.add_argument("--quiet", "-q", action="store_true")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    ap = argparse.ArgumentParser(prog="python -m agent", description="Autonomous agent with tunable guardrails.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_chat = sub.add_parser("chat", help="interactive conversation")
    p_run = sub.add_parser("run", help="run one task and exit")
    p_run.add_argument("task")
    p_mem = sub.add_parser("memory", help="list | recall Q | add TEXT | forget Q")
    p_mem.add_argument("action", choices=["list", "recall", "add", "forget"])
    p_mem.add_argument("text", nargs="?", default="")
    p_sk = sub.add_parser("skills", help="list | show NAME")
    p_sk.add_argument("action", choices=["list", "show"], nargs="?", default="list")
    p_sk.add_argument("name", nargs="?")
    p_perm = sub.add_parser("permissions", help="show the effective permissions")
    p_aud = sub.add_parser("audit", help="show the last audit entries")
    p_aud.add_argument("-n", type=int, default=20)
    for p in (p_chat, p_run, p_mem, p_sk, p_perm, p_aud):
        common(p)
    args = ap.parse_args(argv)
    if args.cmd in ("memory", "skills", "permissions", "audit"):
        args.provider = "mock"  # these commands never call a model
    try:
        agent, perms = build(args)
    except (LLMError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.cmd == "run":
        res = agent.run(args.task)
        print(res.answer)
        print(f"[{res.stop_reason}] steps={res.steps} tool_calls={res.tool_calls} tokens={res.tokens}", file=sys.stderr)
        return 0 if res.stop_reason == "final" else 1
    if args.cmd == "chat":
        print(f"autonomous-agent {__version__} — model: {getattr(agent.llm, 'model', '?')} — /exit to quit, /perms, /memory", file=sys.stderr)
        print(perms.summary(), file=sys.stderr)
        while True:
            try:
                line = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line in ("/exit", "/quit"):
                return 0
            if line == "/perms":
                print(perms.summary())
                continue
            if line == "/memory":
                print(agent.ctx.memory.context() or "(empty)")
                continue
            res = agent.run(line)
            print(f"\nagent> {res.answer}")
    if args.cmd == "memory":
        mem = agent.ctx.memory
        if args.action == "list":
            for e in mem.recall("", limit=1000):
                print(f"[{e.get('id')}] ({e.get('kind')}) {e['text']}")
        elif args.action == "recall":
            for e in mem.recall(args.text):
                print(f"[{e.get('id')}] score={e['score']} {e['text']}")
        elif args.action == "add":
            print(json.dumps(mem.write(args.text), ensure_ascii=False))
        else:
            print(f"forgot {mem.forget(args.text)} item(s)")
        return 0
    if args.cmd == "skills":
        lib = agent.ctx.skills
        if args.action == "show":
            try:
                print(lib.load(args.name or ""))
            except KeyError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
        else:
            print(lib.index() or "no skills")
        return 0
    if args.cmd == "permissions":
        print(perms.summary())
        print("\ntools and their categories:")
        for t in agent.registry.tools.values():
            d = perms.decide(t.name, t.category)
            print(f"  {t.name:14s} {t.category:8s} -> {d.mode}")
        return 0
    if args.cmd == "audit":
        for e in agent.audit.tail(args.n):
            print(json.dumps(e, ensure_ascii=False))
        return 0
    return 0


assert set(CATEGORIES) >= {"read", "write", "execute", "network", "send", "spend"}
