# Connected services (MCP) / Services connectés (MCP)

**[English](#english) | [Français](#francais)** · [← README](../README.md) · [Docs](README.md)

<a id="english"></a>

## English

**In one sentence:** MCP (Model Context Protocol) is an open standard that lets the assistant use your other
tools — your files, GitHub, and many more services — and it always asks you before changing anything.

### Connect a service (1 minute)

1. Open the **Connect** tab, section **Connected services**.
2. Click a button:
   - **📁 My files** — choose a folder (for example `~/Documents`). The assistant can read and organise the
     files of that folder only. Needs [Node.js](https://nodejs.org/) (free); the app tells you if it is missing.
   - **🐙 GitHub** — paste a GitHub token ([create one](https://github.com/settings/personal-access-tokens/new),
     2 minutes). Nothing to install.
   - **🌐 Other (web address)** — paste the MCP address given by the service (often ending in `/mcp`) and its
     token if it asks for one.
3. Click **Add and test**. The card says **Connected** and lists **what it can do**, or **Not connected** with
   the reason in plain words (for example “Node.js is not installed on this computer” with a link to install it).
4. Ask in the chat, for example “List the files in my Documents folder”. The chat shows which service was used
   (🔌 *The assistant used My files: List Directory*).

Each card has **Test** (check again), **Change** (new folder or token), **Remove**, and an **On** switch: a
service that is off is never used and costs nothing.

**Advanced:** “a program on this computer” accepts any command from a service's instructions
(`npx …`, `uvx …`, `docker …`) and optional secret values (`NAME=value`, one per line).

### Safety

- **Reading** actions (marked read-only by the service) run directly, like reading a file. **Everything else
  asks you first** with the usual approval card, which names the service and the action.
- What a service returns is treated as **data, never as orders** (it is fenced as `<external_content>`), and
  secrets in it are hidden.
- **Tokens and values are stored like your API keys** (system keychain, or a private file readable only by
  you) and are only ever shown masked. They are never given to the model, never written in the logs.
- A local program only receives a minimal environment: **your AI keys are never passed to it**.
- Every action is written to the security log (`audit.jsonl`), with the service name.
- Services can only be added or changed from the computer running the app.

### When something does not work

The app never breaks the chat: if a service is slow (more than 45 s), stopped or refuses its token, the
assistant tells you in one sentence and the card shows why. Click **Test** after fixing it.

### For the curious

- Tools are named `mcp_<service>_<tool>`. A local program starts the first time it is needed (or when you
  click Test) and stops when the app quits.
- To stay within the free Groq limit (8,000 tokens per minute), only enabled services are used, their
  descriptions are shortened, and at most 8 of their actions — the most relevant to your request — are sent
  with each message (3 when a request has to be shortened).
- Transports: stdio (local program) and Streamable HTTP (web address), JSON-RPC 2.0.

---

<a id="francais"></a>

## Français

**En une phrase :** MCP (Model Context Protocol) est un standard ouvert qui permet à l'assistant d'utiliser
tes autres outils — tes fichiers, GitHub et beaucoup d'autres services — et il te demande toujours avant de
modifier quoi que ce soit.

### Connecter un service (1 minute)

1. Ouvre l'onglet **Connexion**, partie **Services connectés**.
2. Clique sur un bouton :
   - **📁 Mes fichiers** — choisis un dossier (par exemple `~/Documents`). L'assistant peut lire et ranger
     les fichiers de ce dossier seulement. Il faut [Node.js](https://nodejs.org/fr) (gratuit) ; l'application
     te prévient s'il manque.
   - **🐙 GitHub** — colle un jeton GitHub ([en créer un](https://github.com/settings/personal-access-tokens/new),
     2 minutes). Rien à installer.
   - **🌐 Autre (adresse web)** — colle l'adresse MCP donnée par le service (elle finit souvent par `/mcp`)
     et son jeton s'il en demande un.
3. Clique sur **Ajouter et tester**. La carte affiche **Connecté** et la liste de **ce qu'il peut faire**, ou
   **Pas connecté** avec la raison en mots simples (par exemple « Node.js n'est pas installé sur cet
   ordinateur » avec un lien pour l'installer).
4. Demande dans le chat, par exemple « Liste les fichiers de mon dossier Documents ». Le chat montre quel
   service a été utilisé (🔌 *L'assistant a utilisé Mes fichiers : List Directory*).

Chaque carte a **Tester** (vérifier à nouveau), **Modifier** (nouveau dossier ou jeton), **Supprimer**, et
un interrupteur **Activé** : un service désactivé n'est jamais utilisé et ne coûte rien.

**Avancé :** « un programme sur cet ordinateur » accepte n'importe quelle commande donnée dans la notice d'un
service (`npx …`, `uvx …`, `docker …`) et des valeurs secrètes facultatives (`NOM=valeur`, une par ligne).

### Sécurité

- Les actions de **lecture** (marquées « lecture seule » par le service) se font directement, comme lire un
  fichier. **Tout le reste te demande d'abord** avec la carte d'accord habituelle, qui nomme le service et
  l'action.
- Ce que renvoie un service est traité comme **des données, jamais comme des ordres** (encadré par
  `<external_content>`), et les secrets qu'il contient sont masqués.
- **Les jetons et valeurs sont rangés comme tes clés d'API** (trousseau du système, ou fichier privé lisible
  par toi seul) et ne sont jamais affichés autrement que masqués. Ils ne sont jamais donnés au modèle, jamais
  écrits dans les journaux.
- Un programme local ne reçoit qu'un environnement minimal : **tes clés d'IA ne lui sont jamais transmises**.
- Chaque action est écrite dans le journal de sécurité (`audit.jsonl`), avec le nom du service.
- Les services ne peuvent être ajoutés ou modifiés que depuis l'ordinateur où tourne l'application.

### Quand quelque chose ne marche pas

L'application ne casse jamais le chat : si un service est lent (plus de 45 s), arrêté ou refuse son jeton,
l'assistant te le dit en une phrase et la carte affiche pourquoi. Clique sur **Tester** une fois corrigé.

### Pour les curieux

- Les outils s'appellent `mcp_<service>_<outil>`. Un programme local démarre la première fois qu'on en a
  besoin (ou quand tu cliques sur Tester) et s'arrête quand l'application se ferme.
- Pour rester dans la limite gratuite de Groq (8 000 tokens par minute), seuls les services activés sont
  utilisés, leurs descriptions sont raccourcies, et au plus 8 de leurs actions — les plus utiles pour ta
  demande — sont envoyées avec chaque message (3 quand une demande doit être raccourcie).
- Transports : stdio (programme local) et Streamable HTTP (adresse web), JSON-RPC 2.0.
