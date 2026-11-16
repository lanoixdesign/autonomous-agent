**New in 0.6.0 / Nouveautés de la 0.6.0 — made for beginners, with a day mode / pensé pour les débutants, avec un mode jour**

- ☀ **Day / ☾ Night theme**: a sun/moon button on every page (and in the phone menu); Settings → Theme: Day / Night / Automatic (default: follows your computer). The light theme meets WCAG AA contrast. / **Thème Jour / Nuit** : un bouton soleil/lune sur chaque page (et dans le menu du téléphone) ; Réglages → Thème : Jour / Nuit / Automatique (par défaut : suit votre ordinateur). Le thème clair respecte le contraste WCAG AA.
- Questions in plain words: "The agent wants to write the file report.md. Do you allow it?" with big ✓ Allow / ✕ Refuse buttons; technical details folded. / Des questions en mots simples : « L'agent veut écrire le fichier report.md. Vous l'autorisez ? » avec de grands boutons ✓ Autoriser / ✕ Refuser.
- The chat starts with example tasks and a short guided tour; a new **Help** tab explains everything in 4 steps. / Le chat s'ouvre sur des exemples et une courte visite guidée ; un nouvel onglet **Aide** explique tout en 4 étapes.
- "What the agent did" in sentences (Technical view in Settings). / « Ce qu'a fait l'agent » en phrases (vue Technique dans Réglages).
- 📁 **My files**: see, add and download your files; files the agent creates get a ⬇ Download button. / **Mes fichiers** : voir, ajouter et télécharger vos fichiers ; les fichiers créés par l'agent ont un bouton ⬇ Télécharger.
- Wizard: "Try without a key" first, Groq recommended (free) with a step-by-step guide, the service is recognised from the key. / Assistant : « Essayer sans clé » en premier, Groq recommandé (gratuit) avec un guide pas à pas, service reconnu d'après la clé.
- Settings in **Simple** or **Expert** mode, ❓ help on each setting, larger text option, error messages translated. / Réglages en mode **Simple** ou **Expert**, aide ❓ sur chaque réglage, texte plus grand, messages d'erreur traduits.
- Unchanged safety: send/spend are always asked, keys stay masked and local. / Sécurité inchangée : envoi/dépense toujours demandés, clés masquées et locales.

**Also in 0.5.0 / Aussi dans la 0.5.0 — no terminal at all / plus aucun terminal**

- ⚙ **Settings page** (EN/FR): add, edit, delete and test API keys per use, with limits (requests / tokens / cost per day or month) and a failover order; keys shown masked with their usage; changes apply without a restart. / **Page Réglages** : ajouter, modifier, supprimer et tester les clés d'API par usage, avec limites et ordre de relais ; clés masquées avec leur consommation ; changements appliqués sans redémarrage.
- Keys stored locally in a private file (0600) in `~/AutonomousAgent/data`, or the system keychain if available; never sent back to the browser, never logged, never in the audit. Settings can only be changed from the computer running the agent (`AGENT_REMOTE_SETTINGS=1` + sign-in + CSRF to allow phones). / Clés stockées localement dans un fichier privé (0600), ou dans le trousseau ; jamais renvoyées au navigateur, ni journalisées, ni dans l'audit. Réglages modifiables seulement depuis l'ordinateur de l'agent.
- Settings also cover language, IDC, permissions per category (send/spend can never be "allow"), phone access (tunnel, QR, new token), conversations at once, approval timeout, workspace. / Les réglages couvrent aussi langue, IDC, autorisations (envoi/dépense jamais « autoriser »), accès téléphone, tâches simultanées, délai de validation, dossier de travail.
- First-run wizard: language → API key (with a test) or demo mode → done. / Assistant de premier lancement : langue → clé d'API (avec test) ou mode démo → terminé.
- **Quit** and **Restart** buttons; double-clicking again just reopens the browser; no console window on Windows. / Boutons **Quitter** et **Redémarrer** ; un nouveau double-clic rouvre le navigateur ; plus de console sous Windows.
- Navigation fixed: Chat | Dashboard | Settings | Connect tabs on every page (☰ menu on phones), "← Back to chat", browser back/forward. / Navigation corrigée : onglets sur chaque page, « ← Retour au chat », retour/avance du navigateur.
- Collapsible work trace in the chat ("How the agent worked · 3 agents · 8 actions"), closed by default; approval cards stay visible. / Trace de travail repliable dans le chat, fermée par défaut ; les cartes de validation restent visibles.

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

The app opens in your browser with a 3-step wizard (language → API key or demo mode → done); everything else is in ⚙ Settings, and **Quit** stops it.
Your files, keys and data live in `~/AutonomousAgent` (Windows: `C:\Users\<you>\AutonomousAgent`).

L'application s'ouvre dans le navigateur avec un assistant en 3 étapes (langue → clé d'API ou mode démo → terminé) ;
tout le reste est dans ⚙ Réglages, et **Quitter** l'arrête. Vos fichiers, clés et données sont dans `~/AutonomousAgent`.

`SHA256SUMS.txt` lets you check the downloads / permet de vérifier les téléchargements.
Full guide / guide complet : see the README.
