"""Command line: python -m agent chat | run "task" | serve | memory | skills | permissions | audit."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, i18n
from .audit import AuditLog
from .llm import LLMError, make_llm
from .loop import Agent, Budget
from .memory import Memory
from .permissions import CATEGORIES, Permissions
from .skills import SkillLibrary
from .swarm import SwarmConfig
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


def make_confirm(interactive: bool, lang: str = "en"):
    always: set[str] = set()

    def confirm(tool: str, category: str, args: dict, reason: str) -> bool:
        if tool in always:
            return True
        if not interactive:
            print(i18n.t(lang, "cli.noTerminal", tool=tool, category=category), file=sys.stderr)
            return False
        shown = json.dumps(args, ensure_ascii=False)
        if len(shown) > 600:
            shown = shown[:600] + "..."
        print(f"\n  ? {tool} [{category}] {shown}\n    ({reason})", file=sys.stderr)
        while True:
            try:
                ans = input(i18n.t(lang, "cli.ask")).strip().lower()
            except EOFError:
                return False
            if ans in ("y", "yes", "o", "oui"):
                return True
            if ans in ("a", "always", "t", "toujours"):
                always.add(tool)
                return True
            if ans in ("", "n", "no", "non"):
                return False

    return confirm


def printer(kind: str, data: dict) -> None:
    who = f"[{data['agent']}] " if data.get("agent") else ""
    if kind == "tool":
        args = json.dumps(data["args"], ensure_ascii=False)
        print(f"  {who}-> {data['name']} [{data['category']}] {args[:160]} : {data['decision']}", file=sys.stderr)
    elif kind == "assistant" and not data["final"]:
        print(f"  {who}.. {data['content'][:300]}", file=sys.stderr)
    elif kind == "assistant" and who:
        print(f"  {who}<- {data['content'][:300]}", file=sys.stderr)
    elif kind == "stop":
        print(f"  {who}[stop: {data['reason']}]", file=sys.stderr)
    elif kind == "idc" and data.get("commit"):
        c = data["commit"]
        print(f"  {who}[idc] {c['id']} {c['kind']} (-{c['cost']:g}, vitality {data['vitality']:g}): {c['text'][:200]}",
              file=sys.stderr)
    elif kind == "idc" and data.get("collapse"):
        print(f"  {who}[idc] collapse: {data['collapse']} (vitality {data['vitality']:g})", file=sys.stderr)


def parts(args) -> tuple[Permissions, ToolContext, Path]:
    """What every agent of this process shares: permissions, tool context (workspace, memory, skills), state dir."""
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
    args._router = make_router(args, ws, state)
    return perms, ctx, state


def keys_file(args, ws: Path) -> Path | None:
    """--keys, else AGENT_KEYS_FILE, else ./providers.yaml or <workspace>/providers.yaml if present."""
    if getattr(args, "keys", None):
        return Path(args.keys)
    if os.environ.get("AGENT_KEYS_FILE"):
        return Path(os.environ["AGENT_KEYS_FILE"])
    for cand in (Path.cwd() / "providers.yaml", ws / "providers.yaml"):
        if cand.is_file():
            return cand
    return None


def make_router(args, ws: Path, state: Path):
    """A KeyRouter when a keys file is configured and no --provider was forced; else None (.env mode)."""
    if args.provider and not getattr(args, "keys", None):
        return None
    path = keys_file(args, ws)
    if path is None:
        return None
    if not path.is_file():
        raise FileNotFoundError(f"keys file not found: {path}")
    from .keys import KeyRouter
    return KeyRouter.from_file(path, state / "usage.json", AuditLog(state / "audit.jsonl"))


def new_agent(args, perms: Permissions, ctx: ToolContext, audit: AuditLog, confirm, on_event, cancel=None,
              idc: bool | None = None) -> Agent:
    """`idc`: None = follow the configuration (env, file, CLI); True/False = force (harness, per conversation)."""
    router = getattr(args, "_router", None)
    if router is not None:
        from .llm import RoutedLLM
        llm = RoutedLLM(router, args.category)
    else:
        llm = make_llm(args.provider, args.model)
    registry = default_registry(enable_web=not args.offline, enable_github=not args.offline)
    budget = Budget(max_steps=args.max_steps, max_tool_calls=args.max_tool_calls, max_tokens=args.max_tokens)
    swarm = (SwarmConfig(max_depth=args.max_depth, max_children=args.max_children,
                         max_parallel=max(1, args.max_parallel)) if args.max_depth > 0 else None)
    ctrl = None
    cfg = idc_config(args, perms)
    if cfg.enabled if idc is None else idc:
        from .idc import IDC
        ctrl = IDC(cfg, lang=args.lang)
    return Agent(llm, registry, perms, audit, ctx, budget, confirm=confirm, on_event=on_event,
                 swarm=swarm, cancel=cancel, idc=ctrl)


def idc_config(args, perms: Permissions):
    """IDC settings: defaults < `idc:` in the permissions file < AGENT_IDC* env < --idc/--no-idc, --idc-vitality."""
    from .idc import IDCConfig
    cfg = IDCConfig.from_sources(perms.idc, enabled=getattr(args, "idc", None))
    if getattr(args, "idc_vitality", None) is not None:
        cfg.vitality = args.idc_vitality
        cfg.validate()
    return cfg


def build(args) -> tuple[Agent, Permissions]:
    perms, ctx, state = parts(args)
    agent = new_agent(args, perms, ctx, AuditLog(state / "audit.jsonl"), make_confirm(sys.stdin.isatty(), args.lang),
                      None if args.quiet else printer)
    return agent, perms


def serve(args) -> int:
    from .harness import Harness, make_server

    perms, ctx, state = parts(args)
    if args._router is None:
        make_llm(args.provider, args.model)   # fail fast on a missing key

    def factory(task, audit, confirm, cancel, on_event):
        return new_agent(args, perms, ctx, audit, confirm, on_event, cancel, idc=False)   # the harness sets IDC

    idc_cfg = idc_config(args, perms)

    store = None
    if not args.no_persist:
        from .store import Store
        store = Store(Path(args.db).resolve() if args.db else state / "harness.sqlite3")
    h = Harness(factory, state / "audit.jsonl", approval_timeout=args.approval_timeout, max_tasks=args.max_tasks,
                workspace=ctx.workspace, max_upload_mb=args.max_upload_mb, max_message_mb=args.max_message_mb,
                key_router=args._router, store=store, backend=backend_info(args), idc_config=idc_cfg,
                lang=args.lang)
    srv = make_server(h, args.host, args.port, os.environ.get("AGENT_HARNESS_TOKEN"))
    host, port = srv.server_address[:2]
    print(f"harness on http://{'127.0.0.1' if host == '127.0.0.1' else host}:{port}/  "
          f"(workspace {ctx.workspace}, {perms.source}"
          f"{', token required' if os.environ.get('AGENT_HARNESS_TOKEN') else ''}) — Ctrl+C to stop", file=sys.stderr)
    import signal

    def _stop(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _stop)
    except ValueError:  # not in the main thread
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        h.shutdown()
        srv.server_close()
        if store is not None:
            store.close()
    return 0


def backend_info(args) -> dict:
    """Single-key (.env) backend, for GET /health: provider, model, base URL, masked key. No network."""
    from .keys import mask
    from .llm import PROVIDERS
    provider = (args.provider or os.environ.get("AGENT_PROVIDER") or "mock").lower()
    cfg = PROVIDERS.get(provider)
    if cfg is None:
        return {"provider": provider, "model": args.model, "base_url": None, "key": None}
    secret = os.environ.get(cfg.get("key_env") or "") if cfg.get("key_env") else None
    return {"provider": provider, "model": args.model or os.environ.get("AGENT_MODEL") or cfg.get("model"),
            "base_url": os.environ.get("AGENT_BASE_URL") or cfg.get("base_url"),
            "key": mask(secret) if secret else "(not set)", "key_env": cfg.get("key_env")}


def common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace", "-w", default=".", help="directory the agent may work in (default: .)")
    p.add_argument("--permissions", "-p", default=None, help="permissions.yaml/.json (default: ./permissions.yaml if present, else safe defaults)")
    p.add_argument("--model", "-m", default=None, help="model name (default: AGENT_MODEL or provider default)")
    p.add_argument("--provider", default=None, help="groq|openai|openrouter|ollama|custom|mock (default: AGENT_PROVIDER or mock)")
    p.add_argument("--state-dir", default=None, help="memory + audit directory (default: <workspace>/.agent)")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--max-tool-calls", type=int, default=24)
    p.add_argument("--max-tokens", type=int, default=60000)
    p.add_argument("--max-depth", type=int, default=2, help="sub-agent nesting limit; 0 disables multi-agent mode")
    p.add_argument("--max-children", type=int, default=5, help="max sub-agents per run (whole tree)")
    p.add_argument("--max-parallel", type=int, default=3,
                   help="spawn_agents: read-only sub-agents run in parallel up to this many (1 = sequential)")
    p.add_argument("--keys", default=None,
                   help="providers.yaml with several keys + limits (default: AGENT_KEYS_FILE or ./providers.yaml if present)")
    p.add_argument("--category", default="text", help="key category used for the chat model (text, code...)")
    p.add_argument("--yolo", action="store_true", help="turn 'ask' into 'allow' EXCEPT for send and spend")
    p.add_argument("--offline", action="store_true", help="do not register network tools (web, GitHub)")
    p.add_argument("--quiet", "-q", action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--idc", dest="idc", action="store_true", default=None,
                   help="IDC mode: vitality budget, append-only commitments, forced collapse (default: AGENT_IDC or off)")
    g.add_argument("--no-idc", dest="idc", action="store_false", help="turn IDC mode off")
    p.add_argument("--idc-vitality", type=float, default=None, help="IDC: initial vitality per user message")
    p.add_argument("--lang", default=None, choices=i18n.LANGS,
                   help="language of terminal prompts/messages: en|fr (default: AGENT_LANG, else en)")


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
    p_keys = sub.add_parser("keys", help="API keys: remaining quota per key and category (keys masked)")
    p_srv = sub.add_parser("serve", help="local harness: JSON API + web page, approvals queue")
    p_srv.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    p_srv.add_argument("--port", type=int, default=8765)
    p_srv.add_argument("--approval-timeout", type=float, default=300.0,
                       help="seconds to wait for an approval; no answer = deny (default 300)")
    p_srv.add_argument("--max-upload-mb", type=float, default=20, help="chat attachments: max size per file (MB)")
    p_srv.add_argument("--max-message-mb", type=float, default=50, help="chat attachments: max total per message (MB)")
    p_srv.add_argument("--max-tasks", type=int, default=4, help="conversations/tasks running at once (default 4)")
    p_srv.add_argument("--db", default=None,
                       help="SQLite file for conversations, events, schedules, rules (default <state-dir>/harness.sqlite3)")
    p_srv.add_argument("--no-persist", action="store_true", help="keep everything in memory only (lost on restart)")
    for p in (p_chat, p_run, p_mem, p_sk, p_perm, p_aud, p_srv, p_keys):
        common(p)
    args = ap.parse_args(argv)
    args.lang = i18n.normalize(args.lang) if getattr(args, "lang", None) else i18n.env_lang()
    if args.cmd in ("memory", "skills", "permissions", "audit"):
        args.provider = "mock"  # these commands never call a model
    if args.cmd == "keys":
        try:
            ws = Path(args.workspace).resolve()
            state = Path(args.state_dir).resolve() if args.state_dir else ws / ".agent"
            args.provider = None
            router = make_router(args, ws, state)
        except (ValueError, FileNotFoundError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if router is None:
            print(i18n.t(args.lang, "cli.noKeys"), file=sys.stderr)
            return 0
        st = router.status()
        for k in st["keys"]:
            flag = "" if k["available"] else i18n.t(args.lang, "cli.unavailable")
            if k["cooldown_s"]:
                flag += i18n.t(args.lang, "cli.cooldown", s=k["cooldown_s"])
            print(f"{k['name']}  {k['key']}  p{k['priority']}  {','.join(k['categories'])}{flag}")
            for f, v in k["limits"].items():
                print(i18n.t(args.lang, "cli.limit", name=f, used=f"{v['used']:g}", limit=f"{v['limit']:g}",
                             left=f"{v['remaining']:g}"))
        return 0
    if args.cmd == "serve":
        try:
            return serve(args)
        except (LLMError, ValueError, FileNotFoundError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    try:
        agent, perms = build(args)
    except (LLMError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.cmd == "run":
        res = agent.run(args.task)
        print(res.answer)
        print(f"[{res.stop_reason}] steps={res.steps} tool_calls={res.tool_calls} tokens={res.tokens}", file=sys.stderr)
        if agent.idc is not None:
            v = agent.idc.snapshot()
            print(f"[idc] vitality {v['vitality']:g}/{v['max']:g}, commitments {v['commitments']}", file=sys.stderr)
        return 0 if res.stop_reason in ("final", "idc_collapse") else 1
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
