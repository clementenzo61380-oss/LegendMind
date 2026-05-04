"""Rank prediction service — uses the official CoC global leaderboard.

How it works
------------
1. `RankPredictor.refresh()` calls `coc.Client.get_location_players('global')`
   to download the current worldwide Legend League rankings (up to ~200 entries
   from the Supercell API; each entry has `rank` and `trophies`).

2. From those (rank, trophies) pairs we fit a *decreasing log-linear curve*:
       trophies ≈ a − b × ln(rank)
   using least-squares regression.  This lets us extrapolate rank for any
   trophy count — even for players outside the top-200 API window.

3. `estimate_current_rank(trophies)` inverts the curve:
       rank ≈ exp((a − trophies) / b)

4. `predict_season_end_rank(snapshots, league)` combines:
   - `predict_end_of_season_trophies()` (existing pace logic)
   - The rank curve to convert projected trophies → projected rank.

All state lives in memory; no DB writes. `RankPredictor` is a long-lived
singleton injected into the bot at startup and refreshed via an asyncio task
every `RANK_CACHE_TTL_SECONDS`.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import coc

from constants import (
    COC_GLOBAL_LOCATION_ID,
    RANK_CACHE_TTL_SECONDS,
    RANK_MIN_SAMPLES,
    LeagueType,
)
from models import LegendSnapshot
from services.game_tuning import get_tuning
from services.logic import predict_end_of_season_trophies

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class RankDataPoint:
    """One entry from the global Legend leaderboard."""

    rank: int
    trophies: int
    player_tag: str
    player_name: str


@dataclass(slots=True)
class RankCurve:
    """Fitted decreasing log-linear model: trophies = a - b * ln(rank).

    `a` and `b` are regression coefficients; `r_squared` measures fit quality
    (values above 0.90 indicate a reliable curve).

    The inversion gives: rank = exp((a - trophies) / b).
    """

    a: float
    b: float
    r_squared: float
    min_trophies: int  # minimum trophies seen in the sample
    max_trophies: int  # maximum trophies seen in the sample
    sample_size: int
    built_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def estimate_rank(self, trophies: int) -> int | None:
        """Return the estimated rank for a given trophy count.

        Returns None when the curve has poor fit or the input is out of
        the meaningful extrapolation range (below the minimum observed
        trophies, meaning the player is likely very far from the top).
        """
        if self.r_squared < 0.70:
            return None
        cap = get_tuning().legend_total_players_estimate
        if trophies < self.min_trophies * 0.85:
            # Way below the leaderboard — clamp to a rough estimate.
            return cap
        if self.b == 0.0:
            return None
        raw = math.exp((self.a - trophies) / self.b)
        # Clamp to plausible range [1, cap].
        return max(1, min(cap, round(raw)))


@dataclass(slots=True)
class LeaderboardSnapshot:
    """Cached result of one leaderboard fetch cycle."""

    points: list[RankDataPoint]
    curve: RankCurve | None
    fetched_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Predictor
# ─────────────────────────────────────────────────────────────────────────────
class RankPredictor:
    """Periodically refreshes the global leaderboard and estimates ranks.

    Lifecycle: construct once, call `start()` to begin the background refresh
    task, then use `estimate_current_rank()` and `predict_season_end_rank()`
    from any coroutine. Thread-safe because asyncio is single-threaded.
    """

    def __init__(
        self,
        coc_client: coc.Client,
        ttl_seconds: int = RANK_CACHE_TTL_SECONDS,
    ) -> None:
        self._coc = coc_client
        self._ttl = ttl_seconds
        self._snapshot: LeaderboardSnapshot | None = None
        self._refresh_task: asyncio.Task[None] | None = None

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        """Launch the background refresh coroutine.  Call once at bot startup."""
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(
                self._refresh_loop(),
                name="rank-predictor-refresh",
            )

    def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()

    async def _refresh_loop(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(self._ttl)

    # ── public API ───────────────────────────────────────────────────────
    async def refresh(self) -> None:
        """Fetch the current global leaderboard and rebuild the curve."""
        try:
            raw = await self._coc.get_location_players(
                COC_GLOBAL_LOCATION_ID,
                limit=200,
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to fetch global Legend rankings")
            return

        points = [
            RankDataPoint(
                rank=int(p.rank or 0),
                trophies=int(p.trophies or 0),
                player_tag=p.tag,
                player_name=p.name or "",
            )
            for p in raw
            if (p.rank or 0) > 0 and (p.trophies or 0) > 0
        ]

        if len(points) < RANK_MIN_SAMPLES:
            log.warning(
                "Rank leaderboard too small (%d points); keeping old curve",
                len(points),
            )
            return

        curve = _fit_curve(points)
        self._snapshot = LeaderboardSnapshot(
            points=points,
            curve=curve,
            fetched_at=datetime.now(timezone.utc),
        )
        log.info(
            "Rank curve rebuilt: %d points, r²=%.3f, range [%d..%d] trophies",
            len(points),
            curve.r_squared if curve else 0.0,
            min(p.trophies for p in points),
            max(p.trophies for p in points),
        )

    def estimate_current_rank(self, trophies: int) -> int | None:
        """Estimate the current global rank for a given trophy count.

        Uses the cached leaderboard curve. Returns None when no data is
        available or when the curve fit is too poor to trust.
        """
        if self._snapshot is None or self._snapshot.curve is None:
            return None
        return self._snapshot.curve.estimate_rank(trophies)

    def predict_season_end_rank(
        self,
        snapshots: list[LegendSnapshot],
        league: LeagueType,
        season_end: datetime | None = None,
    ) -> int | None:
        """Combine the pace projection with the rank curve.

        1. `predict_end_of_season_trophies(snapshots, league)` → projected trophies.
        2. `estimate_current_rank(projected_trophies)` → projected rank.

        Returns None when data is too thin for a reliable estimate.
        """
        if not snapshots or league == LeagueType.UNKNOWN:
            return None
        projected_trophies = predict_end_of_season_trophies(
            snapshots,
            league,
            season_end=season_end,
        )
        if projected_trophies <= 0:
            return None
        return self.estimate_current_rank(projected_trophies)

    def is_stale(self) -> bool:
        """True when the cached curve is older than 2 × TTL (potential issue)."""
        if self._snapshot is None:
            return True
        age = (datetime.now(timezone.utc) - self._snapshot.fetched_at).total_seconds()
        return age > self._ttl * 2

    def leaderboard_age_minutes(self) -> float:
        """Seconds since last successful leaderboard fetch, or ∞ if never."""
        if self._snapshot is None:
            return float("inf")
        return (datetime.now(timezone.utc) - self._snapshot.fetched_at).total_seconds() / 60.0

    @property
    def top_entry(self) -> RankDataPoint | None:
        if self._snapshot and self._snapshot.points:
            return self._snapshot.points[0]
        return None

    @property
    def curve(self) -> RankCurve | None:
        return self._snapshot.curve if self._snapshot else None


# ─────────────────────────────────────────────────────────────────────────────
# Curve fitting helpers
# ─────────────────────────────────────────────────────────────────────────────
def _fit_curve(points: list[RankDataPoint]) -> RankCurve | None:
    """Fit trophies = a − b × ln(rank) via least-squares.

    The model is linear in ln(rank), so we run standard OLS after the
    log-transform.  We handle the degenerate case (< 2 distinct ranks) by
    returning None.
    """
    n = len(points)
    if n < 2:
        return None

    xs = [math.log(max(1, p.rank)) for p in points]  # ln(rank)
    ys = [float(p.trophies) for p in points]  # trophies

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in ys)

    if ss_xx == 0:
        return None

    b = ss_xy / ss_xx  # slope (should be negative: more rank = fewer trophies)
    a = mean_y - b * mean_x

    # R-squared
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_yy if ss_yy > 0 else 0.0

    return RankCurve(
        a=a,
        b=-b,  # store as positive "slope"; estimate_rank inverts with negative b
        r_squared=round(r2, 4),
        min_trophies=min(p.trophies for p in points),
        max_trophies=max(p.trophies for p in points),
        sample_size=n,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers (used by /predict embed)
# ─────────────────────────────────────────────────────────────────────────────
def format_rank(rank: int | None) -> str:
    """Human-readable rank with a thousand-separator, or '—' when unknown."""
    if rank is None:
        return "—"
    return f"#{rank:,}".replace(",", " ")  # narrow no-break space


def rank_emoji(rank: int | None) -> str:
    """Medal emoji for top ranks, plain ▪ otherwise."""
    if rank is None:
        return "▪"
    if rank <= 10:
        return "🥇"
    if rank <= 100:
        return "🥈"
    if rank <= 1_000:
        return "🥉"
    if rank <= 10_000:
        return "🏅"
    return "▪"
