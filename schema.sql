-- LegendMind V3 — PostgreSQL schema
-- This file is the source of truth. Migrations under scripts/migrations/
-- apply incremental diffs; this snapshot is what a fresh install creates.

-- ─────────────────────────────────────────────────────────────────────────
-- Migration registry — applied automatically at startup.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(40)  PRIMARY KEY,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────
-- Players: one row per linked CoC account.
-- Index on discord_user_id supports the per-user dashboard lookup.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS players (
    tag                 VARCHAR(15)  PRIMARY KEY,
    discord_user_id     BIGINT       NOT NULL,
    guild_id            BIGINT,
    name                VARCHAR(64),
    current_trophies    INT          DEFAULT 0,
    current_league      SMALLINT     DEFAULT 0,
    -- Avril 2026 : tier déclaré au /setup (rank-based, plus dérivé des trophées).
    -- 'unknown' jusqu'à déclaration, puis 'legend_i' / 'legend_ii' / 'legend_iii'.
    -- (L'index associé est créé par la migration 005 pour rester safe sur
    -- les bases existantes où la colonne est ajoutée à postériori.)
    legend_tier         VARCHAR(16)  NOT NULL DEFAULT 'unknown',
    last_polled_at      TIMESTAMPTZ,
    is_active           BOOLEAN      DEFAULT TRUE,
    linked_at           TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_players_discord_user
    ON players (discord_user_id);
CREATE INDEX IF NOT EXISTS idx_players_active_polling
    ON players (is_active, last_polled_at) WHERE is_active = TRUE;

-- ─────────────────────────────────────────────────────────────────────────
-- Snapshots (Step 1): time-series of trophy + attack state per player.
-- Dedup contraint: at most one row per player per minute.
-- Latest-snapshot lookups are the hottest read path → covering index.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS player_snapshots (
    id              BIGSERIAL    PRIMARY KEY,
    player_tag      VARCHAR(15)  NOT NULL REFERENCES players(tag) ON DELETE CASCADE,
    trophies        INT          NOT NULL,
    league_type     SMALLINT     NOT NULL,
    attacks_done    SMALLINT     DEFAULT 0,
    trophies_gained INT          DEFAULT 0,
    trophies_lost   INT          DEFAULT 0,
    captured_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
-- Per-minute dedup (UTC) — `timestamptz` + `date_trunc` direct est STABLE ;
-- on tronque en `timestamp` UTC (IMMUTABLE) pour l’index unique.
CREATE UNIQUE INDEX IF NOT EXISTS uq_snapshots_player_minute
    ON player_snapshots (
        player_tag,
        date_trunc('minute', captured_at AT TIME ZONE 'UTC')
    );
-- Range scans (history graph) → DESC on captured_at.
CREATE INDEX IF NOT EXISTS idx_snapshots_player_time
    ON player_snapshots (player_tag, captured_at DESC);
-- Latest-snapshot lookup (delta computation hot path).
CREATE INDEX IF NOT EXISTS idx_snapshots_latest
    ON player_snapshots (player_tag, captured_at DESC)
    INCLUDE (trophies, attacks_done);

-- ─────────────────────────────────────────────────────────────────────────
-- User-level preferences (one row per Discord user).
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_preferences (
    discord_user_id        BIGINT      PRIMARY KEY,
    enable_error_notebook  BOOLEAN     DEFAULT FALSE,
    enable_alerts          BOOLEAN     DEFAULT TRUE,
    quiet_hours_start      SMALLINT,
    quiet_hours_end        SMALLINT,
    language               VARCHAR(5)  DEFAULT 'fr',
    alert_on_defense       BOOLEAN     NOT NULL DEFAULT TRUE,
    digest_daily_enabled   BOOLEAN     NOT NULL DEFAULT FALSE,
    digest_hour_utc        SMALLINT    NOT NULL DEFAULT 9,
    digest_last_sent_on    DATE,
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────
-- Goals: user-defined season targets.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS league_goals (
    player_tag              VARCHAR(15)  PRIMARY KEY REFERENCES players(tag) ON DELETE CASCADE,
    target_trophies         INT          NOT NULL,
    target_attacks_per_day  SMALLINT     NOT NULL DEFAULT 8,
    notes                   TEXT         DEFAULT '',
    updated_at              TIMESTAMPTZ  DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────
-- Carnet d'Erreurs (Step 2): one row per defense event with malchance score.
-- Two indexes: per-player chronological (recent listing) and per-player by
-- malchance DESC (worst-defense lookup for weekly report).
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS defense_log (
    id                BIGSERIAL    PRIMARY KEY,
    player_tag        VARCHAR(15)  NOT NULL REFERENCES players(tag) ON DELETE CASCADE,
    trophies_lost     INT          NOT NULL,
    opponent_tag      VARCHAR(15),
    opponent_trophies INT,
    attack_count      SMALLINT     DEFAULT 1,
    malchance_score   REAL         DEFAULT 0,
    league_type       SMALLINT     NOT NULL,
    season_week       SMALLINT,
    logged_at         TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_defense_log_player
    ON defense_log (player_tag, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_defense_log_malchance
    ON defense_log (player_tag, malchance_score DESC);

-- ─────────────────────────────────────────────────────────────────────────
-- Alert history (Step 3): every alert sent, used for cooldown deduplication.
-- The cooldown query reads (player_tag, alert_type, sent_at DESC) — this is
-- the index covering it.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_history (
    id              BIGSERIAL    PRIMARY KEY,
    player_tag      VARCHAR(15)  NOT NULL REFERENCES players(tag) ON DELETE CASCADE,
    alert_type      VARCHAR(30)  NOT NULL,
    discord_user_id BIGINT       NOT NULL,
    message_preview VARCHAR(200),
    sent_at         TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_history_cooldown
    ON alert_history (player_tag, alert_type, sent_at DESC);

-- ─────────────────────────────────────────────────────────────────────────
-- Guild config (Step 5–6): per-Discord-server settings for leaderboard.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id                  BIGINT       PRIMARY KEY,
    leaderboard_limit         SMALLINT     NOT NULL DEFAULT 15,
    leaderboard_public        BOOLEAN      NOT NULL DEFAULT TRUE,
    leaderboard_legend_only   BOOLEAN      NOT NULL DEFAULT TRUE,
    alerts_channel_id         BIGINT,
    leaderboard_channel_id    BIGINT,
    leaderboard_message_id    BIGINT,
    admin_role_id             BIGINT,
    language                  VARCHAR(5)   DEFAULT 'fr',
    timezone                  VARCHAR(50)  DEFAULT 'UTC',
    legend_role_i_id          BIGINT,
    legend_role_ii_id         BIGINT,
    legend_role_iii_id        BIGINT,
    created_at                TIMESTAMPTZ  DEFAULT NOW(),
    updated_at                TIMESTAMPTZ  DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────
-- Seasons (Step 7): one open row (period_end IS NULL) — enforced below.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS seasons (
    id              BIGSERIAL    PRIMARY KEY,
    label           VARCHAR(40)  NOT NULL,
    period_start    TIMESTAMPTZ  NOT NULL,
    period_end      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);
-- Une seule saison ouverte : index constant sous filtre (IMMUTABLE).
CREATE UNIQUE INDEX IF NOT EXISTS uq_seasons_single_open
    ON seasons ((1))
    WHERE period_end IS NULL;

CREATE TABLE IF NOT EXISTS season_results (
    id              BIGSERIAL    PRIMARY KEY,
    season_id       BIGINT       NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    guild_id        BIGINT       NOT NULL,
    player_tag      VARCHAR(15)  NOT NULL REFERENCES players(tag) ON DELETE CASCADE,
    final_trophies  INT          NOT NULL,
    league_type     SMALLINT     NOT NULL,
    guild_rank      SMALLINT,
    net_trophies    INT          NOT NULL DEFAULT 0,
    UNIQUE (season_id, player_tag)
);
CREATE INDEX IF NOT EXISTS idx_season_results_lookup
    ON season_results (season_id, guild_id, guild_rank);

-- ─────────────────────────────────────────────────────────────────────────
-- Metrics (Step 8): hourly rollups per player for charts / pace analytics.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metrics_hourly (
    player_tag          VARCHAR(15)  NOT NULL REFERENCES players(tag) ON DELETE CASCADE,
    bucket_start        TIMESTAMPTZ  NOT NULL,
    net_trophies_delta  INT          NOT NULL DEFAULT 0,
    attacks_delta       INT          NOT NULL DEFAULT 0,
    snapshot_count      INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (player_tag, bucket_start)
);
CREATE INDEX IF NOT EXISTS idx_metrics_hourly_time
    ON metrics_hourly (bucket_start DESC);

-- Agrégats bot (observabilité prompt §8) — une ligne globale par heure UTC.
CREATE TABLE IF NOT EXISTS bot_metrics_hourly (
    hour_bucket      TIMESTAMPTZ  NOT NULL PRIMARY KEY,
    polls_total      INT          NOT NULL DEFAULT 0,
    errors_total     INT          NOT NULL DEFAULT 0,
    alerts_sent      INT          NOT NULL DEFAULT 0,
    avg_latency_ms   REAL         NOT NULL DEFAULT 0,
    p95_latency_ms   REAL         NOT NULL DEFAULT 0
);

-- ─────────────────────────────────────────────────────────────────────────
-- Billing (Stripe) + per-user monthly quotas (Free vs Premium).
-- One row per Discord user; trial_used guards against re-claiming the 7-day
-- trial. `current_period_end` is the source of truth for "is the user in
-- premium right now?" — checked by `BillingService.is_entitled`.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    discord_user_id        BIGINT       PRIMARY KEY,
    plan                   VARCHAR(16)  NOT NULL DEFAULT 'free',
    status                 VARCHAR(20)  NOT NULL DEFAULT 'inactive',
    trial_used             BOOLEAN      NOT NULL DEFAULT FALSE,
    trial_started_at       TIMESTAMPTZ,
    current_period_end     TIMESTAMPTZ,
    stripe_customer_id     VARCHAR(64),
    stripe_subscription_id VARCHAR(64),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_period_end
    ON subscriptions (current_period_end);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer
    ON subscriptions (stripe_customer_id);

-- Per-month counter for the 50 ping/mois quota. `year_month` is the calendar
-- bucket 'YYYY-MM' (UTC). `warned_full` ensures we only DM the upsell once
-- per bucket when the user runs out.
CREATE TABLE IF NOT EXISTS ping_quota (
    discord_user_id  BIGINT       NOT NULL,
    year_month       CHAR(7)      NOT NULL,
    used             INT          NOT NULL DEFAULT 0,
    warned_full      BOOLEAN      NOT NULL DEFAULT FALSE,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (discord_user_id, year_month)
);
