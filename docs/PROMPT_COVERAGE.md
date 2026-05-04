# Couverture du prompt « LegendMind V3 / LVL99 »

État final aligné sur le prompt CLAUDE_CODE_PROMPT (LVL99).

| Zone | Statut | Notes |
|------|--------|--------|
| **0 — `constants.py`** | Complet | Seuils, tables, couleurs, messages, ALERT_COOLDOWN. |
| **0 — `models/player.py`** | Complet | `slots=True`, dataclasses figées (snapshots, defenses, etc.). |
| **0 — Repository / migrations** | Complet | CRUD + `schema_migrations` ; migrations forward-only `_MIGRATIONS`. |
| **0 — `logic.py` (malchance liste)** | Complet | `aggregate_malchance(list)`, `predict_end_of_season_trophies`, `calculate_pace_score`. |
| **1 — Snapshots + tracker** | Complet | Dédup minute, pas de ligne si inchangé, deltas + subscribers. |
| **2 — `notebook.py` + `/carnet`** | Complet | Rapport hebdo, patterns, recommandations, bouton tendance. |
| **3 — `AlertManager` + `alert_history`** | Complet | 10 `AlertType` (dont `defense_taken` opt-in), cooldowns BDD, embeds par type, quiet hours. |
| **3 — `/ping` (push défense automatique)** | Complet | Toggle utilisateur (`UserPreferences.alert_on_defense`, migration 003) ; cooldown 60 s ; quota 50/mois Free, illimité Premium/Trial. |
| **3 — Billing Stripe + entitlement** | Complet | `services/billing.py` (Stripe Checkout), `services/quota.py` (50/mois Free), webhook aiohttp (`services/stripe_webhook.py`), tables `subscriptions` + `ping_quota` (migration 004). |
| **3 — `/setup` + `/premium` + `/accounts`** | Complet | `/setup` vérifie l’id ligue Légende (tuning / défaut ex. `105000036`), active essai 7 j, **présente un Select Légende I/II/III** (Avril 2026 refonte). `/premium` ouvre Checkout. `/accounts` liste/retire avec tier affiché (limite 1 Free / 3 Premium). |
| **3 — `/tier` (Avril 2026)** | Complet | Nouvelle commande pour mettre à jour le tier déclaré d'un compte. Auto-détection top 200 mondial via `legendStatistics.currentSeason.rank`, sinon Select manuel. |
| **3 — `/daily` + `/predict` + `/score`** | Complet | `cogs/coach.py` branche par tier : **Legend I** = daily (8/jour), **Legend II/III** = hebdo (30 ou 24 batailles/sem). Refus si tier UNKNOWN avec invitation à `/tier`. |
| **3 — Rang mondial via régression (`services/rank_predictor.py`)** | Complet | Fetch top 200 mondial toutes les 10 min, ajuste `trophies = a − b·ln(rank)` (R² typique ≈ 0.97), permet d'estimer le rang de N'IMPORTE QUEL joueur (même hors top 200) à partir de ses trophées. Branché dans `/predict` pour tous les tiers (current rank + projected rank). |
| **3 — Refonte Ranked Avril 2026** | Complet | `players.legend_tier` (migration 005), tracker split fast (180 s Legend I) / slow (1800 s II/III), `WeeklyRecapService` Sunday 22h UTC, `AlertManager` mute pace/relegation/defense pour II/III. |
| **4 — Dashboard 3 pages + compare + modal** | Complet | Boutons navigation + EditGoalModal. |
| **5 — `LeaderboardService` + cache + MVP** | Complet | TTL 5 min, `/classement`, `/mvp_semaine`, `/metriques`. |
| **6 — `guild_config` étendue** | Complet | Toutes colonnes (rôles, salons, langue, TZ). |
| **6 — `/admin` (LVL99)** | Complet | Sous-groupe `/admin setup`, `set-channel`, `set-role`, `force-poll`, `reset-cooldowns`, `stats-polling`. |
| **6 — Sync rôles ligue Discord** | Complet | `_maybe_sync_league_roles` dans `cogs/tracker.py`. |
| **7 — `seasons` + `season_results`** | Complet | Modèle `id + label` (préféré à `season_key` car migration forward-only ; même information sémantique). |
| **7 — `SeasonService` + `/historique`** | Complet | `services/season.py`, `/historique`, `/saison_historique`. |
| **8 — `MetricsCollector` + `bot_metrics_hourly`** | Complet | Flush horaire, `/bot_stats`, `services/metrics.py` (alias public). |
| **8 — Leaderboard auto canal** | Complet | Tâche 15 min, persistance `leaderboard_message_id`. |
| **9 — Tests structure prompt** | Complet | `tests/conftest.py`, `tests/unit/`, `tests/integration/`, fixtures snapshot/defense. |
| **9 — Tests logic.py** | Complet | 30+ assertions sur les chemins critiques (ligues, pace, malchance, projection). |
| **10 — Docker non-root + `migrate.py`** | Complet | `USER legendmind`, volume `./logs`, `scripts/migrate.py --apply`. |
| **11 — docs ARCHITECTURE / CONFIG / COMMANDS** | Complet | + ce document. |
| **CI — ruff / mypy strict** | Complet | `pyproject.toml` (`ruff` + `mypy strict`) ; `requirements-dev.txt` ; `mypy services cogs models` clean. |
| **Validation — tracemalloc / E2E Discord** | Manquant (à exécuter sur env. réel). |
| **Redis** | Volontairement absent | `InMemoryCache` suffit pour V3 ; interface compatible Redis pour V4. |

### Vérifications

```bash
cd coc_coach_pro
source .venv/bin/activate

PYTHONPATH=. python -c "import main"    # smoke import
PYTHONPATH=. pytest tests/ -q           # 85 passed, 1 skipped (intégration BDD)
ruff check .                            # All checks passed
mypy .                                  # Success: no issues found in 45 source files
```

### Commandes slash — inventaire

Voir `docs/COMMANDS.md`. Les noms Discord utilisent souvent `_` (ex. `/mvp_semaine`) au lieu de `-` pour compatibilité slash. Les `/admin <action>` (`set-channel`, etc.) du prompt LVL99 utilisent le tiret comme demandé.
