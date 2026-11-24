"""v0.9.13 strings: starting a new version while an old one still runs, and the start error page."""

EN_V0913 = {
    "help.q6": "A new version does not start?",
    "help.a6": "From version 0.9.13 on, the new version closes the old one by itself. If it still does not start: "
               "click ⏻ Quit here first, delete the old app, put the new one in the Applications folder (Mac), "
               "then right-click it → Open (macOS 15: System Settings → Privacy & Security → Open Anyway). "
               "The log file is AutonomousAgent/data/app.log in your user folder.",
    "srv.takeover": "Only a new copy of the app on this computer can close this one.",
    "desktop.sameVersion": "This version ({version}) is already running: opening {url}",
    "desktop.replacing": "Version {old} is still running: closing it and starting {new}…",
    "desktop.replaced": "Version {old} closed.",
    "desktop.otherPort": "The other copy could not be closed: this version starts on another port ({port}).",
    "desktop.translocated": "macOS is running this app from a temporary copy (it was opened from Downloads). "
                            "Move it to the Applications folder for a reliable start.",
    "desktop.err.title": "The app could not start",
    "desktop.err.lead": "Something went wrong while starting autonomous-agent {version}. Nothing has been lost: your "
                     "conversations, keys and files are still in {home}.",
    "desktop.err.todo": "What to do",
    "desktop.err.s1": "Close this page, then open the app again.",
    "desktop.err.s2": "Still not working? Restart the computer, then open the app again.",
    "desktop.err.s3": "On a Mac: put the app in the Applications folder (replace the old one), then right-click it → "
                   "Open. On macOS 15 or later: System Settings → Privacy & Security → Open Anyway.",
    "desktop.err.s4": "If it still fails, send this file to the developer: {log}",
    "desktop.err.detail": "Technical details",
}

FR_V0913 = {
    "help.q6": "Une nouvelle version ne se lance pas ?",
    "help.a6": "Depuis la version 0.9.13, la nouvelle version ferme l'ancienne toute seule. Si elle ne se lance "
               "toujours pas : clique d'abord ici sur ⏻ Quitter, supprime l'ancienne appli, mets la nouvelle dans le "
               "dossier Applications (Mac), puis clic droit dessus → Ouvrir (macOS 15 : Réglages Système → "
               "Confidentialité et sécurité → Ouvrir quand même). Le fichier de suivi est AutonomousAgent/data/app.log "
               "dans ton dossier utilisateur.",
    "srv.takeover": "Seule une nouvelle copie de l'appli sur cet ordinateur peut fermer celle-ci.",
    "desktop.sameVersion": "Cette version ({version}) tourne déjà : ouverture de {url}",
    "desktop.replacing": "La version {old} tourne encore : je la ferme et je lance la {new}…",
    "desktop.replaced": "Version {old} fermée.",
    "desktop.otherPort": "L'autre copie n'a pas pu être fermée : cette version démarre sur un autre port ({port}).",
    "desktop.translocated": "macOS lance cette appli depuis une copie temporaire (elle a été ouverte depuis "
                            "Téléchargements). Mets-la dans le dossier Applications pour un démarrage fiable.",
    "desktop.err.title": "L'appli n'a pas pu démarrer",
    "desktop.err.lead": "Un problème est survenu au démarrage d'autonomous-agent {version}. Rien n'est perdu : tes "
                     "conversations, tes clés et tes fichiers sont toujours dans {home}.",
    "desktop.err.todo": "Que faire",
    "desktop.err.s1": "Ferme cette page, puis rouvre l'appli.",
    "desktop.err.s2": "Ça ne marche toujours pas ? Redémarre l'ordinateur, puis rouvre l'appli.",
    "desktop.err.s3": "Sur Mac : mets l'appli dans le dossier Applications (en remplaçant l'ancienne), puis clic droit "
                   "dessus → Ouvrir. Sur macOS 15 ou plus récent : Réglages Système → Confidentialité et sécurité → "
                   "Ouvrir quand même.",
    "desktop.err.s4": "Si ça échoue encore, envoie ce fichier au développeur : {log}",
    "desktop.err.detail": "Détails techniques",
}
