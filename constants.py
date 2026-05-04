"""LegendMind V3 — central constants.

All business-domain magic numbers, table names, league thresholds, colors,
and standard messages live here. Never inline these values elsewhere.

Sources annotated per constant; refresh when CoC patch notes change.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final


# ─────────────────────────────────────────────────────────────────────────────
# Legend tier definitions (Avril 2026 — refonte Ranked Mode Supercell).
#
# IMPORTANT — Le tier n'est PLUS dérivé des trophées. Supercell définit
# désormais les tiers Legend I/II/III par RANG :
#   * Legend I   : top 12 500 mondiaux (8 batailles/jour, tournoi 4 semaines)
#   * Legend II  : rangs 12 501–62 500 (30 batailles/semaine)
#   * Legend III : reste des Legend (24 batailles/semaine)
#
# L'API publique CoC n'expose ``currentSeason.rank`` QUE pour le top 200
# mondial → on ne peut pas auto-détecter le tier de façon fiable. La source
# de vérité est ``players.legend_tier`` (déclaré au /setup, modifiable via
# /tier). L'enum ci-dessous garde les mêmes valeurs SMALLINT pour
# compatibilité avec les snapshots existants (rétro-actifs).
# ─────────────────────────────────────────────────────────────────────────────
class LeagueType(IntEnum):
    """Numeric identifier for each Legend tier (stored in BDD as SMALLINT).

    Avril 2026 : sémantique TIER (rank-based) — non dérivée des trophées.
    """

    UNKNOWN = 0
    LEGEND_III = 1
    LEGEND_II = 2
    LEGEND_I = 3


# Trophy thresholds (lower bound of each league).
# Source: CoC matchmaking rules, Legend ranking system.
# AVRIL 2026 : ces seuils sont conservés UNIQUEMENT pour l'affichage trophy
# (barres de progression, embeds /dashboard) — ils ne définissent plus le
# tier officiel. Un joueur Legend III peut être au-dessus de 6000 trophées
# (et inversement) selon son rang mondial.
LEAGUE_LOWER_BOUND: Final[dict[LeagueType, int]] = {
    LeagueType.LEGEND_III: 5000,
    LeagueType.LEGEND_II: 5500,
    LeagueType.LEGEND_I: 6000,
}

# Cap rank au-delà duquel l'API CoC cesse de renvoyer un rang utile.
# Source : CoC API docs (top 200 location/global leaderboard uniquement).
COC_API_RANK_CUTOFF: Final[int] = 200

# Quotas de batailles par tier (Avril 2026 update).
LEGEND_I_DAILY_BATTLES: Final[int] = 8  # daily quota
LEGEND_II_WEEKLY_BATTLES: Final[int] = 30  # weekly tournament
LEGEND_III_WEEKLY_BATTLES: Final[int] = 24  # weekly tournament

# Format du tournoi : 4 semaines pour Legend I, hebdomadaire pour II/III.
LEGEND_I_TOURNAMENT_WEEKS: Final[int] = 4
LEGEND_II_III_TOURNAMENT_WEEKS: Final[int] = 1

# Polling cadence par tier (en secondes). Legend II/III joue moins souvent ;
# inutile de marteler l'API toutes les 3 minutes pour eux.
POLL_INTERVAL_LEGEND_I_SECONDS: Final[int] = 180
POLL_INTERVAL_LEGEND_II_III_SECONDS: Final[int] = 1800

# Recap hebdo Legend II/III : envoyé chaque DIMANCHE à 22h UTC
# (juste avant le reset hebdo Supercell, qui tombe en début de semaine).
WEEKLY_RECAP_DAY_OF_WEEK: Final[int] = 6  # 0=lundi, 6=dimanche
WEEKLY_RECAP_HOUR_UTC: Final[int] = 22

# Recap attaques faibles Legend I : envoyé chaque LUNDI matin.
# Résume la semaine écoulée (lun–dim) : jours où le gain moyen < seuil,
# patterns détectés, conseils ciblés.
ATTACK_RECAP_DAY_OF_WEEK: Final[int] = 0  # lundi
ATTACK_RECAP_HOUR_UTC: Final[int] = 9     # 9h UTC ≈ 11h Paris (CEST)
ATTACK_RECAP_ALERT_KEY: Final[str] = "attack_weekly_recap"  # cooldown dedup

# Digest automatique (/daily + /predict + /score) — un DM par jour et par user.
DIGEST_POLL_INTERVAL_SECONDS: Final[int] = 300
DIGEST_DEFAULT_HOUR_UTC: Final[int] = 9

# Distance to next league cutoff that triggers a "promotion possible" alert.
PROMOTION_PROXIMITY_TROPHIES: Final[int] = 50

# Distance below current league's lower bound that triggers
# a "relegation imminent" alert.
RELEGATION_PROXIMITY_TROPHIES: Final[int] = 60


# ─────────────────────────────────────────────────────────────────────────────
# Daily attack quota (Legend I only — source: live attack mechanic)
# Legend II/III use weekly aggregates; per-day tracking is informational.
# ─────────────────────────────────────────────────────────────────────────────
LEGEND_I_DAILY_ATTACK_QUOTA: Final[int] = LEGEND_I_DAILY_BATTLES
LEGEND_I_PACE_WARNING_REMAINING: Final[int] = 4  # < 4 attacks left → warning
LEGEND_I_PACE_CRITICAL_REMAINING: Final[int] = 2  # < 2 attacks left → critical

# Legend League daily reset hour (UTC).
# Défaut ~19h Europe/Paris en heure d'été (CEST = UTC+2 → 17h UTC).
# Ajuster si besoin (hiver CET = UTC+1 → 18h UTC pour 19h Paris) ou via GAME_TUNING_URL.
LEGEND_DAILY_RESET_HOUR_UTC: Final[int] = 17


# ─────────────────────────────────────────────────────────────────────────────
# Malchance (bad-luck) scoring
# Internal heuristic: blends trophies-lost-per-defense, opponent strength gap,
# and multi-attack pile-on. Range [0.0, 1.0]; values >0.7 = high bad luck.
# ─────────────────────────────────────────────────────────────────────────────
MALCHANCE_HIGH_THRESHOLD: Final[float] = 0.70
MALCHANCE_TROPHY_LOSS_NORMAL: Final[int] = 32  # typical defense loss
MALCHANCE_OPPONENT_GAP_TOLERANCE: Final[int] = 200  # trophies above defender


# ─────────────────────────────────────────────────────────────────────────────
# Polling / API
# ─────────────────────────────────────────────────────────────────────────────
POLL_BACKOFF_BASE_SECONDS: Final[float] = 2.0
POLL_BACKOFF_MAX_SECONDS: Final[float] = 300.0
POLL_BACKOFF_MULTIPLIER: Final[float] = 2.0
POLL_BACKOFF_JITTER: Final[float] = 0.25

API_TIMEOUT_SECONDS: Final[float] = 15.0
API_RETRY_MAX_ATTEMPTS: Final[int] = 4


# ─────────────────────────────────────────────────────────────────────────────
# Pace / prediction
# ─────────────────────────────────────────────────────────────────────────────
PACE_REGRESSION_MIN_SAMPLES: Final[int] = 5
PACE_PROJECTION_WINDOW_DAYS: Final[int] = 3


# ─────────────────────────────────────────────────────────────────────────────
# Alerts — per-type cooldown (seconds). Anti-spam window between identical
# (player_tag, alert_type) messages. Tuned by signal volatility:
# - Streaks change fast → short cooldown.
# - Relegation/promotion are sticky → long cooldown.
# ─────────────────────────────────────────────────────────────────────────────
ALERT_COOLDOWN_SECONDS: Final[dict[str, int]] = {
    "relegation_imminent": 3 * 3600,
    "promotion_possible": 3 * 3600,
    "pace_critical": 2 * 3600,
    "pace_warning": 4 * 3600,
    "streak_positive": 6 * 3600,
    "streak_negative": 6 * 3600,
    "season_best_broken": 12 * 3600,
    "daily_goal_reached": 20 * 3600,
    "comeback_detected": 12 * 3600,
    # Per-defense push: short cooldown to allow back-to-back defenses to fire
    # individually, but long enough to absorb double-poll edge cases.
    "defense_taken": 60,
    # Low-gain attack: 3 min cooldown — chaque attaque faible reçoit un DM
    # sans spam (le poller ne revient pas avant ~3 min de toute façon).
    "attack_low_gain": 180,
}

# Streak detection: number of consecutive events of the same sign required.
ALERT_STREAK_LENGTH: Final[int] = 3

# Comeback alert: minimum positive net trophies over 24h.
ALERT_COMEBACK_DELTA: Final[int] = 200

# ─────────────────────────────────────────────────────────────────────────────
# Low-gain attack analysis
# Fires when a new attack batch averages < ATTACK_WEAK_GAIN_THRESHOLD trophies.
# Threshold of 40 = below the median win in Legend I (typical gain ≈ 32–44).
# Source: community data, Supercell Legend trophy formula.
# ─────────────────────────────────────────────────────────────────────────────
ATTACK_WEAK_GAIN_THRESHOLD: Final[int] = 40   # trophies per attack (avg)
ATTACK_WEAK_MIN_ATTACKS: Final[int] = 1       # min new attacks to evaluate

# Quiet hours: alerts during a user's quiet window are suppressed entirely.
# (cooldown still consumes the slot to avoid a flood when the window ends.)


# ─────────────────────────────────────────────────────────────────────────────
# Discord
# ─────────────────────────────────────────────────────────────────────────────
COLOR_DANGER: Final[int] = 0xE74C3C
COLOR_WARNING: Final[int] = 0xF39C12
COLOR_SUCCESS: Final[int] = 0x2ECC71
COLOR_INFO: Final[int] = 0x3498DB
COLOR_NEUTRAL: Final[int] = 0x95A5A6

EMBED_TITLE_DASHBOARD: Final[str] = "🏆 LegendMind — Tableau de bord"
EMBED_TITLE_NOTEBOOK: Final[str] = "📓 Carnet d'Erreurs"
EMBED_TITLE_LEADERBOARD: Final[str] = "🏅 Classement LegendMind"
EMBED_TITLE_SEASON: Final[str] = "📅 Saison Legend"
EMBED_TITLE_METRICS: Final[str] = "📊 Métriques (fenêtre horaire)"


# ─────────────────────────────────────────────────────────────────────────────
# Database table names (single source of truth for all SQL strings)
# ─────────────────────────────────────────────────────────────────────────────
TBL_PLAYERS: Final[str] = "players"
TBL_PLAYER_SNAPSHOTS: Final[str] = "player_snapshots"
TBL_DEFENSE_LOG: Final[str] = "defense_log"
TBL_ALERT_HISTORY: Final[str] = "alert_history"
TBL_GUILD_CONFIG: Final[str] = "guild_config"
TBL_USER_PREFERENCES: Final[str] = "user_preferences"
TBL_LEAGUE_GOALS: Final[str] = "league_goals"
TBL_SEASONS: Final[str] = "seasons"
TBL_SEASON_RESULTS: Final[str] = "season_results"
TBL_METRICS_HOURLY: Final[str] = "metrics_hourly"
TBL_BOT_METRICS_HOURLY: Final[str] = "bot_metrics_hourly"
TBL_SUBSCRIPTIONS: Final[str] = "subscriptions"
TBL_PING_QUOTA: Final[str] = "ping_quota"
TBL_SCHEMA_MIGRATIONS: Final[str] = "schema_migrations"


# ─────────────────────────────────────────────────────────────────────────────
# Billing / quotas
# Source de vérité pour les commandes /setup, /premium, /ping, /accounts.
# ─────────────────────────────────────────────────────────────────────────────
# CoC Legend League canonical id (single league CoC-side; we sub-tier locally
# via LeagueType III/II/I based on trophy thresholds).
#
# Note (May 2026): Supercell's league id has been observed as 105000036 via the
# CoC API. We still keep the name-based fallback in /setup for robustness.
COC_LEGEND_LEAGUE_ID: Final[int] = 105000036

# Durée d'essai par défaut (première liaison /setup ou /premium hors serveur listé).
# Serveurs avec essai prolongé : EXTENDED_TRIAL_GUILD_IDS + EXTENDED_TRIAL_DAYS (config).
PREMIUM_TRIAL_DAYS: Final[int] = 7

# Libellé affiché dans Discord. Le montant facturé est celui du Price Stripe
# (``STRIPE_PRICE_ID_MONTHLY``) — doit correspondre dans le Dashboard Stripe.
PREMIUM_MONTHLY_PRICE_EUR_DISPLAY: Final[str] = "2,99 €"

# Quota mensuel de DM "défense subie" pour les comptes Free.
PING_QUOTA_FREE_MONTHLY: Final[int] = 50

# Limites de comptes CoC liés.
MAX_LINKED_ACCOUNTS_FREE: Final[int] = 1
MAX_LINKED_ACCOUNTS_PREMIUM: Final[int] = 3

# Top-N mondial servi par l'API CoC. L'identifiant de "location" pour
# le classement global est la chaîne littérale "global" (l'API attend
# /locations/global/rankings/players, pas un integer). Les autres
# valeurs sont des codes pays (ex. 32000087 = France).
COC_GLOBAL_LOCATION_ID: Final[str] = "global"
WORLD_TOP_LEADERBOARD_SIZE: Final[int] = 200

# ─────────────────────────────────────────────────────────────────────────────
# RankPredictor — log-linear regression on the global leaderboard.
# ─────────────────────────────────────────────────────────────────────────────
# Population mondiale Legend (estimation Avril 2026) :
#   Legend I  ≈ 12 500   (top mondial)
#   Legend II ≈ 50 000   (rangs 12 501 – 62 500)
#   Legend III ≈ ~200 000 (reste, varie selon la saison)
# Sert de borne haute quand un joueur a des trophées TRÈS en dessous du
# leaderboard mesurable — on le clamp à cette estimation pour éviter de
# renvoyer des rangs absurdes.
LEGEND_TOTAL_PLAYERS_ESTIMATE: Final[int] = 250_000

# Fréquence de refresh du leaderboard mondial (en secondes). Le top 200
# bouge lentement, 10 min suffisent largement et ménagent les quotas API.
RANK_CACHE_TTL_SECONDS: Final[int] = 600

# Nombre minimum de points pour ajuster la courbe de régression. En
# dessous on garde la courbe précédente plutôt que d'en construire une
# trop bruitée.
RANK_MIN_SAMPLES: Final[int] = 20


# ─────────────────────────────────────────────────────────────────────────────
# Standard error messages (user-facing, French)
# ─────────────────────────────────────────────────────────────────────────────
ERR_PLAYER_NOT_FOUND: Final[str] = "Joueur introuvable. Vérifie le tag."
ERR_NOT_LINKED: Final[str] = "Aucun compte CoC lié. Utilise `/lier <#TAG>` d'abord."
ERR_API_UNAVAILABLE: Final[str] = "L'API CoC est indisponible. Réessaie dans quelques instants."
ERR_PERMISSION_DENIED: Final[str] = "Tu n'as pas la permission requise."
