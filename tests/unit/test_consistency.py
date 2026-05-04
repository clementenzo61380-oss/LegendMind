"""Tests for the Legend Consistency Score and optimal-attack-hour heuristics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from constants import LeagueType
from models import LegendSnapshot
from services.logic import legend_consistency_score, optimal_attack_hour


def _snap(when: datetime, attacks: int, trophies: int = 5800) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag="#X",
        trophies=trophies,
        league_type=LeagueType.LEGEND_I,
        attacks_done=attacks,
        trophies_gained=0,
        trophies_lost=0,
        captured_at=when,
    )


def test_consistency_score_all_full_days() -> None:
    base = datetime(2026, 5, 3, 10, tzinfo=timezone.utc)
    snaps = []
    for d in range(5):
        for atk in (0, 4, 8):
            snaps.append(_snap(base + timedelta(days=d, hours=atk), atk))
    ratio, full, total = legend_consistency_score(snaps, days=10)
    assert total == 5
    assert full == 5
    assert ratio == 1.0


def test_consistency_score_mixed() -> None:
    base = datetime(2026, 5, 3, 10, tzinfo=timezone.utc)
    snaps = []
    # 3 days at 8/8, 2 days at 6/8.
    for d in range(3):
        snaps.append(_snap(base + timedelta(days=d, hours=10), 8))
    for d in range(3, 5):
        snaps.append(_snap(base + timedelta(days=d, hours=10), 6))
    ratio, full, total = legend_consistency_score(snaps, days=10)
    assert total == 5
    assert full == 3
    assert ratio == 0.6


def test_consistency_score_empty_returns_zero() -> None:
    ratio, full, total = legend_consistency_score([], days=30)
    assert (ratio, full, total) == (0.0, 0, 0)


def test_optimal_hour_picks_modal_window() -> None:
    base = datetime(2026, 5, 3, 0, 0, tzinfo=timezone.utc)
    snaps = []
    # 3 attacks attributed to hour 19 (post-19:00 polls).
    snaps.append(_snap(base + timedelta(hours=18, minutes=58), 0))
    snaps.append(_snap(base + timedelta(hours=19, minutes=2), 1))
    snaps.append(_snap(base + timedelta(hours=19, minutes=15), 2))
    snaps.append(_snap(base + timedelta(hours=19, minutes=45), 3))
    # 1 attack at hour 22 — should not win.
    snaps.append(_snap(base + timedelta(hours=22, minutes=0), 4))
    assert optimal_attack_hour(snaps, lookback_days=2) == 19


def test_optimal_hour_returns_none_when_too_few_attacks() -> None:
    base = datetime(2026, 5, 3, 12, tzinfo=timezone.utc)
    snaps = [_snap(base, 0), _snap(base + timedelta(minutes=5), 1)]
    assert optimal_attack_hour(snaps, lookback_days=2) is None


def test_optimal_hour_ignores_reset_boundary() -> None:
    """A drop in attacks_done (new day) must NOT be counted as an attack."""
    base = datetime(2026, 5, 3, 4, 55, tzinfo=timezone.utc)
    snaps = [
        _snap(base, 8),
        _snap(base + timedelta(minutes=10), 0),  # reset → drop
        _snap(base + timedelta(hours=2), 1),  # 1 actual attack at ~07h
    ]
    # Only 1 attack observed → below the 3-min threshold, returns None.
    assert optimal_attack_hour(snaps, lookback_days=2) is None
