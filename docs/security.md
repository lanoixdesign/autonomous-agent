# Security / Sécurité

**[English](#english) | [Français](#francais)** · [← README](../README.md) · [Docs](README.md)

<a id="english"></a>

## English

### Security (0.9.3)

A full security audit was done in 0.9.3 and every high / medium finding was fixed. In short: the app only listens
on your computer, every send or payment asks you first (even in YOLO mode, even if the domain is allow-listed),
chained commands like `git log && curl …` always ask, the sandbox blocks the low-level way to start programs,
`.env` / keys / `.git` stay unreachable (even via `..`, a symbolic link or capital letters), the web tools refuse
`localhost`, your local network and cloud metadata addresses, keys never follow a redirect to another site, outside
content is marked "data, not instructions" for the model, and pages cannot be embedded by another site.
Check a download with `SHA256SUMS.txt` and `gh attestation verify` (see [SECURITY.md](SECURITY.md)). Found a
problem? Report it privately, see [SECURITY.md](SECURITY.md). The apps are not code-signed yet.

---

<a id="francais"></a>

## Français

### Sécurité (0.9.3)

Un audit de sécurité complet a été fait pour la 0.9.3 et chaque problème important ou moyen a été corrigé. En bref :
l'application n'écoute que sur ton ordinateur, chaque envoi ou paiement te demande ton accord (même en mode YOLO,
même si le domaine est dans la liste autorisée), les commandes enchaînées comme `git log && curl …` demandent
toujours, le bac à sable bloque le moyen bas niveau de lancer des programmes, `.env` / clés / `.git` restent
inaccessibles (même via `..`, un lien symbolique ou des majuscules), les outils web refusent `localhost`, ton réseau
local et les adresses de métadonnées du cloud, tes clés ne suivent jamais une redirection vers un autre site, le
contenu venu de l'extérieur est marqué « données, pas des instructions » pour le modèle, et aucun autre site ne peut
intégrer les pages. Vérifie un téléchargement avec `SHA256SUMS.txt` et `gh attestation verify` (voir
[SECURITY.md](SECURITY.md)). Tu as trouvé un problème ? Signale-le en privé, voir [SECURITY.md](SECURITY.md).
Les applications ne sont pas encore signées.
