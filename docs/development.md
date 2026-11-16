# Command line, development and tests / Ligne de commande, développement et tests

**[English](#english) | [Français](#francais)** · [← README](../README.md) · [Docs](README.md)

<a id="english"></a>

## English

### Install

```bash
git clone https://github.com/lanoixdesign/autonomous-agent.git
cd autonomous-agent
python -m venv .venv && . .venv/bin/activate   # Python 3.10+
pip install pyyaml pytest   # both optional: a built-in YAML subset parser is used without PyYAML
cp docs/examples/.env.example .env        # then put your key in .env (never commit it)
```

### Configure the model

Environment variables (or `.env`):

| Variable | Meaning |
|---|---|
| `AGENT_PROVIDER` | `groq`, `openai`, `openrouter`, `ollama`, `custom`, `mock` (default `mock`) |
| `AGENT_MODEL` | model name (defaults: groq `openai/gpt-oss-20b`, openai `gpt-4o-mini`, openrouter `openai/gpt-4o-mini`, ollama `llama3.1`) |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | key for the chosen provider |
| `AGENT_BASE_URL`, `AGENT_API_KEY` | any other OpenAI-compatible endpoint (`custom`) |
| `GITHUB_TOKEN` | optional, for GitHub tools (otherwise the `gh` CLI login is used) |
| `AGENT_SEARCH_URL` | optional web search endpoint (DuckDuckGo HTML by default) |

No key is ever hard-coded. Requests send a `User-Agent` header (some providers behind Cloudflare
reject requests without one).

### Use

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
python -m agent keys               # API keys (masked) and remaining quotas, if providers.yaml is used
```

Options: `--workspace/-w`, `--permissions/-p`, `--model/-m`, `--provider`, `--state-dir`
(memory + audit, default `<workspace>/.agent`), `--max-steps`, `--max-tool-calls`, `--max-tokens`,
`--max-depth`, `--max-children`, `--max-parallel`, `--keys`, `--category`, `--yolo`, `--offline`, `--quiet`.

Example (real run, Groq `openai/gpt-oss-120b`, no terminal so `ask` = refused):

```
  -> list_files [read] {"depth": 1, "path": "."} : allow
  -> read_file [read] {"limit": 200, "path": "notes.md"} : allow
  -> memory_write [write] {"kind": "note", ...} : allow
  ! write_file [write] needs confirmation but there is no terminal -> refused
[final] steps=5 tool_calls=4 tokens=6520
```

### Tests

```bash
python -m pytest -q
```

CI (GitHub Actions) runs the tests on Python 3.10–3.13, with and without PyYAML, plus an offline
end-to-end run with the mock backend, and a build of the desktop app (PyInstaller) that is started
and checked through `/health`. Tagging `v*` runs `.github/workflows/release.yml`: Windows and macOS
builds, each smoke-tested, attached to a GitHub Release.

### Honest limitations

- **0.9**: the Critic is the same model as the agent: it catches missing items and language slips, not every factual error, and each round costs one model call (with a free Groq key, expect rate-limit pauses). Semantic memory needs a key with « embeddings » ticked (Groq has none). Business APIs: JSON / text only, one auth header, no OAuth flow, no file upload; OpenAPI is read once (JSON only, not YAML). Models sometimes do the specialist's work themselves instead of handing over.
- **Language and retries (0.8.2)**: the language of a request is guessed from common words and accents
  (French / English only); a very short or mixed message uses the previous turn's language, then the app's.
  Models may still slip into English inside tool output or code comments. A malformed action is retried 3
  times; after that the helper (or the task) stops with the provider's error. Developer-mode confinement
  covers the file tools and the sandbox commands that create, move or delete files; with the sandbox off,
  the shell is not confined, and a Python program run in the sandbox may still write anywhere in the work
  folder.
- **Rate limits (0.8.1)**: with a single key, the task waits instead of stopping (max 60 s per pause, 6
  pauses per request, nothing waited for beyond 5 min); a long pause still makes a slow task. The tokens per
  minute counter shows the provider's figures after the first answer; before that, and for providers that
  send no `x-ratelimit-*` headers, it is an estimate (Groq assumed 8,000 tokens/minute). Single `.env` key
  mode (no Settings keys) waits too but shows no counter.
- **No security audit has been done.** This is a small educational project.
- **The shell is dangerous if you set it to `allow`.** Command deny patterns are a seatbelt, easy to
  bypass (`bash -c`, scripts, aliases…). For untrusted tasks, run the agent in a container/VM.
- With the sandbox **off**, workspace confinement applies to the file tools only and the shell can reach
  anything your user can. With it **on**, the Python audit hook is a guard-rail for an assistant that makes
  mistakes, not a jail against hostile code: audit hooks can in theory be bypassed from inside Python,
  CPU/memory limits are POSIX-only (not Windows), and Python's own installation stays readable. For
  untrusted code, use a container or VM.
- Developer mode: templates are deliberately tiny (no npm, no build step, standard library only); the
  website check is static (it does not run the page's JavaScript); the desktop builds need a Python 3
  installed on the computer to run Python projects (pytest is used only if it is installed, else unittest).
- Secret redaction is pattern-based: an unknown secret format can slip through.
- Web content can contain prompt injection; the system prompt warns the model, it does not prevent it.
- Memory recall is simple keyword matching, no embeddings.
- `web_search` scrapes a public HTML endpoint and may be blocked; prefer `web_fetch` on known URLs.
- Quality depends heavily on the model; small local models often call tools badly.
- The desktop builds are **unsigned** (SmartScreen / Gatekeeper warnings), large (the Python runtime is
  inside, ~10–30 MB) and separate for Apple Silicon and Intel Macs. Antivirus software sometimes flags
  unsigned PyInstaller executables (false positives).
- Remote access: sessions live in memory (a restart signs phones out); no TLS of its own (use a
  tunnel); not tested against every tunnel/proxy setup; the PWA works offline only for the page shell.
- Settings page: on Windows the private key file relies on your user folder's permissions (0600 is a
  POSIX mode); the system keychain is used only if the Python `keyring` package is installed (it is not
  bundled in the desktop builds). **Test the key** only checks the provider's `/models` endpoint, not
  access to a given model. Restarting from Settings cancels running tasks. Validation messages from the
  server are in English.
- Day theme: checked for WCAG AA contrast on the main text colours and visually on every page, but not
  audited with a screen reader; the theme choice is stored per browser (Settings sets the default).
- Key pool: a helper's job is guessed from keywords in its task text (EN/FR), and the "fast / strong"
  proposal from the provider and model name: both are heuristics you can override in Settings. The pool
  lives in the running app (one process); a helper keeps its key while it works, and counts as busy for
  2 minutes after its last call if it did not finish cleanly. Pasted keys are hidden by intercepting the
  paste and by masking the box (`-webkit-text-security`); in browsers without that CSS (older Firefox),
  characters **typed** directly in the paste box are visible until Enter, so type keys in the
  "+ Add another key" rows (password fields) instead.
- This project is independent: it is **not** Grok Bot and does not reproduce it.

---

<a id="francais"></a>

## Français

### Installation

```bash
git clone https://github.com/lanoixdesign/autonomous-agent.git
cd autonomous-agent
python -m venv .venv && . .venv/bin/activate   # Python 3.10+
pip install pyyaml pytest   # facultatifs : sans PyYAML, un mini-analyseur YAML intégré est utilisé
cp docs/examples/.env.example .env        # mets ta clé dans .env (ne le commite jamais)
```

### Configurer le modèle

Variables d'environnement (ou `.env`) :

| Variable | Rôle |
|---|---|
| `AGENT_PROVIDER` | `groq`, `openai`, `openrouter`, `ollama`, `custom`, `mock` (défaut `mock`) |
| `AGENT_MODEL` | nom du modèle (défauts : groq `openai/gpt-oss-20b`, openai `gpt-4o-mini`, openrouter `openai/gpt-4o-mini`, ollama `llama3.1`) |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | clé du fournisseur choisi |
| `AGENT_BASE_URL`, `AGENT_API_KEY` | tout autre point d'accès compatible OpenAI (`custom`) |
| `GITHUB_TOKEN` | facultatif, pour les outils GitHub (sinon la connexion du CLI `gh`) |
| `AGENT_SEARCH_URL` | facultatif, moteur de recherche web (DuckDuckGo HTML par défaut) |

Aucune clé n'est écrite dans le code. Les requêtes envoient un en-tête `User-Agent` (certains
fournisseurs derrière Cloudflare refusent les requêtes sans).

### Utilisation

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

### Tests

```bash
python -m pytest -q
```

La CI (GitHub Actions) lance les tests sous Python 3.10 à 3.13, avec et sans PyYAML, plus un essai
de bout en bout hors ligne avec le backend mock, et une compilation de l'application de bureau
(PyInstaller) lancée puis vérifiée via `/health`. Pousser une étiquette `v*` lance
`.github/workflows/release.yml` : versions Windows et macOS, chacune testée, jointes à une Release GitHub.

### Limites (honnêtement)

- **0.9** : le Critique est le même modèle que l'agent : il repère les oublis et les erreurs de langue, pas toutes les erreurs de fond, et chaque tour coûte un appel au modèle (avec une clé Groq gratuite, attends-toi à des pauses de limite). La mémoire par le sens demande une clé avec « embeddings » coché (Groq n'en a pas). API métier : JSON / texte seulement, un seul en-tête d'authentification, pas de flux OAuth, pas d'envoi de fichiers ; OpenAPI lu une fois (JSON seulement, pas YAML). Les modèles font parfois eux-mêmes le travail du spécialiste au lieu de passer la main.
- **Langue et nouvelles tentatives (0.8.2)** : la langue d'une demande est devinée d'après des mots courants
  et les accents (français / anglais seulement) ; un message très court ou mélangé garde la langue du tour
  précédent, sinon celle de l'application. Le modèle peut encore glisser de l'anglais dans les sorties
  d'outils ou les commentaires de code. Une action mal formée est redemandée 3 fois ; ensuite l'assistant (ou
  la tâche) s'arrête avec l'erreur du fournisseur. Le confinement du mode développeur couvre les outils
  fichiers et les commandes du bac à sable qui créent, déplacent ou suppriment des fichiers ; bac à sable
  désactivé, le shell n'est pas confiné, et un programme Python lancé dans le bac à sable peut encore écrire
  ailleurs dans le dossier de travail.
- **Limites de débit (0.8.1)** : avec une seule clé, la tâche attend au lieu de s'arrêter (60 s max par
  pause, 6 pauses par demande, rien au-delà de 5 min d'attente) ; une longue pause rend quand même la tâche
  plus lente. Le compteur de tokens par minute affiche les chiffres du fournisseur après la première réponse ;
  avant, et pour les fournisseurs sans en-têtes `x-ratelimit-*`, c'est une estimation (Groq : 8 000
  tokens/minute supposés). Le mode clé unique `.env` (sans clé dans Réglages) attend aussi mais sans compteur.
- **Aucun audit de sécurité n'a été fait.** C'est un petit projet pédagogique.
- **Le shell est dangereux si tu le mets en `allow`.** Les motifs de commandes interdites sont une
  ceinture de sécurité facile à contourner (`bash -c`, scripts, alias…). Pour des tâches non fiables,
  lance l'agent dans un conteneur ou une VM.
- Bac à sable **désactivé** : le confinement vaut pour les outils fichiers seulement, et le shell accède à
  tout ce que ton utilisateur peut atteindre. **Activé** : le hook d'audit Python est un garde-fou pour un
  assistant qui se trompe, pas une prison contre du code hostile : un hook d'audit peut en théorie être
  contourné depuis Python, les limites processeur/mémoire n'existent que sous POSIX (pas Windows), et
  l'installation de Python reste lisible. Pour du code non fiable, utilise un conteneur ou une VM.
- Mode développeur : modèles volontairement minimes (pas de npm, pas de compilation, bibliothèque standard
  seulement) ; le contrôle du site est statique (il n'exécute pas le JavaScript de la page) ; les versions
  de bureau ont besoin d'un Python 3 installé sur l'ordinateur pour lancer les projets Python (pytest
  seulement s'il est installé, sinon unittest).
- Le masquage des secrets repose sur des motifs : un format inconnu peut passer.
- Le contenu web peut contenir de l'injection de prompt ; le prompt système prévient le modèle, il ne l'empêche pas.
- Le rappel mémoire est une simple recherche par mots-clés, sans embeddings.
- `web_search` lit une page HTML publique et peut être bloqué ; préfère `web_fetch` sur des URL connues.
- La qualité dépend beaucoup du modèle ; les petits modèles locaux appellent souvent mal les outils.
- Les versions de bureau ne sont **pas signées** (avertissements SmartScreen / Gatekeeper), assez lourdes
  (Python est inclus, ~10–30 Mo) et distinctes pour Mac puce Apple et Intel. Certains antivirus signalent
  à tort les exécutables PyInstaller non signés (faux positifs).
- Accès distant : les sessions sont en mémoire (un redémarrage déconnecte les téléphones) ; pas de TLS
  intégré (utilise un tunnel) ; pas testé avec toutes les configurations de tunnel/proxy ; hors ligne,
  la PWA n'affiche que l'enveloppe des pages.
- Page Réglages : sous Windows, le fichier privé des clés repose sur les droits de ton dossier
  utilisateur (0600 est un mode POSIX) ; le trousseau du système n'est utilisé que si le paquet Python
  `keyring` est installé (il n'est pas inclus dans les versions de bureau). **Tester la clé** ne vérifie
  que le point `/models` du fournisseur, pas l'accès à un modèle précis. Redémarrer depuis Réglages
  annule les tâches en cours. Les messages de validation du serveur sont en anglais.
- Thème jour : contraste WCAG AA vérifié sur les couleurs de texte principales et visuellement sur chaque
  page, mais pas audité avec un lecteur d'écran ; le choix du thème est gardé par navigateur (Réglages fixe
  la valeur par défaut).
- Ce projet est indépendant : ce n'est **pas** Grok Bot et il ne le reproduit pas.
- Réserve de clés : le travail d'un assistant est deviné d'après des mots-clés de sa tâche (EN/FR), et la
  proposition « rapide / puissant » d'après le service et le nom du modèle : ce sont des heuristiques,
  modifiables dans Réglages. La réserve vit dans l'application en cours (un seul processus) ; un
  assistant garde sa clé pendant son travail. Les clés collées sont masquées (interception du collage et
  `-webkit-text-security`) ; dans un navigateur sans ce CSS (ancien Firefox), les caractères **tapés**
  directement dans la zone de collage restent visibles jusqu'à Entrée : tape plutôt dans les lignes
  « + Ajouter une autre clé » (champs mot de passe).
