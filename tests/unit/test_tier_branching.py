"""Unit tests for the Avril 2026 tier-aware refactor.

Covers:
  * ``services/coach_briefing.py`` weekly helpers (``weekly_attacks_used``,
    ``weekly_consistency``, ``current_week_window``).
  * ``services/recap.py`` digest computation (``_RecapDigest`` properties).
  * Tier helpers (``weekly_quota``).

The Discord-facing parts of the cogs (Select callbacks, embed rendering)
are integration territory; these tests exercise the *pure* logic only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.coach_briefing import (
    current_week_window,
    weekly_attacks_used,
    weekly_consistency,
    weekly_quota,
)
from constants import (
    LEGEND_II_WEEKLY_BATTLES,
    LEGEND_III_WEEKLY_BATTLES,
    LeagueType,
)
from models import LegendSnapshot
from services.recap import _RecapDigest


def _snap(
    when: datetime, trophies: int, attacks: int, lost: int = 0, gained: int = 0,
    tier: LeagueType = LeagueType.LEGEND_II,
) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag="#TEST",
        trophies=trophies,
        league_type=tier,
        attacks_done=attacks,
        trophies_gained=gained,
        trophies_lost=lost,
        captured_at=when,
    )


# ─────────────────────────────────────────────────────────────────────────────
# weekly_quota
# ─────────────────────────────────────────────────────────────────────────────
def test_weekly_quota_legend_ii() -> None:
    assert weekly_quota(LeagueType.LEGEND_II) == LEGEND_II_WEEKLY_BATTLES


def test_weekly_quota_legend_iii() -> None:
    assert weekly_quota(LeagueType.LEGEND_III) == LEGEND_III_WEEKLY_BATTLES


def test_weekly_quota_legend_i_returns_zero() -> None:
    """Legend I est en daily — pas de quota hebdo."""
    assert weekly_quota(LeagueType.LEGEND_I) == 0


# ─────────────────────────────────────────────────────────────────────────────
# current_week_window
# ─────────────────────────────────────────────────────────────────────────────
def test_current_week_window_keeps_only_this_iso_week() -> None:
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    last_week = monday - timedelta(days=2)
    this_week = monday + timedelta(hours=2)
    snapshots = [_snap(last_week, 5500, 0), _snap(this_week, 5550, 0)]
    week = current_week_window(snapshots)
    assert len(week) == 1
    assert week[0].captured_at == this_week


# ─────────────────────────────────────────────────────────────────────────────
# weekly_attacks_used — daily resets summed across the week.
# ─────────────────────────────────────────────────────────────────────────────
def test_weekly_attacks_used_sums_per_day_max() -> None:
    """``attacks_done`` reset chaque jour côté API CoC ; on somme le max
    par jour pour reconstruire le total hebdo (Legend II/III)."""
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    week = [
        _snap(monday + timedelta(hours=12), 5500, 3),  # mardi 3 attaques
        _snap(monday + timedelta(days=1, hours=10), 5510, 2),  # peak du jour 2 → 2
        _snap(monday + timedelta(days=1, hours=23), 5510, 5),  # max du jour 2 = 5
        _snap(monday + timedelta(days=2, hours=8), 5520, 4),  # jour 3 → 4
    ]
    used = weekly_attacks_used(week, latest_attacks_done=4)
    assert used == 3 + 5 + 4  # = 12


def test_weekly_attacks_used_falls_back_to_latest_when_empty_window() -> None:
    used = weekly_attacks_used([], latest_attacks_done=7)
    assert used == 7


# ─────────────────────────────────────────────────────────────────────────────
# weekly_consistency
# ─────────────────────────────────────────────────────────────────────────────
def test_weekly_consistency_full_week_counts() -> None:
    """Une semaine complète (quota atteint) compte 1 plein."""
    base = datetime(2026, 4, 6, 8, 0, tzinfo=timezone.utc)  # ISO Monday
    quota = LEGEND_II_WEEKLY_BATTLES  # 30
    snapshots = [
        _snap(base + timedelta(days=i, hours=12), 5500, attacks=10)
        for i in range(3)
    ]
    full, total, ratio = weekly_consistency(snapshots, quota=quota)
    assert total == 1
    assert full == 1
    assert ratio == 1.0


def test_weekly_consistency_partial_week_counts_as_total_only() -> None:
    base = datetime(2026, 4, 6, 8, 0, tzinfo=timezone.utc)
    quota = LEGEND_II_WEEKLY_BATTLES
    snapshots = [
        _snap(base + timedelta(days=i, hours=12), 5500, attacks=2)
        for i in range(3)
    ]
    full, total, ratio = weekly_consistency(snapshots, quota=quota)
    assert total == 1
    assert full == 0
    assert ratio == 0.0


def test_weekly_consistency_handles_empty_input() -> None:
    full, total, ratio = weekly_consistency([], quota=30)
    assert (full, total, ratio) == (0, 0, 0.0)


def test_weekly_consistency_handles_zero_quota() -> None:
    """Legend I (quota=0) ⇒ on retourne (0, 0, 0.0) plutôt qu'un /0."""
    base = datetime(2026, 4, 6, 8, 0, tzinfo=timezone.utc)
    snapshots = [_snap(base, 5500, attacks=8)]
    full, total, ratio = weekly_consistency(snapshots, quota=0)
    assert (full, total, ratio) == (0, 0, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# _RecapDigest computation
# ─────────────────────────────────────────────────────────────────────────────
def test_recap_digest_computes_week_deltas() -> None:
    base = datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc)
    snapshots = [
        _snap(base, 5500, attacks=0, gained=0, lost=0,
              tier=LeagueType.LEGEND_II),
        _snap(base + timedelta(days=6), 5460, attacks=12, gained=180, lost=220,
              tier=LeagueType.LEGEND_II),
    ]
    digest = _RecapDigest(
        player_tag="#X",
        discord_user_id=42,
        name="Player",
        tier=LeagueType.LEGEND_II,
        snapshots=snapshots,
    )
    assert digest.trophies_delta == -40
    assert digest.trophies_won == 180
    assert digest.trophies_lost == 220
    assert digest.attacks_done == 12
    assert digest.quota == LEGEND_II_WEEKLY_BATTLES


def test_recap_digest_handles_attack_counter_reset() -> None:
    """Si la fenêtre traverse un reset de saison, on retourne le compteur
    courant plutôt qu'une valeur négative absurde."""
    base = datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc)
    snapshots = [
        _snap(base, 5500, attacks=20, tier=LeagueType.LEGEND_III),
        _snap(base + timedelta(days=6), 5550, attacks=5,
              tier=LeagueType.LEGEND_III),
    ]
    digest = _RecapDigest(
        player_tag="#X",
        discord_user_id=42,
        name="Player",
        tier=LeagueType.LEGEND_III,
        snapshots=snapshots,
    )
    assert digest.attacks_done == 5
    assert digest.quota == LEGEND_III_WEEKLY_BATTLES
