# MCP — Model Context Protocol

**English** | [Français](#francais)

## English

Autonomous-agent can connect to external MCP servers (stdio or HTTP) and turn their tools into agent tools.

### Adding a server

In the Connect tab → **My MCP servers**:

You can click a ready-made button (**My files**, **GitHub**, **Calendar**) or fill the form yourself:

- **Name**: a simple name (e.g. My files)
- **Type**: “Local program” or “Web address”
- **Command or address**: what to run (an example is shown under the field)

Optional token is stored masked.  
Only servers **you** add are used. The assistant cannot invent commands.

### Tool naming

Tools appear as `mcp_<server>_<tool>`.

- Tools annotated `readOnlyHint` use the **read** category (allowed by default).
- All others require your agreement (network / write / etc.).

Results are wrapped in `<external_content>` so the model treats them as data.

### Limits

Only tools from **enabled** servers are sent to the model (to stay under free Groq token limits). The automatic request reduction from v0.9.4 still applies.

### Security

- Network calls respect `netguard` (no private ranges by default).
- Every call is written to `audit.jsonl` (secrets redacted).
- Secrets never appear in the UI or logs.

---

<a id="francais"></a>

## Français

Autonomous-agent peut se connecter à des serveurs MCP externes (stdio ou HTTP) et transformer leurs outils en outils de l'agent.

### Ajouter un serveur

Dans l’onglet **Connexion → Mes serveurs MCP** :

Tu peux cliquer sur un bouton prêt à l’emploi (**Mes fichiers**, **GitHub**, **Agenda**) ou remplir le formulaire toi-même :

- **Nom** : un nom simple (ex. Mes fichiers)
- **Type** : « Programme local » ou « Adresse web »
- **Commande ou adresse** : ce qu’il faut lancer (un exemple est affiché sous le champ)

Le jeton optionnel est stocké masqué.  
Seuls les serveurs que **tu** ajoutes sont utilisés. L’assistant ne peut pas inventer de commandes.

### Nommage des outils

Les outils apparaissent sous la forme `mcp_<serveur>_<outil>`.

- Les outils annotés `readOnlyHint` utilisent la catégorie **read** (autorisée par défaut).
- Tous les autres demandent ton accord.

Les résultats sont encadrés dans `<external_content>` pour que le modèle les traite comme des données.

### Limites

Seuls les outils des serveurs **activés** sont envoyés au modèle (pour rester sous la limite de tokens Groq gratuite). Le mécanisme de réduction automatique de la v0.9.4 continue de s'appliquer.

### Sécurité

- Les appels réseau respectent `netguard`.
- Chaque appel est écrit dans `audit.jsonl` (secrets masqués).
- Les secrets n'apparaissent jamais dans l'interface ni dans les journaux.
