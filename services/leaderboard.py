"""Classement serveur avec cache TTL (prompt §5)."""
from __future__ import annotations

import logging
from typing import Final

from constants import LeagueType
from models import LeaderboardEntry
from services.cache import InMemoryCache
from services.db import Repository

log = logging.getLogger(__name__)

_CACHE_TTL: Final[int] = 300


class LeaderboardService:
    """Lecture classement + MVP semaine ; invalide le cache à la demande."""

    def __init__(self, repository: Repository, cache: InMemoryCache) -> None:
        self._repo = repository
        self._cache = cache

    def _key(
        self,
        guild_id: int,
        *,
        limit: int,
        legend_only: bool,
        league: LeagueType | None,
    ) -> str:
        lf = league.value if league is not None else -1
        return f"lb:{guild_id}:{limit}:{legend_only}:{lf}"

    async def get_server_leaderboard(
        self,
        guild_id: int,
        *,
        league_filter: LeagueType | None = None,
        limit: int = 10,
        legend_only: bool = True,
    ) -> list[LeaderboardEntry]:
        """Classement avec cache 5 min."""
        key = self._key(guild_id, limit=limit, legend_only=legend_only, league=league_filter)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        rows = await self._repo.list_guild_leaderboard(
            guild_id,
            limit=limit,
            legend_only=legend_only,
            league_filter=league_filter,
        )
        await self._cache.set(key, rows, ttl=_CACHE_TTL)
        return rows

    async def get_weekly_mvp(self, guild_id: int) -> LeaderboardEntry | None:
        """Joueur avec le plus fort gain net sur 7 jours (snapshots)."""
        rows = await self.get_server_leaderboard(
            guild_id,
            league_filter=None,
            limit=50,
            legend_only=False,
        )
        if not rows:
            return None
        return max(rows, key=lambda e: e.weekly_gain)

    async def invalidate_guild(self, guild_id: int) -> None:
        await self._cache.invalidate_prefix(f"lb:{guild_id}:")
