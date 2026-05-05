"""Database layer — asyncpg pool wrapper + typed Repository.

Architecture:
- `Database` owns the pool lifecycle (connect/close) and applies migrations.
- `Repository` exposes typed CRUD methods over domain models. Cogs and
  other services *must* go through `Repository`; raw SQL outside this
  module is a code smell.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg

from constants import (
    TBL_ALERT_HISTORY,
    TBL_BOT_METRICS_HOURLY,
    TBL_DEFENSE_LOG,
    TBL_GUILD_CONFIG,
    TBL_LEAGUE_GOALS,
    TBL_METRICS_HOURLY,
    TBL_PING_QUOTA,
    TBL_PLAYER_SNAPSHOTS,
    TBL_PLAYERS,
    TBL_SCHEMA_MIGRATIONS,
    TBL_SEASON_RESULTS,
    TBL_SEASONS,
    TBL_SUBSCRIPTIONS,
    TBL_USER_PREFERENCES,
    LeagueType,
)
from models import (
    AttackDelta,
    DefenseLog,
    GuildConfig,
    LeaderboardEntry,
    LegendSnapshot,
    MetricsHourlyRow,
    PingQuotaState,
    PlayerGoal,
    PollTarget,
    SeasonHistoryEntry,
    SeasonRecord,
    SeasonResultRow,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    UserPreferences,
)
from services.logic import utc_hour_floor

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Migrations — minimal forward-only registry.
# Each migration has an immutable version string and SQL body. Applied in
# alphabetical order; recorded in `schema_migrations` so reruns are no-ops.
# ─────────────────────────────────────────────────────────────────────────────
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    (
        "002_guild_and_bot_metrics",
        """
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS leaderboard_channel_id BIGINT;
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS leaderboard_message_id BIGINT;
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS admin_role_id BIGINT;
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS language VARCHAR(5) DEFAULT 'fr';
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS timezone VARCHAR(50) DEFAULT 'UTC';
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS legend_role_i_id BIGINT;
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS legend_role_ii_id BIGINT;
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS legend_role_iii_id BIGINT;
        ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
            DEFAULT NOW();
        CREATE TABLE IF NOT EXISTS bot_metrics_hourly (
            hour_bucket      TIMESTAMPTZ  NOT NULL PRIMARY KEY,
            polls_total      INT          NOT NULL DEFAULT 0,
            errors_total     INT          NOT NULL DEFAULT 0,
            alerts_sent      INT          NOT NULL DEFAULT 0,
            avg_latency_ms   REAL         NOT NULL DEFAULT 0,
            p95_latency_ms   REAL         NOT NULL DEFAULT 0
        );
        """,
    ),
    (
        "003_user_alert_on_defense",
        """
        ALTER TABLE user_preferences
            ADD COLUMN IF NOT EXISTS alert_on_defense BOOLEAN NOT NULL DEFAULT TRUE;
        """,
    ),
    (
        "004_billing_and_quota",
        """
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

        CREATE TABLE IF NOT EXISTS ping_quota (
            discord_user_id  BIGINT       NOT NULL,
            year_month       CHAR(7)      NOT NULL,
            used             INT          NOT NULL DEFAULT 0,
            warned_full      BOOLEAN      NOT NULL DEFAULT FALSE,
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (discord_user_id, year_month)
        );
        """,
    ),
    (
        "005_players_legend_tier",
        """
        ALTER TABLE players
            ADD COLUMN IF NOT EXISTS legend_tier VARCHAR(16) NOT NULL
                DEFAULT 'unknown';
        CREATE INDEX IF NOT EXISTS idx_players_legend_tier
            ON players (legend_tier) WHERE is_active = TRUE;
        """,
    ),
    (
        "006_user_preferences_digest",
        """
        ALTER TABLE user_preferences
            ADD COLUMN IF NOT EXISTS digest_daily_enabled BOOLEAN NOT NULL
                DEFAULT FALSE;
        ALTER TABLE user_preferences
            ADD COLUMN IF NOT EXISTS digest_hour_utc SMALLINT NOT NULL DEFAULT 9;
        ALTER TABLE user_preferences
            ADD COLUMN IF NOT EXISTS digest_last_sent_on DATE;
        """,
    ),
    (
        "007_players_verified_and_clan",
        """
        -- Account ownership verification via CoC in-game token.
        ALTER TABLE players
            ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE players
            ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

        -- Clan info — refreshed each poll cycle, never NULL after first poll.
        ALTER TABLE players
            ADD COLUMN IF NOT EXISTS clan_tag VARCHAR(15);
        ALTER TABLE players
            ADD COLUMN IF NOT EXISTS clan_name VARCHAR(64);

        -- Official season history cache — one row per (player_tag, season_id).
        CREATE TABLE IF NOT EXISTS season_api_history (
            player_tag   VARCHAR(15)  NOT NULL REFERENCES players(tag)
                         ON DELETE CASCADE,
            season_id    VARCHAR(10)  NOT NULL,   -- ex. "2026-04"
            final_rank   INT,                     -- rank in top-200 if available
            trophies     INT          NOT NULL,
            fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (player_tag, season_id)
        );
        CREATE INDEX IF NOT EXISTS idx_season_api_history_player
            ON season_api_history (player_tag, season_id DESC);
        """,
    ),
    (
        "008_attack_feedback",
        """
        -- Feedback joueur sur les attaques faibles (< 40 tr. de gain moyen).
        -- Rempli via les boutons Discord envoyés dans le DM ATTACK_LOW_GAIN.
        -- Aggrégé le lundi matin pour le recap hebdo d'amélioration.
        CREATE TABLE IF NOT EXISTS attack_feedback (
            id              BIGSERIAL    PRIMARY KEY,
            player_tag      VARCHAR(15)  NOT NULL REFERENCES players(tag)
                            ON DELETE CASCADE,
            discord_user_id BIGINT       NOT NULL,
            -- Trophées gagnés sur ce batch d'attaques (peut être 0).
            trophies_gained INT          NOT NULL DEFAULT 0,
            -- Nombre d'attaques du batch.
            n_attacks       SMALLINT     NOT NULL DEFAULT 1,
            -- Catégorie sélectionnée par le joueur :
            --   'timing'    = fail de timing (trop tôt/tard)
            --   'funnel'    = funnel raté (armée mal orientée)
            --   'execution' = erreur d'exécution (sorts, drops)
            --   'other'     = autre / inconnu
            --   'false_pos' = l'attaque était en réalité correcte
            feedback        VARCHAR(12)  NOT NULL DEFAULT 'other',
            -- Message Discord associé (pour éviter les double-clics).
            discord_message_id BIGINT,
            logged_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_attack_feedback_player
            ON attack_feedback (player_tag, logged_at DESC);
        CREATE INDEX IF NOT EXISTS idx_attack_feedback_week
            ON attack_feedback (player_tag, logged_at DESC, feedback);
        """,
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Pool wrapper
# ─────────────────────────────────────────────────────────────────────────────
class Database:
    """Owns the asyncpg pool and bootstraps the schema."""

    def __init__(self, dsn: str, *, ssl: bool = False) -> None:
        self._dsn = dsn
        self._ssl = ssl
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() not called")
        return self._pool

    async def connect(self) -> None:
        """Open the pool and apply pending migrations."""
        kwargs: dict[str, object] = {
            "min_size": 2,
            "max_size": 10,
            "command_timeout": 30.0,
        }
        if self._ssl:
            kwargs["ssl"] = True
        self._pool = await asyncpg.create_pool(self._dsn, **kwargs)
        await self._bootstrap_schema()
        await self._apply_migrations()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _bootstrap_schema(self) -> None:
        """Apply schema.sql idempotently. Safe on every boot."""
        schema_path = Path(__file__).parent.parent / "schema.sql"
        if not schema_path.exists():
            log.warning("schema.sql not found at %s", schema_path)
            return
        sql = schema_path.read_text(encoding="utf-8")
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    async def _apply_migrations(self) -> None:
        async with self.pool.acquire() as conn:
            applied = {
                r["version"]
                for r in await conn.fetch(f"SELECT version FROM {TBL_SCHEMA_MIGRATIONS}")
            }
            for version, body in _MIGRATIONS:
                if version in applied:
                    continue
                log.info("Applying migration %s", version)
                async with conn.transaction():
                    await conn.execute(body)
                    await conn.execute(
                        f"INSERT INTO {TBL_SCHEMA_MIGRATIONS}(version) VALUES($1)",
                        version,
                    )


# ─────────────────────────────────────────────────────────────────────────────
# Repository — typed CRUD facade.
# ─────────────────────────────────────────────────────────────────────────────
class Repository:
    """Typed access layer. All persistence goes through here."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── players ───────────────────────────────────────────────────────────
    async def link_player(
        self,
        tag: str,
        discord_user_id: int,
        guild_id: int | None,
        name: str | None,
    ) -> None:
        """Create or refresh the linkage between a CoC tag and a Discord user.

        ``legend_tier`` is left untouched on conflict (declared via /setup
        Select afterwards or updated via /tier).
        """
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_PLAYERS}
                (tag, discord_user_id, guild_id, name, is_active)
            VALUES ($1, $2, $3, $4, TRUE)
            ON CONFLICT (tag) DO UPDATE SET
                discord_user_id = EXCLUDED.discord_user_id,
                guild_id        = EXCLUDED.guild_id,
                name            = COALESCE(EXCLUDED.name, {TBL_PLAYERS}.name),
                is_active       = TRUE
            """,
            tag,
            discord_user_id,
            guild_id,
            name,
        )

    async def set_legend_tier(self, tag: str, tier: LeagueType) -> None:
        """Persist the user-declared Legend tier for an active tag.

        Stored as canonical lowercase string ('legend_i'/'legend_ii'/
        'legend_iii'/'unknown') in ``players.legend_tier``.
        """
        await self._db.pool.execute(
            f"UPDATE {TBL_PLAYERS} SET legend_tier=$1 WHERE tag=$2",
            _tier_to_db(tier),
            tag,
        )

    async def get_legend_tier(self, tag: str) -> LeagueType:
        """Return the declared tier or ``UNKNOWN`` if never set."""
        row = await self._db.pool.fetchrow(
            f"SELECT legend_tier FROM {TBL_PLAYERS} WHERE tag=$1",
            tag,
        )
        if row is None:
            return LeagueType.UNKNOWN
        return _tier_from_db(row["legend_tier"])

    async def get_active_players_for_polling(self) -> list[PollTarget]:
        """Lightweight projection feeding the polling queue.

        Includes ``legend_tier`` so the tracker can route Legend I (fast)
        vs Legend II/III (slow) without an extra round-trip per target.
        """
        rows = await self._db.pool.fetch(
            f"""
            SELECT tag, discord_user_id, guild_id, last_polled_at,
                   COALESCE(legend_tier, 'unknown') AS legend_tier
            FROM {TBL_PLAYERS}
            WHERE is_active = TRUE
            ORDER BY last_polled_at NULLS FIRST
            """
        )
        return [
            PollTarget(
                player_tag=r["tag"],
                discord_user_id=r["discord_user_id"],
                guild_id=r["guild_id"],
                last_polled_at=r["last_polled_at"],
                legend_tier=_tier_from_db(r["legend_tier"]),
            )
            for r in rows
        ]

    async def mark_polled(self, tag: str, when: datetime) -> None:
        await self._db.pool.execute(
            f"UPDATE {TBL_PLAYERS} SET last_polled_at=$1 WHERE tag=$2",
            when,
            tag,
        )

    async def update_clan_info(
        self,
        tag: str,
        clan_tag: str | None,
        clan_name: str | None,
    ) -> None:
        """Refresh the cached clan tag + name for a player (called each poll)."""
        await self._db.pool.execute(
            f"""
            UPDATE {TBL_PLAYERS}
            SET clan_tag=$1, clan_name=$2
            WHERE tag=$3
            """,
            clan_tag,
            clan_name,
            tag,
        )

    async def set_verified(self, tag: str) -> None:
        """Mark a player as ownership-verified via CoC in-game token."""
        await self._db.pool.execute(
            f"""
            UPDATE {TBL_PLAYERS}
            SET verified=TRUE, verified_at=NOW()
            WHERE tag=$1
            """,
            tag,
        )

    async def get_player_row(self, tag: str) -> dict[str, object] | None:
        """Return raw player row including verified, clan_tag, clan_name."""
        row = await self._db.pool.fetchrow(
            f"SELECT * FROM {TBL_PLAYERS} WHERE tag=$1",
            tag,
        )
        return dict(row) if row else None

    # ── attack feedback ────────────��─────────────────────────────────────
    async def insert_attack_feedback(
        self,
        player_tag: str,
        discord_user_id: int,
        trophies_gained: int,
        n_attacks: int,
        feedback: str,
        discord_message_id: int | None = None,
    ) -> int:
        """Persist a player's self-reported reason for a weak attack."""
        row = await self._db.pool.fetchrow(
            """
            INSERT INTO attack_feedback
                (player_tag, discord_user_id, trophies_gained, n_attacks,
                 feedback, discord_message_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            player_tag, discord_user_id, trophies_gained, n_attacks,
            feedback, discord_message_id,
        )
        return int(row["id"])

    async def get_attack_feedback_since(
        self, player_tag: str, since: datetime,
    ) -> list[dict[str, object]]:
        """All feedback rows for a player since `since` (for weekly recap)."""
        rows = await self._db.pool.fetch(
            """
            SELECT id, player_tag, discord_user_id, trophies_gained,
                   n_attacks, feedback, logged_at
            FROM attack_feedback
            WHERE player_tag = $1 AND logged_at >= $2
            ORDER BY logged_at DESC
            """,
            player_tag, since,
        )
        return [dict(r) for r in rows]

    async def has_attack_recap_been_sent_this_week(
        self, player_tag: str, week_start: datetime,
    ) -> bool:
        """True if the Monday recap was already dispatched this week."""
        row = await self._db.pool.fetchrow(
            """
            SELECT sent_at FROM alert_history
            WHERE player_tag = $1
              AND alert_type = 'attack_weekly_recap'
              AND sent_at >= $2
            LIMIT 1
            """,
            player_tag, week_start,
        )
        return row is not None

    # ── official season history (CoC API /leagues/.../seasons/...) ────────
    async def upsert_season_api_entry(
        self,
        player_tag: str,
        season_id: str,
        trophies: int,
        final_rank: int | None,
    ) -> None:
        await self._db.pool.execute(
            """
            INSERT INTO season_api_history
                (player_tag, season_id, trophies, final_rank, fetched_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (player_tag, season_id) DO UPDATE SET
                trophies   = EXCLUDED.trophies,
                final_rank = EXCLUDED.final_rank,
                fetched_at = NOW()
            """,
            player_tag,
            season_id,
            trophies,
            final_rank,
        )

    async def get_season_api_history(
        self,
        tag: str,
        limit: int = 12,
    ) -> list[dict[str, object]]:
        rows = await self._db.pool.fetch(
            """
            SELECT season_id, trophies, final_rank, fetched_at
            FROM season_api_history
            WHERE player_tag = $1
            ORDER BY season_id DESC
            LIMIT $2
            """,
            tag,
            limit,
        )
        return [dict(r) for r in rows]

    async def get_owner_id_for_tag(self, tag: str) -> int | None:
        """Return the Discord user id who linked `tag`, or None if unknown."""
        row = await self._db.pool.fetchrow(
            f"SELECT discord_user_id FROM {TBL_PLAYERS} WHERE tag = $1",
            tag,
        )
        return int(row["discord_user_id"]) if row else None

    async def get_first_active_tag(self, discord_user_id: int) -> str | None:
        row = await self._db.pool.fetchrow(
            f"""
            SELECT tag FROM {TBL_PLAYERS}
            WHERE discord_user_id = $1 AND is_active = TRUE
            LIMIT 1
            """,
            discord_user_id,
        )
        return row["tag"] if row else None

    async def list_active_tags(self, discord_user_id: int) -> list[str]:
        """All tags currently linked + active for this Discord user.

        Used by ``/accounts`` and the multi-account limit enforcement at
        ``/setup`` time. Order: insertion order (oldest first).
        """
        rows = await self._db.pool.fetch(
            f"""
            SELECT tag FROM {TBL_PLAYERS}
            WHERE discord_user_id = $1 AND is_active = TRUE
            ORDER BY linked_at ASC NULLS LAST, tag ASC
            """,
            discord_user_id,
        )
        return [r["tag"] for r in rows]

    async def list_active_accounts(
        self,
        discord_user_id: int,
    ) -> list[tuple[str, str | None, LeagueType]]:
        """Active accounts with their declared tier for the /accounts UI.

        Returns ``(tag, name, tier)`` tuples ordered by ``linked_at``.
        """
        rows = await self._db.pool.fetch(
            f"""
            SELECT tag, name, COALESCE(legend_tier, 'unknown') AS legend_tier
            FROM {TBL_PLAYERS}
            WHERE discord_user_id = $1 AND is_active = TRUE
            ORDER BY linked_at ASC NULLS LAST, tag ASC
            """,
            discord_user_id,
        )
        return [(r["tag"], r["name"], _tier_from_db(r["legend_tier"])) for r in rows]

    async def list_active_legend_players_in_tier(
        self,
        *tiers: LeagueType,
    ) -> list[tuple[str, int, str | None, LeagueType]]:
        """Enumerate active players matching any of the given tiers.

        Used by ``WeeklyRecapService`` to scan Legend II/III at scheduled
        recap time. Returns ``(tag, discord_user_id, name, tier)``.
        """
        if not tiers:
            return []
        tier_strings = [_tier_to_db(t) for t in tiers]
        rows = await self._db.pool.fetch(
            f"""
            SELECT tag, discord_user_id, name,
                   COALESCE(legend_tier, 'unknown') AS legend_tier
            FROM {TBL_PLAYERS}
            WHERE is_active = TRUE AND legend_tier = ANY($1::text[])
            ORDER BY discord_user_id, tag
            """,
            tier_strings,
        )
        return [
            (r["tag"], int(r["discord_user_id"]), r["name"], _tier_from_db(r["legend_tier"]))
            for r in rows
        ]

    async def list_active_players_for_export(self) -> list[tuple[str, str | None]]:
        """Tags actifs avec nom affiché (export quotidien)."""
        rows = await self._db.pool.fetch(
            f"""
            SELECT tag, name FROM {TBL_PLAYERS}
            WHERE is_active = TRUE
            ORDER BY tag ASC
            """,
        )
        return [(r["tag"], r["name"]) for r in rows]

    async def get_global_usage_counts(self) -> dict[str, int]:
        """Agrégats pour le propriétaire du bot : utilisateurs, comptes, serveurs.

        - ``discord_users`` : Discord distincts avec au moins un tag actif.
        - ``active_accounts`` : lignes ``players`` actives (un user peut en avoir plusieurs).
        - ``servers_with_links`` : ``guild_id`` distincts non nuls parmi les joueurs actifs.
        - ``premium_active`` : abonnements avec ``current_period_end`` dans le futur.
        """
        row = await self._db.pool.fetchrow(
            f"""
            SELECT
              (SELECT COUNT(DISTINCT discord_user_id)::bigint
                 FROM {TBL_PLAYERS} WHERE is_active = TRUE) AS discord_users,
              (SELECT COUNT(*)::bigint
                 FROM {TBL_PLAYERS} WHERE is_active = TRUE) AS active_accounts,
              (SELECT COUNT(DISTINCT guild_id)::bigint
                 FROM {TBL_PLAYERS}
                 WHERE is_active = TRUE AND guild_id IS NOT NULL) AS servers_with_links,
              (SELECT COUNT(*)::bigint FROM {TBL_SUBSCRIPTIONS}
                 WHERE current_period_end IS NOT NULL
                   AND current_period_end > NOW()) AS premium_active
            """,
        )
        assert row is not None
        return {
            "discord_users": int(row["discord_users"] or 0),
            "active_accounts": int(row["active_accounts"] or 0),
            "servers_with_links": int(row["servers_with_links"] or 0),
            "premium_active": int(row["premium_active"] or 0),
        }

    async def deactivate_player(self, tag: str, discord_user_id: int) -> bool:
        """Soft-delete a tag for the given owner. No-op if mismatch.

        Returns True iff a row was actually flipped to ``is_active=FALSE``.
        Used by ``/accounts`` "Retirer" — never hard-deletes so historical
        snapshots and season results stay intact.
        """
        status = await self._db.pool.execute(
            f"""
            UPDATE {TBL_PLAYERS}
            SET is_active = FALSE
            WHERE tag = $1 AND discord_user_id = $2 AND is_active = TRUE
            """,
            tag,
            discord_user_id,
        )
        parts = str(status).split()
        return bool(parts) and parts[-1] != "0"

    # ── snapshots ─────────────────────────────────────────────────────────
    async def save_snapshot(self, snap: LegendSnapshot) -> bool:
        """Insert a snapshot. Returns False if the per-minute dedup blocked it."""
        try:
            await self._db.pool.execute(
                f"""
                INSERT INTO {TBL_PLAYER_SNAPSHOTS}
                    (player_tag, trophies, league_type,
                     attacks_done, trophies_gained, trophies_lost,
                     captured_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                snap.player_tag,
                snap.trophies,
                int(snap.league_type),
                snap.attacks_done,
                snap.trophies_gained,
                snap.trophies_lost,
                snap.captured_at,
            )
            return True
        except asyncpg.UniqueViolationError:
            # Dedup: another snapshot already exists for this minute.
            return False

    async def get_latest_snapshot(self, tag: str) -> LegendSnapshot | None:
        row = await self._db.pool.fetchrow(
            f"""
            SELECT player_tag, trophies, league_type, attacks_done,
                   trophies_gained, trophies_lost, captured_at
            FROM {TBL_PLAYER_SNAPSHOTS}
            WHERE player_tag = $1
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            tag,
        )
        return _row_to_snapshot(row) if row else None

    async def get_latest_snapshot_before(
        self,
        tag: str,
        cutoff: datetime,
    ) -> LegendSnapshot | None:
        """Dernier snapshot strictement avant ``cutoff`` (bornes de journée Légende)."""
        row = await self._db.pool.fetchrow(
            f"""
            SELECT player_tag, trophies, league_type, attacks_done,
                   trophies_gained, trophies_lost, captured_at
            FROM {TBL_PLAYER_SNAPSHOTS}
            WHERE player_tag = $1 AND captured_at < $2
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            tag,
            cutoff,
        )
        return _row_to_snapshot(row) if row else None

    async def get_snapshots_since(
        self,
        tag: str,
        since: datetime,
    ) -> list[LegendSnapshot]:
        rows = await self._db.pool.fetch(
            f"""
            SELECT player_tag, trophies, league_type, attacks_done,
                   trophies_gained, trophies_lost, captured_at
            FROM {TBL_PLAYER_SNAPSHOTS}
            WHERE player_tag = $1 AND captured_at >= $2
            ORDER BY captured_at ASC
            """,
            tag,
            since,
        )
        return [_row_to_snapshot(r) for r in rows]

    async def get_delta_since_last_snapshot(
        self,
        tag: str,
        current: LegendSnapshot,
    ) -> AttackDelta | None:
        """Build an `AttackDelta` between the latest stored snap and `current`.

        Returns None if no prior snapshot exists (first poll for this player).
        """
        previous = await self.get_latest_snapshot(tag)
        if previous is None:
            return None
        return AttackDelta.between(previous, current)

    # ── preferences ───────────────────────────────────────────────────────
    async def get_preferences(self, discord_user_id: int) -> UserPreferences:
        row = await self._db.pool.fetchrow(
            f"SELECT * FROM {TBL_USER_PREFERENCES} WHERE discord_user_id=$1",
            discord_user_id,
        )
        if row is None:
            return UserPreferences(discord_user_id=discord_user_id)
        # `alert_on_defense` is added by migration 003; tolerate missing column for older rows.
        alert_def = True
        if "alert_on_defense" in row.keys():
            alert_def = bool(row["alert_on_defense"])
        digest_en = False
        digest_hour = 9
        digest_last = None
        if "digest_daily_enabled" in row.keys():
            digest_en = bool(row["digest_daily_enabled"])
        if "digest_hour_utc" in row.keys() and row["digest_hour_utc"] is not None:
            digest_hour = int(row["digest_hour_utc"])
        if "digest_last_sent_on" in row.keys():
            digest_last = row["digest_last_sent_on"]
        return UserPreferences(
            discord_user_id=row["discord_user_id"],
            enable_error_notebook=row["enable_error_notebook"],
            enable_alerts=row["enable_alerts"],
            quiet_hours_start=row["quiet_hours_start"],
            quiet_hours_end=row["quiet_hours_end"],
            language=row["language"],
            alert_on_defense=alert_def,
            digest_daily_enabled=digest_en,
            digest_hour_utc=digest_hour,
            digest_last_sent_on=digest_last,
        )

    async def upsert_preferences(self, prefs: UserPreferences) -> None:
        hour = max(0, min(23, prefs.digest_hour_utc))
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_USER_PREFERENCES}
                (discord_user_id, enable_error_notebook, enable_alerts,
                 quiet_hours_start, quiet_hours_end, language,
                 alert_on_defense, digest_daily_enabled, digest_hour_utc,
                 updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (discord_user_id) DO UPDATE SET
                enable_error_notebook = EXCLUDED.enable_error_notebook,
                enable_alerts         = EXCLUDED.enable_alerts,
                quiet_hours_start     = EXCLUDED.quiet_hours_start,
                quiet_hours_end       = EXCLUDED.quiet_hours_end,
                language              = EXCLUDED.language,
                alert_on_defense      = EXCLUDED.alert_on_defense,
                digest_daily_enabled  = EXCLUDED.digest_daily_enabled,
                digest_hour_utc       = EXCLUDED.digest_hour_utc,
                updated_at            = NOW()
            """,
            prefs.discord_user_id,
            prefs.enable_error_notebook,
            prefs.enable_alerts,
            prefs.quiet_hours_start,
            prefs.quiet_hours_end,
            prefs.language,
            prefs.alert_on_defense,
            prefs.digest_daily_enabled,
            hour,
        )

    async def list_digest_due_user_ids(
        self,
        hour_utc: int,
        today_utc: date,
    ) -> list[int]:
        """Users scheduled for ``hour_utc`` who have not received a digest today."""
        rows = await self._db.pool.fetch(
            f"""
            SELECT discord_user_id FROM {TBL_USER_PREFERENCES}
            WHERE digest_daily_enabled = TRUE
              AND digest_hour_utc = $1
              AND (digest_last_sent_on IS NULL OR digest_last_sent_on < $2)
            """,
            hour_utc,
            today_utc,
        )
        return [int(r["discord_user_id"]) for r in rows]

    async def mark_digest_sent(
        self,
        discord_user_id: int,
        sent_on: date,
    ) -> None:
        await self._db.pool.execute(
            f"""
            UPDATE {TBL_USER_PREFERENCES}
            SET digest_last_sent_on = $2, updated_at = NOW()
            WHERE discord_user_id = $1
            """,
            discord_user_id,
            sent_on,
        )

    # ── goals ─────────────────────────────────────────────────────────────
    async def get_goal(self, tag: str) -> PlayerGoal | None:
        row = await self._db.pool.fetchrow(
            f"SELECT * FROM {TBL_LEAGUE_GOALS} WHERE player_tag=$1",
            tag,
        )
        if row is None:
            return None
        return PlayerGoal(
            player_tag=row["player_tag"],
            target_trophies=row["target_trophies"],
            target_attacks_per_day=row["target_attacks_per_day"],
            notes=row["notes"] or "",
        )

    async def upsert_goal(self, goal: PlayerGoal) -> None:
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_LEAGUE_GOALS}
                (player_tag, target_trophies, target_attacks_per_day, notes,
                 updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (player_tag) DO UPDATE SET
                target_trophies        = EXCLUDED.target_trophies,
                target_attacks_per_day = EXCLUDED.target_attacks_per_day,
                notes                  = EXCLUDED.notes,
                updated_at             = NOW()
            """,
            goal.player_tag,
            goal.target_trophies,
            goal.target_attacks_per_day,
            goal.notes,
        )

    # ── defense log (Carnet d'Erreurs) ────────────────────────────────────
    async def insert_defense(
        self,
        player_tag: str,
        trophies_lost: int,
        opponent_tag: str | None,
        opponent_trophies: int | None,
        attack_count: int,
        malchance_score: float,
        league: LeagueType,
        season_week: int | None,
    ) -> int:
        row = await self._db.pool.fetchrow(
            f"""
            INSERT INTO {TBL_DEFENSE_LOG}
                (player_tag, trophies_lost, opponent_tag, opponent_trophies,
                 attack_count, malchance_score, league_type, season_week)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            player_tag,
            trophies_lost,
            opponent_tag,
            opponent_trophies,
            attack_count,
            malchance_score,
            int(league),
            season_week,
        )
        return int(row["id"])

    async def get_defenses_between(
        self,
        tag: str,
        start: datetime,
        end: datetime,
    ) -> list[DefenseLog]:
        rows = await self._db.pool.fetch(
            f"""
            SELECT id, player_tag, trophies_lost, opponent_tag,
                   opponent_trophies, attack_count, malchance_score,
                   league_type, season_week, logged_at
            FROM {TBL_DEFENSE_LOG}
            WHERE player_tag = $1 AND logged_at >= $2 AND logged_at < $3
            ORDER BY logged_at ASC
            """,
            tag,
            start,
            end,
        )
        return [_row_to_defense(r) for r in rows]

    async def count_defenses_between(
        self,
        tag: str,
        start: datetime,
        end: datetime,
    ) -> int:
        v = await self._db.pool.fetchval(
            f"""
            SELECT COUNT(*)::int FROM {TBL_DEFENSE_LOG}
            WHERE player_tag = $1 AND logged_at >= $2 AND logged_at < $3
            """,
            tag,
            start,
            end,
        )
        return int(v or 0)

    async def aggregate_defenses_between(
        self,
        tag: str,
        start: datetime,
        end: datetime,
    ) -> tuple[int, int]:
        """Return (count, sum_trophies_lost) for defenses in [start, end)."""
        row = await self._db.pool.fetchrow(
            f"""
            SELECT
              COUNT(*)::bigint AS n,
              COALESCE(SUM(trophies_lost), 0)::bigint AS lost
            FROM {TBL_DEFENSE_LOG}
            WHERE player_tag = $1 AND logged_at >= $2 AND logged_at < $3
            """,
            tag,
            start,
            end,
        )
        if row is None:
            return 0, 0
        return int(row["n"] or 0), int(row["lost"] or 0)

    async def get_worst_defense_between(
        self,
        tag: str,
        start: datetime,
        end: datetime,
    ) -> DefenseLog | None:
        row = await self._db.pool.fetchrow(
            f"""
            SELECT id, player_tag, trophies_lost, opponent_tag,
                   opponent_trophies, attack_count, malchance_score,
                   league_type, season_week, logged_at
            FROM {TBL_DEFENSE_LOG}
            WHERE player_tag = $1 AND logged_at >= $2 AND logged_at < $3
            ORDER BY malchance_score DESC, trophies_lost DESC
            LIMIT 1
            """,
            tag,
            start,
            end,
        )
        return _row_to_defense(row) if row else None

    # ── alert history ─────────────────────────────────────────────────────
    async def get_last_alert_at(
        self,
        player_tag: str,
        alert_type: str,
    ) -> datetime | None:
        row = await self._db.pool.fetchrow(
            f"""
            SELECT sent_at FROM {TBL_ALERT_HISTORY}
            WHERE player_tag = $1 AND alert_type = $2
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            player_tag,
            alert_type,
        )
        return row["sent_at"] if row else None

    async def record_alert(
        self,
        player_tag: str,
        alert_type: str,
        discord_user_id: int,
        message_preview: str,
    ) -> None:
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_ALERT_HISTORY}
                (player_tag, alert_type, discord_user_id, message_preview)
            VALUES ($1, $2, $3, $4)
            """,
            player_tag,
            alert_type,
            discord_user_id,
            message_preview[:200],
        )

    # ── guild config ──────────────────────────────────────────────────────
    async def get_guild_config(self, guild_id: int) -> GuildConfig:
        row = await self._db.pool.fetchrow(
            f"SELECT * FROM {TBL_GUILD_CONFIG} WHERE guild_id=$1",
            guild_id,
        )
        if row is None:
            return GuildConfig(guild_id=guild_id)
        return _guild_from_row(row)

    async def upsert_guild_config(self, cfg: GuildConfig) -> None:
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_GUILD_CONFIG}
                (guild_id, leaderboard_limit, leaderboard_public,
                 leaderboard_legend_only, alerts_channel_id,
                 leaderboard_channel_id, leaderboard_message_id, admin_role_id,
                 language, timezone,
                 legend_role_i_id, legend_role_ii_id, legend_role_iii_id,
                 updated_at)
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW()
            )
            ON CONFLICT (guild_id) DO UPDATE SET
                leaderboard_limit         = EXCLUDED.leaderboard_limit,
                leaderboard_public        = EXCLUDED.leaderboard_public,
                leaderboard_legend_only   = EXCLUDED.leaderboard_legend_only,
                alerts_channel_id         = EXCLUDED.alerts_channel_id,
                leaderboard_channel_id    = EXCLUDED.leaderboard_channel_id,
                leaderboard_message_id    = EXCLUDED.leaderboard_message_id,
                admin_role_id             = EXCLUDED.admin_role_id,
                language                  = EXCLUDED.language,
                timezone                  = EXCLUDED.timezone,
                legend_role_i_id          = EXCLUDED.legend_role_i_id,
                legend_role_ii_id         = EXCLUDED.legend_role_ii_id,
                legend_role_iii_id        = EXCLUDED.legend_role_iii_id,
                updated_at                = NOW()
            """,
            cfg.guild_id,
            max(3, min(50, cfg.leaderboard_limit)),
            cfg.leaderboard_public,
            cfg.leaderboard_legend_only,
            cfg.alerts_channel_id,
            cfg.leaderboard_channel_id,
            cfg.leaderboard_message_id,
            cfg.admin_role_id,
            cfg.language,
            cfg.timezone,
            cfg.legend_role_i_id,
            cfg.legend_role_ii_id,
            cfg.legend_role_iii_id,
        )

    # ── leaderboard ───────────────────────────────────────────────────────
    async def list_guild_leaderboard(
        self,
        guild_id: int,
        *,
        limit: int,
        legend_only: bool,
        league_filter: LeagueType | None = None,
    ) -> list[LeaderboardEntry]:
        lf = int(league_filter) if league_filter is not None else None
        rows = await self._db.pool.fetch(
            f"""
            SELECT p.tag, p.name, p.discord_user_id,
                   ls.trophies, ls.league_type, ls.attacks_done,
                   COALESCE(ls.trophies, 0) - COALESCE(fw.trophies, COALESCE(ls.trophies, 0))
                       AS weekly_gain,
                   ROW_NUMBER() OVER (ORDER BY ls.trophies DESC NULLS LAST) AS rnk
            FROM {TBL_PLAYERS} p
            LEFT JOIN LATERAL (
                SELECT trophies, league_type, attacks_done
                FROM {TBL_PLAYER_SNAPSHOTS}
                WHERE player_tag = p.tag
                ORDER BY captured_at DESC
                LIMIT 1
            ) ls ON TRUE
            LEFT JOIN LATERAL (
                SELECT trophies
                FROM {TBL_PLAYER_SNAPSHOTS}
                WHERE player_tag = p.tag
                  AND captured_at >= (NOW() AT TIME ZONE 'utc') - INTERVAL '7 days'
                ORDER BY captured_at ASC
                LIMIT 1
            ) fw ON TRUE
            WHERE p.guild_id = $1 AND p.is_active = TRUE
              AND ($2::bool IS FALSE OR COALESCE(ls.trophies, 0) >= 5000)
              AND ($4::smallint IS NULL OR COALESCE(ls.league_type, 0) = $4::smallint)
            ORDER BY ls.trophies DESC NULLS LAST
            LIMIT $3
            """,
            guild_id,
            legend_only,
            limit,
            lf,
        )
        out: list[LeaderboardEntry] = []
        for r in rows:
            out.append(
                LeaderboardEntry(
                    rank=int(r["rnk"]),
                    player_tag=r["tag"],
                    display_name=r["name"],
                    discord_user_id=int(r["discord_user_id"]),
                    trophies=int(r["trophies"] or 0),
                    league_type=LeagueType(int(r["league_type"] or 0)),
                    attacks_today=int(r["attacks_done"] or 0),
                    weekly_gain=int(r["weekly_gain"] or 0),
                )
            )
        return out

    async def get_poll_target(self, tag: str) -> PollTarget | None:
        row = await self._db.pool.fetchrow(
            f"""
            SELECT tag, discord_user_id, guild_id, last_polled_at,
                   COALESCE(legend_tier, 'unknown') AS legend_tier
            FROM {TBL_PLAYERS}
            WHERE tag = $1 AND is_active = TRUE
            """,
            tag,
        )
        if row is None:
            return None
        return PollTarget(
            player_tag=row["tag"],
            discord_user_id=int(row["discord_user_id"]),
            guild_id=row["guild_id"],
            last_polled_at=row["last_polled_at"],
            legend_tier=_tier_from_db(row["legend_tier"]),
        )

    async def delete_alert_history_for_tag(self, player_tag: str) -> int:
        status = await self._db.pool.execute(
            f"DELETE FROM {TBL_ALERT_HISTORY} WHERE player_tag = $1",
            player_tag,
        )
        parts = str(status).split()
        return int(parts[-1]) if parts else 0

    async def list_player_season_history(
        self,
        player_tag: str,
        limit: int = 8,
    ) -> list[SeasonHistoryEntry]:
        rows = await self._db.pool.fetch(
            f"""
            SELECT s.label, s.period_end, sr.final_trophies, sr.league_type,
                   sr.guild_rank, sr.net_trophies
            FROM {TBL_SEASON_RESULTS} sr
            JOIN {TBL_SEASONS} s ON s.id = sr.season_id
            WHERE sr.player_tag = $1
            ORDER BY COALESCE(s.period_end, s.period_start) DESC NULLS LAST
            LIMIT $2
            """,
            player_tag,
            limit,
        )
        return [
            SeasonHistoryEntry(
                season_label=str(r["label"]),
                period_end=r["period_end"],
                final_trophies=int(r["final_trophies"]),
                league_type=LeagueType(int(r["league_type"])),
                guild_rank=int(r["guild_rank"]) if r["guild_rank"] is not None else None,
                net_trophies=int(r["net_trophies"] or 0),
            )
            for r in rows
        ]

    # ── seasons ───────────────────────────────────────────────────────────
    async def get_active_season(self) -> SeasonRecord | None:
        row = await self._db.pool.fetchrow(
            f"""
            SELECT id, label, period_start, period_end
            FROM {TBL_SEASONS}
            WHERE period_end IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
        )
        return _row_to_season(row) if row else None

    async def ensure_active_season(self) -> SeasonRecord:
        cur = await self.get_active_season()
        if cur is not None:
            return cur
        from services.logic import season_month_label  # noqa: PLC0415

        label = season_month_label(datetime.now(timezone.utc))
        row = await self._db.pool.fetchrow(
            f"""
            INSERT INTO {TBL_SEASONS} (label, period_start)
            VALUES ($1, NOW())
            RETURNING id, label, period_start, period_end
            """,
            label,
        )
        assert row is not None
        return _row_to_season(row)

    async def list_recent_closed_seasons(self, limit: int = 5) -> list[SeasonRecord]:
        rows = await self._db.pool.fetch(
            f"""
            SELECT id, label, period_start, period_end
            FROM {TBL_SEASONS}
            WHERE period_end IS NOT NULL
            ORDER BY period_end DESC
            LIMIT $1
            """,
            limit,
        )
        return [_row_to_season(r) for r in rows]

    async def get_season_results_for_guild(
        self,
        season_id: int,
        guild_id: int,
        limit: int = 30,
    ) -> list[SeasonResultRow]:
        rows = await self._db.pool.fetch(
            f"""
            SELECT season_id, guild_id, player_tag, final_trophies,
                   league_type, guild_rank, net_trophies
            FROM {TBL_SEASON_RESULTS}
            WHERE season_id = $1 AND guild_id = $2
            ORDER BY guild_rank ASC NULLS LAST, final_trophies DESC
            LIMIT $3
            """,
            season_id,
            guild_id,
            limit,
        )
        return [_row_to_season_result(r) for r in rows]

    async def find_player_season_rank(
        self,
        season_id: int,
        guild_id: int,
        player_tag: str,
    ) -> SeasonResultRow | None:
        row = await self._db.pool.fetchrow(
            f"""
            SELECT season_id, guild_id, player_tag, final_trophies,
                   league_type, guild_rank, net_trophies
            FROM {TBL_SEASON_RESULTS}
            WHERE season_id = $1 AND guild_id = $2 AND player_tag = $3
            """,
            season_id,
            guild_id,
            player_tag,
        )
        return _row_to_season_result(row) if row else None

    async def close_active_season_and_open_next(self) -> tuple[int, int]:
        """Freeze rankings for every guild, close the open season, open a new one.

        Returns `(closed_season_id, new_season_id)`.
        """
        from services.logic import season_month_label  # noqa: PLC0415

        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                active = await conn.fetchrow(
                    f"""
                    SELECT id, label, period_start FROM {TBL_SEASONS}
                    WHERE period_end IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                )
                if active is None:
                    raise RuntimeError("No active season row")
                sid_old = int(active["id"])
                period_start: datetime = active["period_start"]

                guilds = await conn.fetch(
                    f"""
                    SELECT DISTINCT guild_id FROM {TBL_PLAYERS}
                    WHERE guild_id IS NOT NULL AND is_active = TRUE
                    """,
                )

                for gr in guilds:
                    gid = int(gr["guild_id"])
                    tags = await conn.fetch(
                        f"""
                        SELECT tag FROM {TBL_PLAYERS}
                        WHERE guild_id = $1 AND is_active = TRUE
                        """,
                        gid,
                    )
                    ranked: list[tuple[str, int, LeagueType, int]] = []
                    for tr in tags:
                        tag = tr["tag"]
                        snap_row = await conn.fetchrow(
                            f"""
                            SELECT trophies, league_type FROM {TBL_PLAYER_SNAPSHOTS}
                            WHERE player_tag = $1
                            ORDER BY captured_at DESC LIMIT 1
                            """,
                            tag,
                        )
                        if snap_row is None:
                            continue
                        trophies = int(snap_row["trophies"])
                        lg = LeagueType(int(snap_row["league_type"]))
                        first = await conn.fetchrow(
                            f"""
                            SELECT trophies FROM {TBL_PLAYER_SNAPSHOTS}
                            WHERE player_tag = $1 AND captured_at >= $2
                            ORDER BY captured_at ASC LIMIT 1
                            """,
                            tag,
                            period_start,
                        )
                        net = trophies - int(first["trophies"]) if first is not None else 0
                        ranked.append((tag, trophies, lg, net))
                    ranked.sort(key=lambda x: x[1], reverse=True)
                    for idx, (tag, trophies, lg, net) in enumerate(ranked, start=1):
                        await conn.execute(
                            f"""
                            INSERT INTO {TBL_SEASON_RESULTS}
                                (season_id, guild_id, player_tag,
                                 final_trophies, league_type, guild_rank,
                                 net_trophies)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            ON CONFLICT (season_id, player_tag) DO UPDATE SET
                                final_trophies = EXCLUDED.final_trophies,
                                league_type    = EXCLUDED.league_type,
                                guild_rank     = EXCLUDED.guild_rank,
                                net_trophies   = EXCLUDED.net_trophies
                            """,
                            sid_old,
                            gid,
                            tag,
                            trophies,
                            int(lg),
                            idx,
                            net,
                        )

                await conn.execute(
                    f"""
                    UPDATE {TBL_SEASONS}
                    SET period_end = NOW()
                    WHERE id = $1
                    """,
                    sid_old,
                )

                label = season_month_label(datetime.now(timezone.utc))
                new_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {TBL_SEASONS} (label, period_start)
                    VALUES ($1, NOW())
                    RETURNING id
                    """,
                    label,
                )
                assert new_row is not None
                sid_new = int(new_row["id"])
                return sid_old, sid_new

    async def close_season(self) -> tuple[int, int]:
        """Clôture la saison active et en ouvre une nouvelle (alias §7)."""
        return await self.close_active_season_and_open_next()

    async def merge_bot_metrics_hourly(
        self,
        chunk: dict[str, float | int],
    ) -> None:
        """Accumule une fenêtre dans `bot_metrics_hourly` (bucket = heure UTC courante)."""
        polls = int(chunk["polls_total"])
        errs = int(chunk["errors_total"])
        alerts = int(chunk["alerts_sent"])
        avg_lat = float(chunk["avg_latency_ms"])
        p95 = float(chunk["p95_latency_ms"])
        if polls == 0 and errs == 0 and alerts == 0:
            return
        bucket = utc_hour_floor(datetime.now(timezone.utc))
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_BOT_METRICS_HOURLY}
                (hour_bucket, polls_total, errors_total, alerts_sent,
                 avg_latency_ms, p95_latency_ms)
            VALUES (
                $1::timestamptz, $2, $3, $4, $5, $6
            )
            ON CONFLICT (hour_bucket) DO UPDATE SET
                polls_total = {TBL_BOT_METRICS_HOURLY}.polls_total + EXCLUDED.polls_total,
                errors_total = {TBL_BOT_METRICS_HOURLY}.errors_total + EXCLUDED.errors_total,
                alerts_sent = {TBL_BOT_METRICS_HOURLY}.alerts_sent + EXCLUDED.alerts_sent,
                avg_latency_ms = CASE
                    WHEN {TBL_BOT_METRICS_HOURLY}.polls_total + EXCLUDED.polls_total > 0 THEN (
                        (
                            {TBL_BOT_METRICS_HOURLY}.avg_latency_ms::numeric
                            * {TBL_BOT_METRICS_HOURLY}.polls_total::numeric
                        )
                        + (
                            EXCLUDED.avg_latency_ms::numeric
                            * EXCLUDED.polls_total::numeric
                        )
                    ) / NULLIF(
                        {TBL_BOT_METRICS_HOURLY}.polls_total + EXCLUDED.polls_total,
                        0
                    )::numeric
                    ELSE {TBL_BOT_METRICS_HOURLY}.avg_latency_ms
                END,
                p95_latency_ms = GREATEST(
                    {TBL_BOT_METRICS_HOURLY}.p95_latency_ms,
                    EXCLUDED.p95_latency_ms
                )
            """,
            bucket,
            polls,
            errs,
            alerts,
            avg_lat,
            p95,
        )

    async def list_guild_ids_with_leaderboard_channel(self) -> list[int]:
        rows = await self._db.pool.fetch(
            f"""
            SELECT guild_id FROM {TBL_GUILD_CONFIG}
            WHERE leaderboard_channel_id IS NOT NULL
            """,
        )
        return [int(r["guild_id"]) for r in rows]

    # ── hourly metrics ────────────────────────────────────────────────────
    async def bump_hourly_metrics(self, delta: AttackDelta) -> None:
        """Accumulate per-hour deltas when snapshot movement is detected."""
        tag = delta.current.player_tag
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_METRICS_HOURLY}
                (player_tag, bucket_start, net_trophies_delta,
                 attacks_delta, snapshot_count)
            VALUES (
                $1,
                date_trunc('hour', $2::timestamptz),
                $3,
                $4,
                1
            )
            ON CONFLICT (player_tag, bucket_start) DO UPDATE SET
                net_trophies_delta = {TBL_METRICS_HOURLY}.net_trophies_delta
                    + EXCLUDED.net_trophies_delta,
                attacks_delta = {TBL_METRICS_HOURLY}.attacks_delta
                    + EXCLUDED.attacks_delta,
                snapshot_count = {TBL_METRICS_HOURLY}.snapshot_count
                    + EXCLUDED.snapshot_count
            """,
            tag,
            delta.current.captured_at,
            delta.net_trophies,
            delta.new_attacks,
        )

    async def aggregate_metrics_window(
        self,
        player_tag: str,
        since: datetime,
        until: datetime,
    ) -> tuple[int, int, int]:
        """Sum (net trophies, attacks, snapshots) across hourly buckets."""
        row = await self._db.pool.fetchrow(
            f"""
            SELECT
                COALESCE(SUM(net_trophies_delta), 0)::bigint AS nt,
                COALESCE(SUM(attacks_delta), 0)::bigint AS atk,
                COALESCE(SUM(snapshot_count), 0)::bigint AS sn
            FROM {TBL_METRICS_HOURLY}
            WHERE player_tag = $1
              AND bucket_start >= $2 AND bucket_start < $3
            """,
            player_tag,
            since,
            until,
        )
        if row is None:
            return 0, 0, 0
        return int(row["nt"]), int(row["atk"]), int(row["sn"])

    async def list_metrics_hourly(
        self,
        player_tag: str,
        since: datetime,
        until: datetime,
    ) -> list[MetricsHourlyRow]:
        rows = await self._db.pool.fetch(
            f"""
            SELECT player_tag, bucket_start, net_trophies_delta,
                   attacks_delta, snapshot_count
            FROM {TBL_METRICS_HOURLY}
            WHERE player_tag = $1
              AND bucket_start >= $2 AND bucket_start < $3
            ORDER BY bucket_start ASC
            """,
            player_tag,
            since,
            until,
        )
        return [
            MetricsHourlyRow(
                player_tag=r["player_tag"],
                bucket_start=r["bucket_start"],
                net_trophies_delta=int(r["net_trophies_delta"]),
                attacks_delta=int(r["attacks_delta"]),
                snapshot_count=int(r["snapshot_count"]),
            )
            for r in rows
        ]

    # ── subscriptions (Stripe) ────────────────────────────────────────────
    async def get_subscription(self, discord_user_id: int) -> Subscription:
        """Return the user's billing row, or a fresh ``FREE`` default."""
        row = await self._db.pool.fetchrow(
            f"SELECT * FROM {TBL_SUBSCRIPTIONS} WHERE discord_user_id=$1",
            discord_user_id,
        )
        if row is None:
            return Subscription(discord_user_id=discord_user_id)
        return Subscription(
            discord_user_id=int(row["discord_user_id"]),
            plan=SubscriptionPlan(row["plan"]),
            status=SubscriptionStatus(row["status"]),
            trial_used=bool(row["trial_used"]),
            trial_started_at=row["trial_started_at"],
            current_period_end=row["current_period_end"],
            stripe_customer_id=row["stripe_customer_id"],
            stripe_subscription_id=row["stripe_subscription_id"],
        )

    async def upsert_subscription(self, sub: Subscription) -> None:
        """Persist a Subscription row (insert or full update)."""
        await self._db.pool.execute(
            f"""
            INSERT INTO {TBL_SUBSCRIPTIONS}
                (discord_user_id, plan, status, trial_used, trial_started_at,
                 current_period_end, stripe_customer_id, stripe_subscription_id,
                 updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (discord_user_id) DO UPDATE SET
                plan                   = EXCLUDED.plan,
                status                 = EXCLUDED.status,
                trial_used             = EXCLUDED.trial_used OR
                                          {TBL_SUBSCRIPTIONS}.trial_used,
                trial_started_at       = COALESCE(
                    {TBL_SUBSCRIPTIONS}.trial_started_at,
                    EXCLUDED.trial_started_at),
                current_period_end     = EXCLUDED.current_period_end,
                stripe_customer_id     = COALESCE(
                    EXCLUDED.stripe_customer_id,
                    {TBL_SUBSCRIPTIONS}.stripe_customer_id),
                stripe_subscription_id = COALESCE(
                    EXCLUDED.stripe_subscription_id,
                    {TBL_SUBSCRIPTIONS}.stripe_subscription_id),
                updated_at             = NOW()
            """,
            sub.discord_user_id,
            sub.plan.value,
            sub.status.value,
            sub.trial_used,
            sub.trial_started_at,
            sub.current_period_end,
            sub.stripe_customer_id,
            sub.stripe_subscription_id,
        )

    async def get_subscription_by_stripe_customer(
        self,
        stripe_customer_id: str,
    ) -> Subscription | None:
        """Reverse lookup used by the Stripe webhook to map events → users."""
        row = await self._db.pool.fetchrow(
            f"""
            SELECT * FROM {TBL_SUBSCRIPTIONS}
            WHERE stripe_customer_id = $1
            """,
            stripe_customer_id,
        )
        if row is None:
            return None
        return Subscription(
            discord_user_id=int(row["discord_user_id"]),
            plan=SubscriptionPlan(row["plan"]),
            status=SubscriptionStatus(row["status"]),
            trial_used=bool(row["trial_used"]),
            trial_started_at=row["trial_started_at"],
            current_period_end=row["current_period_end"],
            stripe_customer_id=row["stripe_customer_id"],
            stripe_subscription_id=row["stripe_subscription_id"],
        )

    # ── ping quota (50/mois pour les comptes Free) ────────────────────────
    async def get_ping_quota(
        self,
        discord_user_id: int,
        year_month: str,
    ) -> PingQuotaState:
        """Fetch the (user, calendar month) bucket — empty if absent."""
        row = await self._db.pool.fetchrow(
            f"""
            SELECT discord_user_id, year_month, used, warned_full
            FROM {TBL_PING_QUOTA}
            WHERE discord_user_id = $1 AND year_month = $2
            """,
            discord_user_id,
            year_month,
        )
        if row is None:
            return PingQuotaState(
                discord_user_id=discord_user_id,
                year_month=year_month,
            )
        return PingQuotaState(
            discord_user_id=int(row["discord_user_id"]),
            year_month=str(row["year_month"]).strip(),
            used=int(row["used"]),
            warned_full=bool(row["warned_full"]),
        )

    async def increment_ping_quota(
        self,
        discord_user_id: int,
        year_month: str,
    ) -> int:
        """Atomically +1 the bucket and return the new ``used`` value."""
        row = await self._db.pool.fetchrow(
            f"""
            INSERT INTO {TBL_PING_QUOTA}
                (discord_user_id, year_month, used, warned_full, updated_at)
            VALUES ($1, $2, 1, FALSE, NOW())
            ON CONFLICT (discord_user_id, year_month) DO UPDATE SET
                used       = {TBL_PING_QUOTA}.used + 1,
                updated_at = NOW()
            RETURNING used
            """,
            discord_user_id,
            year_month,
        )
        return int(row["used"])

    async def mark_ping_quota_warned(
        self,
        discord_user_id: int,
        year_month: str,
    ) -> None:
        """Flip ``warned_full=TRUE`` so the upsell DM is sent at most once."""
        await self._db.pool.execute(
            f"""
            UPDATE {TBL_PING_QUOTA}
            SET warned_full = TRUE
            WHERE discord_user_id = $1 AND year_month = $2
            """,
            discord_user_id,
            year_month,
        )


# ─────────────────────────────────────────────────────────────────────────────
# LegendTier ↔ DB string helpers (column ``players.legend_tier``).
# ─────────────────────────────────────────────────────────────────────────────
_TIER_DB_VALUES: dict[LeagueType, str] = {
    LeagueType.UNKNOWN: "unknown",
    LeagueType.LEGEND_III: "legend_iii",
    LeagueType.LEGEND_II: "legend_ii",
    LeagueType.LEGEND_I: "legend_i",
}
_TIER_DB_REVERSE: dict[str, LeagueType] = {v: k for k, v in _TIER_DB_VALUES.items()}


def _tier_to_db(tier: LeagueType) -> str:
    return _TIER_DB_VALUES.get(tier, "unknown")


def _tier_from_db(value: str | None) -> LeagueType:
    if value is None:
        return LeagueType.UNKNOWN
    return _TIER_DB_REVERSE.get(str(value).strip().lower(), LeagueType.UNKNOWN)


def _opt_int(row: asyncpg.Record, key: str) -> int | None:
    if key not in row:
        return None
    v = row[key]
    return int(v) if v is not None else None


def _guild_from_row(row: asyncpg.Record) -> GuildConfig:
    """Construit ``GuildConfig`` avec tolérance aux vieilles lignes partielles."""
    lang = row["language"] if "language" in row and row["language"] else "fr"
    tz = row["timezone"] if "timezone" in row and row["timezone"] else "UTC"
    return GuildConfig(
        guild_id=int(row["guild_id"]),
        leaderboard_limit=int(row["leaderboard_limit"]),
        leaderboard_public=bool(row["leaderboard_public"]),
        leaderboard_legend_only=bool(row["leaderboard_legend_only"]),
        alerts_channel_id=_opt_int(row, "alerts_channel_id"),
        leaderboard_channel_id=_opt_int(row, "leaderboard_channel_id"),
        leaderboard_message_id=_opt_int(row, "leaderboard_message_id"),
        admin_role_id=_opt_int(row, "admin_role_id"),
        language=str(lang),
        timezone=str(tz),
        legend_role_i_id=_opt_int(row, "legend_role_i_id"),
        legend_role_ii_id=_opt_int(row, "legend_role_ii_id"),
        legend_role_iii_id=_opt_int(row, "legend_role_iii_id"),
    )


def _row_to_season(row: asyncpg.Record) -> SeasonRecord:
    return SeasonRecord(
        id=int(row["id"]),
        label=str(row["label"]),
        period_start=row["period_start"],
        period_end=row["period_end"],
    )


def _row_to_season_result(row: asyncpg.Record) -> SeasonResultRow:
    return SeasonResultRow(
        season_id=int(row["season_id"]),
        guild_id=int(row["guild_id"]),
        player_tag=row["player_tag"],
        final_trophies=int(row["final_trophies"]),
        league_type=LeagueType(int(row["league_type"])),
        guild_rank=int(row["guild_rank"]) if row["guild_rank"] is not None else None,
        net_trophies=int(row["net_trophies"] or 0),
    )


def _row_to_defense(row: asyncpg.Record) -> DefenseLog:
    return DefenseLog(
        id=row["id"],
        player_tag=row["player_tag"],
        trophies_lost=row["trophies_lost"],
        opponent_tag=row["opponent_tag"],
        opponent_trophies=row["opponent_trophies"],
        attack_count=row["attack_count"],
        malchance_score=float(row["malchance_score"]),
        league_type=LeagueType(row["league_type"]),
        season_week=row["season_week"],
        logged_at=row["logged_at"],
    )


def _row_to_snapshot(row: asyncpg.Record) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag=row["player_tag"],
        trophies=row["trophies"],
        league_type=LeagueType(row["league_type"]),
        attacks_done=row["attacks_done"],
        trophies_gained=row["trophies_gained"],
        trophies_lost=row["trophies_lost"],
        captured_at=row["captured_at"],
    )
