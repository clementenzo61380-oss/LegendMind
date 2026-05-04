"""LegendMind V3 — entrypoint.

Wires config → coc.Client → Database/Repository → Discord bot → cogs.
Stays small on purpose; nothing here should know domain logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time as _dbg_time
from pathlib import Path

import coc
import discord
from discord.ext import commands

from cogs.admin import AdminCog
from cogs.attack_feedback import AttackFeedbackCog
from cogs.billing import BillingCog
from cogs.coach import CoachCog
from cogs.dashboard import DashboardCog
from cogs.guild_admin import GuildAdminCog
from cogs.leaderboard import LeaderboardCog
from cogs.notebook import NotebookCog
from cogs.seasons import SeasonCog
from cogs.tracker import LegendPoller
from config import Config, load_config
from models import AttackDelta
from services.alerts import AlertManager
from services.attack_recap import WeeklyAttackRecapService
from services.billing import BillingService
from services.cache import InMemoryCache
from services.daily_legend_export import DailyLegendExportService, DailyLegendExportSettings
from services.db import Database, Repository
from services.digest import DailyDigestService
from services.leaderboard import LeaderboardService
from services.metrics_collector import MetricsCollector
from services.notebook import ErrorNotebookService
from services.patch_sync import PatchNotesSyncService
from services.quota import QuotaService
from services.rank_predictor import RankPredictor
from services.recap import WeeklyRecapService
from services.season_api import SeasonApiService
from services.stripe_webhook import StripeWebhookServer
from services.debug_ndjson import debug_ndjson

_AGENT_DEBUG_MAIN = "/Users/enzoclement/coc-bot/.cursor/debug-15bc98.log"


def _agent_debug_main(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, object],
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "15bc98",
            "timestamp": int(_dbg_time.time() * 1000),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "runId": "fix-verify",
        }
        with open(_AGENT_DEBUG_MAIN, "a", encoding="utf-8") as df:
            df.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # #endregion


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

async def _purge_global_slash_commands(bot: commands.Bot) -> None:
    """Delete all global app commands on Discord.

    This is a one-shot maintenance tool to remove 'duplicate' commands after
    migrating to guild-only sync. It preserves the local tree by restoring
    commands after the empty sync.
    """
    log = logging.getLogger("legendmind.main")
    cmds = bot.tree.get_commands(guild=None)
    if not cmds:
        log.info("Global command purge: no local commands found; syncing empty anyway")
    log.warning("Purging GLOBAL slash commands (%d) — this affects all servers", len(cmds))
    debug_ndjson(
        hypothesis_id="DUP",
        location="main.py:_purge_global_slash_commands:before",
        message="purging global commands",
        data={"local_global_cmds": len(cmds)},
    )
    bot.tree.clear_commands(guild=None)
    try:
        await bot.tree.sync()
    finally:
        # Restore local tree for guild sync / runtime usage.
        for c in cmds:
            bot.tree.add_command(c, override=True)
    debug_ndjson(
        hypothesis_id="DUP",
        location="main.py:_purge_global_slash_commands:after",
        message="purge done",
        data={},
    )


async def _discord_wait_ready(bot: discord.Client, loop_name: str) -> None:
    """Guard wait_until_ready for shutdown races / cancel during login.

    When the client tears down mid-flight (Ctrl+C cluster), discord.py may
    raise RuntimeError from wait_until_ready. Background loops must swallow
    that instead of bubbling out of asyncio.run().
    """
    # #region agent log
    _agent_debug_main(
        "SHUT",
        "main.py:_discord_wait_ready:enter",
        "wait_until_ready entry",
        {"loop": loop_name, "closed": bot.is_closed()},
    )
    # #endregion
    if bot.is_closed():
        return
    try:
        await bot.wait_until_ready()
    except asyncio.CancelledError:
        raise
    except RuntimeError as exc:
        _agent_debug_main(
            "SHUT",
            "main.py:_discord_wait_ready:skip",
            "wait_until_ready aborted",
            {"loop": loop_name, "exc_type": type(exc).__name__, "exc": str(exc)[:160]},
        )
        return


async def _run(config: Config) -> None:  # noqa: PLR0915 — entry point wiring is linear by design
    log = logging.getLogger("legendmind.main")

    db = Database(config.database_url, ssl=config.database_use_ssl)
    await db.connect()
    repo = Repository(db)
    await repo.ensure_active_season()

    # timeout=10 : si l'API CoC ne répond pas en 10s, on lève une exception
    # immédiatement au lieu d'attendre 30s (défaut). Évite les /setup qui
    # "tournent" 30 secondes avant d'afficher une erreur.
    coc_client = coc.Client(timeout=10.0)
    await coc_client.login(config.coc_email, config.coc_password)

    intents = discord.Intents.default()
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    patch_sync = PatchNotesSyncService(
        url=config.game_tuning_url,
        poll_interval_seconds=config.game_tuning_poll_seconds,
        bot=bot,
    )

    metrics = MetricsCollector()
    cache = InMemoryCache()
    leaderboard_service = LeaderboardService(repo, cache)

    notebook_service = ErrorNotebookService(repo)
    billing = BillingService(
        repository=repo,
        stripe_api_key=config.stripe_api_key,
        stripe_price_id_monthly=config.stripe_price_id_monthly,
        stripe_success_url=config.stripe_success_url,
        stripe_cancel_url=config.stripe_cancel_url,
        lifetime_entitled_discord_ids=config.lifetime_entitled_discord_ids,
        extended_trial_guild_ids=config.extended_trial_guild_ids,
        extended_trial_days=config.extended_trial_days,
    )
    quota = QuotaService(repository=repo, billing=billing)

    alert_manager = AlertManager(
        bot=bot,
        repository=repo,
        default_cooldown_seconds=config.alert_cooldown_default_seconds,
        metrics_collector=metrics,
        quota_service=quota,
    )

    poller = LegendPoller(
        bot=bot,
        coc_client=coc_client,
        repository=repo,
        poll_interval_seconds=config.poll_interval_seconds,
        queue_max=config.poll_queue_max,
        metrics_collector=metrics,
    )

    async def _on_delta(delta: AttackDelta) -> None:
        owner_id = await _owner_for_tag_cache.get_or_fetch(delta.current.player_tag)
        if owner_id is None:
            _agent_debug_main(
                "H2",
                "main.py:_on_delta:no_owner",
                "skipping delta: no discord owner for tag",
                {"tag": delta.current.player_tag},
            )
            return
        prefs = await repo.get_preferences(owner_id)
        await alert_manager.evaluate_and_dispatch(delta, prefs)
        try:
            await repo.bump_hourly_metrics(delta)
        except Exception:  # noqa: BLE001
            log.exception("Hourly metrics rollup failed for %s", delta.current.player_tag)

    # Tag → owner is read directly from the players table; cache it briefly
    # to avoid one DB round-trip per delta.
    _owner_for_tag_cache = _OwnerCache(repo)
    poller.subscribe_to_deltas(_on_delta)

    async def _bot_metrics_hourly_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                chunk = await metrics.prepare_hourly_flush()
                if chunk["polls_total"] or chunk["errors_total"] or chunk["alerts_sent"]:
                    await repo.merge_bot_metrics_hourly(chunk)
                await metrics.commit_hourly_flush()
            except Exception:  # noqa: BLE001
                log.exception("Hourly bot_metrics flush failed")

    metrics_flush_task = asyncio.create_task(_bot_metrics_hourly_loop())

    recap_service = WeeklyRecapService(bot=bot, repository=repo)

    async def _weekly_recap_loop() -> None:
        """Send the Sunday 22h UTC digest to Legend II/III opted-in users.

        Runs a coarse 5-min check loop (cheap) and only fires when we hit
        the (Sunday, 22h UTC) boundary. The recap service itself dedupes
        per (tag, week) so multiple ticks within the same hour are safe.
        """
        from services.game_tuning import get_tuning

        try:
            await _discord_wait_ready(bot, "weekly_recap_loop")
        except asyncio.CancelledError:
            return
        if bot.is_closed():
            return
        while True:
            try:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                tun = get_tuning()
                if (
                    now.weekday() == tun.weekly_recap_day_of_week
                    and now.hour == tun.weekly_recap_hour_utc
                ):
                    sent = await recap_service.run()
                    if sent:
                        log.info("Weekly recap dispatched to %d users", sent)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Weekly recap loop iteration failed")
            await asyncio.sleep(300)

    weekly_recap_task = asyncio.create_task(_weekly_recap_loop())

    # ── Recap attaques du lundi — Legend I ───────────────────────────────
    attack_recap_service = WeeklyAttackRecapService(bot=bot, repository=repo)

    async def _attack_recap_loop() -> None:
        """Lundi matin : recap hebdo des attaques faibles pour Legend I.

        Tick toutes les 5 min, ne s'exécute que (lundi, ATTACK_RECAP_HOUR_UTC).
        La déduplication via alert_history garantit 1 seul DM par semaine.
        """
        from constants import ATTACK_RECAP_DAY_OF_WEEK, ATTACK_RECAP_HOUR_UTC

        try:
            await _discord_wait_ready(bot, "attack_recap_loop")
        except asyncio.CancelledError:
            return
        if bot.is_closed():
            return
        while True:
            try:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                if (
                    now.weekday() == ATTACK_RECAP_DAY_OF_WEEK
                    and now.hour == ATTACK_RECAP_HOUR_UTC
                ):
                    sent = await attack_recap_service.run()
                    if sent:
                        log.info("Attack recap (lundi) dispatched to %d users", sent)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Attack recap loop iteration failed")
            await asyncio.sleep(300)

    attack_recap_task = asyncio.create_task(_attack_recap_loop())

    # Rank predictor — fetches the global Legend leaderboard every TTL and
    # fits a log-linear curve so we can estimate ANY player's rank from
    # their trophy count (works even outside the API top-200 window).
    rank_predictor = RankPredictor(coc_client=coc_client)
    # Ne pas bloquer le démarrage du bot sur le refresh du leaderboard.
    # Le predictor se remplit en arrière-plan ; /predict affiche "—" le temps
    # du premier fetch (~quelques secondes après le boot).
    rank_predictor.start()

    digest_service = DailyDigestService(
        bot=bot,
        repository=repo,
        rank_predictor=rank_predictor,
    )

    async def _digest_loop() -> None:
        from constants import DIGEST_POLL_INTERVAL_SECONDS

        try:
            await _discord_wait_ready(bot, "digest_loop")
        except asyncio.CancelledError:
            return
        if bot.is_closed():
            return
        while True:
            try:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                n = await digest_service.run_tick(now)
                if n:
                    log.info("Daily digest delivered to %d users", n)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Daily digest loop iteration failed")
            await asyncio.sleep(DIGEST_POLL_INTERVAL_SECONDS)

    digest_task = asyncio.create_task(_digest_loop())

    legend_export_settings = DailyLegendExportSettings(
        enabled=config.daily_legend_export_enabled,
        minute_after_reset=config.daily_legend_export_minute_after_reset,
        xlsx_path=Path(config.daily_legend_export_xlsx_path),
        state_path=Path(config.daily_legend_export_state_path),
        discord_channel_id=config.daily_legend_export_discord_channel_id,
    )
    legend_export_service = DailyLegendExportService(bot, repo, legend_export_settings)

    async def _legend_export_loop() -> None:
        try:
            await _discord_wait_ready(bot, "legend_export_loop")
        except asyncio.CancelledError:
            return
        if bot.is_closed():
            return
        while True:
            try:
                from datetime import datetime, timezone

                n = await legend_export_service.run_if_due(datetime.now(timezone.utc))
                if n:
                    log.info("Export Légende quotidien : %d joueurs", n)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Daily legend export loop failed")
            await asyncio.sleep(60)

    legend_export_task = asyncio.create_task(_legend_export_loop())

    # Stripe webhook server — only useful when Stripe is configured. Bound
    # unconditionally so a healthcheck on /health always works.
    webhook_server = StripeWebhookServer(
        billing=billing,
        webhook_secret=config.stripe_webhook_secret,
        host=config.webhook_host,
        port=config.webhook_port,
    )
    try:
        await webhook_server.start()
    except OSError as exc:
        log.warning(
            "Stripe webhook server failed to bind on %s:%d (%s); continuing without HTTP server.",
            config.webhook_host,
            config.webhook_port,
            exc,
        )
        webhook_server = None  # type: ignore[assignment]

    @bot.event
    async def on_ready() -> None:  # noqa: WPS430
        log.info("Bot ready as %s (%d guilds)", bot.user, len(bot.guilds))
        mode = (config.slash_sync_mode or "both").strip().lower()
        if mode not in {"guild", "global", "both"}:
            log.warning("Unknown SLASH_SYNC_MODE=%r; falling back to 'both'", mode)
            mode = "both"

        if config.slash_purge_global:
            try:
                await _purge_global_slash_commands(bot)
            except Exception:  # noqa: BLE001
                log.exception("Global command purge failed")

        # Evidence: what Discord thinks exists, before/after sync.
        try:
            global_remote = await bot.tree.fetch_commands()
            guild_remote_counts: dict[int, int] = {}
            for g in bot.guilds:
                guild_remote_counts[g.id] = len(await bot.tree.fetch_commands(guild=g))
            debug_ndjson(
                hypothesis_id="DUP",
                location="main.py:on_ready:remote_counts",
                message="remote command counts",
                data={
                    "sync_mode": mode,
                    "remote_global": len(global_remote),
                    "remote_guild_counts": guild_remote_counts,
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to fetch remote commands for debug")

        if mode in {"guild", "both"}:
            # Sync guild-specific first (instantané).
            for guild in bot.guilds:
                try:
                    bot.tree.copy_global_to(guild=guild)
                    await bot.tree.sync(guild=guild)
                    log.info("Slash commands synced to guild %s (%d)", guild.name, guild.id)
                except Exception:  # noqa: BLE001
                    log.exception("Guild sync failed for %s", guild.id)

        if mode in {"global", "both"}:
            # Sync global (peut prendre du temps à se propager).
            try:
                await bot.tree.sync()
                log.info("Global slash commands synced")
            except Exception:  # noqa: BLE001
                log.exception("Global slash command sync failed")

        try:
            global_remote2 = await bot.tree.fetch_commands()
            guild_remote_counts2: dict[int, int] = {}
            for g in bot.guilds:
                guild_remote_counts2[g.id] = len(await bot.tree.fetch_commands(guild=g))
            debug_ndjson(
                hypothesis_id="DUP",
                location="main.py:on_ready:remote_counts_after",
                message="remote command counts after sync",
                data={
                    "sync_mode": mode,
                    "remote_global": len(global_remote2),
                    "remote_guild_counts": guild_remote_counts2,
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to fetch remote commands after sync for debug")

    await bot.add_cog(poller)
    patch_sync.attach_poller(poller)
    patch_sync_task = asyncio.create_task(patch_sync.run_forever())
    await bot.add_cog(NotebookCog(bot, repo, notebook_service))
    await bot.add_cog(DashboardCog(bot, repo, notebook_service, coc_client, billing))
    await bot.add_cog(LeaderboardCog(bot, leaderboard_service, repo))
    await bot.add_cog(GuildAdminCog(bot, repo))
    season_api_service = SeasonApiService(coc_client=coc_client, repository=repo)
    await bot.add_cog(SeasonCog(bot, repo, season_api=season_api_service))
    await bot.add_cog(AdminCog(bot, repo, poller, metrics))
    await bot.add_cog(BillingCog(bot, repo, billing, quota))
    await bot.add_cog(CoachCog(bot, repo, coc_client, rank_predictor))
    await bot.add_cog(AttackFeedbackCog(bot, repo))

    stop_event = asyncio.Event()

    def _request_stop(*_args: object) -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, _request_stop)

    bot_task = asyncio.create_task(bot.start(config.discord_token))
    await stop_event.wait()

    log.info("Stopping bot…")
    metrics_flush_task.cancel()
    weekly_recap_task.cancel()
    attack_recap_task.cancel()
    digest_task.cancel()
    legend_export_task.cancel()
    patch_sync_task.cancel()
    rank_predictor.stop()

    bg_names = (
        ("metrics_flush", metrics_flush_task),
        ("weekly_recap", weekly_recap_task),
        ("attack_recap", attack_recap_task),
        ("digest", digest_task),
        ("legend_export", legend_export_task),
        ("patch_sync", patch_sync_task),
    )
    for name, t in bg_names:
        try:
            await t
        except asyncio.CancelledError:
            pass
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "properly initialis" in msg:
                log.debug(
                    "%s loop ended during Discord teardown: %s", name, exc,
                )
                _agent_debug_main(
                    "SHUT",
                    f"main.py:_run:shutdown.await.{name}",
                    "RuntimeError while awaiting cancelled background task",
                    {"msg": str(exc)[:200]},
                )
                continue
            raise

    if webhook_server is not None:
        await webhook_server.stop()
    await bot.close()
    await coc_client.close()
    await db.close()
    await asyncio.gather(bot_task, return_exceptions=True)


class _OwnerCache:
    """Tag → discord_user_id with a small in-process LRU.

    Cogs can mutate ownership (re-link), but the alert path only needs an
    eventually-consistent value. TTL is short enough that re-links converge
    quickly without round-tripping the DB on every delta.
    """

    def __init__(self, repo: Repository, max_entries: int = 512) -> None:
        self._repo = repo
        self._cache: dict[str, int] = {}
        self._max = max_entries

    async def get_or_fetch(self, tag: str) -> int | None:
        cached = self._cache.get(tag)
        if cached is not None:
            return cached
        owner = await self._repo.get_owner_id_for_tag(tag)
        if owner is None:
            _agent_debug_main(
                "H2",
                "main.py:_OwnerCache:get_or_fetch",
                "get_owner_id_for_tag returned None",
                {"tag": tag},
            )
            return None
        if len(self._cache) >= self._max:
            self._cache.pop(next(iter(self._cache)))
        self._cache[tag] = owner
        return owner


def main() -> None:
    cfg = load_config()
    _configure_logging(cfg.log_level)
    # #region agent log
    debug_ndjson(
        hypothesis_id="BOOT",
        location="main.py:main",
        message="process starting",
        data={"slash_sync_mode": getattr(cfg, "slash_sync_mode", None)},
    )
    # #endregion
    asyncio.run(_run(cfg))


if __name__ == "__main__":
    main()
