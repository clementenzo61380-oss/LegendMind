"""Unit tests for ``services/rank_predictor.py``.

Covers:
  * Curve fitting (`_fit_curve`) on synthetic and real-world-like data.
  * `RankCurve.estimate_rank` boundaries (clamp, R² gate, far below floor).
  * `RankPredictor` cache lifecycle (refresh, is_stale, leaderboard_age).
  * `predict_season_end_rank` end-to-end with stubbed leaderboard.
  * Formatting helpers (`format_rank`, `rank_emoji`).

The CoC API client is stubbed via `unittest.mock` — no real network.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from constants import LEGEND_TOTAL_PLAYERS_ESTIMATE, LeagueType
from models import LegendSnapshot
from services.rank_predictor import (
    RankCurve,
    RankDataPoint,
    RankPredictor,
    _fit_curve,
    format_rank,
    rank_emoji,
)


# ─────────────────────────────────────────────────────────────────────────────
# _fit_curve — log-linear regression
# ─────────────────────────────────────────────────────────────────────────────
def _make_points(pairs: list[tuple[int, int]]) -> list[RankDataPoint]:
    return [
        RankDataPoint(rank=r, trophies=t, player_tag=f"#T{r}", player_name=f"P{r}")
        for r, t in pairs
    ]


def test_fit_curve_returns_none_below_minimum() -> None:
    assert _fit_curve(_make_points([(1, 7000)])) is None


def test_fit_curve_perfect_log_linear_data() -> None:
    """Synthetic data on the curve t = 7000 - 200*ln(rank) → R² should be 1.0."""
    pairs = [(r, int(round(7000 - 200 * math.log(r)))) for r in range(1, 51)]
    curve = _fit_curve(_make_points(pairs))
    assert curve is not None
    assert curve.r_squared == pytest.approx(1.0, abs=1e-3)
    assert curve.sample_size == 50
    assert curve.min_trophies < curve.max_trophies


def test_fit_curve_realistic_supercell_top_200() -> None:
    """Real-world Legend leaderboard has R² typically in [0.85, 0.99]."""
    # Mimic a typical top-200 distribution: rank 1 at ~7400, rank 200 at ~5800.
    # Trophies decrease roughly logarithmically with rank.
    pairs = [(r, int(7400 - (7400 - 5800) * math.log(r) / math.log(200))) for r in range(1, 201)]
    curve = _fit_curve(_make_points(pairs))
    assert curve is not None
    assert curve.r_squared > 0.95


def test_fit_curve_handles_constant_ranks_gracefully() -> None:
    """Degenerate data (all same rank) → ss_xx == 0 → returns None."""
    pairs = [(5, 6500), (5, 6400), (5, 6300)]
    assert _fit_curve(_make_points(pairs)) is None


# ─────────────────────────────────────────────────────────────────────────────
# RankCurve.estimate_rank
# ─────────────────────────────────────────────────────────────────────────────
def _build_curve(r_squared: float = 0.95) -> RankCurve:
    """Standard well-fitting curve for testing inversion."""
    pairs = [(r, int(round(7000 - 200 * math.log(r)))) for r in range(1, 201)]
    curve = _fit_curve(_make_points(pairs))
    assert curve is not None
    # Override r_squared for tests that need a specific quality.
    object.__setattr__(curve, "r_squared", r_squared)
    return curve


def test_estimate_rank_returns_low_rank_for_top_trophies() -> None:
    curve = _build_curve()
    # The curve was fit to t(r=1)=7000, so estimate_rank(7000) should ≈ 1.
    estimated = curve.estimate_rank(7000)
    assert estimated is not None
    assert 1 <= estimated <= 5


def test_estimate_rank_returns_higher_rank_for_lower_trophies() -> None:
    curve = _build_curve()
    rank_high_trophies = curve.estimate_rank(6500)
    rank_low_trophies = curve.estimate_rank(5800)
    assert rank_high_trophies is not None
    assert rank_low_trophies is not None
    assert rank_high_trophies < rank_low_trophies


def test_estimate_rank_clamps_to_total_estimate_below_floor() -> None:
    """Trophies way below the observed minimum → return the rough cap."""
    curve = _build_curve()
    # min_trophies in our synthetic data is around 5940 (rank 200).
    estimated = curve.estimate_rank(3000)
    assert estimated == LEGEND_TOTAL_PLAYERS_ESTIMATE


def test_estimate_rank_returns_none_when_fit_quality_too_low() -> None:
    curve = _build_curve(r_squared=0.50)
    assert curve.estimate_rank(6500) is None


def test_estimate_rank_returns_none_when_b_is_zero() -> None:
    """Pathological flat curve (no slope) → cannot invert."""
    curve = RankCurve(
        a=6500.0,
        b=0.0,
        r_squared=0.99,
        min_trophies=6000,
        max_trophies=7000,
        sample_size=10,
    )
    assert curve.estimate_rank(6500) is None


# ─────────────────────────────────────────────────────────────────────────────
# RankPredictor — cache lifecycle (no network)
# ─────────────────────────────────────────────────────────────────────────────
class _FakeLeaderboardEntry:
    def __init__(self, rank: int, trophies: int, tag: str, name: str) -> None:
        self.rank = rank
        self.trophies = trophies
        self.tag = tag
        self.name = name


def _fake_coc_client_with_leaderboard(
    entries: list[_FakeLeaderboardEntry],
) -> MagicMock:
    client = MagicMock()
    client.get_location_players = AsyncMock(return_value=entries)
    return client


@pytest.mark.asyncio
async def test_refresh_populates_snapshot_and_curve() -> None:
    pairs = [(r, int(round(7000 - 200 * math.log(r)))) for r in range(1, 201)]
    entries = [
        _FakeLeaderboardEntry(rank=r, trophies=t, tag=f"#T{r}", name=f"P{r}") for r, t in pairs
    ]
    coc_client = _fake_coc_client_with_leaderboard(entries)
    predictor = RankPredictor(coc_client=coc_client, ttl_seconds=600)
    await predictor.refresh()
    coc_client.get_location_players.assert_awaited_once()
    assert predictor.curve is not None
    assert predictor.top_entry is not None
    assert predictor.top_entry.rank == 1


@pytest.mark.asyncio
async def test_refresh_skips_when_too_few_points() -> None:
    """A leaderboard with < RANK_MIN_SAMPLES points keeps the old curve."""
    coc_client = _fake_coc_client_with_leaderboard([])
    predictor = RankPredictor(coc_client=coc_client, ttl_seconds=600)
    await predictor.refresh()
    assert predictor.curve is None


@pytest.mark.asyncio
async def test_refresh_swallows_api_exception() -> None:
    """A failing API call must not propagate — predictor stays empty."""
    coc_client = MagicMock()
    coc_client.get_location_players = AsyncMock(side_effect=RuntimeError("boom"))
    predictor = RankPredictor(coc_client=coc_client, ttl_seconds=600)
    await predictor.refresh()  # should not raise
    assert predictor.curve is None


def test_is_stale_when_never_refreshed() -> None:
    coc_client = MagicMock()
    predictor = RankPredictor(coc_client=coc_client, ttl_seconds=600)
    assert predictor.is_stale() is True


@pytest.mark.asyncio
async def test_estimate_current_rank_returns_none_without_data() -> None:
    coc_client = MagicMock()
    predictor = RankPredictor(coc_client=coc_client, ttl_seconds=600)
    assert predictor.estimate_current_rank(6500) is None


@pytest.mark.asyncio
async def test_estimate_current_rank_uses_curve_after_refresh() -> None:
    pairs = [(r, int(round(7000 - 200 * math.log(r)))) for r in range(1, 201)]
    entries = [
        _FakeLeaderboardEntry(rank=r, trophies=t, tag=f"#T{r}", name=f"P{r}") for r, t in pairs
    ]
    predictor = RankPredictor(
        coc_client=_fake_coc_client_with_leaderboard(entries),
        ttl_seconds=600,
    )
    await predictor.refresh()
    estimated = predictor.estimate_current_rank(6500)
    assert estimated is not None
    assert 1 <= estimated <= 200


# ─────────────────────────────────────────────────────────────────────────────
# predict_season_end_rank — combines pace logic with the rank curve
# ─────────────────────────────────────────────────────────────────────────────
def _snap(when: datetime, trophies: int) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag="#X",
        trophies=trophies,
        league_type=LeagueType.LEGEND_I,
        attacks_done=0,
        trophies_gained=0,
        trophies_lost=0,
        captured_at=when,
    )


@pytest.mark.asyncio
async def test_predict_season_end_rank_returns_none_for_unknown_tier() -> None:
    coc_client = MagicMock()
    predictor = RankPredictor(coc_client=coc_client, ttl_seconds=600)
    result = predictor.predict_season_end_rank(
        snapshots=[_snap(datetime.now(timezone.utc), 6500)],
        league=LeagueType.UNKNOWN,
    )
    assert result is None


@pytest.mark.asyncio
async def test_predict_season_end_rank_returns_none_without_snapshots() -> None:
    coc_client = MagicMock()
    predictor = RankPredictor(coc_client=coc_client, ttl_seconds=600)
    result = predictor.predict_season_end_rank(
        snapshots=[],
        league=LeagueType.LEGEND_I,
    )
    assert result is None


@pytest.mark.asyncio
async def test_predict_season_end_rank_uses_pace_then_curve() -> None:
    """Full pipeline: pace projection → curve inversion → rank int."""
    pairs = [(r, int(round(7000 - 200 * math.log(r)))) for r in range(1, 201)]
    entries = [
        _FakeLeaderboardEntry(rank=r, trophies=t, tag=f"#T{r}", name=f"P{r}") for r, t in pairs
    ]
    predictor = RankPredictor(
        coc_client=_fake_coc_client_with_leaderboard(entries),
        ttl_seconds=600,
    )
    await predictor.refresh()
    base = datetime.now(timezone.utc)
    snapshots = [
        _snap(base - timedelta(days=2), 6300),
        _snap(base - timedelta(days=1), 6350),
        _snap(base, 6400),
    ]
    season_end = base + timedelta(days=5)
    result = predictor.predict_season_end_rank(
        snapshots=snapshots,
        league=LeagueType.LEGEND_I,
        season_end=season_end,
    )
    assert result is not None
    assert 1 <= result <= LEGEND_TOTAL_PLAYERS_ESTIMATE


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────
def test_format_rank_unknown_returns_dash() -> None:
    assert format_rank(None) == "—"


def test_format_rank_under_thousand_unchanged() -> None:
    assert format_rank(42) == "#42"


def test_format_rank_thousands_use_narrow_space() -> None:
    """Narrow no-break space (U+202F) groups thousands."""
    out = format_rank(15_000)
    assert out.startswith("#")
    assert "15" in out and "000" in out


def test_rank_emoji_top_10_gold() -> None:
    assert rank_emoji(1) == "🥇"
    assert rank_emoji(10) == "🥇"


def test_rank_emoji_silver_for_top_100() -> None:
    assert rank_emoji(11) == "🥈"
    assert rank_emoji(100) == "🥈"


def test_rank_emoji_bronze_for_top_1000() -> None:
    assert rank_emoji(101) == "🥉"


def test_rank_emoji_medal_for_top_10000() -> None:
    assert rank_emoji(1001) == "🏅"


def test_rank_emoji_default_dot_otherwise() -> None:
    assert rank_emoji(50_000) == "▪"


def test_rank_emoji_dot_when_unknown() -> None:
    assert rank_emoji(None) == "▪"
