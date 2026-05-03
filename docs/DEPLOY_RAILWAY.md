# Déployer LegendMind sur Railway

Guide pour faire tourner le bot **24h/24** avec **PostgreSQL** managé et une URL HTTPS pour le webhook Stripe.

## Prérequis

- Compte [Railway](https://railway.app) (crédit trial / facturation selon ton plan).
- Dépot Git (GitHub, etc.) contenant **`coc_coach_pro/`** à la racine du service **ou** monorepo avec sous-dossier (voir ci-dessous).

## 1. Postgres

1. Nouveau projet Railway → **+ New** → **Database** → **PostgreSQL**.
2. Onglet **Variables** du service Postgres : repère `DATABASE_URL` (ou **Connect** → copie l’URL interne).

## 2. Service du bot (Dockerfile)

1. **+ New** → **GitHub Repo** (ou **Empty service** + branche un repo).
2. **Settings** :
   - **Root Directory** : mets `coc_coach_pro` si ton repo est un monorepo (`coc-bot/coc_coach_pro`, etc.). Si le dépôt **n’est que** ce dossier, laisse vide.
   - **Builder** : **Dockerfile** (fichier `Dockerfile` à la racine du *root directory*).
3. **Variables** (onglet *Variables* du service **bot**, pas Postgres) :

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `DISCORD_TOKEN` | oui | Token du bot Discord. |
| `COC_EMAIL` | oui | Compte API Supercell. |
| `COC_PASSWORD` | oui | Mot de passe API Supercell. |
| `DATABASE_URL` | oui | **Référence** vers le Postgres Railway : *Add Reference* → service Postgres → `DATABASE_URL`. |
| `STRIPE_*` | si Premium | Voir `.env.example` / `docs/STRIPE_SETUP.md`. |
| `LIFETIME_ENTITLED_DISCORD_IDS` | non | IDs Discord Premium à vie. |
| Autres | non | `LOG_LEVEL`, `GAME_TUNING_URL`, export Excel, etc. |

Railway injecte automatiquement :

- `PORT` → le bot écoute le **webhook HTTP + `/health`** sur ce port (pas besoin de `WEBHOOK_PORT` sauf cas particulier).
- `RAILWAY_ENVIRONMENT` → active **SSL** vers Postgres (`DATABASE_SSL` peut forcer / désactiver, voir `config.py`).

4. **Networking** : génère un **domaine public** (Settings → *Networking* → *Generate Domain*).  
   URL webhook Stripe :  
   `https://<ton-domaine-railway>/stripe/webhook`  
   Déclare cette URL dans le Dashboard Stripe (événements `checkout.session.completed`, `customer.subscription.*`, etc.) et mets `STRIPE_WEBHOOK_SECRET` avec le secret du endpoint.

5. **Deploy** : le conteneur lance `python main.py` ; schéma + migrations s’appliquent au **démarrage** (comme en local).

## 3. Vérifications

- Logs Railway : pas d’erreur `asyncpg` / SSL → si besoin, ajoute `DATABASE_SSL=true` ou `false` (voir `infer_database_ssl()` dans `config.py`).
- Santé HTTP : `https://<domaine>/health` doit répondre `ok`.
- Discord : le bot apparaît en ligne ; teste une commande slash.

## 4. Limites à connaître

- **Disque éphémère** : fichiers sous `/app/data` (export Excel, état export) peuvent être **perdus** au redeploy. Pour un historique persistant, prévois plus tard un volume ou un stockage externe.
- **Crédit Railway** : surveille l’usage ; un bot + une petite Postgres restent souvent dans les offres d’essai, selon trafic et plan.

## 5. Monorepo

Si le Dockerfile est dans `coc_coach_pro/` mais le repo est à la racine parente, configure **Root Directory** = `coc_coach_pro` pour que le build voie le bon `Dockerfile` et `requirements.txt`.
