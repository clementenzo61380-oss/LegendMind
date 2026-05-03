"""Integration tests Repository (PostgreSQL).

Skip si ``DATABASE_URL_TEST`` n'est pas défini : la CI publique n'a pas
forcément Postgres ; en local, exporter une URL vers une base jetable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from constants import LeagueType
from models import LegendSnapshot
from services.db import Database, Repository


@pytest.mark.asyncio
async def test_link_and_snapshot_roundtrip(db_url_for_integration: str | None) -> None:
    if not db_url_for_integration:
        pytest.skip("DATABASE_URL_TEST non défini")
    db = Database(db_url_for_integration)
    await db.connect()
    repo = Repository(db)
    try:
        await repo.link_player("#TEST123", 1, None, "TestPlayer")
        snap = LegendSnapshot(
            player_tag="#TEST123",
            trophies=5500,
            league_type=LeagueType.LEGEND_II,
            attacks_done=1,
            trophies_gained=20,
            trophies_lost=0,
            captured_at=datetime.now(timezone.utc),
        )
        ok = await repo.save_snapshot(snap)
        assert ok is True
        latest = await repo.get_latest_snapshot("#TEST123")
        assert latest is not None and latest.trophies == 5500
    finally:
        await db.close()
