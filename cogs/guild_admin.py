"""Guild-level configuration (étape 6) + assistant `/admin setup` (étapes UI)."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from constants import COLOR_INFO
from models import GuildConfig
from services.db import Repository


# ─────────────────────────────────────────────────────────────────────────────
# Étape 4/4 — rôles de ligue (optionnels)
# ─────────────────────────────────────────────────────────────────────────────
class _LeagueRoleSelect(discord.ui.RoleSelect["SetupStepLeague"]):
    """Sélecteur d'un rôle Discord pour une ligue donnée (III/II/I)."""

    def __init__(self, label: str, row: int) -> None:
        super().__init__(
            placeholder=f"Légende {label} (optionnel)",
            min_values=0,
            max_values=1,
            row=row,
        )
        self._field = label

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = cast("SetupStepLeague", self.view)
        rid = int(self.values[0].id) if self.values else None
        if self._field == "III":
            parent.cfg = replace(parent.cfg, legend_role_iii_id=rid)
        elif self._field == "II":
            parent.cfg = replace(parent.cfg, legend_role_ii_id=rid)
        else:
            parent.cfg = replace(parent.cfg, legend_role_i_id=rid)
        await interaction.response.defer()


class SetupStepLeague(discord.ui.View):
    """Étape 4/4 — rôles de ligue optionnels + bouton enregistrer."""

    def __init__(self, repository: Repository, cfg: GuildConfig) -> None:
        super().__init__(timeout=600)
        self._repo = repository
        self.cfg = cfg
        self.add_item(_LeagueRoleSelect("III", 0))
        self.add_item(_LeagueRoleSelect("II", 1))
        self.add_item(_LeagueRoleSelect("I", 2))

    @discord.ui.button(label="Enregistrer", style=discord.ButtonStyle.success, row=3)
    async def done(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button["SetupStepLeague"],
    ) -> None:
        await self._repo.upsert_guild_config(self.cfg)
        embed = discord.Embed(
            title="✅ Configuration enregistrée",
            description=(
                "Salons et rôles sont enregistrés. Tu peux affiner avec `/serveur_config`."
            ),
            color=COLOR_INFO,
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ─────────────────────────────────────────────────────────────────────────────
# Étape 3/4 — rôle opérateur bot
# ─────────────────────────────────────────────────────────────────────────────
class SetupStepAdminRole(discord.ui.View):
    """Étape 3/4 — rôle autorisé à exécuter les commandes `/admin`."""

    def __init__(self, repository: Repository, cfg: GuildConfig) -> None:
        super().__init__(timeout=600)
        self._repo = repository
        self.cfg = cfg

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Rôle autorisé pour `/bot_stats` et outils admin",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def admin_role(
        self,
        interaction: discord.Interaction,
        select: discord.ui.RoleSelect["SetupStepAdminRole"],
    ) -> None:
        rid = int(select.values[0].id)
        self.cfg = replace(self.cfg, admin_role_id=rid)
        embed = discord.Embed(
            title="Assistant LegendMind — étape 4/4",
            description=(
                "Associe **optionnellement** les rôles Discord aux ligues "
                "(sync automatique avec les trophées)."
            ),
            color=COLOR_INFO,
        )
        await interaction.response.edit_message(
            embed=embed,
            view=SetupStepLeague(self._repo, self.cfg),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Étape 2/4 — salon classement auto
# ─────────────────────────────────────────────────────────────────────────────
class SetupStepLb(discord.ui.View):
    """Étape 2/4 — salon où le classement auto sera publié et actualisé."""

    def __init__(self, repository: Repository, cfg: GuildConfig) -> None:
        super().__init__(timeout=600)
        self._repo = repository
        self.cfg = cfg

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Salon pour le classement (mis à jour automatiquement)",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def lb_channel(
        self,
        interaction: discord.Interaction,
        select: discord.ui.ChannelSelect["SetupStepLb"],
    ) -> None:
        cid = int(select.values[0].id)
        self.cfg = replace(self.cfg, leaderboard_channel_id=cid)
        embed = discord.Embed(
            title="Assistant LegendMind — étape 3/4",
            description="Choisis le **rôle** qui peut utiliser les commandes opérateur.",
            color=COLOR_INFO,
        )
        await interaction.response.edit_message(
            embed=embed,
            view=SetupStepAdminRole(self._repo, self.cfg),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Étape 1/4 — salon des alertes
# ─────────────────────────────────────────────────────────────────────────────
class SetupStepAlerts(discord.ui.View):
    """Étape 1/4 — salon où le bot poste les alertes push."""

    def __init__(self, repository: Repository, cfg: GuildConfig) -> None:
        super().__init__(timeout=600)
        self._repo = repository
        self.cfg = cfg

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Salon où poster les alertes push",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def alerts_channel(
        self,
        interaction: discord.Interaction,
        select: discord.ui.ChannelSelect["SetupStepAlerts"],
    ) -> None:
        cid = int(select.values[0].id)
        self.cfg = replace(self.cfg, alerts_channel_id=cid)
        embed = discord.Embed(
            title="Assistant LegendMind — étape 2/4",
            description="Choisis le salon pour le **classement** (embed auto toutes les 15 min).",
            color=COLOR_INFO,
        )
        await interaction.response.edit_message(
            embed=embed,
            view=SetupStepLb(self._repo, self.cfg),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cog `/serveur_config`
# ─────────────────────────────────────────────────────────────────────────────
class GuildAdminCog(commands.Cog):
    """`/serveur_config` — réglages serveur (top, visibilité, etc.)."""

    def __init__(self, bot: commands.Bot, repository: Repository) -> None:
        self.bot = bot
        self._repo = repository

    serveur_config = app_commands.Group(
        name="serveur_config",
        description="Réglages LegendMind pour ce serveur.",
    )

    @serveur_config.command(name="voir", description="Affiche la config actuelle.")
    @app_commands.default_permissions(manage_guild=True)
    async def voir(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Sur un serveur seulement.",
                ephemeral=True,
            )
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        await interaction.response.send_message(
            f"**Top** : {cfg.leaderboard_limit}\n"
            f"**Public** : {'oui' if cfg.leaderboard_public else 'non (ephemeral)'}\n"
            f"**Légende seulement** : {'oui' if cfg.leaderboard_legend_only else 'non'}\n"
            f"**Salon alertes** : {cfg.alerts_channel_id or '—'}\n"
            f"**Salon classement auto** : {cfg.leaderboard_channel_id or '—'}\n"
            f"**Rôle admin bot** : {cfg.admin_role_id or '—'}\n"
            f"**Rôles ligue** : I={cfg.legend_role_i_id or '—'} "
            f"II={cfg.legend_role_ii_id or '—'} III={cfg.legend_role_iii_id or '—'}",
            ephemeral=True,
        )

    @serveur_config.command(
        name="classement",
        description="Limite du top, visibilité publique, filtre Légende.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        limite="Nombre de lignes (3–50).",
        public="Si oui, tout le monde voit `/classement`.",
        legende_seulement="Si oui, masque les comptes sous 5000 trophées.",
    )
    async def classement_cfg(
        self,
        interaction: discord.Interaction,
        limite: int | None = None,
        public: bool | None = None,
        legende_seulement: bool | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Sur un serveur seulement.",
                ephemeral=True,
            )
            return
        cur = await self._repo.get_guild_config(interaction.guild_id)
        new = cur
        if limite is not None:
            new = replace(new, leaderboard_limit=limite)
        if public is not None:
            new = replace(new, leaderboard_public=public)
        if legende_seulement is not None:
            new = replace(new, leaderboard_legend_only=legende_seulement)
        await self._repo.upsert_guild_config(new)
        await interaction.response.send_message("✅ Config mise à jour.", ephemeral=True)
