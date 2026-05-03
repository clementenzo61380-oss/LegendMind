# Configuration — LegendMind V3

Toutes les variables sont lues depuis `.env` (ou l'environnement shell).
Copie `.env.example` → `.env` et renseigne les valeurs obligatoires avant
de démarrer le bot ou d'exécuter `scripts/migrate.py`.

---

## Variables principales

| Variable | Req. | Défaut | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Token du bot Discord (onglet **Bot** dans le Developer Portal). |
| `COC_EMAIL` | ✅ | — | Adresse email du compte Supercell utilisé pour l'API CoC. |
| `COC_PASSWORD` | ✅ | — | Mot de passe du même compte Supercell. |
| `DATABASE_URL` | ✅ | — | DSN asyncpg complet, ex. `postgresql://legendmind:legendmind@localhost:5432/legendmind_v3`. Docker surcharge cette valeur automatiquement. |
| `DATABASE_SSL` | ❌ | auto | `true` / `false` pour forcer TLS vers Postgres. Sur **Railway**, si `RAILWAY_ENVIRONMENT` est défini, TLS est activé par défaut (voir `infer_database_ssl()` dans `config.py`). |
| `LOG_LEVEL` | ❌ | `INFO` | Niveau de log Python (`DEBUG`, `INFO`, `WARNING`, `ERROR`). En prod, utilise `INFO` ou `WARNING`. |

---

## Polling

| Variable | Req. | Défaut | Description |
|---|---|---|---|
| `POLL_INTERVAL_SECONDS` | ❌ | `180` | Intervalle de la boucle de poll **Legend I** (fast loop). La slow loop Legend II/III est fixée à `1800 s` dans `constants.py`. |
| `POLL_QUEUE_MAX` | ❌ | `2000` | Capacité max de chaque `asyncio.Queue`. Augmenter si plus de ~2 000 joueurs Legend I actifs. |
| `ALERT_COOLDOWN_DEFAULT_SECONDS` | ❌ | `3600` | Cooldown de secours pour un type d'alerte absent de `constants.ALERT_COOLDOWN_SECONDS`. |

---

## Stripe (Premium — tous optionnels)

Laisse ces variables vides pour faire tourner le bot en mode **Free-only**.
La commande `/premium` et le serveur webhook sont simplement désactivés.

| Variable | Req. | Défaut | Description |
|---|---|---|---|
| `STRIPE_API_KEY` | ❌ | — | Clé secrète Stripe (`sk_test_…` en test, `sk_live_…` en prod). |
| `STRIPE_WEBHOOK_SECRET` | ❌ | — | Secret webhook Stripe (`whsec_…`). Nécessaire pour valider la signature des événements reçus sur `/stripe/webhook`. |
| `STRIPE_PRICE_ID_MONTHLY` | ❌ | — | ID du Price Stripe mensuel (`price_…`). Créer dans Dashboard Stripe → Produits. |
| `STRIPE_SUCCESS_URL` | ❌ | `https://discord.com/channels/@me` | URL de redirection après paiement réussi. |
| `STRIPE_CANCEL_URL` | ❌ | `https://discord.com/channels/@me` | URL de redirection si l'utilisateur annule le Checkout. |

---

## Serveur HTTP webhook

| Variable | Req. | Défaut | Description |
|---|---|---|---|
| `WEBHOOK_HOST` | ❌ | `0.0.0.0` | Interface d'écoute du serveur aiohttp interne. |
| `WEBHOOK_PORT` | ❌ | `8000` ou `PORT` | Port du webhook Stripe. Sur **Railway**, la plateforme injecte `PORT` : si `WEBHOOK_PORT` est absent, sa valeur est utilisée (nécessaire pour exposer `/stripe/webhook`). |

---

## Valeurs recommandées par environnement

| Variable | dev | staging | prod |
|---|---|---|---|
| `LOG_LEVEL` | `DEBUG` | `INFO` | `INFO` |
| `POLL_INTERVAL_SECONDS` | `60` (court pour tests manuels — attention rate limits CoC) | `180` | `180` |
| `POLL_QUEUE_MAX` | `200` | `1000` | `2000` |
| `ALERT_COOLDOWN_DEFAULT_SECONDS` | `60` (spam volontaire en test) | `1800` | `3600` |
| `STRIPE_API_KEY` | `sk_test_…` | `sk_test_…` | `sk_live_…` |
| `DATABASE_URL` | `postgresql://…@localhost/…` | DSN staging | DSN prod RDS/Supabase |
| `WEBHOOK_PORT` | `8000` | `8000` | `8000` **ou** variable `PORT` sur PaaS (Railway) ; derrière reverse-proxy en prod. |

---

## Vérification rapide

```bash
# Smoke import — vérifie que toutes les variables obligatoires sont présentes.
PYTHONPATH=. python -c "from config import load_config; cfg = load_config(); print('OK', cfg.database_url[:30])"

# Appliquer schema + migrations :
PYTHONPATH=. python scripts/migrate.py --apply

# Dry-run (aucune connexion BDD) :
PYTHONPATH=. python scripts/migrate.py --dry-run
```

---

## Docker

`docker-compose.yml` surcharge `DATABASE_URL` pour pointer vers le conteneur
`postgres` interne. Les autres variables sont lues depuis `.env` via `env_file`.
Le bot attend que Postgres soit `healthy` (healthcheck `pg_isready`) avant de démarrer.

```bash
cp .env.example .env
# Remplir DISCORD_TOKEN, COC_EMAIL, COC_PASSWORD dans .env
docker compose up --build
```
