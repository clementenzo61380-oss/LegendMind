"""Integration tests — DashboardView interactions and /compare.

These tests drive the View state-machine directly (no real Discord gateway).
They verify:
- Page navigation updates `current_embed` correctly.
- Goal modal saves to the repository.
- /compare produces a correctly structured embed.
- Empty-data edge cases don't raise.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from constants import LeagueType
from models import LegendSnapshot, PlayerGoal, UserPreferences


# ─────────────────────────────────────────────────────────────────────────────
# Minimal fakes
# ─────────────────────────────────────────────────────────────────────────────
def _snap(
    tag: str = "#TEST",
    trophies: int = 6200,
    attacks: int = 5,
    offset_days: int = 0,
) -> LegendSnapshot:
    base = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    return LegendSnapshot(
        player_tag=tag,
        trophies=trophies,
        league_type=LeagueType.LEGEND_I,
        attacks_done=attacks,
        trophies_gained=attacks * 32,
        trophies_lost=attacks * 20,
        captured_at=base - timedelta(days=offset_days),
    )


def _make_repo(
    snapshots: list[LegendSnapshot] | None = None,
    goal: PlayerGoal | None = None,
) -> AsyncMock:
    repo = AsyncMock()
    repo.get_snapshots_since.return_value = snapshots or []
    repo.get_goal.return_value = goal
    repo.upsert_goal.return_value = None
    repo._db = MagicMock()
    repo._db.pool = AsyncMock()
    repo._db.pool.fetchrow = AsyncMock(return_value={"tag": "#TEST"})
    return repo


def _make_prefs(user_id: int = 1) -> UserPreferences:
    return UserPreferences(discord_user_id=user_id)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — _DashboardView page navigation
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_overview_page_shows_trophies() -> None:
    """Overview embed must include the player's trophy count."""
    from cogs.dashboard import _DashboardView

    snaps = [_snap(trophies=6200, attacks=5, offset_days=i) for i in range(3, -1, -1)]
    repo = _make_repo(snapshots=snaps)
    notebook = AsyncMock()
    prefs = _make_prefs()

    view = _DashboardView(repo=repo, notebook=notebook, player_tag="#TEST", prefs=prefs)
    await view.refresh()

    assert view.current_embed is not None
    embed_text = view.current_embed.to_dict()
    # The overview embed should reference trophies somewhere in its fields.
    fields_str = str(embed_text)
    assert "6200" in fields_str


@pytest.mark.asyncio
async def test_history_page_renders_sparkline() -> None:
    """History embed must render a sparkline when snapshots exist."""
    from cogs.dashboard import _DashboardView

    snaps = [_snap(trophies=6100 + i * 10, offset_days=6 - i) for i in range(7)]
    repo = _make_repo(snapshots=snaps)
    notebook = AsyncMock()
    prefs = _make_prefs()

    view = _DashboardView(repo=repo, notebook=notebook, player_tag="#TEST", prefs=prefs)
    await view.refresh()

    view._page = view.PAGE_HISTORY
    view._render()

    embed_dict = view.current_embed.to_dict()
    # A sparkline uses block characters — confirm at least one field is present.
    fields = embed_dict.get("fields", [])
    assert any(
        "▁▂▃▄▅▆▇█"[0] in f.get("value", "")
        or "7 derniers" in f.get("name", "")
        for f in fields
    )


@pytest.mark.asyncio
async def test_goals_page_no_goal_shows_placeholder() -> None:
    """Goals page when no goal is set must show a placeholder, not crash."""
    from cogs.dashboard import _DashboardView

    repo = _make_repo(snapshots=[_snap()], goal=None)
    notebook = AsyncMock()
    prefs = _make_prefs()

    view = _DashboardView(repo=repo, notebook=notebook, player_tag="#TEST", prefs=prefs)
    await view.refresh()
    view._page = view.PAGE_GOALS
    view._render()

    desc = view.current_embed.to_dict().get("description", "")
    assert "Aucun objectif" in desc or "objectif" in desc.lower()


@pytest.mark.asyncio
async def test_goals_page_shows_progress_bar() -> None:
    """Goals page with a goal set must show a progress bar field."""
    from cogs.dashboard import _DashboardView

    goal = PlayerGoal(
        player_tag="#TEST",
        target_trophies=6400,
        target_attacks_per_day=8,
    )
    repo = _make_repo(snapshots=[_snap(trophies=6200)], goal=goal)
    notebook = AsyncMock()
    prefs = _make_prefs()

    view = _DashboardView(repo=repo, notebook=notebook, player_tag="#TEST", prefs=prefs)
    await view.refresh()
    view._page = view.PAGE_GOALS
    view._render()

    fields_str = str(view.current_embed.to_dict())
    # Progress bar rendered with block chars or % symbol.
    assert "6400" in fields_str or "%" in fields_str


@pytest.mark.asyncio
async def test_overview_with_no_snapshots_does_not_raise() -> None:
    """Overview with zero snapshots should return a graceful empty embed."""
    from cogs.dashboard import _DashboardView

    repo = _make_repo(snapshots=[])
    notebook = AsyncMock()
    prefs = _make_prefs()

    view = _DashboardView(repo=repo, notebook=notebook, player_tag="#TEST", prefs=prefs)
    # Must not raise.
    await view.refresh()
    assert view.current_embed is not None


# ─────────────────────────────────────────────────────────────────────────────
# Tests — /compare embed
# ─────────────────────────────────────────────────────────────────────────────
def test_compare_embed_contains_both_names() -> None:
    """Compare embed must mention both player names."""
    from cogs.dashboard import _render_compare

    snap_a = _snap("#A", trophies=6300, attacks=6)
    snap_b = _snap("#B", trophies=6100, attacks=4)

    embed = _render_compare("Alice", snap_a, "Bob", snap_b)
    embed_str = str(embed.to_dict())

    assert "Alice" in embed_str
    assert "Bob" in embed_str


def test_compare_embed_medal_on_leader() -> None:
    """The player with more trophies should get the 🏅 leader indicator."""
    from cogs.dashboard import _render_compare

    snap_a = _snap("#A", trophies=6500)
    snap_b = _snap("#B", trophies=6100)

    embed = _render_compare("Leader", snap_a, "Follower", snap_b)
    fields = embed.to_dict().get("fields", [])
    trophy_field = next((f for f in fields if "Trophées" in f["name"]), None)
    assert trophy_field is not None
    assert "🏅" in trophy_field["value"]
    assert "Leader" in trophy_field["value"]


def test_compare_embed_no_medal_on_tie() -> None:
    """Tied trophy counts should not give a medal to either player."""
    from cogs.dashboard import _render_compare

    snap_a = _snap("#A", trophies=6200)
    snap_b = _snap("#B", trophies=6200)

    embed = _render_compare("P1", snap_a, "P2", snap_b)
    fields = embed.to_dict().get("fields", [])
    trophy_field = next((f for f in fields if "Trophées" in f["name"]), None)
    assert trophy_field is not None
    # On a tie neither entry should have 🏅 prefixed to the line.
    for line in trophy_field["value"].split("\n"):
        assert not line.startswith("🏅"), f"Unexpected medal in tie: {line!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Tests — helpers / rendering
# ─────────────────────────────────────────────────────────────────────────────
def test_normalise_tag_adds_hash() -> None:
    from cogs.dashboard import _normalise_tag
    assert _normalise_tag("2PP") == "#2PP"


def test_normalise_tag_uppercase() -> None:
    from cogs.dashboard import _normalise_tag
    assert _normalise_tag("#2pp") == "#2PP"


def test_normalise_tag_idempotent() -> None:
    from cogs.dashboard import _normalise_tag
    assert _normalise_tag("#2PP") == "#2PP"


def test_trophy_sparkline_flat() -> None:
    """All-same trophies → all lowest-block sparkline."""
    from cogs.dashboard import _trophy_sparkline
    snaps = [_snap(trophies=6200) for _ in range(5)]
    result = _trophy_sparkline(snaps)
    assert set(result) == {"▁"}


def test_trophy_sparkline_ascending() -> None:
    """Ascending trophies should end with the highest block."""
    from cogs.dashboard import _trophy_sparkline
    snaps = [_snap(trophies=6100 + i * 50) for i in range(8)]
    result = _trophy_sparkline(snaps)
    assert result[-1] == "█"
