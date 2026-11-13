**New in 0.4.0 / Nouveautés de la 0.4.0 — a new look / un nouveau look**

- Dark neon interface for the chat, the dashboard and the phone pages (purple glow, neon blue/purple accents, visible keyboard focus). / Interface néon sombre pour le chat, le tableau de bord et les pages mobiles (halo violet, accents bleu/violet néon, focus clavier visible).
- Live swarm graph: sub-agents appear as cards around the coordinator, with real progress (steps / budget); when they finish they merge into a document with a link to the answer and the files written. / Graphe de l'essaim en direct : les sous-agents apparaissent en cartes autour du coordinateur, avec leur vraie progression ; à la fin ils fusionnent en un document qui mène à la réponse et aux fichiers écrits.
- Approval cards ask a plain question ("Allow writing report.md?" / « Autoriser l'écriture de report.md ? »), with the reason translated; send/spend are still never remembered. / Les cartes de validation posent une question claire, avec la raison traduite ; envoi/dépense ne sont toujours jamais retenus.
- "Agent is thinking…" indicator, timestamps on your messages. / Indicateur « L'agent réfléchit… », heure sur vos messages.
- Since 0.3.0: use it from your phone (`--remote`, QR pairing, Tailscale / Cloudflare). / Depuis la 0.3.0 : utilisable depuis le téléphone.

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
