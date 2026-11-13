**New in 0.3.0 / Nouveautés de la 0.3.0 — use it from your phone / utilisable depuis le téléphone**

- Mobile-friendly chat and dashboard, installable as an app (PWA). / Chat et tableau de bord adaptés au téléphone, installables comme une appli (PWA).
- `--remote` (desktop app: `AGENT_REMOTE=1` in `.env`): mandatory sign-in, QR code with a one-time pairing code, sessions, rate-limited login. / connexion obligatoire, QR code à usage unique, sessions, tentatives limitées.
- Private HTTPS via Tailscale (`AGENT_TUNNEL=tailscale`) or Cloudflare Tunnel (`AGENT_TUNNEL=cloudflared`). See the README: *Use from your phone / Utiliser depuis le mobile*.
- Optional IDC mode (since 0.2.0). / Mode IDC facultatif (depuis la 0.2.0).

**Desktop builds — no command line needed / Versions de bureau — sans ligne de commande**

| File / Fichier | For / Pour |
|---|---|
| `AutonomousAgent-windows-x64.exe` | Windows 10/11 (64-bit) |
| `AutonomousAgent-macos-arm64.zip` | Mac with Apple Silicon (M1, M2, M3, M4…) |
| `AutonomousAgent-macos-intel.zip` | Mac with an Intel processor |

⚠️ **These builds are not signed.** Windows and macOS will warn you the first time.
⚠️ **Ces versions ne sont pas signées.** Windows et macOS afficheront un avertissement la première fois.

- **Windows:** double-click the `.exe` → SmartScreen "Windows protected your PC" → **More info → Run anyway**.
  / double-cliquez sur le `.exe` → « Windows a protégé votre ordinateur » → **Informations complémentaires → Exécuter quand même**.
- **macOS:** unzip, move `AutonomousAgent.app` to Applications, then **right-click → Open → Open**
  (or System Settings → Privacy & Security → **Open Anyway**). Last resort / en dernier recours :
  `xattr -dr com.apple.quarantine /Applications/AutonomousAgent.app`
  / décompressez, déplacez l'app dans Applications, puis **clic droit → Ouvrir → Ouvrir**.

A console window opens (keep it open: it shows the logs; close it to stop) and the chat opens in your browser.
Your files, keys and data live in `~/AutonomousAgent` (Windows: `C:\Users\<you>\AutonomousAgent`).
Without an API key the app runs in **demo mode**: open `~/AutonomousAgent/.env`, follow the comments, restart.

Une fenêtre de console s'ouvre (laissez-la ouverte : elle affiche le journal ; fermez-la pour arrêter) et le chat
s'ouvre dans le navigateur. Vos fichiers, clés et données sont dans `~/AutonomousAgent`. Sans clé d'API,
l'application tourne en **mode démo** : ouvrez `~/AutonomousAgent/.env`, suivez les commentaires, relancez.

`SHA256SUMS.txt` lets you check the downloads / permet de vérifier les téléchargements.
Full guide / guide complet : see the README.
