"""Unit tests `LeaderboardService` (cache + MVP) sans BDD."""

from __future__ import annotations

from typing import Any

import pytest

from constants import LeagueType
from models import LeaderboardEntry
from services.cache import InMemoryCache
from services.leaderboard import LeaderboardService


class _RepoStub:
    def __init__(self, rows: list[LeaderboardEntry]) -> None:
        self._rows = rows
        self.calls = 0

    async def list_guild_leaderboard(
        self,
        _guild_id: int,
        **kwargs: Any,
    ) -> list[LeaderboardEntry]:
        self.calls += 1
        return list(self._rows)


@pytest.mark.asyncio
async def test_leaderboard_cache_hits_after_first_call() -> None:
    rows = [
        LeaderboardEntry(
            rank=1,
            player_tag="#A",
            display_name="A",
            discord_user_id=1,
            trophies=5800,
            league_type=LeagueType.LEGEND_II,
            weekly_gain=120,
        ),
    ]
    repo = _RepoStub(rows)
    svc = LeaderboardService(repo, InMemoryCache())  # type: ignore[arg-type]
    a = await svc.get_server_leaderboard(123, limit=10)
    b = await svc.get_server_leaderboard(123, limit=10)
    assert a == b == rows
    assert repo.calls == 1


@pytest.mark.asyncio
async def test_leaderboard_invalidate_guild() -> None:
    rows = [
        LeaderboardEntry(
            rank=1,
            player_tag="#A",
            display_name="A",
            discord_user_id=1,
            trophies=5800,
            league_type=LeagueType.LEGEND_II,
            weekly_gain=120,
        ),
    ]
    repo = _RepoStub(rows)
    svc = LeaderboardService(repo, InMemoryCache())  # type: ignore[arg-type]
    await svc.get_server_leaderboard(123, limit=10)
    await svc.invalidate_guild(123)
    await svc.get_server_leaderboard(123, limit=10)
    assert repo.calls == 2


@pytest.mark.asyncio
async def test_mvp_picks_max_weekly_gain() -> None:
    rows = [
        LeaderboardEntry(
            rank=1,
            player_tag="#A",
            display_name="A",
            discord_user_id=1,
            trophies=5800,
            league_type=LeagueType.LEGEND_II,
            weekly_gain=80,
        ),
        LeaderboardEntry(
            rank=2,
            player_tag="#B",
            display_name="B",
            discord_user_id=2,
            trophies=5700,
            league_type=LeagueType.LEGEND_II,
            weekly_gain=200,
        ),
    ]
    svc = LeaderboardService(_RepoStub(rows), InMemoryCache())  # type: ignore[arg-type]
    mvp = await svc.get_weekly_mvp(123)
    assert mvp is not None and mvp.player_tag == "#B"


@pytest.mark.asyncio
async def test_mvp_returns_none_when_empty() -> None:
    svc = LeaderboardService(_RepoStub([]), InMemoryCache())  # type: ignore[arg-type]
    assert await svc.get_weekly_mvp(123) is None
