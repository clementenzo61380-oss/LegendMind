"""Carnet d'Erreurs Discord cog — `/carnet [semaine]`.

Renders a `NotebookReport` as an embed with a trend graph button.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from constants import COLOR_INFO, COLOR_WARNING, EMBED_TITLE_NOTEBOOK
from models import NotebookReport
from services.db import Repository
from services.notebook import ErrorNotebookService

log = logging.getLogger(__name__)


class NotebookCog(commands.Cog):
    """Slash commands for the Carnet d'Erreurs feature."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: Repository,
        notebook: ErrorNotebookService,
    ) -> None:
        self.bot = bot
        self._repo = repository
        self._notebook = notebook

    @app_commands.command(
        name="carnet",
        description="Affiche ton Carnet d'Erreurs hebdomadaire.",
    )
    @app_commands.describe(
        semaine_offset=("0 = semaine en cours, 1 = semaine dernière, etc. (défaut : 0)"),
    )
    async def carnet(
        self,
        interaction: discord.Interaction,
        semaine_offset: app_commands.Range[int, 0, 26] = 0,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        tag = await self._resolve_player_tag(interaction.user.id)
        if tag is None:
            await interaction.followup.send(
                "Aucun compte CoC lié. Utilise `/setup` d'abord.",
                ephemeral=True,
            )
            return

        anchor = datetime.now(timezone.utc) - timedelta(weeks=semaine_offset)
        report = await self._notebook.get_weekly_report(tag, anchor)
        embed = _render_report(report)
        view = _NotebookView(self._notebook, tag)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def _resolve_player_tag(self, discord_user_id: int) -> str | None:
        return await self._repo.get_first_active_tag(discord_user_id)


# ─────────────────────────────────────────────────────────────────────────────
# Embed & view rendering
# ─────────────────────────────────────────────────────────────────────────────
def _render_report(report: NotebookReport) -> discord.Embed:
    color = COLOR_WARNING if report.avg_malchance_score >= 0.5 else COLOR_INFO
    embed = discord.Embed(
        title=f"{EMBED_TITLE_NOTEBOOK} — Semaine du {report.week_start:%d/%m}",
        color=color,
    )

    bar = _progress_bar(report.avg_malchance_score, width=10)
    embed.add_field(
        name="Score de malchance moyen",
        value=f"{bar}  `{report.avg_malchance_score:.2f}`",
        inline=False,
    )

    if report.worst_defense is not None:
        worst = report.worst_defense
        opp = worst.opponent_tag or "inconnu"
        embed.add_field(
            name="Pire défense",
            value=(
                f"–{worst.trophies_lost} trophées contre `{opp}` "
                f"(score {worst.malchance_score:.2f}, "
                f"{worst.attack_count} attaque(s))"
            ),
            inline=False,
        )

    if report.patterns:
        embed.add_field(
            name="Patterns détectés",
            value="\n".join(f"• {p}" for p in report.patterns),
            inline=False,
        )

    if report.recommendations:
        numbered = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(report.recommendations))
        embed.add_field(
            name="Recommandations",
            value=numbered,
            inline=False,
        )

    if report.total_trophies_lost_to_bad_luck:
        embed.set_footer(
            text=(
                f"Trophées perdus à cause de malchance forte : "
                f"{report.total_trophies_lost_to_bad_luck}"
            )
        )
    return embed


def _progress_bar(value: float, width: int = 10) -> str:
    """Unicode progress bar for [0,1] values; clipped to width."""
    filled = max(0, min(width, round(value * width)))
    return "█" * filled + "░" * (width - filled)


class _NotebookView(discord.ui.View):
    """Buttons attached to the carnet embed."""

    def __init__(
        self,
        notebook: ErrorNotebookService,
        player_tag: str,
    ) -> None:
        super().__init__(timeout=180.0)
        self._notebook = notebook
        self._tag = player_tag

    @discord.ui.button(
        label="📊 Tendance malchance (7j)",
        style=discord.ButtonStyle.secondary,
    )
    async def show_trend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        trend = await self._notebook.get_malchance_trend(self._tag, days=7)
        graph = _render_trend(trend)
        await interaction.response.send_message(
            f"**Tendance malchance (7 derniers jours)**\n```\n{graph}\n```",
            ephemeral=True,
        )


def _render_trend(values: list[float]) -> str:
    """ASCII sparkline for a [0,1]-valued series."""
    if not values:
        return "(aucune donnée)"
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(
        blocks[min(len(blocks) - 1, max(0, round(v * (len(blocks) - 1))))] for v in values
    )
