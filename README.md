# autonomous-agent

*[Version française : README.fr.md](README.fr.md)*

A small, readable, open-source autonomous agent in Python (stdlib only) with **tools, durable
memory and skills**, and **guardrails that you tune yourself**: every tool has a risk category,
and a `permissions.yaml` file decides, per category and per tool, whether it is `allow`ed, `ask`ed
(confirmation in the terminal) or `deny`ed. Every tool call is written to an append-only audit log,
with secrets redacted.

> It is not "an agent without guardrails". The guardrails are there; **you** set them.

## Features

| | |
|---|---|
| **Loop** | plan → tool call → observation → … → answer, with limits on steps, tool calls and tokens, plus a "no progress" stop (same call repeated). Pluggable `stop_rule`. |
| **Tools** | `read_file`, `list_files`, `search_files`, `write_file`, `edit_file` (workspace only), `shell`, `web_fetch`, `web_search` (best-effort), `github_get`, `github_write`, `memory_write`, `memory_recall`, `memory_forget`, `list_skills`, `load_skill`, `spawn_agent`, `spawn_agents` (sub-agents) |
| **Risk categories** | `read`, `write`, `execute`, `network`, `send` (visible to others), `spend` (costs money), `delegate` (launch sub-agents) |
| **Memory** | plain files: `memory/profile.md` + `memory/journal.jsonl`, keyword recall, `forget` |
| **Skills** | `skills/<name>/SKILL.md` with `name` / `description` frontmatter; only the index is in the prompt, bodies are loaded on demand. Examples: `research`, `code-review`, `release-notes`. |
| **LLM** | any OpenAI-compatible API: Groq, OpenAI, OpenRouter, Ollama (local), custom URL; `mock` backend for offline tests |

## Install

```bash
git clone https://github.com/lanoixdesign/autonomous-agent.git
cd autonomous-agent
python -m venv .venv && . .venv/bin/activate   # Python 3.10+
pip install pyyaml pytest   # both optional: a built-in YAML subset parser is used without PyYAML
cp .env.example .env        # then put your key in .env (never commit it)
```

## Configure the model

Environment variables (or `.env`):

| Variable | Meaning |
|---|---|
| `AGENT_PROVIDER` | `groq`, `openai`, `openrouter`, `ollama`, `custom`, `mock` (default `mock`) |
| `AGENT_MODEL` | model name (defaults: groq `openai/gpt-oss-120b`, openai `gpt-4o-mini`, openrouter `openai/gpt-4o-mini`, ollama `llama3.1`) |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | key for the chosen provider |
| `AGENT_BASE_URL`, `AGENT_API_KEY` | any other OpenAI-compatible endpoint (`custom`) |
| `GITHUB_TOKEN` | optional, for GitHub tools (otherwise the `gh` CLI login is used) |
| `AGENT_SEARCH_URL` | optional web search endpoint (DuckDuckGo HTML by default) |

No key is ever hard-coded. Requests send a `User-Agent` header (some providers behind Cloudflare
reject requests without one).

## Use

```bash
python -m agent run "Summarise notes.md and save the key point in memory" --workspace ~/project
python -m agent chat --workspace ~/project --provider groq
python -m agent run "..." --model openai/gpt-oss-20b --permissions my-perms.yaml
python -m agent run "List the files" --provider mock --offline        # no network at all

python -m agent permissions      # effective permissions, tool by tool
python -m agent audit -n 20      # last audit entries
python -m agent memory list | recall "query" | add "text" | forget "text-or-id"
python -m agent skills list | show code-review
python -m agent serve --port 8765  # local harness: web page + JSON API + approvals queue
```

Options: `--workspace/-w`, `--permissions/-p`, `--model/-m`, `--provider`, `--state-dir`
(memory + audit, default `<workspace>/.agent`), `--max-steps`, `--max-tool-calls`, `--max-tokens`,
`--max-depth`, `--max-children`, `--max-parallel`, `--yolo`, `--offline`, `--quiet`.

Example (real run, Groq `openai/gpt-oss-120b`, no terminal so `ask` = refused):

```
  -> list_files [read] {"depth": 1, "path": "."} : allow
  -> read_file [read] {"limit": 200, "path": "notes.md"} : allow
  -> memory_write [write] {"kind": "note", ...} : allow
  ! write_file [write] needs confirmation but there is no terminal -> refused
[final] steps=5 tool_calls=4 tokens=6520
```

## Permission model

`permissions.yaml` (or `.json`). Resolution for each call:

1. mode = `tools.<tool>` if set, otherwise `defaults.<category>`;
2. a matching **deny** pattern (`paths.deny`, `commands.deny`, `domains.deny`) → **deny** (always wins, even with `--yolo`);
3. `paths.allow` non-empty and the path does not match → deny;
4. `commands.allow` / `domains.allow` match and mode is `ask` → allow;
5. `--yolo` turns `ask` into `allow` **except for `send` and `spend`**: those only follow what you wrote in the file.

Safe defaults: `read: allow`, `write: ask`, `execute: ask`, `network: ask`, `send: ask`, `spend: deny`, `delegate: ask`.
`ask` prompts `[y]es / [n]o / [a]lways this session`; without a terminal, `ask` means refused.

```yaml
defaults: {read: allow, write: ask, execute: ask, network: ask, send: ask, spend: deny}
tools:
  memory_write: allow
  shell: deny            # e.g. forbid the shell completely
paths:
  deny: [".env", "**/.env", "**/*.pem", ".git/**", ".agent/**"]
commands:
  allow: ["git status*", "python -m pytest*"]
  deny: ["sudo *", "*rm -rf /*", "*curl *|*sh*"]
domains:
  allow: ["api.github.com"]
```

**Audit**: `<state-dir>/audit.jsonl`, one JSON line per tool call (allowed, refused, invalid),
opened in `O_APPEND` mode. Arguments and results are truncated and redacted: values of environment
variables whose name contains KEY/TOKEN/SECRET/PASSWORD…, and common token formats (`sk-…`, `gsk_…`,
`ghp_…`, `github_pat_…`, Bearer, private keys). The shell tool runs with those variables removed
from its environment.

## Writing a skill

```
skills/my-skill/SKILL.md
---
name: my-skill
description: One sentence saying when to use it.
---
# Steps
1. ...
```

Skills are looked up in `<workspace>/skills`, `<state-dir>/skills`, then the repository's `skills/`.

## Stop rule and IDC (optional)

The loop stops irreversibly at the first of: final answer, `max_steps`, `max_tool_calls`,
`max_tokens`, repeated identical call, LLM error. This explicit-stop design is inspired by the
author's IDC project ([lanoixdesign/idc-wrapper](https://github.com/lanoixdesign/idc-wrapper)); it is
**not** a dependency. To plug in your own criterion: `Agent(..., stop_rule=lambda state: "my_reason" if ... else None)`.

## Multi-agent mode (sub-agents)

An agent can launch **sub-agents** with `spawn_agent(task, max_steps?, allowed_tools?)`, or several
in a row with `spawn_agents(tasks, ...)`. A sub-agent is a normal agent run in-process, with the same
model, workspace, memory and audit log; its final answer comes back to the parent as the observation.

Limits (all enforced in code, see `agent/swarm.py`):
- launching is the `delegate` risk category, **`ask` by default**;
- a sub-agent uses the **parent's permission policy**, optionally narrowed with `allowed_tools`: it can
  never do more than its parent (a `deny`, or `send` / `spend`, stays as the parent has it);
- its budget is capped by what the parent has left, and its usage is **deducted** from the parent;
- `--max-depth` (default 2: agent → sub-agent → sub-sub-agent; `0` disables the mode) and
  `--max-children` (default 5 sub-agents per run, whole tree);
- every audit line carries `agent` (`root`, `root.1`, `root.1.2`…) and `depth`, plus `spawn` /
  `child_done` events.

```bash
python -m agent run "Review src/ and docs/ in parallel: one sub-agent per folder, then merge" \
  --workspace ~/project --max-depth 1 --max-children 3
```

```
  -> spawn_agents [delegate] {"tasks": ["review src/", "review docs/"], "allowed_tools": ["read_file", "list_files"]} : allow
  [root.1] -> list_files [read] {"path": "src"} : allow
  [root.2] -> list_files [read] {"path": "docs"} : allow
```

Sub-agents share the parent's memory and inherit its `ask` confirmations.

**Parallel children** (`--max-parallel`, default 3). `spawn_agents` picks one mode per batch:

| children | mode |
|---|---|
| read-only (`allowed_tools` given, only `read`/`network` tools already `allow`/`deny`) | parallel, shared workspace |
| may write / execute, and no approval can be needed — or running under the harness | parallel, **one isolated copy of the workspace per child**, merged at the end |
| may need an approval in the terminal (`run`, `chat`) | sequential, shared workspace (prompts never mix) |

**Isolated copies**: each child works in a private temp dir (mode 0700) holding a copy of the parent
workspace, without `.git`, virtualenvs, `node_modules`, caches, `build`/`dist`, symlinks and files over
20 MB (the whole copy is capped at 200 MB; above that the batch runs sequentially). When the batch
ends, the changes are merged back:
- a file created / modified / deleted by **one** child (or identically by several) → applied;
- a file changed differently by **several** children, or changed in the parent meanwhile →
  **conflict**: the parent file is **not** touched, each child's version is written as
  `<file>.conflict-<agent id>` (e.g. `notes.md.conflict-root.2`); a deletion is only reported;
- the parent's observation lists what was applied and the conflicts, and the audit log gets an
  `event: merge` line. A cancelled task merges nothing. Temp copies are always removed.

Budget reservations, the child counter, memory writes and the audit writer are thread-safe. In the
example above the two children run in parallel in the shared workspace (read-only tools).

## Harness (local server, chat, approvals)

`python -m agent serve` starts a local harness: conversations run in background threads, sub-agents
included, and every `ask` goes to an **approval queue** instead of the terminal. Standard library only
(`http.server` + `threading`).

```bash
python -m agent serve --workspace ~/project --port 8765          # then open http://127.0.0.1:8765/
AGENT_HARNESS_TOKEN=change-me python -m agent serve --approval-timeout 120 --max-parallel 3 --max-tasks 4
```

**Chat** (`/` or `/chat`): type a message to start a conversation, or to continue the selected one
(same agent, history kept). Agent messages, tool steps, sub-agent launches, merges and conflicts appear
as chat bubbles labelled with the agent id (`root`, `root.1`, `root.1.2`…). Pending approvals pop up as
cards (top right) showing the agent id, the tool, the risk category and the arguments (secrets
redacted); several can be pending at once and each is answered on its own. The sidebar lists the
conversations, which can run at the same time (at most `--max-tasks`, default 4; the others wait as
`queued`). `/dashboard` keeps the compact view (agent tree + event log). The pages poll every second.

Because the harness can take several approvals at once, **writing sub-agents run in parallel** there,
each in its isolated copy (see above).

**Attachments**: the 📎 button or drag-and-drop (several files at once). Files show as chips before
sending, then as attachments in your bubble. They are saved under
`<workspace>/uploads/<conversation id>/`, and the agent's message gets the list of their
workspace-relative paths (small text files are also inlined), so it can open them with `read_file`.
- names are reduced to a plain file name (no directories, `..`, absolute paths, leading dot or control
  characters); files are created without following symlinks and never overwrite (`notes-1.md`); a
  symlinked `uploads/` directory is refused;
- `--max-upload-mb` per file (default 20) and `--max-message-mb` per message (default 50) → HTTP 413;
- same token / same-origin checks as the other POSTs; each file is audit-logged (`event: upload`,
  path, size, sha256).

| | |
|---|---|
| `POST /tasks` `{"task": "..."}` | start a conversation → `{"id": ...}` |
| `POST /tasks/{id}/messages` `{"text": "..."}` | continue it (409 while a turn is running) |
| `"files": [{"name": "a.md", "content_b64": "..."}]` | optional on both: attachments (base64 in the JSON body) · `GET /config`: limits |
| `GET /tasks` · `GET /tasks/{id}` | list · one task: status, result, usage, agent tree |
| `GET /tasks/{id}/events?since=N` | events (audit lines, messages, approvals) from N, for polling |
| `POST /tasks/{id}/cancel` | stop at the next step; its pending approvals are denied |
| `GET /approvals` (`?all=1`) · `POST /approvals/{id}` `{"decision": "approve"\|"deny"}` | approval queue |

```bash
curl -s -X POST localhost:8765/tasks -H 'Content-Type: application/json' -d '{"task":"Summarise notes.md"}'
curl -s localhost:8765/approvals
curl -s -X POST localhost:8765/approvals/<id> -H 'Content-Type: application/json' -d '{"decision":"approve"}'
```

- **No answer = deny**: an approval waits `--approval-timeout` seconds (default 300), then is refused.
- Binds **127.0.0.1** by default. With `AGENT_HARNESS_TOKEN` set, every API call needs
  `Authorization: Bearer <token>` (paste it in the page's token field). Binding another host prints a
  warning. POSTs must be JSON and same-origin, and the `Host` header is checked on localhost.
- Same `permissions.yaml`, memory and `audit.jsonl` as the CLI (harness lines carry a `task_id`).
  Terminal mode (`run`, `chat`) is unchanged.
- Not a multi-user server: no accounts, no TLS. Conversations live in memory and are lost when it
  stops (Ctrl+C / SIGTERM cancel running turns and remove temp copies).

## Tests

```bash
python -m pytest -q
```

CI (GitHub Actions) runs the tests on Python 3.10–3.13, with and without PyYAML, plus an offline
end-to-end run with the mock backend.

## Honest limitations

- **No security audit has been done.** This is a small educational project, not a sandbox.
- **The shell is dangerous if you set it to `allow`.** Command deny patterns are a seatbelt, easy to
  bypass (`bash -c`, scripts, aliases…). For untrusted tasks, run the agent in a container/VM.
- Workspace confinement applies to the file tools only; the shell can reach anything your user can.
- Secret redaction is pattern-based: an unknown secret format can slip through.
- Web content can contain prompt injection; the system prompt warns the model, it does not prevent it.
- Memory recall is simple keyword matching, no embeddings.
- `web_search` scrapes a public HTML endpoint and may be blocked; prefer `web_fetch` on known URLs.
- Quality depends heavily on the model; small local models often call tools badly.
- This project is independent: it is **not** Grok Bot and does not reproduce it.

## License

MIT — see [LICENSE](LICENSE).
