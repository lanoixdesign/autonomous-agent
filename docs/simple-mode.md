# Simple and Advanced mode / Mode simple et mode avancé

**[English](#english) | [Français](#francais)** · [← README](../README.md) · [Docs](README.md)

<a id="english"></a>

## English

The app opens in **Simple mode** (new in 0.9.9, also for people who already used it, unless they had chosen
Advanced). It shows only what a beginner needs. Switch in **⚙ Settings → General → Display mode**.

| | Simple (default) | Advanced |
|---|---|---|
| Sidebar | Chat, New conversation, your conversations, Services, Settings, Help, Quit | + Dashboard, Dev, My files, theme, EN/FR, mode switch, advanced options |
| Conversations | the title, and a small dot while the agent works | + number of turns and status |
| Top of the chat | **Stop**, only while the agent works | + title, status, ⇩ MD / ⇩ JSON, IDC switch, Stop all, folder line |
| Work details | “The agent is working…” / “The agent is waiting for your answer”, steps under **See the details** | step counts and pending approvals |
| Approval card | one plain sentence, **Allow** / **Refuse**, a small “Don't ask me again in this conversation” box | + “until the app is closed” |
| Services | the three buttons and your service cards | + sign-in, pairing, My APIs, local programs |
| Settings | keys, language, theme, display mode, app | + sandbox, answer check, phone access, safety, IDC… |

Nothing is removed: everything stays in Advanced mode. Other things moved:

- **Export (Markdown)** and **Open the folder** are in each conversation's **⋯** menu.
- Without a key, a banner says so kindly, with an **Add a key** button that opens the key step of the welcome assistant.
- Approval cards say what a connected service will do in plain words: “The agent wants to write a file in My files”
  (built from the service's action name: read, write, list, create, delete, search, change, move, copy, send…;
  otherwise “The agent wants to use My files”). The exact action stays under **Technical details**.

<a id="francais"></a>

## Français

L'application s'ouvre en **mode simple** (nouveau en 0.9.9, aussi pour ceux qui l'utilisaient déjà, sauf s'ils
avaient choisi le mode avancé). Elle ne montre que l'essentiel. Pour changer : **⚙ Réglages → Général → Mode d'affichage**.

| | Simple (par défaut) | Avancé |
|---|---|---|
| Barre latérale | Chat, Nouvelle conversation, tes conversations, Services, Réglages, Aide, Quitter | + Tableau de bord, Dév, Mes fichiers, thème, EN/FR, bouton de mode, options avancées |
| Conversations | le titre, et un petit point pendant que l'agent travaille | + nombre de tours et état |
| Haut du chat | **Arrêter**, seulement pendant que l'agent travaille | + titre, état, ⇩ MD / ⇩ JSON, IDC, Tout arrêter, ligne du dossier |
| Détail du travail | « L'agent travaille… » / « L'agent attend ta réponse », les étapes sous **Voir le détail** | nombre d'étapes et validations en attente |
| Carte de validation | une phrase simple, **Autoriser** / **Refuser**, une petite case « Ne plus me demander dans cette conversation » | + « jusqu'à la fermeture de l'application » |
| Services | les trois boutons et les fiches de tes services | + connexion, appairage, Mes API, programmes locaux |
| Réglages | clés, langue, thème, mode d'affichage, application | + bac à sable, vérification des réponses, téléphone, sécurité, IDC… |

Rien n'est perdu : tout reste dans le mode avancé. Ce qui a bougé :

- **Exporter (Markdown)** et **Ouvrir le dossier** sont dans le menu **⋯** de chaque conversation.
- Sans clé, un bandeau le dit gentiment, avec un bouton **Ajouter une clé** qui ouvre l'étape « clé » de l'assistant de bienvenue.
- Les cartes de validation disent en mots simples ce qu'un service connecté va faire : « L'agent veut écrire un
  fichier dans Mes fichiers » (d'après le nom de l'action : lire, écrire, regarder, créer, supprimer, chercher,
  modifier, déplacer, copier, envoyer… ; sinon « L'agent veut utiliser Mes fichiers »). L'action exacte reste dans
  **Détails techniques**.
