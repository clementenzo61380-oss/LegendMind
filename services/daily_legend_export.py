"""Orchestration export PDF : une passe après chaque reset Légende (+ décalage minutes)."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import discord

from services.daily_legend_pdf import append_legend_day_rows_pdf
from services.db import Repository
from services.game_tuning import get_tuning
from services.legend_day_export import (
    LegendDayStats,
    completed_legend_day_window,
    compute_legend_day_stats,
)

log = logging.getLogger(__name__)


@dataclass(slots=True)
class DailyLegendExportSettings:
    enabled: bool
    minute_after_reset: int
    pdf_path: Path
    history_path: Path
    state_path: Path
    discord_channel_id: int | None


class DailyLegendExportService:
    def __init__(
        self,
        bot: discord.Client,
        repository: Repository,
        settings: DailyLegendExportSettings,
    ) -> None:
        self._bot = bot
        self._repo = repository
        self._settings = settings

    def should_run_tick(self, now_utc: datetime) -> bool:
        if not self._settings.enabled:
            return False
        m = self._settings.minute_after_reset
        if not (0 <= m <= 59):
            return False
        tun = get_tuning()
        return now_utc.hour == tun.legend_daily_reset_hour_utc and now_utc.minute == m

    def _already_exported(self, legend_day_end: datetime) -> bool:
        p = self._settings.state_path
        if not p.exists():
            return False
        try:
            prev = p.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return prev == legend_day_end.isoformat()

    def _mark_exported(self, legend_day_end: datetime) -> None:
        p = self._settings.state_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(legend_day_end.isoformat(), encoding="utf-8")

    async def run_if_due(self, now_utc: datetime) -> int:
        """Si l'heure correspond et la journée n'est pas déjà exportée, met à jour le PDF.

        Retourne le nombre de joueurs écrits (0 si rien à faire).
        """
        if not self.should_run_tick(now_utc):
            return 0
        tun = get_tuning()
        window = completed_legend_day_window(now_utc, tun.legend_daily_reset_hour_utc)
        if self._already_exported(window.end_utc):
            return 0

        players = await self._repo.list_active_players_for_export()
        rows: list[LegendDayStats] = []
        for tag, name in players:
            start_snap = await self._repo.get_latest_snapshot_before(tag, window.start_utc)
            end_snap = await self._repo.get_latest_snapshot_before(tag, window.end_utc)
            n_def, sum_lost = await self._repo.aggregate_defenses_between(
                tag, window.start_utc, window.end_utc
            )
            row = compute_legend_day_stats(
                tag,
                name,
                window,
                start_snap,
                end_snap,
                n_def,
                defense_trophies_lost=sum_lost,
            )
            if row is not None:
                rows.append(row)

        if not rows:
            log.warning(
                "Export Légende: aucune donnée pour la fenêtre se terminant %s",
                window.end_utc.isoformat(),
            )
            self._mark_exported(window.end_utc)
            return 0

        append_legend_day_rows_pdf(
            self._settings.pdf_path,
            self._settings.history_path,
            rows,
        )
        self._mark_exported(window.end_utc)
        log.info(
            "Export Légende: %d joueurs → %s",
            len(rows),
            self._settings.pdf_path,
        )

        ch_id = self._settings.discord_channel_id
        if ch_id is not None:
            await self._post_to_discord(ch_id)

        return len(rows)

    async def _post_to_discord(self, channel_id: int) -> None:
        channel = self._bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.warning("DAILY_LEGEND_EXPORT_DISCORD_CHANNEL_ID: salon introuvable %s", channel_id)
            return
        path = self._settings.pdf_path
        if not path.is_file():
            return
        try:
            raw = path.read_bytes()
            await channel.send(
                content="📄 Export quotidien Légende (PDF, auto)",
                file=discord.File(io.BytesIO(raw), filename=path.name),
            )
        except OSError:
            log.exception("Lecture fichier export Légende pour Discord")
        except discord.HTTPException:
            log.exception("Échec envoi Discord de l'export Légende")
