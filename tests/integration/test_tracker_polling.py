"""Integration tests — LegendPoller pipeline (no real DB, no real Discord).

Tests the full polling cycle end-to-end with injected fakes, verifying:
- Snapshot persistence on state change.
- Deduplication when state is unchanged.
- Delta fan-out to subscribers.
- Backoff and retry behaviour on transient CoC API errors.
- Per-tier queue routing (Legend I → fast queue, II/III → slow queue).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constants import LeagueType
from models import AttackDelta, LegendSnapshot, PollTarget


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / minimal fakes
# ─────────────────────────────────────────────────────────────────────────────
def _make_snap(
    tag: str = "#TEST",
    trophies: int = 6200,
    attacks: int = 5,
    league: LeagueType = LeagueType.LEGEND_I,
    offset_s: int = 0,
) -> LegendSnapshot:
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    return LegendSnapshot(
        player_tag=tag,
        trophies=trophies,
        league_type=league,
        attacks_done=attacks,
        trophies_gained=attacks * 32,
        trophies_lost=attacks * 20,
        captured_at=base.replace(second=offset_s),
    )


def _make_poll_target(
    tag: str = "#TEST",
    tier: LeagueType = LeagueType.LEGEND_I,
) -> PollTarget:
    return PollTarget(
        player_tag=tag,
        discord_user_id=123,
        guild_id=456,
        last_polled_at=None,
        legend_tier=tier,
    )


class _FakeCocPlayer:
    def __init__(self, tag: str, trophies: int, attacks: int = 5) -> None:
        self.tag = tag
        self.trophies = trophies

        class _Season:
            num_attacks = attacks
            trophies_gained = attacks * 32
            trophies_lost = attacks * 20

        class _LegendStats:
            current_season = _Season()

        self.legend_statistics = _LegendStats()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_snapshot_saved_when_state_changes() -> None:
    """A new snapshot is persisted when trophies change between polls."""
    from cogs.tracker import LegendPoller

    repo = AsyncMock()
    repo.get_active_players_for_polling.return_value = [
        _make_poll_target("#TESTCHANGE"),
    ]
    previous = _make_snap("#TESTCHANGE", trophies=6150, attacks=3)
    repo.get_latest_snapshot.return_value = previous
    repo.save_snapshot.return_value = True
    repo.mark_polled.return_value = None

    coc_client = AsyncMock()
    coc_client.get_player.return_value = _FakeCocPlayer("#TESTCHANGE", 6200, 5)

    bot = MagicMock()
    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=180,
        queue_max=100,
    )

    received_deltas: list[AttackDelta] = []

    async def _collect(delta: AttackDelta) -> None:
        received_deltas.append(delta)

    poller.subscribe_to_deltas(_collect)

    # Directly call _process_task bypassing the queue loop.
    from cogs.tracker import _PollTask

    await poller._process_task(_PollTask(target=_make_poll_target("#TESTCHANGE")))

    repo.save_snapshot.assert_awaited_once()
    assert len(received_deltas) == 1
    delta = received_deltas[0]
    assert delta.current.trophies == 6200
    assert delta.previous.trophies == 6150
    assert delta.net_trophies == 50


@pytest.mark.asyncio
async def test_snapshot_not_saved_when_unchanged() -> None:
    """No snapshot is written and no delta is fired when state is identical."""
    from cogs.tracker import LegendPoller, _PollTask

    repo = AsyncMock()
    repo.get_active_players_for_polling.return_value = [_make_poll_target()]
    repo.mark_polled.return_value = None

    snap = _make_snap(trophies=6200, attacks=5)
    repo.get_latest_snapshot.return_value = snap

    # API returns the exact same observable state.
    coc_client = AsyncMock()
    coc_client.get_player.return_value = _FakeCocPlayer("#TEST", 6200, 5)

    bot = MagicMock()
    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=180,
        queue_max=100,
    )
    received: list[AttackDelta] = []

    async def _collect_sync(d: AttackDelta) -> None:
        received.append(d)

    poller.subscribe_to_deltas(_collect_sync)

    await poller._process_task(_PollTask(target=_make_poll_target()))

    repo.save_snapshot.assert_not_awaited()
    assert received == []


@pytest.mark.asyncio
async def test_first_snapshot_saved_no_delta_fired() -> None:
    """First ever snapshot is saved but no delta (no previous to diff against)."""
    from cogs.tracker import LegendPoller, _PollTask

    repo = AsyncMock()
    repo.get_latest_snapshot.return_value = None  # first poll
    repo.save_snapshot.return_value = True
    repo.mark_polled.return_value = None

    coc_client = AsyncMock()
    coc_client.get_player.return_value = _FakeCocPlayer("#NEW", 6100, 4)

    bot = MagicMock()
    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=180,
        queue_max=100,
    )
    fired: list[AttackDelta] = []

    async def _collect_fired(d: AttackDelta) -> None:
        fired.append(d)

    poller.subscribe_to_deltas(_collect_fired)

    await poller._process_task(_PollTask(target=_make_poll_target("#NEW")))

    repo.save_snapshot.assert_awaited_once()
    assert fired == [], "No delta should fire on first snapshot"


@pytest.mark.asyncio
async def test_backoff_retries_on_429() -> None:
    """Poller retries on HTTP 429 and eventually succeeds."""
    import coc

    from cogs.tracker import LegendPoller

    call_count = 0

    async def _flaky_get(tag: str) -> _FakeCocPlayer:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Pass status as int — coc.HTTPException only reads .status from
            # ClientResponse or int; MagicMock would fall to the else branch
            # and set status=0, which would not be caught as a 429.
            raise coc.errors.HTTPException(429, {"reason": "throttled"})
        return _FakeCocPlayer(tag, 6200, 5)

    repo = AsyncMock()
    repo.get_latest_snapshot.return_value = None
    repo.save_snapshot.return_value = True
    repo.mark_polled.return_value = None

    coc_client = MagicMock()
    coc_client.get_player = _flaky_get

    bot = MagicMock()
    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=180,
        queue_max=100,
    )

    # Patch asyncio.sleep to avoid actually waiting during tests.
    with patch("cogs.tracker.asyncio.sleep", new_callable=AsyncMock):
        from cogs.tracker import _PollTask

        await poller._process_task(_PollTask(target=_make_poll_target()))

    assert call_count == 3
    repo.save_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_legend_i_target_goes_to_fast_queue() -> None:
    """Legend I target is enqueued into the fast (high-priority) queue."""
    from cogs.tracker import LegendPoller

    repo = AsyncMock()
    bot = MagicMock()
    coc_client = MagicMock()
    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=180,
        queue_max=100,
    )

    t = _make_poll_target("#L1", tier=LeagueType.LEGEND_I)
    poller.enqueue_immediate(t)

    assert poller._queue.qsize() == 1
    assert poller._slow_queue.qsize() == 0


@pytest.mark.asyncio
async def test_legend_iii_target_goes_to_slow_queue() -> None:
    """Legend III target is enqueued into the slow (low-priority) queue."""
    from cogs.tracker import LegendPoller

    repo = AsyncMock()
    bot = MagicMock()
    coc_client = MagicMock()
    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=180,
        queue_max=100,
    )

    t = _make_poll_target("#L3", tier=LeagueType.LEGEND_III)
    poller.enqueue_immediate(t)

    assert poller._slow_queue.qsize() == 1
    assert poller._queue.qsize() == 0


@pytest.mark.asyncio
async def test_subscriber_exception_does_not_kill_pipeline() -> None:
    """A crashing delta subscriber must not propagate and stop other subs."""
    from cogs.tracker import LegendPoller, _PollTask

    repo = AsyncMock()
    previous = _make_snap(trophies=6100, attacks=3)
    repo.get_latest_snapshot.return_value = previous
    repo.save_snapshot.return_value = True
    repo.mark_polled.return_value = None

    coc_client = AsyncMock()
    coc_client.get_player.return_value = _FakeCocPlayer("#TEST", 6200, 5)

    bot = MagicMock()
    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=180,
        queue_max=100,
    )

    second_called = False

    async def _crashing(delta: AttackDelta) -> None:
        raise RuntimeError("subscriber boom")

    async def _second(delta: AttackDelta) -> None:
        nonlocal second_called
        second_called = True

    poller.subscribe_to_deltas(_crashing)
    poller.subscribe_to_deltas(_second)

    # Should not raise despite _crashing blowing up.
    await poller._process_task(_PollTask(target=_make_poll_target()))
    assert second_called, "Second subscriber must still fire after first crashes"
