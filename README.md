# Bot Telegram de supervision DevOps

Modèle **générique** de bot Telegram en Python pour surveiller une application web et consulter l'historique de pipelines GitHub Actions. Aucune adresse de projet, aucun identifiant de conversation et aucun secret réel ne sont fournis.

## Fonctionnalités

- **Menu de boutons Telegram** : état des services, machine, dernière CI/CD, historique, statistiques et aide.
- **Surveillance HTTP** d'un frontend (réponse HTTP 200) et d'un backend (réponse HTTP 200 avec JSON `{"status":"ok"}`).
- **Alertes de changement d'état** : notification en cas de panne ou de rétablissement après une précédente vérification.
- **GitHub Actions** : consultation des exécutions, jobs et étapes en échec via l'API GitHub ; notifications des nouvelles exécutions *terminées* (pas de notification au démarrage d'un pipeline).
- **Informations système** : charge Linux, mémoire, disque et uptime.
- **État persistant** dans `state.json` pour limiter les notifications en double après un redémarrage.

> Le bot ne corrige pas automatiquement les pannes et ne garantit pas une supervision 24 h/24 si la machine qui l'héberge s'arrête.

## Prérequis

- Linux, par exemple **Debian sous WSL**, avec **Python 3.9 ou supérieur**.
- Accès Internet vers `api.telegram.org`, `api.github.com` et les URL surveillées.
- Un bot créé avec **@BotFather** et l'identifiant (`chat_id`) de la conversation qui recevra les alertes.
- Facultatif : un jeton GitHub ayant accès au dépôt à surveiller. Pour un dépôt privé, privilégier un *fine-grained personal access token* limité au dépôt, avec la permission **Actions: Read-only**.

Le programme n'utilise **aucune dépendance Python externe** : seule la bibliothèque standard est nécessaire.

## Installation

```bash
sudo apt update
sudo apt install -y python3 python3-venv ca-certificates

unzip telegram_bot_modele.zip
cd telegram_bot_modele

python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env
chmod 600 .env
nano .env
```

Si le dossier est déjà extrait, passe directement à `cd telegram_bot_modele`.

## Configuration

Édite `.env` avec **tes propres valeurs** :

```dotenv
TELEGRAM_BOT_TOKEN=TON_TOKEN_TELEGRAM
TELEGRAM_CHAT_ID=TON_CHAT_ID

GITHUB_TOKEN=TON_TOKEN_GITHUB
GITHUB_REPO=organisation/mon-depot

FRONTEND_URL=https://frontend.example.com/
BACKEND_HEALTH_URL=https://backend.example.com/health

GITHUB_INTERVAL=90
HEALTH_INTERVAL=300
```

| Variable | Rôle |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token du bot Telegram, **obligatoire**. |
| `TELEGRAM_CHAT_ID` | ID de la conversation autorisée, **obligatoire**. |
| `GITHUB_TOKEN` | Jeton de lecture GitHub Actions, facultatif si tu ne souhaites pas surveiller GitHub. |
| `GITHUB_REPO` | Dépôt au format `organisation/depot` ; requis pour la partie GitHub. |
| `FRONTEND_URL` | URL HTTP(S) du frontend à tester. |
| `BACKEND_HEALTH_URL` | URL HTTP(S) de santé du backend, devant répondre `{"status":"ok"}` avec HTTP 200. |
| `GITHUB_INTERVAL` | Intervalle d'interrogation GitHub en secondes (minimum 30, défaut 90). |
| `HEALTH_INTERVAL` | Intervalle des contrôles HTTP en secondes (minimum 30, défaut 300). |

**Important :** le programme lit automatiquement `.env` dans son propre dossier. Il n'est pas nécessaire de faire `source .env` avant son lancement.

Pour obtenir le `chat_id` d'une conversation privée, envoie un message à ton bot puis consulte l'API Telegram `getUpdates` depuis un environnement sûr, sans publier ton token ni le résultat complet en public. Pour un groupe, ajoute le bot au groupe et utilise l'ID du groupe. Le modèle autorise un **seul** `TELEGRAM_CHAT_ID`.

## Démarrer et vérifier

```bash
python3 -m py_compile bot.py
python3 bot.py
```

Au démarrage, le bot envoie un message avec les boutons. Depuis Telegram, utilise `/start` ou `/menu` pour afficher le menu. Arrête le processus avec `Ctrl+C`.

### Commandes Telegram

| Commande | Fonction |
| --- | --- |
| `/start`, `/menu`, `/help` | Affiche l'aide et les boutons. |
| `/status` | Contrôle HTTP du frontend et du backend. |
| `/machine` | Informations système du serveur Linux hébergeant le bot. |
| `/cicd` | Dernière exécution GitHub Actions. |
| `/historique` | Dix dernières exécutions GitHub Actions. |
| `/stats` | Statistiques sur les 30 dernières exécutions. |
| `/run 123456789` | Détails d'une exécution, jobs et étapes échouées. |

Les boutons proposent les principales commandes. Pour consulter une exécution précise, utilise `/run` suivi de son identifiant numérique.

## Fonctionnement des notifications

- **GitHub** : au premier démarrage, les exécutions déjà présentes sont mémorisées **sans déclencher d'alertes rétroactives**. Les nouveaux pipelines terminés sont ensuite signalés à l'intervalle de contrôle. Les pipelines en cours ne déclenchent pas de notification de démarrage.
- **HTTP** : le premier état observé sert de référence. Une alerte est envoyée uniquement si l'état change, puis une notification de rétablissement au retour du service.
- **Historique local** : `state.json` conserve les identifiants GitHub déjà signalés et le dernier état des services.

Les résultats GitHub restent consultables à la demande via `/historique` et `/run` même s'ils précèdent la première exécution du bot.

## Exécution avec systemd (Linux)

Si ta distribution utilise systemd, crée un service en remplaçant **UTILISATEUR** et **CHEMIN_ABSOLU** par les valeurs renvoyées par `whoami` et `pwd` :

```ini
# /etc/systemd/system/telegram-devops.service
[Unit]
Description=Bot Telegram de supervision DevOps
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=UTILISATEUR
WorkingDirectory=CHEMIN_ABSOLU
ExecStart=CHEMIN_ABSOLU/.venv/bin/python CHEMIN_ABSOLU/bot.py
Restart=always
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Puis :

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-devops
sudo systemctl status telegram-devops
sudo journalctl -u telegram-devops -f
```

**WSL :** activer un service systemd ne démarre pas automatiquement ton ordinateur et ne maintient pas la distribution active lorsque Windows est éteint. Pour une surveillance continue, héberge le bot sur un serveur qui reste allumé.

**Évite de lancer simultanément le bot dans un terminal et dans systemd** : deux instances utilisant `getUpdates` peuvent entrer en conflit.

## Sécurité

- Ne publie jamais `.env`, les tokens, `state.json` ou les logs contenant des données sensibles. Le `.gitignore` fourni exclut les principaux fichiers locaux.
- Utilise un jeton GitHub **en lecture seule**, restreint au dépôt nécessaire.
- Le programme ignore les commandes reçues de conversations dont l'identifiant ne correspond pas à `TELEGRAM_CHAT_ID`. Cela ne remplace pas une politique d'autorisation par utilisateur pour un groupe.
- **Attention aux groupes Telegram** : toute personne pouvant lire les messages du groupe peut consulter les informations que le bot y publie. Ne partage pas de secrets dans les alertes.
- Le code utilise `getUpdates` (long polling) et désactive tout webhook Telegram déjà configuré au lancement : n'utilise pas simultanément ce token avec un autre bot ou un webhook.
- Pour des notifications plus fiables, une supervision 24 h/24 et une journalisation avancée, prévois un hébergement permanent, des contrôles supplémentaires et une gestion plus fine des accès.

## Dépannage

| Symptôme | Vérification |
| --- | --- |
| `Configurer TELEGRAM_BOT_TOKEN...` | Vérifie l'existence de `.env` et les deux variables Telegram. |
| Pas de message au démarrage | Vérifie le token, le `chat_id`, la connexion Internet et que tu as démarré la conversation avec le bot. |
| Boutons sans réponse | Vérifie qu'une seule instance utilise `getUpdates`. |
| CI/CD indisponible | Vérifie `GITHUB_REPO`, la validité du token et la permission `Actions: Read-only`. |
| Backend indiqué en panne | Vérifie que `/health` répond en HTTP 200 avec `{"status":"ok"}`. |
| Bot arrêté sur WSL | Vérifie que Debian WSL est démarré et, si configuré, le statut du service systemd. |

## Structure du projet

```text
telegram_bot_modele/
├── bot.py          # Code Python du bot
├── .env.example    # Exemple de configuration (sans secrets)
├── .gitignore      # Fichiers à exclure de Git
├── README.md       # Documentation
├── .env            # Configuration locale (à créer, non versionnée)
└── state.json      # État créé automatiquement à l'exécution
```

## Licence

Aucune licence n'est fournie avec ce modèle. Ajoute une licence adaptée si tu souhaites le publier ou autoriser sa réutilisation.
