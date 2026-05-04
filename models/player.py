"""Domain models — typed dataclasses for the Legend tracking pipeline.

These objects are the contracts shared between services (db ↔ logic ↔
tracker ↔ alerts ↔ notebook). Keep them dependency-free so they can be
imported from anywhere without circular trouble.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime

from constants import LeagueType


# ─────────────────────────────────────────────────────────────────────────────
# Snapshots & deltas
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class LegendSnapshot:
    """A frozen reading of a player's Legend stats at a point in time.

    Immutable so it can be safely shared across coroutines without locking.
    """

    player_tag: str
    trophies: int
    league_type: LeagueType
    attacks_done: int
    trophies_gained: int
    trophies_lost: int
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class AttackDelta:
    """Computed difference between two consecutive snapshots.

    Always derived from `LegendSnapshot` pairs — never mutated directly.
    `new_attacks` and `net_trophies` are precomputed for hot-path use.
    """

    previous: LegendSnapshot
    current: LegendSnapshot
    new_attacks: int
    net_trophies: int

    @classmethod
    def between(cls, previous: LegendSnapshot, current: LegendSnapshot) -> "AttackDelta":
        """Compute the delta between two snapshots of the same player."""
        if previous.player_tag != current.player_tag:
            raise ValueError(
                "Cannot diff snapshots of different players: "
                f"{previous.player_tag} vs {current.player_tag}"
            )
        return cls(
            previous=previous,
            current=current,
            new_attacks=max(0, current.attacks_done - previous.attacks_done),
            net_trophies=current.trophies - previous.trophies,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Defenses (input from CoC API → notebook pipeline)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DefenseData:
    """Single defense event extracted from the CoC API.

    Used as input to the malchance scorer; not persisted directly
    (the persisted form is `DefenseLog`).
    """

    trophies_lost: int
    opponent_tag: str | None
    opponent_trophies: int | None
    attack_count: int = 1


@dataclass(frozen=True, slots=True)
class DefenseLog:
    """A persisted defense event with its computed malchance score."""

    id: int
    player_tag: str
    trophies_lost: int
    opponent_tag: str | None
    opponent_trophies: int | None
    attack_count: int
    malchance_score: float
    league_type: LeagueType
    season_week: int | None
    logged_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Goals & preferences
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class PlayerGoal:
    """User-defined season target for a single player.

    Mutable: editable via Discord modal without rebuilding the object.
    """

    player_tag: str
    target_trophies: int
    target_attacks_per_day: int
    notes: str = ""


@dataclass(slots=True)
class UserPreferences:
    """Per-Discord-user preferences governing alert + notebook behavior."""

    discord_user_id: int
    enable_error_notebook: bool = False
    enable_alerts: bool = True
    quiet_hours_start: int | None = None  # UTC hour (0–23)
    quiet_hours_end: int | None = None
    language: str = "fr"
    alert_on_defense: bool = True  # DM push on every detected defense (toggle via /ping)
    digest_daily_enabled: bool = False
    digest_hour_utc: int = 9  # 0–23, when to send the automated briefing DM
    digest_last_sent_on: date | None = None  # UTC calendar day of last digest


# ─────────────────────────────────────────────────────────────────────────────
# Polling
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PollTarget:
    """Lightweight projection used to feed the polling queue.

    Avoids loading entire player rows when we only need tag + Discord owner.
    Carries ``legend_tier`` (Avril 2026 Ranked refonte) so the tracker can
    route Legend I to the fast queue and Legend II/III to the slow queue.
    """

    player_tag: str
    discord_user_id: int
    guild_id: int | None
    last_polled_at: datetime | None
    legend_tier: LeagueType = LeagueType.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class GuildConfig:
    """Per-Discord-guild settings (see prompt étape 6)."""

    guild_id: int
    leaderboard_limit: int = 15
    leaderboard_public: bool = True
    leaderboard_legend_only: bool = True
    alerts_channel_id: int | None = None
    leaderboard_channel_id: int | None = None
    leaderboard_message_id: int | None = None
    admin_role_id: int | None = None
    language: str = "fr"
    timezone: str = "UTC"
    legend_role_i_id: int | None = None
    legend_role_ii_id: int | None = None
    legend_role_iii_id: int | None = None


@dataclass(frozen=True, slots=True)
class SeasonRecord:
    """One Legend season window (typically monthly)."""

    id: int
    label: str
    period_start: datetime
    period_end: datetime | None


@dataclass(frozen=True, slots=True)
class SeasonHistoryEntry:
    """Ligne pour `/historique` — résultats passés d’un joueur."""

    season_label: str
    period_end: datetime | None
    final_trophies: int
    league_type: LeagueType
    guild_rank: int | None
    net_trophies: int


@dataclass(frozen=True, slots=True)
class SeasonResultRow:
    """Frozen ranking snapshot at season close for one player."""

    season_id: int
    guild_id: int
    player_tag: str
    final_trophies: int
    league_type: LeagueType
    guild_rank: int | None
    net_trophies: int


@dataclass(frozen=True, slots=True)
class MetricsHourlyRow:
    """One hour bucket of aggregated deltas."""

    player_tag: str
    bucket_start: datetime
    net_trophies_delta: int
    attacks_delta: int
    snapshot_count: int


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """One row for `/classement` / LeaderboardService."""

    rank: int
    player_tag: str
    display_name: str | None
    discord_user_id: int
    trophies: int
    league_type: LeagueType
    attacks_today: int = 0
    weekly_gain: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Billing / entitlements
# ─────────────────────────────────────────────────────────────────────────────
class SubscriptionPlan(str, enum.Enum):
    """Three-tier plan model. ``TRIAL`` is treated as ``PREMIUM`` for entitlement.

    The ``str`` mixin makes the value safe to persist directly to PostgreSQL
    without an extra cast.
    """

    FREE = "free"
    TRIAL = "trial"
    PREMIUM = "premium"


class SubscriptionStatus(str, enum.Enum):
    """Lifecycle marker reflecting Stripe's own states.

    We collapse Stripe's full state machine into a small surface that the
    UI / quota service actually need. Anything not ``ACTIVE``/``TRIALING``
    is non-entitling once ``current_period_end`` has passed.
    """

    INACTIVE = "inactive"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


@dataclass(slots=True)
class Subscription:
    """Per-user Stripe subscription state cached from webhook events.

    Mutable on purpose — a single instance is loaded, updated by webhooks,
    and re-persisted via ``Repository.upsert_subscription``.
    """

    discord_user_id: int
    plan: SubscriptionPlan = SubscriptionPlan.FREE
    status: SubscriptionStatus = SubscriptionStatus.INACTIVE
    trial_used: bool = False
    trial_started_at: datetime | None = None
    current_period_end: datetime | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    def is_entitled(self, now: datetime) -> bool:
        """True iff the user currently has Premium-level access.

        Both ``TRIAL`` and ``PREMIUM`` count, but only while
        ``current_period_end`` is in the future.
        """
        if self.plan is SubscriptionPlan.FREE:
            return False
        if self.current_period_end is None:
            return False
        return self.current_period_end > now


@dataclass(slots=True)
class PingQuotaState:
    """Snapshot of one (user, calendar month) row in ``ping_quota``."""

    discord_user_id: int
    year_month: str  # 'YYYY-MM' (UTC)
    used: int = 0
    warned_full: bool = False


@dataclass(frozen=True, slots=True)
class NotebookReport:
    """Aggregate output of the weekly Carnet d'Erreurs analysis."""

    player_tag: str
    week_start: date
    week_end: date
    avg_malchance_score: float
    worst_defense: DefenseLog | None
    patterns: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    total_trophies_lost_to_bad_luck: int = 0
