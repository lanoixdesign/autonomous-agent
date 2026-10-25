# autonomous-agent

*[English version: README.md](README.md)*

Un petit agent autonome open source en Python (bibliothèque standard uniquement), lisible, avec
**outils, mémoire durable et compétences (skills)**, et des **garde-fous que vous réglez
vous-même** : chaque outil a une catégorie de risque, et un fichier `permissions.yaml` décide, par
catégorie et par outil, si l'appel est autorisé (`allow`), soumis à confirmation dans le terminal
(`ask`) ou refusé (`deny`). Chaque appel d'outil est écrit dans un journal d'audit en ajout seul,
secrets masqués.

> Ce n'est pas « un agent sans garde-fous ». Les garde-fous existent ; c'est **vous** qui les réglez.

## Fonctions

| | |
|---|---|
| **Boucle** | plan → appel d'outil → observation → … → réponse, avec limites de pas, d'appels d'outils et de tokens, plus un arrêt « pas de progrès » (même appel répété). `stop_rule` personnalisable. |
| **Outils** | `read_file`, `list_files`, `search_files`, `write_file`, `edit_file` (dans l'espace de travail), `shell`, `web_fetch`, `web_search` (au mieux), `github_get`, `github_write`, `memory_write`, `memory_recall`, `memory_forget`, `list_skills`, `load_skill` |
| **Catégories de risque** | `read`, `write`, `execute`, `network`, `send` (visible par d'autres), `spend` (coûte de l'argent) |
| **Mémoire** | fichiers simples : `memory/profile.md` + `memory/journal.jsonl`, rappel par mots-clés, oubli (`forget`) |
| **Compétences** | `skills/<nom>/SKILL.md` avec frontmatter `name` / `description` ; seul l'index est dans le prompt, le contenu est chargé à la demande. Exemples : `research`, `code-review`, `release-notes`. |
| **LLM** | toute API compatible OpenAI : Groq, OpenAI, OpenRouter, Ollama (local), URL personnalisée ; backend `mock` pour les tests hors ligne |

## Installation

```bash
git clone https://github.com/lanoixdesign/autonomous-agent.git
cd autonomous-agent
python -m venv .venv && . .venv/bin/activate   # Python 3.10+
pip install pyyaml pytest   # facultatifs : sans PyYAML, un mini-analyseur YAML intégré est utilisé
cp .env.example .env        # mettez votre clé dans .env (ne le commitez jamais)
```

## Configurer le modèle

Variables d'environnement (ou `.env`) :

| Variable | Rôle |
|---|---|
| `AGENT_PROVIDER` | `groq`, `openai`, `openrouter`, `ollama`, `custom`, `mock` (défaut `mock`) |
| `AGENT_MODEL` | nom du modèle (défauts : groq `openai/gpt-oss-120b`, openai `gpt-4o-mini`, openrouter `openai/gpt-4o-mini`, ollama `llama3.1`) |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | clé du fournisseur choisi |
| `AGENT_BASE_URL`, `AGENT_API_KEY` | tout autre point d'accès compatible OpenAI (`custom`) |
| `GITHUB_TOKEN` | facultatif, pour les outils GitHub (sinon la connexion du CLI `gh`) |
| `AGENT_SEARCH_URL` | facultatif, moteur de recherche web (DuckDuckGo HTML par défaut) |

Aucune clé n'est écrite dans le code. Les requêtes envoient un en-tête `User-Agent` (certains
fournisseurs derrière Cloudflare refusent les requêtes sans).

## Utilisation

```bash
python -m agent run "Résume notes.md et garde l'essentiel en mémoire" --workspace ~/projet
python -m agent chat --workspace ~/projet --provider groq
python -m agent run "..." --model openai/gpt-oss-20b --permissions mes-perms.yaml
python -m agent run "Liste les fichiers" --provider mock --offline   # aucun accès réseau

python -m agent permissions      # permissions effectives, outil par outil
python -m agent audit -n 20      # dernières entrées du journal d'audit
python -m agent memory list | recall "requête" | add "texte" | forget "texte-ou-id"
python -m agent skills list | show code-review
```

Options : `--workspace/-w`, `--permissions/-p`, `--model/-m`, `--provider`, `--state-dir`
(mémoire + audit, défaut `<workspace>/.agent`), `--max-steps`, `--max-tool-calls`, `--max-tokens`,
`--yolo`, `--offline`, `--quiet`.

Exemple (essai réel, Groq `openai/gpt-oss-120b`, sans terminal donc `ask` = refusé) :

```
  -> list_files [read] {"depth": 1, "path": "."} : allow
  -> read_file [read] {"limit": 200, "path": "notes.md"} : allow
  -> memory_write [write] {"kind": "note", ...} : allow
  ! write_file [write] needs confirmation but there is no terminal -> refused
[final] steps=5 tool_calls=4 tokens=6520
```

## Modèle de permissions

`permissions.yaml` (ou `.json`). Pour chaque appel :

1. mode = `tools.<outil>` s'il est défini, sinon `defaults.<catégorie>` ;
2. un motif **deny** correspondant (`paths.deny`, `commands.deny`, `domains.deny`) → **refus** (gagne toujours, même avec `--yolo`) ;
3. `paths.allow` non vide et chemin non couvert → refus ;
4. `commands.allow` / `domains.allow` correspondant et mode `ask` → autorisé ;
5. `--yolo` transforme `ask` en `allow` **sauf pour `send` et `spend`** : pour ces deux-là, seul ce que vous avez écrit dans le fichier compte.

Défauts sûrs : `read: allow`, `write: ask`, `execute: ask`, `network: ask`, `send: ask`, `spend: deny`.
`ask` demande `[y]es / [n]o / [a]lways` (oui / non / toujours pour cette session) ; sans terminal,
`ask` vaut refus.

```yaml
defaults: {read: allow, write: ask, execute: ask, network: ask, send: ask, spend: deny}
tools:
  memory_write: allow
  shell: deny            # par ex. interdire complètement le shell
paths:
  deny: [".env", "**/.env", "**/*.pem", ".git/**", ".agent/**"]
commands:
  allow: ["git status*", "python -m pytest*"]
  deny: ["sudo *", "*rm -rf /*", "*curl *|*sh*"]
domains:
  allow: ["api.github.com"]
```

**Audit** : `<state-dir>/audit.jsonl`, une ligne JSON par appel d'outil (autorisé, refusé,
invalide), ouvert en mode `O_APPEND`. Arguments et résultats sont tronqués et masqués : valeurs des
variables d'environnement dont le nom contient KEY/TOKEN/SECRET/PASSWORD…, et formats de jetons
courants (`sk-…`, `gsk_…`, `ghp_…`, `github_pat_…`, Bearer, clés privées). Le shell s'exécute sans
ces variables dans son environnement.

## Écrire une compétence

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

## Règle d'arrêt et IDC (facultatif)

La boucle s'arrête de façon irréversible au premier de : réponse finale, `max_steps`,
`max_tool_calls`, `max_tokens`, appel identique répété, erreur du LLM. Ce principe d'arrêt explicite
s'inspire du projet IDC de l'auteur ([lanoixdesign/idc-wrapper](https://github.com/lanoixdesign/idc-wrapper)) ;
ce n'est **pas** une dépendance. Pour brancher votre propre critère :
`Agent(..., stop_rule=lambda state: "ma_raison" if ... else None)`.

## Tests

```bash
python -m pytest -q
```

La CI (GitHub Actions) lance les tests sous Python 3.10 à 3.13, avec et sans PyYAML, plus un essai
de bout en bout hors ligne avec le backend mock.

## Limites (honnêtement)

- **Aucun audit de sécurité n'a été fait.** C'est un petit projet pédagogique, pas un bac à sable.
- **Le shell est dangereux si vous le mettez en `allow`.** Les motifs de commandes interdites sont une
  ceinture de sécurité facile à contourner (`bash -c`, scripts, alias…). Pour des tâches non fiables,
  lancez l'agent dans un conteneur ou une VM.
- Le confinement à l'espace de travail vaut pour les outils fichiers ; le shell accède à tout ce que
  votre utilisateur peut atteindre.
- Le masquage des secrets repose sur des motifs : un format inconnu peut passer.
- Le contenu web peut contenir de l'injection de prompt ; le prompt système prévient le modèle, il ne l'empêche pas.
- Le rappel mémoire est une simple recherche par mots-clés, sans embeddings.
- `web_search` lit une page HTML publique et peut être bloqué ; préférez `web_fetch` sur des URL connues.
- La qualité dépend beaucoup du modèle ; les petits modèles locaux appellent souvent mal les outils.
- Ce projet est indépendant : ce n'est **pas** Grok Bot et il ne le reproduit pas.

## Licence

MIT — voir [LICENSE](LICENSE).
