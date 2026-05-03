"""Commandes opérateur (prompt §6).

Deux ergonomies cohabitent :

* sous-groupe `/admin <action>` (prompt LVL99) — `set-channel`, `set-role`,
  `force-poll`, `reset-cooldowns`, `stats-polling` ;
* commandes plates `/bot_stats`, `/admin_stats_polling`, etc. (rétro-compat).

Chaque commande vérifie les droits via :func:`_is_operator` (propriétaire
du serveur, `manage_guild`, ou rôle `admin_role_id`).
"""
from __future__ import annotations

import logging
from dataclasses import replace

import discord
from discord import app_commands
from discord.ext import commands

from cogs.guild_admin import SetupStepAlerts
from cogs.tracker import LegendPoller
from constants import COLOR_INFO, LeagueType
from models import GuildConfig
from services.db import Repository
from services.metrics_collector import MetricsCollector

log = logging.getLogger(__name__)


def _normalise_tag(tag: str) -> str:
    cleaned = tag.strip().upper()
    return cleaned if cleaned.startswith("#") else "#" + cleaned


def _is_operator(interaction: discord.Interaction, cfg: GuildConfig) -> bool:
    if interaction.guild is None or interaction.user is None:
        return False
    if interaction.guild.owner_id == interaction.user.id:
        return True
    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        return False
    if member.guild_permissions.administrator:
        return True
    if cfg.admin_role_id:
        role = interaction.guild.get_role(cfg.admin_role_id)
        if role and role in member.roles:
            return True
    return False


_CHANNEL_KIND = [
    app_commands.Choice(name="alerts", value="alerts"),
    app_commands.Choice(name="leaderboard", value="leaderboard"),
]

_ROLE_LEAGUE = [
    app_commands.Choice(name="admin", value="admin"),
    app_commands.Choice(name="legend_i", value="legend_i"),
    app_commands.Choice(name="legend_ii", value="legend_ii"),
    app_commands.Choice(name="legend_iii", value="legend_iii"),
]


class AdminCog(commands.Cog):
    """`/bot_stats` + sous-groupe `/admin` (`set-channel`, `set-role`, …)."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: Repository,
        poller: LegendPoller,
        metrics: MetricsCollector,
    ) -> None:
        self.bot = bot
        self._repo = repository
        self._poller = poller
        self._metrics = metrics

    # ── /bot_stats (commande plate, déjà documentée) ─────────────────────
    @app_commands.command(
        name="bot_stats",
        description="Santé du bot (latences, file, mémoire). Réservé opérateurs.",
    )
    async def slash_bot_stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            s = await self._metrics.summary()
            lat = round(self.bot.latency * 1000.0, 1)
            await interaction.followup.send(
                f"Uptime {s['uptime_s']}s · WS {lat}ms · "
                f"p95 poll {s['p95_latency_ms']}ms",
                ephemeral=True,
            )
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        if not _is_operator(interaction, cfg):
            await interaction.followup.send("Refusé.", ephemeral=True)
            return
        s = await self._metrics.summary()
        lat = round(self.bot.latency * 1000.0, 1)
        embed = discord.Embed(
            title="📟 Stats bot",
            color=COLOR_INFO,
            description=(
                f"**Uptime** : {s['uptime_s']} s\n"
                f"**Latence Discord WS** : {lat} ms\n"
                f"**Polls OK / KO** : {s['polls_ok']} / {s['polls_fail']}\n"
                f"**429 CoC** : {s['api_429']}\n"
                f"**Alertes envoyées** : {s['alerts_sent']}\n"
                f"**File d’attente** : {s['queue_depth']}\n"
                f"**p50 / p95 poll** : {s['p50_latency_ms']} / "
                f"{s['p95_latency_ms']} ms\n"
                f"**RSS** : ~{s['rss_mb']} MiB"
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── flat aliases ─────────────────────────────────────────────────────
    @app_commands.command(
        name="admin_stats_polling",
        description="Résumé métrique + profondeur de file (alias de /admin stats-polling).",
    )
    async def admin_stats_polling(self, interaction: discord.Interaction) -> None:
        await self._stats_polling_impl(interaction)

    @app_commands.command(
        name="admin_force_poll",
        description="Force un cycle API (alias de /admin force-poll).",
    )
    @app_commands.describe(tag="Tag CoC (optionnel, sinon ton compte lié)")
    async def admin_force_poll(
        self,
        interaction: discord.Interaction,
        tag: str | None = None,
    ) -> None:
        await self._force_poll_impl(interaction, tag)

    @app_commands.command(
        name="admin_reset_cooldowns",
        description="Efface l’historique d’alertes (alias de /admin reset-cooldowns).",
    )
    @app_commands.describe(tag="Tag CoC du joueur")
    async def admin_reset_cooldowns(
        self, interaction: discord.Interaction, tag: str,
    ) -> None:
        await self._reset_cooldowns_impl(interaction, tag)

    # ── sous-groupe /admin <action> (LVL99) ──────────────────────────────
    admin = app_commands.Group(
        name="admin",
        description="Outils opérateur LegendMind (LVL99).",
    )

    @admin.command(
        name="setup",
        description="Assistant 4 étapes : alertes, classement, rôle admin, ligues.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def admin_op_setup(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Sur un serveur seulement.", ephemeral=True,
            )
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        embed = discord.Embed(
            title="Assistant LegendMind — étape 1/4",
            description=(
                "Choisis le salon **texte** où le bot enverra les **alertes** "
                "(attaques, seuils, etc.)."
            ),
            color=COLOR_INFO,
        )
        await interaction.response.send_message(
            embed=embed,
            view=SetupStepAlerts(self._repo, cfg),
            ephemeral=True,
        )

    @admin.command(name="stats-polling", description="Résumé métrique du polling.")
    async def admin_op_stats(self, interaction: discord.Interaction) -> None:
        await self._stats_polling_impl(interaction)

    @admin.command(name="force-poll", description="Force un cycle API immédiat.")
    @app_commands.describe(tag="Tag CoC (optionnel, sinon ton compte lié)")
    async def admin_op_force_poll(
        self,
        interaction: discord.Interaction,
        tag: str | None = None,
    ) -> None:
        await self._force_poll_impl(interaction, tag)

    @admin.command(name="reset-cooldowns", description="Vide les cooldowns d'alerte d'un joueur.")
    @app_commands.describe(tag="Tag CoC du joueur")
    async def admin_op_reset(
        self, interaction: discord.Interaction, tag: str,
    ) -> None:
        await self._reset_cooldowns_impl(interaction, tag)

    @admin.command(
        name="set-channel",
        description="Configure un salon (alerts ou leaderboard).",
    )
    @app_commands.choices(kind=_CHANNEL_KIND)
    @app_commands.describe(
        kind="Type de salon à configurer",
        salon="Salon texte cible",
    )
    async def admin_op_set_channel(
        self,
        interaction: discord.Interaction,
        kind: app_commands.Choice[str],
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Sur un serveur seulement.", ephemeral=True)
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        if not _is_operator(interaction, cfg):
            await interaction.response.send_message("Refusé.", ephemeral=True)
            return
        if kind.value == "alerts":
            cfg = replace(cfg, alerts_channel_id=salon.id)
        else:
            cfg = replace(cfg, leaderboard_channel_id=salon.id)
        await self._repo.upsert_guild_config(cfg)
        await interaction.response.send_message(
            f"✅ {kind.value} → {salon.mention}", ephemeral=True,
        )

    @admin.command(
        name="set-role",
        description="Associe un rôle Discord (admin ou ligue).",
    )
    @app_commands.choices(slot=_ROLE_LEAGUE)
    @app_commands.describe(
        slot="Quel rôle configurer",
        role="Rôle Discord à associer",
    )
    async def admin_op_set_role(
        self,
        interaction: discord.Interaction,
        slot: app_commands.Choice[str],
        role: discord.Role,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Sur un serveur seulement.", ephemeral=True)
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        if not _is_operator(interaction, cfg):
            await interaction.response.send_message("Refusé.", ephemeral=True)
            return
        if slot.value == "admin":
            cfg = replace(cfg, admin_role_id=role.id)
        elif slot.value == "legend_i":
            cfg = replace(cfg, legend_role_i_id=role.id)
        elif slot.value == "legend_ii":
            cfg = replace(cfg, legend_role_ii_id=role.id)
        else:
            cfg = replace(cfg, legend_role_iii_id=role.id)
        await self._repo.upsert_guild_config(cfg)
        await interaction.response.send_message(
            f"✅ {slot.value} → {role.mention}", ephemeral=True,
        )

    # ── shared implementations ───────────────────────────────────────────
    async def _stats_polling_impl(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        if not _is_operator(interaction, cfg):
            await interaction.response.send_message("Refusé.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        s = await self._metrics.summary()
        await interaction.followup.send(
            f"P95 latency poll : **{s['p95_latency_ms']}** ms · "
            f"Queue : **{s['queue_depth']}** · 429 : **{s['api_429']}**",
            ephemeral=True,
        )

    async def _force_poll_impl(
        self, interaction: discord.Interaction, tag: str | None,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        if not _is_operator(interaction, cfg):
            await interaction.response.send_message("Refusé.", ephemeral=True)
            return
        resolved = tag
        if not resolved:
            resolved = await self._repo.get_first_active_tag(interaction.user.id)
        if not resolved:
            await interaction.response.send_message(
                "Aucun tag : passe `tag` ou lie `/lier`.", ephemeral=True,
            )
            return
        nt = _normalise_tag(resolved)
        target = await self._repo.get_poll_target(nt)
        if target is None:
            await interaction.response.send_message(
                f"Tag `{nt}` introuvable ou inactif.", ephemeral=True,
            )
            return
        try:
            self._poller.enqueue_immediate(target)
        except Exception as exc:  # noqa: BLE001
            await interaction.response.send_message(
                f"File pleine : `{exc!s}`", ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Poll forcé pour `{nt}`.", ephemeral=True,
        )

    async def _reset_cooldowns_impl(
        self, interaction: discord.Interaction, tag: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Serveur requis.", ephemeral=True)
            return
        cfg = await self._repo.get_guild_config(interaction.guild_id)
        if not _is_operator(interaction, cfg):
            await interaction.response.send_message("Refusé.", ephemeral=True)
            return
        nt = _normalise_tag(tag)
        n = await self._repo.delete_alert_history_for_tag(nt)
        await interaction.response.send_message(
            f"Supprimé **{n}** ligne(s) d’alertes pour `{nt}`.",
            ephemeral=True,
        )


__all__ = ["AdminCog", "LeagueType"]
