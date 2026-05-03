"""Leaderboard + métriques joueur (services/leaderboard + cache)."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from constants import (
    COLOR_INFO,
    EMBED_TITLE_LEADERBOARD,
    EMBED_TITLE_METRICS,
    LeagueType,
)
from models import GuildConfig, LeaderboardEntry
from services.db import Repository
from services.leaderboard import LeaderboardService

log = logging.getLogger(__name__)

_LIGUE_CHOICES = [
    app_commands.Choice(name="Toutes", value=0),
    app_commands.Choice(name="Légende III", value=1),
    app_commands.Choice(name="Légende II", value=2),
    app_commands.Choice(name="Légende I", value=3),
]


def _league_label(league: LeagueType) -> str:
    return {
        LeagueType.LEGEND_I: "Légende I",
        LeagueType.LEGEND_II: "Légende II",
        LeagueType.LEGEND_III: "Légende III",
        LeagueType.UNKNOWN: "—",
    }[league]


def build_leaderboard_embed(
    rows: list[LeaderboardEntry],
    cfg: GuildConfig,
    league_filter: LeagueType | None,
) -> discord.Embed:
    top_trophies = max(e.trophies for e in rows) or 1
    lines: list[str] = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for e in rows:
        med = medals.get(e.rank, f"{e.rank}.")
        who = f"<@{e.discord_user_id}>"
        bar_w = max(1, int(8 * e.trophies / top_trophies))
        bar = "█" * bar_w + "░" * (8 - bar_w)
        lines.append(
            f"{med} {who}\n"
            f"`{bar}` **{e.trophies}** tr. · {_league_label(e.league_type)} · "
            f"+{e.weekly_gain} / 7j · ⚔️{e.attacks_today}"
        )
    embed = discord.Embed(
        title=EMBED_TITLE_LEADERBOARD,
        description="\n".join(lines),
        color=COLOR_INFO,
    )
    lf_note = ""
    if league_filter is not None:
        lf_note = f" · Filtre {_league_label(league_filter)}"
    legend_note = " · Légende seulement" if cfg.leaderboard_legend_only else ""
    embed.set_footer(text=f"Top {cfg.leaderboard_limit}{legend_note}{lf_note}")
    return embed


class LeaderboardCog(commands.Cog):
    """`/classement`, `/mvp_semaine`, `/metriques`."""

    def __init__(
        self,
        bot: commands.Bot,
        leaderboard: LeaderboardService,
        repository: Repository,
    ) -> None:
        self.bot = bot
        self._lb = leaderboard
        self._repo = repository

    async def cog_load(self) -> None:
        self._refresh_auto_leaderboards.start()

    async def cog_unload(self) -> None:
        self._refresh_auto_leaderboards.cancel()

    @tasks.loop(minutes=15)
    async def _refresh_auto_leaderboards(self) -> None:
        for gid in await self._repo.list_guild_ids_with_leaderboard_channel():
            try:
                await self._push_leaderboard_to_channel(gid)
            except Exception:  # noqa: BLE001
                log.exception("Auto leaderboard refresh failed for guild %s", gid)

    @_refresh_auto_leaderboards.before_loop
    async def _before_refresh_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _push_leaderboard_to_channel(self, guild_id: int) -> None:
        cfg = await self._repo.get_guild_config(guild_id)
        if cfg.leaderboard_channel_id is None:
            return
        channel = self.bot.get_channel(cfg.leaderboard_channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            return
        if self.bot.get_guild(guild_id) is None:
            return
        rows = await self._lb.get_server_leaderboard(
            guild_id,
            league_filter=None,
            limit=cfg.leaderboard_limit,
            legend_only=cfg.leaderboard_legend_only,
        )
        if not rows:
            return
        embed = build_leaderboard_embed(rows, cfg, None)
        if cfg.leaderboard_message_id:
            try:
                msg = await channel.fetch_message(cfg.leaderboard_message_id)
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        msg = await channel.send(embed=embed)
        await self._repo.upsert_guild_config(
            replace(cfg, leaderboard_message_id=msg.id),
        )

    @app_commands.command(
        name="classement",
        description="Classement des membres liés (trophées, filtre ligue).",
    )
    @app_commands.describe(ligue="Ne garder qu’une ligue Legend")
    @app_commands.choices(ligue=_LIGUE_CHOICES)
    async def classement(
        self,
        interaction: discord.Interaction,
        ligue: int = 0,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Utilisable seulement sur un serveur.", ephemeral=True,
            )
            return

        cfg = await self._repo.get_guild_config(interaction.guild_id)
        ephemeral = not cfg.leaderboard_public
        league_filter: LeagueType | None = None
        if ligue in (1, 2, 3):
            league_filter = LeagueType(ligue)

        await interaction.response.defer(ephemeral=ephemeral)

        rows = await self._lb.get_server_leaderboard(
            interaction.guild_id,
            league_filter=league_filter,
            limit=cfg.leaderboard_limit,
            legend_only=cfg.leaderboard_legend_only,
        )
        if not rows:
            await interaction.followup.send(
                "Aucun joueur lié sur ce serveur (ou pas encore de snap).",
                ephemeral=ephemeral,
            )
            return

        embed = build_leaderboard_embed(rows, cfg, league_filter)
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    @app_commands.command(
        name="mvp_semaine",
        description="Joueur avec le meilleur gain net de trophées sur 7 jours.",
    )
    async def mvp_semaine(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Sur un serveur seulement.", ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        mvp = await self._lb.get_weekly_mvp(interaction.guild_id)
        if mvp is None:
            await interaction.followup.send(
                "Pas assez de données pour un MVP.", ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🏆 MVP de la semaine (estimation)",
            description=(
                f"<@{mvp.discord_user_id}>\n"
                f"**{mvp.trophies}** trophées · {_league_label(mvp.league_type)}\n"
                f"Gain ~**{mvp.weekly_gain:+d}** trophées sur la fenêtre 7j\n"
                f"Attaques (snapshot) : **{mvp.attacks_today}**"
            ),
            color=COLOR_INFO,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="metriques",
        description="Synthèse des deltas collectés (fenêtre glissante 24h).",
    )
    async def metriques(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        tag = await self._repo.get_first_active_tag(interaction.user.id)
        if tag is None:
            await interaction.followup.send(
                "Aucun compte CoC lié. Utilise `/lier` d'abord.", ephemeral=True,
            )
            return

        now = discord.utils.utcnow()
        since = now - timedelta(hours=24)
        nt, atk, sn = await self._repo.aggregate_metrics_window(tag, since, now)
        buckets = await self._repo.list_metrics_hourly(tag, since, now)

        spark = ""
        if buckets:
            vals = [b.net_trophies_delta for b in buckets]
            lo, hi = min(vals), max(vals)
            span = max(1, hi - lo)
            blocks = "▁▂▃▄▅▆▇█"
            spark = "".join(
                blocks[
                    min(
                        len(blocks) - 1,
                        round((v - lo) / span * (len(blocks) - 1)),
                    )
                ]
                for v in vals
            )

        embed = discord.Embed(
            title=EMBED_TITLE_METRICS,
            color=COLOR_INFO,
            description=(
                f"**Δ trophées (24h)** : {nt:+d}\n"
                f"**Δ attaques détectées** : {atk}\n"
                f"**Écritures snapshot** : {sn}\n\n"
                f"```{spark or '—'}```"
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
