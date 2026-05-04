"""Unit tests for ``DailyDigestService`` (no Discord HTTP)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from constants import LeagueType
from models import LegendSnapshot
from services.digest import DailyDigestService


class _FakeRank:
    """Minimal stub — digest only needs an object with ``curve`` etc."""

    curve = None

    def estimate_current_rank(self, _trophies: int) -> None:
        return None

    def leaderboard_age_minutes(self) -> float:
        return 0.0


class _FakeRepoEmpty:
    async def list_active_accounts(self, _uid: int) -> list[tuple[str, str | None, LeagueType]]:
        return []

    async def get_latest_snapshot(self, _tag: str) -> None:
        return None

    async def get_snapshots_since(
        self,
        _tag: str,
        _since: datetime,
    ) -> list[LegendSnapshot]:
        return []


@pytest.mark.asyncio
async def test_build_embeds_burns_day_when_no_accounts() -> None:
    svc = DailyDigestService(
        bot=Any,  # type: ignore[arg-type]
        repository=_FakeRepoEmpty(),  # type: ignore[arg-type]
        rank_predictor=_FakeRank(),  # type: ignore[arg-type]
    )
    embeds, burn = await svc._build_embeds_for_user(1)
    assert embeds == []
    assert burn is True


class _FakeRepoUnknownTier:
    async def list_active_accounts(self, _uid: int) -> list[tuple[str, str | None, LeagueType]]:
        return [("#ABC", "n", LeagueType.UNKNOWN)]

    async def get_latest_snapshot(self, _tag: str) -> LegendSnapshot:
        return LegendSnapshot(
            player_tag="#ABC",
            trophies=5000,
            league_type=LeagueType.UNKNOWN,
            attacks_done=0,
            trophies_gained=0,
            trophies_lost=0,
            captured_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
        )

    async def get_snapshots_since(
        self,
        _tag: str,
        _since: datetime,
    ) -> list[LegendSnapshot]:
        return []


@pytest.mark.asyncio
async def test_build_embeds_burns_day_when_all_tiers_unknown() -> None:
    svc = DailyDigestService(
        bot=Any,  # type: ignore[arg-type]
        repository=_FakeRepoUnknownTier(),  # type: ignore[arg-type]
        rank_predictor=_FakeRank(),  # type: ignore[arg-type]
    )
    embeds, burn = await svc._build_embeds_for_user(1)
    assert embeds == []
    assert burn is True
