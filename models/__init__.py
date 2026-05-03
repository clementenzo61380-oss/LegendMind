"""Domain dataclasses (immutable value objects + a few mutable records)."""
from __future__ import annotations

from .player import (
    AttackDelta,
    DefenseData,
    DefenseLog,
    GuildConfig,
    LeaderboardEntry,
    LegendSnapshot,
    MetricsHourlyRow,
    NotebookReport,
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

__all__ = [
    "AttackDelta",
    "DefenseData",
    "DefenseLog",
    "GuildConfig",
    "LeaderboardEntry",
    "LegendSnapshot",
    "MetricsHourlyRow",
    "NotebookReport",
    "PingQuotaState",
    "PlayerGoal",
    "PollTarget",
    "SeasonHistoryEntry",
    "SeasonRecord",
    "SeasonResultRow",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionStatus",
    "UserPreferences",
]
