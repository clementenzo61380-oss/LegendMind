# LegendMind V3

Bot Discord **Legend League** : snapshots PostgreSQL, alertes, carnet d’erreurs, classement, saisons, métriques horaires.

## Prérequis

- **Python 3.10+** (recommandé **3.12**)
- Compte Supercell API (`COC_EMAIL` / `COC_PASSWORD`)
- Token Discord bot (`DISCORD_TOKEN`)

## Installation locale (mise en place)

```bash
cd coc_coach_pro
bash scripts/setup_bot.sh    # venv, .env, indique la suite
```

1. **PostgreSQL** : soit `docker compose up -d postgres` (depuis ce dossier), soit une instance locale (même `DATABASE_URL` que dans `.env`).
2. **Schéma** : `source .venv/bin/activate` puis `PYTHONPATH=. python scripts/migrate.py --apply` (ne requiert que `DATABASE_URL` dans `.env`).
3. **Secrets** : édite `.env` — `DISCORD_TOKEN`, `COC_EMAIL`, `COC_PASSWORD` (obligatoires pour `main.py`).
4. **Lancer** : `PYTHONPATH=. python main.py`

Au premier lancement du bot, le schéma est aussi appliqué si la base était vide.

```bash
pytest tests/
```

Ou avec make : `make install-dev`, `make test`, `make run`.

## Docker Compose

Depuis ce dossier, avec un fichier `.env` contenant au minimum `DISCORD_TOKEN`, `COC_EMAIL`, `COC_PASSWORD` :

```bash
docker compose up -d --build
```

`DATABASE_URL` est **surchargé** dans `docker-compose.yml` pour pointer vers le service `postgres`. Pour utiliser une base externe, retire la section `environment` du service `bot` et renseigne `DATABASE_URL` dans `.env`.

## Railway (hébergement 24h/24)

Pas besoin de laisser ton Mac allumé : Postgres managé + conteneur Dockerfile, webhook Stripe en HTTPS. Voir **`docs/DEPLOY_RAILWAY.md`**.

## Variables utiles

| Variable | Rôle |
|----------|------|
| `LOG_LEVEL` | `INFO`, `DEBUG`, … |
| `POLL_INTERVAL_SECONDS` | Intervalle de refill de la file de poll (défaut 180) |
| `POLL_QUEUE_MAX` | Taille max de la file |
| `ALERT_COOLDOWN_DEFAULT_SECONDS` | Cooldown par défaut hors carte `constants` |

## Documentation

- `docs/PROMPT_COVERAGE.md` — état d’alignement sur le gros prompt « LVL99 »
- `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/COMMANDS.md`

## Migrations SQL

```bash
python scripts/migrate.py --apply
```

## CI

Si la racine du dépôt est `coc-bot/`, le workflow `coc-bot/.github/workflows/legendmind-ci.yml` exécute **pytest** (Python 3.12) sur les changements sous `coc_coach_pro/`.

Si ton dépôt **n’est que** le dossier du bot, copie ce YAML à la racine : `.github/workflows/` et supprime `working-directory` / le préfixe de chemins `coc_coach_pro/`.

## Commandes slash (aperçu)

| Commande | Description |
|----------|-------------|
| `/lier` | Lier tag CoC |
| `/dashboard` | Tableau de bord |
| `/compare` | Comparer avec un membre |
| `/carnet` | Carnet d’erreurs hebdo |
| `/classement` | Top serveur (option ligue) |
| `/mvp_semaine` | Meilleur gain ~7 j |
| `/metriques` | Agrégats 24 h |
| `/historique` | Saisons clôturées (toi ou un tag) |
| `/bot_stats` | Santé bot (opérateur) |
| `/admin_*` | Voir `docs/COMMANDS.md` |
| `/serveur_config` | `voir` / `classement` — config guild |
| `/saison` | Saison active & dernier classement figé |
| `/saison_historique` | Saisons terminées récentes |
| `/admin_saison_cloturer` | Clôturer la saison (administrateur) |
