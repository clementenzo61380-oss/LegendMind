"""LegendMind V3 — entrypoint.

Wires config → coc.Client → Database/Repository → Discord bot → cogs.
Stays small on purpose; nothing here should know domain logic.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

import coc
import discord
from discord.ext import commands

from cogs.admin import AdminCog
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
from services.stripe_webhook import StripeWebhookServer


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def _run(config: Config) -> None:  # noqa: PLR0915 — entry point wiring is linear by design
    log = logging.getLogger("legendmind.main")

    db = Database(config.database_url, ssl=config.database_use_ssl)
    await db.connect()
    repo = Repository(db)
    await repo.ensure_active_season()

    coc_client = coc.Client()
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

        await bot.wait_until_ready()
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
            except Exception:  # noqa: BLE001
                log.exception("Weekly recap loop iteration failed")
            await asyncio.sleep(300)

    weekly_recap_task = asyncio.create_task(_weekly_recap_loop())

    # Rank predictor — fetches the global Legend leaderboard every TTL and
    # fits a log-linear curve so we can estimate ANY player's rank from
    # their trophy count (works even outside the API top-200 window).
    rank_predictor = RankPredictor(coc_client=coc_client)
    await rank_predictor.refresh()  # prime the cache before bot ready
    rank_predictor.start()

    digest_service = DailyDigestService(
        bot=bot, repository=repo, rank_predictor=rank_predictor,
    )

    async def _digest_loop() -> None:
        from constants import DIGEST_POLL_INTERVAL_SECONDS

        await bot.wait_until_ready()
        while True:
            try:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                n = await digest_service.run_tick(now)
                if n:
                    log.info("Daily digest delivered to %d users", n)
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
        await bot.wait_until_ready()
        while True:
            try:
                from datetime import datetime, timezone

                n = await legend_export_service.run_if_due(datetime.now(timezone.utc))
                if n:
                    log.info("Export Légende quotidien : %d joueurs", n)
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
            "Stripe webhook server failed to bind on %s:%d (%s); "
            "continuing without HTTP server.",
            config.webhook_host, config.webhook_port, exc,
        )
        webhook_server = None  # type: ignore[assignment]

    @bot.event
    async def on_ready() -> None:  # noqa: WPS430
        log.info("Bot ready as %s (%d guilds)", bot.user, len(bot.guilds))
        try:
            await bot.tree.sync()
        except Exception:  # noqa: BLE001
            log.exception("Slash command sync failed")

    await bot.add_cog(poller)
    patch_sync.attach_poller(poller)
    patch_sync_task = asyncio.create_task(patch_sync.run_forever())
    await bot.add_cog(NotebookCog(bot, repo, notebook_service))
    await bot.add_cog(DashboardCog(bot, repo, notebook_service, coc_client, billing))
    await bot.add_cog(LeaderboardCog(bot, leaderboard_service, repo))
    await bot.add_cog(GuildAdminCog(bot, repo))
    await bot.add_cog(SeasonCog(bot, repo))
    await bot.add_cog(AdminCog(bot, repo, poller, metrics))
    await bot.add_cog(BillingCog(bot, repo, billing, quota))
    await bot.add_cog(CoachCog(bot, repo, coc_client, rank_predictor))

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
    digest_task.cancel()
    legend_export_task.cancel()
    patch_sync_task.cancel()
    rank_predictor.stop()
    for t in (
        metrics_flush_task,
        weekly_recap_task,
        digest_task,
        legend_export_task,
        patch_sync_task,
    ):
        try:
            await t
        except asyncio.CancelledError:
            pass

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

    async def get_or_fetch(self, tag: str) -> int:
        cached = self._cache.get(tag)
        if cached is not None:
            return cached
        owner = await self._repo.get_owner_id_for_tag(tag)
        if owner is None:
            return 0
        if len(self._cache) >= self._max:
            self._cache.pop(next(iter(self._cache)))
        self._cache[tag] = owner
        return owner


def main() -> None:
    cfg = load_config()
    _configure_logging(cfg.log_level)
    asyncio.run(_run(cfg))


if __name__ == "__main__":
    main()
