"""LegendPoller cog — periodic CoC API polling with snapshots.

Pipeline per cycle:
1. Repository.get_active_players_for_polling() → fill the queue.
2. For each player: fetch from CoC API (with backoff on 429/timeout).
3. Build the current LegendSnapshot.
4. Compute AttackDelta against the latest stored snapshot.
5. Persist the new snapshot ONLY when state changed (avoids row spam).
6. If new attacks detected → fan out to the analysis pipeline (later steps).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import coc
import discord
from discord.ext import commands, tasks

from constants import (
    API_RETRY_MAX_ATTEMPTS,
    POLL_BACKOFF_BASE_SECONDS,
    POLL_BACKOFF_JITTER,
    POLL_BACKOFF_MAX_SECONDS,
    POLL_BACKOFF_MULTIPLIER,
    POLL_INTERVAL_LEGEND_I_SECONDS,
    POLL_INTERVAL_LEGEND_II_III_SECONDS,
    LeagueType,
)
from models import AttackDelta, LegendSnapshot, PollTarget
from services.db import Repository
from services.game_tuning import get_tuning
from services.metrics_collector import MetricsCollector

log = logging.getLogger(__name__)

_AGENT_DEBUG_LOG = "/Users/enzoclement/coc-bot/.cursor/debug-15bc98.log"


def _agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, object],
    *,
    run_id: str = "fix-verify",
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "15bc98",
            "timestamp": int(time.time() * 1000),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
        }
        with open(_AGENT_DEBUG_LOG, "a", encoding="utf-8") as df:
            df.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # #endregion


@dataclass(slots=True)
class _PollTask:
    target: PollTarget
    attempts: int = 0


class LegendPoller(commands.Cog):
    """Periodic poller. Drives the entire snapshot/alert pipeline.

    The cog owns three things only:
    - the asyncio.Queue of pending poll tasks
    - the discord.ext.tasks loop that refills it
    - the worker coroutines that drain it

    All side effects (DB writes, alert dispatch) go through injected
    services — never inlined here.
    """

    def __init__(
        self,
        bot: commands.Bot,
        coc_client: coc.Client,
        repository: Repository,
        poll_interval_seconds: int,
        queue_max: int,
        worker_count: int = 4,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        self.bot = bot
        self._coc = coc_client
        self._repo = repository
        self._metrics = metrics_collector
        # Two queues — Legend I burns API quota fast, Legend II/III is sparse.
        self._queue: asyncio.Queue[_PollTask] = asyncio.Queue(maxsize=queue_max)
        self._slow_queue: asyncio.Queue[_PollTask] = asyncio.Queue(maxsize=queue_max)
        self._workers: list[asyncio.Task[None]] = []
        self._worker_count = worker_count
        self._delta_subscribers: list[Callable[[AttackDelta], Awaitable[None]]] = []
        self._fast_poll_seconds = poll_interval_seconds
        # Legend I : intervalle issu de la config bot ; II/III : ``game_tuning``.
        self._fast_loop.change_interval(seconds=poll_interval_seconds)
        self._slow_loop.change_interval(
            seconds=get_tuning().poll_interval_legend_ii_iii_seconds,
        )

    def apply_tuning_poll_intervals(self) -> None:
        """Recharge les intervalles depuis ``game_tuning`` (après patch JSON)."""
        tun = get_tuning()
        self._fast_loop.change_interval(seconds=tun.poll_interval_legend_i_seconds)
        self._slow_loop.change_interval(seconds=tun.poll_interval_legend_ii_iii_seconds)
        log.info(
            "LegendPoller: intervalles polling → fast=%ds, slow=%ds",
            tun.poll_interval_legend_i_seconds,
            tun.poll_interval_legend_ii_iii_seconds,
        )

    # ── lifecycle ────────────────────────────────────────────────────────
    async def cog_load(self) -> None:
        for i in range(self._worker_count):
            self._workers.append(
                asyncio.create_task(
                    self._worker_run(i, self._queue),
                    name=f"poll-fast-{i}",
                )
            )
        # One slow worker is enough — quotas are gentle on Legend II/III cohort.
        self._workers.append(
            asyncio.create_task(
                self._worker_run(99, self._slow_queue),
                name="poll-slow",
            )
        )
        self._fast_loop.start()
        self._slow_loop.start()
        log.info(
            "LegendPoller started: fast=%ds (Legend I), slow=%ds (II/III), fast workers=%d",
            self._fast_poll_seconds,
            get_tuning().poll_interval_legend_ii_iii_seconds,
            self._worker_count,
        )

    async def cog_unload(self) -> None:
        self._fast_loop.cancel()
        self._slow_loop.cancel()
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    # ── public API ───────────────────────────────────────────────────────
    def subscribe_to_deltas(
        self,
        callback: Callable[[AttackDelta], Awaitable[None]],
    ) -> None:
        """Register a coroutine ``async (delta: AttackDelta) -> None``.

        Called once per non-trivial delta. Subscribers must not raise.
        """
        self._delta_subscribers.append(callback)

    # ── refill loops (fast = Legend I, slow = Legend II/III/unknown) ────
    @tasks.loop(seconds=POLL_INTERVAL_LEGEND_I_SECONDS)
    async def _fast_loop(self) -> None:
        await self._refill(legend_i_only=True)

    @tasks.loop(seconds=POLL_INTERVAL_LEGEND_II_III_SECONDS)
    async def _slow_loop(self) -> None:
        await self._refill(legend_i_only=False)

    async def _refill(self, *, legend_i_only: bool) -> None:
        try:
            targets = await self._repo.get_active_players_for_polling()
        except Exception:  # noqa: BLE001
            log.exception("Failed to load polling targets")
            return
        queue = self._queue if legend_i_only else self._slow_queue
        for t in targets:
            is_legend_i = t.legend_tier is LeagueType.LEGEND_I
            if legend_i_only and not is_legend_i:
                continue
            if not legend_i_only and is_legend_i:
                continue
            try:
                queue.put_nowait(_PollTask(target=t))
            except asyncio.QueueFull:
                log.warning(
                    "%s poll queue full; dropping %s",
                    "Fast" if legend_i_only else "Slow",
                    t.player_tag,
                )
        if self._metrics:
            await self._metrics.set_queue_depth(
                self._queue.qsize() + self._slow_queue.qsize(),
            )

    @_fast_loop.before_loop
    async def _before_fast_loop(self) -> None:
        try:
            await self.bot.wait_until_ready()
        except (asyncio.CancelledError, RuntimeError):
            return

    @_slow_loop.before_loop
    async def _before_slow_loop(self) -> None:
        try:
            await self.bot.wait_until_ready()
        except (asyncio.CancelledError, RuntimeError):
            return

    # ── workers ──────────────────────────────────────────────────────────
    async def _worker_run(
        self,
        idx: int,
        queue: asyncio.Queue[_PollTask],
    ) -> None:
        while True:
            task = await queue.get()
            try:
                await self._process_task(task)
            except Exception:  # noqa: BLE001
                log.exception(
                    "Unhandled error in worker %d for %s",
                    idx,
                    task.target.player_tag,
                )
            finally:
                queue.task_done()

    def enqueue_immediate(self, target: PollTarget) -> bool:
        """Admin / debug : injecte une cible en tête de traitement.

        Returns True if enqueued, False if the queue is full.
        Routée selon le tier — Legend I dans la file rapide, sinon lente.
        """
        queue = (
            self._queue
            if target.legend_tier is LeagueType.LEGEND_I
            else self._slow_queue
        )
        try:
            queue.put_nowait(_PollTask(target=target))
            return True
        except asyncio.QueueFull:
            log.warning(
                "enqueue_immediate: queue full, dropping %s", target.player_tag
            )
            return False

    async def _process_task(self, task: _PollTask) -> None:
        """Fetch → snapshot → diff → persist → fan out."""
        target = task.target
        t0 = time.perf_counter()
        fetch_ok = False
        try:
            player = await self._fetch_with_backoff(target.player_tag)
            fetch_ok = True
        except coc.errors.NotFound:
            log.info("Player %s gone (404); deactivating", target.player_tag)
            _agent_debug_log(
                "H1",
                "tracker.py:_process_task:NotFound",
                "coc NotFound branch entered",
                {
                    "tag": target.player_tag,
                    "discord_user_id": target.discord_user_id,
                },
            )
            try:
                deactivated = await self._repo.deactivate_player(
                    target.player_tag, target.discord_user_id
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "Failed to deactivate missing player %s", target.player_tag
                )
                deactivated = False
            _agent_debug_log(
                "H1",
                "tracker.py:_process_task:NotFound:after_deactivate",
                "deactivate_player result",
                {"tag": target.player_tag, "deactivated": deactivated},
            )
        except Exception:  # noqa: BLE001
            log.exception("API failure for %s — abandoning cycle", target.player_tag)
        finally:
            if self._metrics:
                await self._metrics.record_poll(
                    (time.perf_counter() - t0) * 1000.0,
                    success=fetch_ok,
                )

        if not fetch_ok:
            return

        current = self._snapshot_from_player(player, target.legend_tier)
        previous = await self._repo.get_latest_snapshot(target.player_tag)
        await self._repo.mark_polled(target.player_tag, datetime.now(timezone.utc))

        # Refresh clan info on every poll — cheap UPDATE, always up-to-date.
        clan = getattr(player, "clan", None)
        await self._repo.update_clan_info(
            target.player_tag,
            clan_tag=getattr(clan, "tag", None),
            clan_name=getattr(clan, "name", None),
        )

        if previous is not None and _is_unchanged(previous, current):
            return  # nothing happened → no row written, no events fired

        await self._repo.save_snapshot(current)
        if previous is None:
            return  # first snapshot for this player → nothing to diff yet

        delta = AttackDelta.between(previous, current)
        await self._maybe_sync_league_roles(target, delta)
        await self._fanout_delta(delta)

    async def _maybe_sync_league_roles(
        self,
        target: PollTarget,
        delta: AttackDelta,
    ) -> None:
        """Met à jour les rôles Discord si la ligue Legend change (prompt §6)."""
        if delta.previous.league_type == delta.current.league_type:
            return
        if target.guild_id is None:
            return
        cfg = await self._repo.get_guild_config(target.guild_id)
        mapping = {
            LeagueType.LEGEND_I: cfg.legend_role_i_id,
            LeagueType.LEGEND_II: cfg.legend_role_ii_id,
            LeagueType.LEGEND_III: cfg.legend_role_iii_id,
        }
        old_id = mapping.get(delta.previous.league_type)
        new_id = mapping.get(delta.current.league_type)
        if old_id is None and new_id is None:
            return
        guild = self.bot.get_guild(target.guild_id)
        if guild is None:
            return
        member = guild.get_member(target.discord_user_id)
        if member is None:
            try:
                member = await guild.fetch_member(target.discord_user_id)
            except discord.HTTPException:
                log.warning("Role sync: membre %s introuvable", target.discord_user_id)
                return
        try:
            if old_id:
                r_old = guild.get_role(old_id)
                if r_old and r_old in member.roles:
                    await member.remove_roles(r_old, reason="LegendMind — ligue")
            if new_id:
                r_new = guild.get_role(new_id)
                if r_new:
                    await member.add_roles(r_new, reason="LegendMind — ligue")
        except discord.Forbidden:
            log.warning("Role sync: permissions insuffisantes sur %s", guild.id)
        if cfg.alerts_channel_id:
            ch = guild.get_channel(cfg.alerts_channel_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(
                        f"<@{target.discord_user_id}> "
                        f"**Ligue** : {delta.previous.league_type.name} → "
                        f"{delta.current.league_type.name}",
                    )
                except discord.HTTPException:
                    log.warning("Impossible d'annoncer le changement de ligue")

    # ── helpers ──────────────────────────────────────────────────────────
    async def _fetch_with_backoff(self, tag: str) -> coc.Player:
        """Retry the CoC fetch on transient errors with exponential backoff."""
        delay = POLL_BACKOFF_BASE_SECONDS
        last_exc: Exception | None = None
        for attempt in range(1, API_RETRY_MAX_ATTEMPTS + 1):
            try:
                return await self._coc.get_player(tag)
            except (coc.errors.Maintenance, coc.errors.GatewayError, asyncio.TimeoutError) as exc:
                last_exc = exc
            except coc.errors.HTTPException as exc:
                if exc.status != 429:
                    raise
                last_exc = exc
            jitter = random.uniform(-POLL_BACKOFF_JITTER, POLL_BACKOFF_JITTER) * delay
            sleep_for = min(POLL_BACKOFF_MAX_SECONDS, delay + jitter)
            log.warning(
                "Backoff %.1fs (attempt %d/%d) for %s: %r",
                sleep_for,
                attempt,
                API_RETRY_MAX_ATTEMPTS,
                tag,
                last_exc,
            )
            await asyncio.sleep(max(0.5, sleep_for))
            delay = min(POLL_BACKOFF_MAX_SECONDS, delay * POLL_BACKOFF_MULTIPLIER)
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _snapshot_from_player(
        player: coc.Player,
        tier: LeagueType,
    ) -> LegendSnapshot:
        """Map a coc.Player into our domain snapshot.

        Legend statistics live under `player.legend_statistics`. When
        absent (player not in Legend), zero-fill the activity counters.

        ``tier`` is the user-declared Legend tier (Avril 2026 refonte) read
        from ``players.legend_tier`` — NOT inferred from trophies. Falls
        back to ``UNKNOWN`` when the user hasn't declared yet.
        """
        ls = player.legend_statistics
        attacks_done = getattr(ls, "current_season", None)
        attacks = getattr(attacks_done, "num_attacks", 0) if attacks_done else 0
        gained = getattr(attacks_done, "trophies_gained", 0) if attacks_done else 0
        lost = getattr(attacks_done, "trophies_lost", 0) if attacks_done else 0

        return LegendSnapshot(
            player_tag=player.tag,
            trophies=player.trophies,
            league_type=tier,
            attacks_done=int(attacks or 0),
            trophies_gained=int(gained or 0),
            trophies_lost=int(lost or 0),
            captured_at=datetime.now(timezone.utc),
        )

    async def _fanout_delta(self, delta: AttackDelta) -> None:
        """Notify all subscribers; isolate failures so one bad cb won't kill the cycle."""
        for cb in self._delta_subscribers:
            try:
                await cb(delta)
            except Exception:  # noqa: BLE001
                log.exception("Delta subscriber raised; continuing")


def _is_unchanged(previous: LegendSnapshot, current: LegendSnapshot) -> bool:
    """True when both snapshots carry the same observable state."""
    return (
        previous.trophies == current.trophies
        and previous.attacks_done == current.attacks_done
        and previous.trophies_gained == current.trophies_gained
        and previous.trophies_lost == current.trophies_lost
        and previous.league_type == current.league_type
    )
