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
| **Outils** | `read_file`, `list_files`, `search_files`, `write_file`, `edit_file` (dans l'espace de travail), `shell`, `web_fetch`, `web_search` (au mieux), `github_get`, `github_write`, `memory_write`, `memory_recall`, `memory_forget`, `list_skills`, `load_skill`, `spawn_agent`, `spawn_agents` (sous-agents) |
| **Catégories de risque** | `read`, `write`, `execute`, `network`, `send` (visible par d'autres), `spend` (coûte de l'argent), `delegate` (lancer des sous-agents) |
| **Mémoire** | fichiers simples : `memory/profile.md` + `memory/journal.jsonl`, rappel par mots-clés, oubli (`forget`) |
| **Compétences** | `skills/<nom>/SKILL.md` avec frontmatter `name` / `description` ; seul l'index est dans le prompt, le contenu est chargé à la demande. Exemples : `research`, `code-review`, `release-notes`. |
| **LLM** | toute API compatible OpenAI : Groq, OpenAI, OpenRouter, Ollama (local), URL personnalisée ; backend `mock` pour les tests hors ligne |
| **Harness** | `python -m agent serve` : chat local avec cartes de validation, pièces jointes, plusieurs clés d'API avec quotas, direct (SSE), conversations enregistrées dans SQLite, arrêt d'urgence, validations retenues (jamais pour send/spend), consommation par agent, export Markdown/JSON, prompts planifiés, `/health` |

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
python -m agent serve --port 8765  # harness local : page web + API JSON + file de validation
python -m agent keys               # clés d'API (masquées) et quotas restants, si providers.yaml est utilisé
```

Options : `--workspace/-w`, `--permissions/-p`, `--model/-m`, `--provider`, `--state-dir`
(mémoire + audit, défaut `<workspace>/.agent`), `--max-steps`, `--max-tool-calls`, `--max-tokens`,
`--max-depth`, `--max-children`, `--max-parallel`, `--keys`, `--category`, `--yolo`, `--offline`, `--quiet`.

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

Défauts sûrs : `read: allow`, `write: ask`, `execute: ask`, `network: ask`, `send: ask`, `spend: deny`, `delegate: ask`.
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

## Plusieurs clés d'API, par catégorie, avec limites

Facultatif. Sans fichier de clés rien ne change : la clé unique du `.env` est utilisée comme avant.
Copiez `providers.example.yaml` en `providers.yaml` (ignoré par git ; ou `--keys FICHIER`, ou la
variable `AGENT_KEYS_FILE`). Chaque entrée indique la **variable d'environnement** qui contient la clé
(`key_env`), jamais la clé elle-même, plus `provider`/`base_url`, `model` ou `models` par catégorie,
`categories` (`text`, `code`, `image`, `audio_tts`, `audio_stt`, `embeddings`, ou les vôtres),
`priority` (la plus basse d'abord), `pricing` facultatif et des `limits` : `requests_per_minute`,
`requests_per_day`, `tokens_per_day`, `tokens_per_month`, `cost_per_day`, `cost_per_month` (dans votre
`currency`, nécessite `pricing`), `images_per_day`, `audio_minutes_per_day`.

```yaml
currency: EUR
keys:
  - name: groq-main
    provider: groq
    key_env: GROQ_API_KEY
    categories: [text, code]
    model: openai/gpt-oss-120b
    priority: 1
    pricing: {input_per_1m: 0.15, output_per_1m: 0.60}
    limits: {requests_per_day: 1000, tokens_per_day: 500000, cost_per_month: 5}
  - name: openrouter-backup
    provider: openrouter
    key_env: OPENROUTER_API_KEY
    categories: [text, code]
    model: openai/gpt-4o-mini
    priority: 2
```

- **Choix de la clé** : à chaque appel du modèle, le routeur prend la première clé de la catégorie (par
  priorité) qui est définie, pas en pause, et qui peut accepter la requête **sans dépasser aucune
  limite**. La requête est réservée avant l'envoi (jetons : invite estimée + plafond `max_tokens`
  envoyé au fournisseur, coût d'après `pricing`), donc des agents en parallèle ne peuvent pas dépasser
  ensemble. La consommation réelle est enregistrée ensuite.
- **Bascule** : un 429 (avec `Retry-After`) ou une erreur 5xx / réseau met la clé en pause et la clé
  suivante est essayée. Quand aucune clé ne peut servir la catégorie, l'appel s'arrête avec une erreur
  claire qui donne la raison pour chaque clé (l'agent finit en `llm_error`). Rien n'est jamais envoyé
  au-delà d'une limite.
- **Consommation** enregistrée dans `<state-dir>/usage.json` (par minute / jour / mois, heure locale,
  plus les pauses), donc les limites tiennent après un redémarrage. Une limite atteinte ou une erreur
  du fournisseur est journalisée (`event: key_limit` / `key_error`).
- `--category code` choisit la catégorie du modèle de chat ; `agent/media.py` fournit des interfaces
  minimales (`ImageGenerator`, `TextToSpeech`, `SpeechToText`, `Embeddings`) qui réservent une clé de
  leur catégorie pour l'appel au fournisseur que vous branchez (pas de génération d'image/son intégrée).
- `python -m agent keys` et le harness (`GET /keys`, barre latérale du chat, `/dashboard`) affichent le
  quota restant par clé et par catégorie, avec les clés masquées (`gsk_…abcd`).

## Mode essaim (sous-agents)

Un agent peut lancer des **sous-agents** avec `spawn_agent(task, max_steps?, allowed_tools?)`, ou
plusieurs à la suite avec `spawn_agents(tasks, ...)`. Un sous-agent est un agent normal exécuté dans
le même processus, avec le même modèle, le même espace de travail, la même mémoire et le même journal
d'audit ; sa réponse finale revient au parent comme observation.

Limites (appliquées dans le code, voir `agent/swarm.py`) :
- lancer un sous-agent relève de la catégorie de risque `delegate`, **`ask` par défaut** ;
- un sous-agent applique **la politique de permissions du parent**, éventuellement restreinte par
  `allowed_tools` : il ne peut jamais faire plus que son parent (un `deny`, ou `send` / `spend`, reste
  tel que le parent l'a) ;
- son budget est plafonné par ce qui reste au parent, et sa consommation est **déduite** du parent ;
- `--max-depth` (défaut 2 : agent → sous-agent → sous-sous-agent ; `0` désactive le mode) et
  `--max-children` (défaut 5 sous-agents par exécution, tout l'arbre compris) ;
- chaque ligne d'audit porte `agent` (`root`, `root.1`, `root.1.2`…) et `depth`, plus les événements
  `spawn` / `child_done`.

```bash
python -m agent run "Relis src/ et docs/ : un sous-agent par dossier, puis fais la synthèse" \
  --workspace ~/projet --max-depth 1 --max-children 3
```

```
  -> spawn_agents [delegate] {"tasks": ["relire src/", "relire docs/"], "allowed_tools": ["read_file", "list_files"]} : allow
  [root.1] -> list_files [read] {"path": "src"} : allow
  [root.2] -> list_files [read] {"path": "docs"} : allow
```

Les sous-agents partagent la mémoire du parent et héritent de ses confirmations `ask`.

**Sous-agents en parallèle** (`--max-parallel`, 3 par défaut). `spawn_agents` choisit un mode par lot :

| enfants | mode |
|---|---|
| lecture seule (`allowed_tools` donné, seulement des outils `read`/`network` déjà `allow`/`deny`) | parallèle, espace de travail partagé |
| peuvent écrire / exécuter sans jamais demander de validation — ou sous le harness | parallèle, **une copie isolée de l'espace de travail par enfant**, fusionnée à la fin |
| peuvent demander une validation dans le terminal (`run`, `chat`) | à la suite, espace partagé (les questions ne se mélangent jamais) |

**Copies isolées** : chaque enfant travaille dans un dossier temporaire privé (droits 0700) contenant une
copie de l'espace de travail du parent, sans `.git`, environnements virtuels, `node_modules`, caches,
`build`/`dist`, liens symboliques ni fichiers de plus de 20 Mo (copie totale plafonnée à 200 Mo ;
au-delà, le lot s'exécute à la suite). À la fin du lot, les changements sont fusionnés :
- un fichier créé / modifié / supprimé par **un seul** enfant (ou de façon identique par plusieurs) → appliqué ;
- un fichier modifié différemment par **plusieurs** enfants, ou modifié entre-temps dans le parent →
  **conflit** : le fichier du parent n'est **pas** touché, la version de chaque enfant est écrite en
  `<fichier>.conflict-<id agent>` (ex. `notes.md.conflict-root.2`) ; une suppression est seulement signalée ;
- l'observation du parent liste ce qui a été appliqué et les conflits, et le journal d'audit reçoit une
  ligne `event: merge`. Une tâche annulée ne fusionne rien. Les copies temporaires sont toujours supprimées.

Les réservations de budget, le compteur d'enfants, les écritures mémoire et l'écriture de l'audit sont
thread-safe. Dans l'exemple ci-dessus, les deux enfants tournent en parallèle dans l'espace partagé
(outils en lecture seule).

## Harness (serveur local, chat, validations)

`python -m agent serve` lance un harness local : les conversations tournent en arrière-plan dans des
threads, sous-agents compris, et chaque `ask` part dans une **file de validation** au lieu du terminal.
Bibliothèque standard uniquement (`http.server` + `threading`).

```bash
python -m agent serve --workspace ~/projet --port 8765          # puis ouvrir http://127.0.0.1:8765/
AGENT_HARNESS_TOKEN=a-changer python -m agent serve --approval-timeout 120 --max-parallel 3 --max-tasks 4
```

**Chat** (`/` ou `/chat`) : tapez un message pour lancer une conversation, ou pour continuer celle qui
est sélectionnée (même agent, historique conservé). Les messages des agents, les étapes d'outils, les
lancements de sous-agents, les fusions et les conflits s'affichent en bulles marquées de l'identifiant
de l'agent (`root`, `root.1`, `root.1.2`…). Les validations en attente apparaissent en cartes (en haut à
droite) avec l'agent, l'outil, la catégorie de risque et les arguments (secrets masqués) ; plusieurs
peuvent attendre en même temps et chacune se traite séparément. La barre latérale liste les
conversations, qui peuvent tourner en même temps (au plus `--max-tasks`, 4 par défaut ; les autres
attendent en `queued`). `/dashboard` garde la vue compacte (arbre des agents + journal), avec en plus la consommation, les
planifications, les règles et l'état du serveur. Le chat reçoit les événements en direct
(Server-Sent Events) et repasse à l'interrogation régulière en cas d'échec.

Comme le harness accepte plusieurs validations à la fois, **les sous-agents qui écrivent tournent en
parallèle** avec lui, chacun dans sa copie isolée (voir plus haut).

**Pièces jointes** : bouton 📎 ou glisser-déposer (plusieurs fichiers à la fois). Les fichiers
apparaissent en pastilles avant l'envoi, puis en pièces jointes dans votre bulle. Ils sont enregistrés
dans `<workspace>/uploads/<id conversation>/`, et le message reçu par l'agent contient la liste de leurs
chemins relatifs à l'espace de travail (les petits fichiers texte sont aussi recopiés), pour qu'il les
ouvre avec `read_file`.
- les noms sont réduits à un simple nom de fichier (pas de dossiers, de `..`, de chemin absolu, de point
  initial ni de caractères de contrôle) ; les fichiers sont créés sans suivre de lien symbolique et
  n'écrasent jamais rien (`notes-1.md`) ; un dossier `uploads/` qui serait un lien symbolique est refusé ;
- `--max-upload-mb` par fichier (20 par défaut) et `--max-message-mb` par message (50 par défaut) → HTTP 413 ;
- mêmes contrôles de jeton / même origine que les autres POST ; chaque fichier est journalisé dans
  l'audit (`event: upload`, chemin, taille, sha256).

| | |
|---|---|
| `POST /tasks` `{"task": "..."}` | lance une conversation → `{"id": ...}` |
| `POST /tasks/{id}/messages` `{"text": "..."}` | la continue (409 pendant qu'un tour est en cours) |
| `"files": [{"name": "a.md", "content_b64": "..."}]` | facultatif sur les deux : pièces jointes (base64 dans le JSON) · `GET /config` : limites |
| `GET /tasks` · `GET /tasks/{id}` | liste · une tâche : statut, résultat, consommation, arbre des agents |
| `GET /tasks/{id}/events?since=N` | événements (lignes d'audit, messages, validations) depuis N, à interroger régulièrement |
| `POST /tasks/{id}/cancel` | arrêt au pas suivant ; ses validations en attente sont refusées |
| `GET /approvals` (`?all=1`) · `POST /approvals/{id}` `{"decision": "approve"\|"deny"}` | file de validation |
| `GET /tasks/{id}/stream` | les mêmes événements, poussés en direct (Server-Sent Events) |
| `POST /approvals/{id}` `{"decision": "approve", "remember": "conversation"\|"session"}` | valider et retenir · `GET /rules` · `POST /rules/{id}/revoke` |
| `POST /stop-all` (`{"disable_schedules": true}`) | arrêt d'urgence |
| `GET /usage` | jetons, coût, pas par conversation et par agent, quotas des clés |
| `GET /tasks/{id}/export?format=md\|json` | conversation + piste d'audit |
| `GET /schedules` · `POST /schedules` · `POST /schedules/{id}` `{"enabled": false}` · `…/run` · `…/delete` | tâches planifiées |
| `GET /health` (`?check=1`) | état, clés masquées, joignabilité du backend |

```bash
curl -s -X POST localhost:8765/tasks -H 'Content-Type: application/json' -d '{"task":"Résume notes.md"}'
curl -s localhost:8765/approvals
curl -s -X POST localhost:8765/approvals/<id> -H 'Content-Type: application/json' -d '{"decision":"approve"}'
```

- **Pas de réponse = refus** : une validation attend `--approval-timeout` secondes (300 par défaut), puis est refusée.
- Écoute sur **127.0.0.1** par défaut. Si `AGENT_HARNESS_TOKEN` est défini, chaque appel d'API exige
  `Authorization: Bearer <jeton>` (à coller dans le champ « token » de la page). Écouter sur une autre
  adresse affiche un avertissement. Les POST doivent être en JSON et de même origine, et l'en-tête
  `Host` est vérifié en local.
- Mêmes `permissions.yaml`, mémoire et `audit.jsonl` que la CLI (les lignes du harness portent un
  `task_id`). Le mode terminal (`run`, `chat`) ne change pas.
- Ce n'est pas un serveur multi-utilisateur : pas de comptes, pas de TLS. Ctrl+C / SIGTERM annulent
  les tours en cours et suppriment les copies temporaires ; les conversations sont gardées sur disque
  (voir ci-dessous), sauf avec `--no-persist`.

### Persistance, direct et contrôle

- **Persistance** : les conversations (avec l'historique de l'agent), leurs événements, les
  planifications et les règles de conversation sont enregistrés dans SQLite
  (`<state-dir>/harness.sqlite3`, droits 0600, contenu masqué ; `--db CHEMIN` pour le déplacer,
  `--no-persist` pour tout garder en mémoire). Ils reviennent au redémarrage et la conversation peut
  continuer. Un tour qui tournait quand le processus s'est arrêté net est marqué **`interrupted`** (ses
  validations sont perdues et rien ne reprend tout seul).
- **Direct** : le chat écoute `GET /tasks/{id}/stream` (SSE ; reprise avec `Last-Event-ID` ou
  `?since=N`). Avec un jeton, `?access_token=` est accepté sur cette route uniquement, car
  `EventSource` ne peut pas envoyer d'en-têtes. Si le flux échoue, la page repasse à l'interrogation de
  `/events` (la barre du haut affiche `● live` ou `○ polling`).
- **Arrêt d'urgence** : le bouton **⛔ Stop all** (chat et tableau de bord) ou `POST /stop-all` annule
  toutes les tâches non terminées et refuse d'un coup toutes les validations en attente. Le bouton met
  aussi en pause toutes les planifications (`"disable_schedules": true`). L'arrêt est journalisé
  (`event: stop_all`).
- **Validations retenues** : une carte propose *Toujours autoriser `<outil>` dans cette conversation*
  ou *… pour cette session*. Une règle ne répond qu'à ce qui serait demandé (`ask`) : elle ne lève
  jamais un `deny` et **ne s'applique jamais à `send` ni à `spend`**, qui sont demandés à chaque fois (la
  carte ne le propose pas et l'API répond 400). Une règle vise un outil et une catégorie, pour tous les
  agents de la conversation, sous-agents compris. Les règles de session s'arrêtent avec le serveur ;
  celles de conversation sont enregistrées. On les voit et on les révoque dans le tableau de bord
  (`GET /rules`, `POST /rules/{id}/revoke`). Audit : `rule_created`, `rule_applied` (à chaque
  utilisation), `rule_revoked`.
- **Tableau de consommation** (`/dashboard`, `GET /usage`) : pas, appels d'outils, jetons et coût par
  conversation et par agent. Les chiffres *inclusifs* comptent les sous-agents, les chiffres *propres*
  non. Les quotas par clé sont affichés aussi. Le coût est connu si le routeur de clés a un `pricing` ;
  il vaut 0 en mode clé unique.
- **Export** : boutons **⇩ MD / ⇩ JSON** du chat, ou `GET /tasks/{id}/export?format=md|json`. On
  obtient la conversation, la consommation, les événements et les lignes d'audit de cette conversation
  (secrets masqués).
- **Tâches planifiées** (tableau de bord, ou `POST /schedules` avec
  `{"prompt": "...", "every_minutes": 60}` ou `{"prompt": "...", "daily_at": "08:30"}` en heure locale).
  Chaque exécution ouvre une **nouvelle conversation** (`source: schedule:<id>`). Elle passe par les
  mêmes permissions, validations, budgets, limites de clés et `--max-tasks` qu'un message du chat. Une
  exécution est sautée tant que la précédente n'est pas finie. On peut activer, désactiver, lancer tout
  de suite ou supprimer une planification. Les planifications sont enregistrées, et les exécutions
  manquées ne sont pas rejouées en rafale. Audit : `schedule_created`, `schedule_run`,
  `schedule_skipped`…
- **`GET /health`** : état, durée de fonctionnement, tâches par statut, validations en attente,
  persistance, et clés (**masquées**) ou fournisseur et modèle du `.env`. Aucun accès réseau par défaut.
  `?check=1` envoie un `GET <base_url>/models` **sans aucune clé d'API** à chaque backend et indique
  s'il répond.

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
