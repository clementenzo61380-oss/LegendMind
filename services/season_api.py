"""Official CoC season history — reads Supercell's /leagues/.../seasons/... API.

What the official API provides
-------------------------------
- ``GET /v1/leagues/{legend_league_id}/seasons`` → list of season IDs available
  (typically the 5–6 most recent completed seasons, format "YYYY-MM").
  ``legend_league_id`` matches :data:`constants.COC_LEGEND_LEAGUE_ID`.
- ``GET /v1/leagues/{legend_league_id}/seasons/{seasonId}`` → AsyncIterator of
  ``RankedPlayer`` objects from the top-200 worldwide final rankings for
  that season (trophies + rank).

Limitations
-----------
- Only the **top-200** players are returned per season.  Players outside
  the top-200 will get `final_rank=None` but their trophy count is
  stored if we happen to find them in the list.
- The current (active) season is NOT in the list — only completed ones.

Usage
-----
``SeasonApiService.sync_player(tag)`` fetches all available seasons,
looks up the player in each season's top-200, and writes results to
``season_api_history``.  It caches season IDs in-process so repeated
calls don't re-fetch unchanged data.
"""

from __future__ import annotations

import logging

import coc

from constants import COC_LEGEND_LEAGUE_ID
from services.db import Repository

log = logging.getLogger(__name__)

# In-process set of season IDs already synced per player, keyed by tag.
# Prevents redundant API calls within the same process lifetime.
_synced: dict[str, set[str]] = {}


class SeasonApiService:
    """Fetches and caches official season history for a CoC player."""

    def __init__(self, coc_client: coc.Client, repository: Repository) -> None:
        self._coc = coc_client
        self._repo = repository

    async def get_available_season_ids(self) -> list[str]:
        """Return the list of completed Legend season IDs from Supercell.

        Returns seasons sorted newest-first, e.g. ["2026-03", "2026-02", …].
        Returns [] on API error (non-fatal).
        """
        try:
            ids: list[str] = await self._coc.get_seasons(COC_LEGEND_LEAGUE_ID)
            # coc.py returns them oldest-first; reverse so newest is [0].
            return list(reversed(ids))
        except Exception:  # noqa: BLE001
            log.exception("Failed to fetch season IDs from CoC API")
            return []

    async def sync_player(self, player_tag: str, max_seasons: int = 6) -> int:
        """Look up `player_tag` across the last `max_seasons` completed seasons.

        Writes any found entries to ``season_api_history``.
        Returns the number of seasons where the player appeared in the top-200.
        """
        season_ids = await self.get_available_season_ids()
        if not season_ids:
            return 0

        already = _synced.setdefault(player_tag, set())
        found = 0

        for season_id in season_ids[:max_seasons]:
            if season_id in already:
                continue
            rank, trophies = await self._find_player_in_season(
                player_tag,
                season_id,
            )
            if trophies is not None:
                await self._repo.upsert_season_api_entry(
                    player_tag=player_tag,
                    season_id=season_id,
                    trophies=trophies,
                    final_rank=rank,
                )
                found += 1
            already.add(season_id)

        return found

    async def _find_player_in_season(
        self,
        player_tag: str,
        season_id: str,
    ) -> tuple[int | None, int | None]:
        """Search the top-200 ranking for `player_tag`.

        Returns (rank, trophies) if found, (None, None) otherwise.
        The top-200 constraint is a Supercell API limitation — players
        ranked below 200 simply won't appear.
        """
        try:
            async for p in self._coc.get_season_rankings(
                COC_LEGEND_LEAGUE_ID,
                season_id,
            ):
                if p.tag == player_tag:
                    return (
                        int(p.rank) if p.rank else None,
                        int(p.trophies) if p.trophies else None,
                    )
        except Exception:  # noqa: BLE001
            log.exception(
                "Failed to fetch season %s rankings from CoC API",
                season_id,
            )
        return None, None

    async def get_enriched_history(
        self,
        player_tag: str,
        max_seasons: int = 6,
    ) -> list[dict[str, object]]:
        """Return cached season history, triggering a sync if any gaps exist.

        Each dict contains: season_id, trophies, final_rank (None if outside
        top-200), fetched_at.
        """
        await self.sync_player(player_tag, max_seasons=max_seasons)
        return await self._repo.get_season_api_history(player_tag, limit=max_seasons)
