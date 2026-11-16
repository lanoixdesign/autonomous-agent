"""v0.9.4 strings (EN/FR, "tu"): clear messages when the model provider cannot answer."""

EN_V094 = {
    "kw.net": "network",
    "kw.waitNet": "Cannot reach the provider with key {key} (network). Trying again in {s} s…",
    "kw.shrink": "The request was too long for this key's per-minute limit: I shortened it and I'm trying again…",
    "err.tls": "Secure connection impossible: this computer could not check the provider's HTTPS certificate. "
               "Update the app (0.9.4 or later). On a Mac with Python from python.org, also run "
               "\"Install Certificates.command\".",
    "err.network": "I cannot reach {host} (no internet, firewall or proxy?). Check your connection, then try again.",
    "err.tooLarge": "Your request is too long for this key ({limit} tokens per minute on the free plan), even after "
                    "shortening it. Start a new conversation, send a shorter text, or add a key with a higher limit "
                    "in Settings → Keys.",
    "err.daily": "Daily limit reached on key {mask}. It comes back around {at}. Add a second key in Settings → Keys "
                 "to continue right away.",
    "err.dailyNoTime": "Daily limit reached on key {mask}. Try again later, or add a second key in Settings → Keys "
                       "to continue right away.",
    "err.keyInvalid": "Key refused by the provider (invalid, revoked or without credit). Check it or paste a new "
                      "one in Settings → Keys.",
    "err.model": "The model {model} is not available at the provider any more. Choose another model in "
                 "Settings → Keys.",
    "err.busy": "Every key is at its limit right now. Try again in a minute, or add a backup key in Settings → Keys.",
    "err.other": "The model could not answer: {detail}",
}

FR_V094 = {
    "kw.net": "réseau",
    "kw.waitNet": "Impossible de joindre le fournisseur avec la clé {key} (réseau). Nouvel essai dans {s} s…",
    "kw.shrink": "La demande était trop longue pour la limite par minute de cette clé : je l'ai raccourcie et je réessaie…",
    "err.tls": "Connexion sécurisée impossible : ton ordinateur n'a pas pu vérifier le certificat HTTPS du "
               "fournisseur. Mets l'application à jour (0.9.4 ou plus). Sur un Mac avec Python de python.org, "
               "lance aussi « Install Certificates.command ».",
    "err.network": "Je n'arrive pas à joindre {host} (pas d'internet, pare-feu ou proxy ?). Vérifie ta connexion, "
                   "puis réessaie.",
    "err.tooLarge": "Ta demande est trop longue pour cette clé ({limit} tokens par minute avec la clé gratuite), même "
                    "après l'avoir raccourcie. Commence une nouvelle conversation, envoie un texte plus court, ou "
                    "ajoute une clé avec une limite plus haute dans Réglages → Clés.",
    "err.daily": "Limite du jour atteinte sur la clé {mask}. Reprise vers {at}. Ajoute une deuxième clé dans "
                 "Réglages → Clés pour continuer tout de suite.",
    "err.dailyNoTime": "Limite du jour atteinte sur la clé {mask}. Réessaie plus tard, ou ajoute une deuxième clé "
                       "dans Réglages → Clés pour continuer tout de suite.",
    "err.keyInvalid": "Clé refusée par le fournisseur (invalide, révoquée ou sans crédit). Vérifie-la ou colles-en "
                      "une nouvelle dans Réglages → Clés.",
    "err.model": "Le modèle {model} n'est plus disponible chez le fournisseur. Choisis un autre modèle dans "
                 "Réglages → Clés.",
    "err.busy": "Toutes tes clés sont à leur limite pour le moment. Réessaie dans une minute, ou ajoute une clé de "
                "secours dans Réglages → Clés.",
    "err.other": "Le modèle n'a pas pu répondre : {detail}",
}
