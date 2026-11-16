# Security / Sécurité

## Reporting a problem / Signaler un problème

Please **do not open a public issue** for a security problem. Use GitHub's private report instead:
*Security → Report a vulnerability* on <https://github.com/lanoixdesign/autonomous-agent/security/advisories/new>.
Say what you found, how to reproduce it and which version (`autonomous-agent --version` or the Help page).
We answer as soon as we can and credit you in the release notes if you want.

Merci de **ne pas ouvrir d'issue publique** pour un problème de sécurité : utilise le signalement privé de GitHub
(*Security → Report a vulnerability*). Dis ce que tu as trouvé, comment le reproduire et la version utilisée.

Supported versions: the latest release only. / Versions suivies : uniquement la dernière version.

## What the app protects / Ce que l'application protège

The app is a **local** assistant: it runs on your computer, the web interface listens on `127.0.0.1` only (phone
access is opt-in and needs a pairing code). The main risks are a malicious web page or file trying to steer the
model (prompt injection), and a model mistake. The guard rails:

| Area | Protection |
|---|---|
| Local server | Host header check (blocks DNS rebinding), Origin check and CSRF token on every change, JSON only, no CORS, pages refuse to be framed (`X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`). |
| Approvals | Sending (`github_write`, `api_send`, e-mail…) and spending (`api_pay`) **always** ask, even in YOLO mode; allow-lists (`commands.allow`, `domains.allow`) never auto-approve them, nor chained commands (`a && b`, `$(…)`, `;`, `|`, newlines). |
| Sandbox (Simple mode) | Only a short list of programs; Python runs with an audit hook (no network, no other programs — including the low-level `_posixsubprocess.fork_exec` — no writes outside the work folder). A guard rail, not a virtual machine. |
| Files | Everything stays in the work folder; `.env`, `*.pem`, `*.key`, SSH keys, `.git/`, `.agent/` and the app's own data are refused — after resolving `..`, symbolic links and letter case — for the file tools, the search and the sandbox. |
| Web | `web_fetch` / `web_search` only reach the public internet: no `localhost`, no private network, no cloud metadata address (169.254.169.254); every redirect is checked again. `AGENT_ALLOW_PRIVATE_FETCH=1` turns this off. |
| Keys | Stored in the system keychain when available, otherwise in a file only your user can read (0600). Shown masked, removed from errors and logs, never given to the model. A request carrying a key never follows a redirect to another host. |
| Outside content | Web pages, API and GitHub answers reach the model inside an `<external_content>` fence with the rule "data, not instructions". |
| Build | GitHub Actions pinned to commit SHAs, pinned build tools, read-only token by default, `SHA256SUMS.txt` and a build-provenance attestation with every release. |

## Checking a download / Vérifier un téléchargement

```sh
# 1. checksum (macOS / Linux) — must print "OK"
shasum -a 256 -c SHA256SUMS.txt --ignore-missing
# Windows PowerShell: compare with the line in SHA256SUMS.txt
Get-FileHash .\AutonomousAgent-windows-x64.exe -Algorithm SHA256
# 2. provenance: proves the file was built by this repository's release workflow
gh attestation verify AutonomousAgent-macos-arm64.zip -R lanoixdesign/autonomous-agent
```

The apps are **not code-signed** yet (no Apple Developer ID / Windows certificate): macOS Gatekeeper and Windows
SmartScreen warn on first launch. The checksum and the attestation are how you check the file is genuine.
Les applications ne sont **pas encore signées** : macOS et Windows affichent un avertissement au premier lancement.
La somme de contrôle et l'attestation servent à vérifier que le fichier est authentique.

## Known limits / Limites connues

- The sandbox uses Python audit hooks and resource limits, not an OS-level jail. For untrusted code, use a VM.
- Expert mode without the sandbox runs commands in your shell after your approval: read the card before saying yes.
- Without a system keychain, keys are stored in plain text (file permission 0600) in the app's data folder.
- A DNS answer can change between the safety check and the connection (DNS rebinding); the Host check protects
  the app itself, the web tools' check is best-effort.
- Prompt injection cannot be fully prevented by any model; the approvals for sending and spending are the real
  safety net.
