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
| **Tools** | `read_file`, `list_files`, `search_files`, `write_file`, `edit_file` (workspace only), `shell`, `web_fetch`, `web_search` (best-effort), `github_get`, `github_write`, `memory_write`, `memory_recall`, `memory_forget`, `list_skills`, `load_skill` |
| **Risk categories** | `read`, `write`, `execute`, `network`, `send` (visible to others), `spend` (costs money) |
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
```

Options: `--workspace/-w`, `--permissions/-p`, `--model/-m`, `--provider`, `--state-dir`
(memory + audit, default `<workspace>/.agent`), `--max-steps`, `--max-tool-calls`, `--max-tokens`,
`--yolo`, `--offline`, `--quiet`.

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

Safe defaults: `read: allow`, `write: ask`, `execute: ask`, `network: ask`, `send: ask`, `spend: deny`.
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
