# Architecture LegendMind V3

---

## Vue d'ensemble des couches

```
┌─────────────────────────────────────────────────────────────────────┐
│  Discord Gateway                                                    │
│  (discord.py commands.Bot)                                          │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ tracker  │ │dashboard │ │notebook  │ │leaderboard│ │ admin    │ │
│  │(cog)     │ │(cog)     │ │(cog)     │ │(cog)     │ │(cog)     │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │             │            │             │            │        │
│  ┌────▼─────┐ ┌────▼─────┐ ┌───▼──────┐ ┌───▼──────┐ ┌───▼──────┐│
│  │ LegendP. │ │Dashboard │ │ Notebook │ │Leaderbd  │ │ Metrics  ││
│  │ (service)│ │ View     │ │ Service  │ │ Service  │ │Collector ││
│  └────┬─────┘ └──────────┘ └──────────┘ └────┬─────┘ └──────────┘│
│       │                                        │                   │
│  ┌────▼──────────────────────────────────┐     │                   │
│  │        AlertManager                   │     │                   │
│  │  eval → cooldown → dispatch → DM      │     │                   │
│  └────┬──────────────────────────────────┘     │                   │
│       │                                        │                   │
│  ┌────▼────────────────────────────────────────▼────────────────┐  │
│  │                    Repository (services/db.py)               │  │
│  │   typed CRUD — jamais de SQL brut hors de ce module          │  │
│  └────────────────────────────┬─────────────────────────────────┘  │
└───────────────────────────────│─────────────────────────────────────┘
                                │
                        ┌───────▼────────┐
                        │  PostgreSQL 16  │
                        │  (asyncpg pool) │
                        └────────────────┘
```

---

## Flux de polling — pipeline complet

```
                    FAST LOOP (180 s)               SLOW LOOP (1 800 s)
                    Legend I only                   Legend II/III + UNKNOWN
                         │                                   │
                         ▼                                   ▼
                ┌────────────────┐               ┌────────────────┐
                │  _fast_queue   │               │  _slow_queue   │
                │  (asyncio.Q)   │               │  (asyncio.Q)   │
                └───────┬────────┘               └───────┬────────┘
                        │ (4 workers)                    │ (1 worker)
                        ▼                                ▼
                ┌──────────────────────────────────────────────┐
                │            _process_task                     │
                │                                              │
                │  1. CoC API get_player (backoff+jitter)      │
                │  2. Build LegendSnapshot from coc.Player     │
                │  3. Load previous snapshot from DB           │
                │  4. _is_unchanged? → early return (no write) │
                │  5. save_snapshot (UniqueViolation = dedup)  │
                │  6. AttackDelta.between(prev, current)       │
                │  7. _fanout_delta → subscribers              │
                └──────────────┬───────────────────────────────┘
                               │
                ┌──────────────▼───────────────────────────────┐
                │  Delta subscribers (wired in main.py)        │
                │  ├─ AlertManager.evaluate_and_dispatch()     │
                │  └─ repo.bump_hourly_metrics(delta)          │
                └──────────────────────────────────────────────┘
```

---

## Cycle de vie d'une alerte

```
AttackDelta
    │
    ▼
AlertManager.evaluate(delta, prefs)
    │
    ├── check_threshold(snapshot)        → RELEGATION / PROMOTION
    ├── check_attack_pace(attacks, tier) → PACE_CRITICAL / WARNING
    ├── _detect_streak(tag)              → STREAK_POS / NEG
    ├── _detect_comeback(snapshot)       → COMEBACK
    ├── _detect_season_best(snapshot)    → SEASON_BEST
    └── _detect_daily_goal(delta)        → DAILY_GOAL
    │
    ▼
list[Alert] (candidates)
    │
    for each Alert:
    ├── _is_in_quiet_hours(user_id)?     → skip
    ├── get_last_alert_at(tag, type)?    → cooldown elapsed?  → skip
    └── _dispatch_one(alert)
          ├── build_embed(_STYLE[type])
          ├── bot.fetch_user(discord_user_id)
          ├── user.send(embed=embed)
          └── repo.record_alert(...)     → alert_history
```

---

## Billing & quotas

```
/setup ou /premium
    │
    ▼
BillingService
    ├── is_entitled(user_id)             → subscriptions table
    ├── start_trial(user_id)             → idempotent (1 essai à vie)
    └── create_checkout_session(user_id) → Stripe Checkout URL
    │
    ▼
Stripe Checkout
    │ webhook POST /stripe/webhook
    ▼
StripeWebhookServer (aiohttp :8000)
    ├── vérif signature HMAC
    └── billing.handle_webhook_event()
          ├── checkout.session.completed → status='active', period_end
          ├── invoice.payment_succeeded  → renouvellement
          └── customer.subscription.deleted → status='cancelled'

QuotaService (ping /50 par mois Free)
    ├── can_consume(user_id)             → ping_quota table
    └── consume(user_id)                 → incrément + warned_full
```

---

## Recap hebdomadaire Legend II/III

```
main.py — _weekly_recap_loop() (boucle 5 min)
    │
    every (Sunday 22h UTC)
    │
    ▼
WeeklyRecapService.run()
    ├── get Legend II/III players with alert_on_defense=True
    ├── skip si alert_history contient 'weekly_recap' < 6 j
    ├── build digest (7 j de snapshots : trophées, batailles, gains)
    └── user.send(embed=digest_embed)
         └── record_alert('weekly_recap', ...) → dédup semaine suivante
```

---

## Modèle de données (ERD simplifié)

```
players ──────────────────────────────────────────┐
  tag PK                                          │
  discord_user_id                                 │
  guild_id → guild_config.guild_id                │
  legend_tier  (déclaratif — source de vérité)    │
  is_active                                       │
         │                                        │
         ├── player_snapshots                     │
         │     player_tag FK                      │
         │     trophies, league_type              │
         │     attacks_done, gained, lost         │
         │     captured_at  (UNIQUE/minute)       │
         │                                        │
         ├── defense_log                          │
         │     player_tag FK                      │
         │     trophies_lost, malchance_score      │
         │     logged_at                          │
         │                                        │
         ├── alert_history                        │
         │     player_tag FK                      │
         │     alert_type, discord_user_id        │
         │     sent_at  (cooldown index)          │
         │                                        │
         ├── league_goals                         │
         │     player_tag PK/FK                   │
         │     target_trophies, target_attacks    │
         │                                        │
         └── season_results                       │
               player_tag FK                      │
               season_id FK → seasons             │
               final_trophies, guild_rank         │
                                                  │
user_preferences                                  │
  discord_user_id PK                             │
  enable_error_notebook, enable_alerts           │
  alert_on_defense, quiet_hours_*               │
                                                  │
subscriptions                                     │
  discord_user_id PK                             │
  plan (free/trial/premium), status             │
  trial_used, current_period_end                │
  stripe_customer_id, stripe_subscription_id   │
                                                  │
ping_quota                                        │
  (discord_user_id, year_month) PK              │
  used, warned_full                              │
                                                  │
guild_config ◄────────────────────────────────────┘
  guild_id PK
  alerts_channel_id, leaderboard_channel_id
  leaderboard_message_id  (embed auto-refresh)
  admin_role_id
  legend_role_i_id / ii_id / iii_id

seasons
  id PK, label, period_start, period_end (NULL = active)
  ↑
season_results
  (season_id, player_tag) UNIQUE

metrics_hourly          (par joueur, 1 h)
bot_metrics_hourly      (agrégat bot, flush depuis main.py)
```

---

## Tier-aware polling (Avril 2026 — refonte Supercell)

| | Legend I | Legend II / III |
|---|---|---|
| **Loop** | fast (180 s) | slow (1 800 s) |
| **Workers** | 4 parallèles | 1 |
| **Source du tier** | `players.legend_tier` | `players.legend_tier` |
| **Alertes** | pace, defense, threshold, streak… | recap hebdo dimanche 22h UTC |
| **`/ping`** | DM par défense (50/mois Free) | recap auto (pas de quota) |

> **Pourquoi déclaratif ?** L'API CoC ne retourne `currentSeason.rank` que
> pour le top 200 mondial — impossible d'auto-détecter le tier pour ~99 %
> des joueurs Legend. Le tier est déclaré au `/setup` (Select) et modifiable
> via `/tier`. La détection par trophy-band (`detect_league()`) est conservée
> pour l'**affichage** uniquement (barres de progression) — elle ne pilote plus
> rien de fonctionnel.

---

## Démarrage local (sans Docker)

```bash
# 1. PostgreSQL
createdb -O legendmind legendmind_v3
PYTHONPATH=. python scripts/migrate.py --apply

# 2. Bot
PYTHONPATH=. python main.py
```

## Démarrage via Docker Compose

```bash
cp .env.example .env   # puis remplir DISCORD_TOKEN, COC_EMAIL, COC_PASSWORD
docker compose up --build
# Postgres devient healthy → bot démarre automatiquement
```
