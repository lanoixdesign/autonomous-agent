# Tools and skills / Outils et compétences

**[English](#english) | [Français](#francais)** · [← README](../README.md) · [Docs](README.md)

<a id="english"></a>

## English

### Features

| | |
|---|---|
| **Loop** | plan → tool call → observation → … → answer, with limits on steps, tool calls and tokens, plus a "no progress" stop (same call repeated). Pluggable `stop_rule`. |
| **Tools** | `read_file`, `list_files`, `search_files`, `write_file`, `edit_file` (workspace only), `shell`, `web_fetch`, `web_search` (best-effort), `github_get`, `github_write`, `memory_write`, `memory_recall`, `memory_forget`, `list_skills`, `load_skill`, `spawn_agent`, `spawn_agents` (sub-agents) |
| **Risk categories** | `read`, `write`, `execute`, `network`, `send` (visible to others), `spend` (costs money), `delegate` (launch sub-agents) |
| **Memory** | plain files: `memory/profile.md` + `memory/journal.jsonl`, keyword recall, `forget` |
| **Skills** | `skills/<name>/SKILL.md` with `name` / `description` frontmatter; only the index is in the prompt, bodies are loaded on demand. Examples: `research`, `code-review`, `release-notes`. |
| **LLM** | any OpenAI-compatible API: Groq, OpenAI, OpenRouter, Ollama (local), custom URL; `mock` backend for offline tests |
| **Harness** | `python -m agent serve`: local chat with approval cards, attachments, several API keys with quotas, live updates (SSE), conversations persisted in SQLite, emergency stop, remembered approvals (never for send/spend), usage per agent, Markdown/JSON export, scheduled prompts, `/health` |
| **Mobile** | responsive chat/dashboard, installable PWA, `--remote` with QR pairing, Tailscale / Cloudflare tunnels |
| **Sandbox** | `shell` restricted to an allowlist inside the workspace: no shell operators, path + symlink checks, no network, scrubbed env, CPU/memory/time/output limits (always on in the app's Simple mode, `--sandbox` / `AGENT_SANDBOX=1` for the CLI) |
| **Developer mode** | `/dev`: website / Python templates in `projects/<name>/`, Coder + Tester helpers, sandboxed live preview, tests in the sandbox, `.zip` download |

### Writing a skill

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

---

<a id="francais"></a>

## Français

### Fonctions

| | |
|---|---|
| **Boucle** | plan → appel d'outil → observation → … → réponse, avec limites de pas, d'appels d'outils et de tokens, plus un arrêt « pas de progrès » (même appel répété). `stop_rule` personnalisable. |
| **Outils** | `read_file`, `list_files`, `search_files`, `write_file`, `edit_file` (dans l'espace de travail), `shell`, `web_fetch`, `web_search` (au mieux), `github_get`, `github_write`, `memory_write`, `memory_recall`, `memory_forget`, `list_skills`, `load_skill`, `spawn_agent`, `spawn_agents` (sous-agents) |
| **Catégories de risque** | `read`, `write`, `execute`, `network`, `send` (visible par d'autres), `spend` (coûte de l'argent), `delegate` (lancer des sous-agents) |
| **Mémoire** | fichiers simples : `memory/profile.md` + `memory/journal.jsonl`, rappel par mots-clés, oubli (`forget`) |
| **Compétences** | `skills/<nom>/SKILL.md` avec frontmatter `name` / `description` ; seul l'index est dans le prompt, le contenu est chargé à la demande. Exemples : `research`, `code-review`, `release-notes`. |
| **LLM** | toute API compatible OpenAI : Groq, OpenAI, OpenRouter, Ollama (local), URL personnalisée ; backend `mock` pour les tests hors ligne |
| **Harness** | `python -m agent serve` : chat local avec cartes de validation, pièces jointes, plusieurs clés d'API avec quotas, direct (SSE), conversations enregistrées dans SQLite, arrêt d'urgence, validations retenues (jamais pour send/spend), consommation par agent, export Markdown/JSON, prompts planifiés, `/health` |
| **Mobile** | chat et tableau de bord adaptés au téléphone, PWA installable, `--remote` avec appairage par QR code, tunnels Tailscale / Cloudflare |
| **Bac à sable** | `shell` limité à une liste de commandes dans l'espace de travail : pas d'opérateurs shell, contrôle des chemins et des liens, pas de réseau, environnement nettoyé, limites processeur/mémoire/temps/sortie (toujours actif en mode Simple, `--sandbox` / `AGENT_SANDBOX=1` en ligne de commande) |
| **Mode développeur** | `/dev` : modèles site web / Python dans `projects/<nom>/`, assistants Codeur + Testeur, aperçu en direct protégé, tests dans le bac à sable, téléchargement `.zip` |

### Écrire une compétence

```
skills/ma-competence/SKILL.md
---
name: ma-competence
description: Une phrase qui dit quand l'utiliser.
---
# Étapes
1. ...
```

Recherche dans `<workspace>/skills`, `<state-dir>/skills`, puis `skills/` du dépôt.
