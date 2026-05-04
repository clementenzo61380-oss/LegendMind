"""Tests fenêtre journée Légende + agrégation export."""

from __future__ import annotations

from datetime import datetime, timezone

from constants import LeagueType
from models import LegendSnapshot
from services.legend_day_export import (
    LegendDayWindow,
    completed_legend_day_window,
    compute_legend_day_stats,
    last_completed_legend_day_end,
)


def _snap(
    tag: str,
    *,
    when: datetime,
    attacks: int,
    trophies: int,
    gained: int = 0,
    lost: int = 0,
) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag=tag,
        trophies=trophies,
        league_type=LeagueType.LEGEND_I,
        attacks_done=attacks,
        trophies_gained=gained,
        trophies_lost=lost,
        captured_at=when,
    )


def test_last_completed_reset_after_reset_today() -> None:
    now = datetime(2026, 5, 3, 18, 5, tzinfo=timezone.utc)
    end = last_completed_legend_day_end(now, reset_hour_utc=18)
    assert end == datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)


def test_last_completed_reset_before_reset_today() -> None:
    now = datetime(2026, 5, 3, 17, 59, tzinfo=timezone.utc)
    end = last_completed_legend_day_end(now, reset_hour_utc=18)
    assert end == datetime(2026, 5, 2, 18, 0, tzinfo=timezone.utc)


def test_completed_window() -> None:
    now = datetime(2026, 5, 3, 18, 5, tzinfo=timezone.utc)
    w = completed_legend_day_window(now, 18)
    assert w.start_utc == datetime(2026, 5, 2, 18, 0, tzinfo=timezone.utc)
    assert w.end_utc == datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)


def test_compute_stats_with_baseline() -> None:
    w = LegendDayWindow(
        start_utc=datetime(2026, 5, 2, 18, 0, tzinfo=timezone.utc),
        end_utc=datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc),
    )
    start = _snap(
        "#abc",
        when=datetime(2026, 5, 2, 18, 1, tzinfo=timezone.utc),
        attacks=0,
        trophies=5000,
    )
    end = _snap(
        "#abc",
        when=datetime(2026, 5, 3, 17, 0, tzinfo=timezone.utc),
        attacks=8,
        trophies=5032,
    )
    row = compute_legend_day_stats("#abc", "Bob", w, start, end, defense_count=2)
    assert row is not None
    assert row.attacks == 8
    assert row.defenses == 2
    assert row.net_battles == 6
    assert row.net_trophies == 32
    assert row.trophies_end == 5032


def test_compute_stats_rejects_stale_end_snap() -> None:
    w = LegendDayWindow(
        start_utc=datetime(2026, 5, 2, 18, 0, tzinfo=timezone.utc),
        end_utc=datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc),
    )
    end = _snap(
        "#abc",
        when=datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
        attacks=1,
        trophies=5000,
    )
    assert compute_legend_day_stats("#abc", None, w, None, end, 0) is None
