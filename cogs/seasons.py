"""Season labels, archives, and admin close (step 7)."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from constants import COLOR_INFO, COLOR_SUCCESS, EMBED_TITLE_SEASON, LeagueType
from services.db import Repository
from services.logic import legend_projection_horizon
from services.season import SeasonService

log = logging.getLogger(__name__)


def _league_label(league: LeagueType) -> str:
    return {
        LeagueType.LEGEND_I: "Légende I",
        LeagueType.LEGEND_II: "Légende II",
        LeagueType.LEGEND_III: "Légende III",
        LeagueType.UNKNOWN: "—",
    }[league]


class SeasonCog(commands.Cog):
    """`/saison` user view + `/admin_saison_cloturer` operator tool."""

    def __init__(self, bot: commands.Bot, repository: Repository) -> None:
        self.bot = bot
        self._repo = repository
        self._svc = SeasonService(repository)

    @app_commands.command(
        name="saison",
        description="Saison ouverte : libellé, fin estimée, ton classement figé.",
    )
    async def saison(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            await interaction.followup.send(
                "Utilisable sur un serveur.", ephemeral=True,
            )
            return

        active = await self._svc.get_current_season()

        tag = await self._repo.get_first_active_tag(interaction.user.id)
        rank_txt = "—"
        if tag is not None:
            prev = await self._repo.list_recent_closed_seasons(limit=1)
            if prev:
                res = await self._repo.find_player_season_rank(
                    prev[0].id,
                    interaction.guild_id,
                    tag,
                )
                if res is not None:
                    rank_txt = (
                        f"#{res.guild_rank} ({res.final_trophies} tr., "
                        f"{_league_label(res.league_type)}) "
                        f"saison `{prev[0].label}`"
                    )

        horizon = legend_projection_horizon(discord.utils.utcnow())
        embed = discord.Embed(
            title=EMBED_TITLE_SEASON,
            color=COLOR_INFO,
            description=(
                f"**Saison active** : `{active.label}`\n"
                f"Début : <t:{int(active.period_start.timestamp())}:D>\n"
                f"Horizon projection : <t:{int(horizon.timestamp())}:f>\n\n"
                f"**Ton dernier classement figé** :\n{rank_txt}"
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="historique",
        description="Tes saisons clôturées (résultats enregistrés) ou un tag #.",
    )
    @app_commands.describe(
        tag="Tag CoC (optionnel : par défaut ton compte lié)",
    )
    async def historique(
        self, interaction: discord.Interaction, tag: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        resolved: str | None
        if tag:
            t = tag.strip().upper()
            resolved = t if t.startswith("#") else "#" + t
        else:
            resolved = await self._repo.get_first_active_tag(interaction.user.id)
        if not resolved:
            await interaction.followup.send(
                "Aucun compte lié. Utilise `/lier` ou indique un `tag`.",
                ephemeral=True,
            )
            return
        rows = await self._svc.get_player_history(resolved, limit=8)
        if not rows:
            await interaction.followup.send(
                f"Aucun résultat archivé pour `{resolved}`.", ephemeral=True,
            )
            return
        lines: list[str] = []
        for r in rows:
            rk = f"#{r.guild_rank}" if r.guild_rank is not None else "—"
            lines.append(
                f"`{r.season_label}` · {rk} · **{r.final_trophies}** tr. "
                f"· {_league_label(r.league_type)} · net {r.net_trophies:+d}"
            )
        embed = discord.Embed(
            title=f"Historique saisons — `{resolved}`",
            description="\n".join(lines),
            color=COLOR_INFO,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="saison_historique",
        description="Liste les saisons terminées récemment.",
    )
    async def saison_historique(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        rows = await self._repo.list_recent_closed_seasons(limit=6)
        if not rows:
            await interaction.followup.send(
                "Aucune saison clôturée pour l'instant.", ephemeral=True,
            )
            return
        lines: list[str] = []
        for r in rows:
            if r.period_end is not None:
                lines.append(
                    f"`{r.label}` · fin <t:{int(r.period_end.timestamp())}:D>",
                )
            else:
                lines.append(f"`{r.label}`")
        embed = discord.Embed(
            title="Archives de saisons",
            description="\n".join(lines),
            color=COLOR_SUCCESS,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="admin_saison_cloturer",
        description="Clôturer la saison active et en ouvrir une nouvelle (Admin).",
    )
    @app_commands.default_permissions(administrator=True)
    async def admin_cloturer(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            old_id, new_id = await self._svc.close_season()
        except Exception as exc:  # noqa: BLE001
            log.exception("Season close failed")
            await interaction.followup.send(f"Échec : `{exc!s}`", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Saison `{old_id}` figée. Nouvelle saison `{new_id}`.",
            ephemeral=True,
        )

