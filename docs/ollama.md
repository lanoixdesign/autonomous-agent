# My own AI with Ollama / Ma propre IA avec Ollama

**[English](#english) | [Français](#francais)** · [← README](../README.md) · [Docs](README.md)

<a id="english"></a>

## English

Instead of a Groq key, the assistant can use **your own model**, running with [Ollama](https://ollama.com) on your
computer, or on another computer of yours, such as a **Shadow PC** (a Windows PC in the cloud). Nothing is sent to an
online AI, and there is no key. Recommended model: **qwen2.5:7b** (about 5 GB). It is good at using tools (files, web…)
and runs well on an 8 GB graphics card such as an RTX 2000.

### 1. Install Ollama (Windows, e.g. on your Shadow PC)

1. Go to [ollama.com/download](https://ollama.com/download), download **Ollama for Windows** and install it.
   Ollama then runs in the background, and a llama icon appears near the clock.
2. Open **Terminal** (or PowerShell) and type:
   ```
   ollama pull qwen2.5:7b
   ```
   Wait for the download to finish. You only do this once.
3. Check that it works:
   ```
   ollama run qwen2.5:7b "Hello, who are you?"
   ```
   An answer appears. You can also open <http://localhost:11434> in a browser: it says “Ollama is running”.
4. Recommended: give the model more room to read (instructions + tools). In **Windows Settings → System → About →
   Advanced system settings → Environment Variables**, add a user variable `OLLAMA_CONTEXT_LENGTH` = `8192`, then
   quit Ollama (right-click the llama icon → Quit) and start it again.

### 2. Connect the app

- **The app runs on the same PC as Ollama.** At the first launch (or ⚙ Settings → *Relaunch the welcome assistant*),
  choose **My AI on my computer (Ollama)** and click **Check**. Your models are listed. Pick **qwen2.5:7b**, then
  click **Save and continue**. The address stays `http://localhost:11434`.
- **The app runs on another computer.** See *Remote access* below, then type the address of the PC that runs Ollama
  and click **Check**.

If a model cannot use tools, the app says so: the assistant could only chat. Pick qwen2.5:7b instead.
To change the model later: ⚙ Settings → API keys & models → *Ollama* → Edit.

### 3. Optional: use Ollama from another computer

Ollama has **no password**. **Never open port 11434 to the internet** (no port forwarding, no public link): anyone
could use your graphics card and read what you send.

- **Tailscale (recommended):** a private network between your own devices, free for personal use.
  1. Install [Tailscale](https://tailscale.com/download) on the Shadow PC and on your other computer, and sign in
     with the same account on both.
  2. On the Shadow PC, add the user variable `OLLAMA_HOST` = `0.0.0.0` (same place as above), then restart Ollama.
     If Windows asks, allow Ollama on **private networks only**.
  3. In the app on the other computer, type `http://<name-of-the-shadow-pc>:11434` (the name or `100.x.y.z` address
     shown in Tailscale), then click **Check**.
- **Cloudflare Tunnel:** only with **Cloudflare Access** in front of it (sign-in required); a tunnel without Access is
  a public link. The app cannot sign in to Cloudflare Access by itself yet, so prefer Tailscale.

**Shadow PC:** Shadow may **shut down your PC when it is idle**. Then Ollama does not answer and the app says so.
Start the Shadow PC again (Ollama starts with Windows). Before any public or “server” use (sharing it with other
people, leaving it on all the time), check Shadow's terms of use.

<a id="francais"></a>

## Français

À la place d'une clé Groq, l'assistant peut utiliser **ton propre modèle**, qui tourne avec
[Ollama](https://ollama.com) sur ton ordinateur, ou sur un autre ordinateur à toi, comme un **PC Shadow** (un PC
Windows dans le cloud). Rien n'est envoyé à une IA en ligne, et il n'y a pas de clé. Modèle conseillé : **qwen2.5:7b**
(environ 5 Go). Il sait bien utiliser les outils (fichiers, web…) et tourne bien sur une carte graphique de 8 Go
comme une RTX 2000.

### 1. Installer Ollama (Windows, par exemple sur ton PC Shadow)

1. Va sur [ollama.com/download](https://ollama.com/download), télécharge **Ollama pour Windows** et installe-le.
   Ollama tourne ensuite en arrière-plan, et une icône de lama apparaît près de l'horloge.
2. Ouvre le **Terminal** (ou PowerShell) et tape :
   ```
   ollama pull qwen2.5:7b
   ```
   Attends la fin du téléchargement. Tu ne le fais qu'une fois.
3. Vérifie que ça marche :
   ```
   ollama run qwen2.5:7b "Bonjour, tu es qui ?"
   ```
   Une réponse s'affiche. Tu peux aussi ouvrir <http://localhost:11434> dans un navigateur : il affiche
   « Ollama is running ».
4. Conseillé : donne au modèle plus de place pour lire (consignes + outils). Dans **Paramètres Windows → Système →
   Informations système → Paramètres avancés du système → Variables d'environnement**, ajoute une variable
   utilisateur `OLLAMA_CONTEXT_LENGTH` = `8192`, puis quitte Ollama (clic droit sur l'icône du lama → Quit) et
   relance-le.

### 2. Connecter l'appli

- **L'appli tourne sur le même PC qu'Ollama.** Au premier lancement (ou ⚙ Réglages → *Relancer l'assistant de
  bienvenue*), choisis **Mon IA sur mon ordinateur (Ollama)** et clique sur **Vérifier**. Tes modèles s'affichent.
  Choisis **qwen2.5:7b**, puis clique sur **Enregistrer et continuer**. L'adresse reste `http://localhost:11434`.
- **L'appli tourne sur un autre ordinateur.** Vois *Accès à distance* ci-dessous, puis tape l'adresse du PC où
  tourne Ollama et clique sur **Vérifier**.

Si un modèle ne sait pas utiliser d'outils, l'appli te le dit : l'assistant pourrait seulement discuter. Choisis
plutôt qwen2.5:7b. Pour changer de modèle plus tard : ⚙ Réglages → Clés d'API et modèles → *Ollama* → Modifier.

### 3. Facultatif : utiliser Ollama depuis un autre ordinateur

Ollama n'a **pas de mot de passe**. **N'ouvre jamais le port 11434 sur Internet** (pas de redirection de port, pas
de lien public) : n'importe qui pourrait utiliser ta carte graphique et lire ce que tu envoies.

- **Tailscale (conseillé) :** un réseau privé entre tes propres appareils, gratuit pour un usage personnel.
  1. Installe [Tailscale](https://tailscale.com/download) sur le PC Shadow et sur ton autre ordinateur, et
     connecte-toi avec le même compte sur les deux.
  2. Sur le PC Shadow, ajoute la variable utilisateur `OLLAMA_HOST` = `0.0.0.0` (au même endroit que plus haut),
     puis relance Ollama. Si Windows le demande, autorise Ollama sur les **réseaux privés seulement**.
  3. Dans l'appli sur l'autre ordinateur, tape `http://<nom-du-pc-shadow>:11434` (le nom ou l'adresse `100.x.y.z`
     affichés dans Tailscale), puis clique sur **Vérifier**.
- **Cloudflare Tunnel :** seulement avec **Cloudflare Access** devant (connexion obligatoire) ; un tunnel sans Access
  est un lien public. L'appli ne sait pas encore se connecter toute seule à Cloudflare Access : préfère Tailscale.

**PC Shadow :** Shadow peut **éteindre ton PC quand il ne sert pas**. Ollama ne répond alors plus, et l'appli te le
dit. Rallume le PC Shadow (Ollama démarre avec Windows). Avant tout usage public ou « serveur » (le partager avec
d'autres personnes, le laisser allumé en permanence), vérifie les conditions d'utilisation de Shadow.
