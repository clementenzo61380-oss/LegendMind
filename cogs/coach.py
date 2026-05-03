"""Coaching cog — `/daily`, `/predict`, `/score`.

These commands surface user-level analytics over the snapshot history we
already collect. They are read-only — no writes happen here.

Avril 2026 — Refonte Ranked Mode Supercell : chaque commande doit
brancher sur le **tier** Legend déclaré (I/II/III), car les formats de
tournoi sont radicalement différents :

  * Legend I   : 8 batailles/jour, reset 22h UTC, classement mondial
                 temps réel → vue quotidienne.
  * Legend II  : 30 batailles/semaine, tournoi hebdo, promo top 3/groupe
                 → vue hebdomadaire.
  * Legend III : 24 batailles/semaine, tournoi hebdo, promo top 5/groupe
                 → vue hebdomadaire.

La source de vérité du tier est ``players.legend_tier`` (déclaré au
``/setup`` et modifiable via ``/tier``). Si UNKNOWN, on invite l'user à
déclarer son tier — on ne devine PAS à partir des trophées.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import coc
import discord
from discord import app_commands
from discord.ext import commands

from constants import LeagueType
from models import LegendSnapshot
from services import coach_briefing as briefing
from services.db import Repository
from services.logic import legend_consistency_score
from services.rank_predictor import RankPredictor

log = logging.getLogger(__name__)


class CoachCog(commands.Cog):
    """User analytics commands, tier-aware (Avril 2026)."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: Repository,
        coc_client: coc.Client,
        rank_predictor: RankPredictor,
    ) -> None:
        self.bot = bot
        self._repo = repository
        self._coc = coc_client
        self._rank_predictor = rank_predictor

    # ── /daily ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="daily",
        description=(
            "Briefing : Legend I = quotidien (8/jour), Legend II/III = hebdo."
        ),
    )
    async def daily(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        ctx = await self._load_context(interaction)
        if ctx is None:
            return
        tag, tier, latest = ctx

        if tier is LeagueType.LEGEND_I:
            since = datetime.now(timezone.utc) - timedelta(days=14)
            snapshots = await self._repo.get_snapshots_since(tag, since)
            embed = briefing.daily_embed_legend_i(tag, latest, snapshots)
        else:
            since = datetime.now(timezone.utc) - timedelta(days=8)
            snapshots = await self._repo.get_snapshots_since(tag, since)
            embed = briefing.weekly_embed(
                tag, tier, latest, snapshots, briefing.weekly_quota(tier),
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /predict ─────────────────────────────────────────────────────────
    @app_commands.command(
        name="predict",
        description=(
            "Projection : Legend I = trophées + rang mondial, "
            "Legend II/III = progression hebdo."
        ),
    )
    async def predict(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        ctx = await self._load_context(interaction)
        if ctx is None:
            return
        tag, tier, latest = ctx
        since = datetime.now(timezone.utc) - timedelta(days=14)
        snapshots = await self._repo.get_snapshots_since(tag, since)

        if tier is LeagueType.LEGEND_I:
            embed = briefing.predict_embed_legend_i(
                tag, latest, snapshots, self._rank_predictor,
            )
        else:
            embed = briefing.weekly_predict_embed(
                tag, tier, latest, snapshots, briefing.weekly_quota(tier),
                self._rank_predictor,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /score ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="score",
        description=(
            "Score de consistance : Legend I = % jours 8/8, "
            "Legend II/III = % semaines complétées."
        ),
    )
    async def score(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        ctx = await self._load_context(interaction)
        if ctx is None:
            return
        tag, tier, _latest = ctx
        if tier is LeagueType.LEGEND_I:
            since = datetime.now(timezone.utc) - timedelta(days=35)
            snapshots = await self._repo.get_snapshots_since(tag, since)
            ratio, full_days, total_days = legend_consistency_score(
                snapshots, days=30,
            )
            if total_days == 0:
                await interaction.followup.send(
                    "Pas encore assez de jours observés pour calculer ton "
                    "Score (reviens après quelques jours d'activité).",
                    ephemeral=True,
                )
                return
            embed = briefing.consistency_embed_daily(
                tag, ratio, full_days, total_days,
            )
        else:
            # Legend II/III : on compte les semaines où le quota hebdo est
            # atteint sur les 4 dernières semaines.
            since = datetime.now(timezone.utc) - timedelta(days=29)
            snapshots = await self._repo.get_snapshots_since(tag, since)
            full_weeks, total_weeks, ratio = briefing.weekly_consistency(
                snapshots, briefing.weekly_quota(tier),
            )
            if total_weeks == 0:
                await interaction.followup.send(
                    "Pas encore assez de semaines observées pour calculer "
                    "ton Score (reviens après 7 jours d'activité).",
                    ephemeral=True,
                )
                return
            embed = briefing.consistency_embed_weekly(
                tag, tier, ratio, full_weeks, total_weeks,
                briefing.weekly_quota(tier),
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── shared loader ────────────────────────────────────────────────────
    async def _load_context(
        self, interaction: discord.Interaction,
    ) -> tuple[str, LeagueType, LegendSnapshot] | None:
        """Resolve (tag, tier, latest snapshot) for the invoking user.

        Sends the appropriate ephemeral followup and returns ``None`` when
        any precondition is missing (no link, tier not declared, no
        snapshot yet).
        """
        tag = await self._repo.get_first_active_tag(interaction.user.id)
        if tag is None:
            await interaction.followup.send(
                "Aucun compte CoC lié. Utilise `/setup tag:#TONTAG` d'abord.",
                ephemeral=True,
            )
            return None
        tier = await self._repo.get_legend_tier(tag)
        if tier is LeagueType.UNKNOWN:
            await interaction.followup.send(
                f"⚠️ Tier Legend non déclaré pour `{tag}`. Lance "
                "`/tier` pour choisir entre Légende I, II ou III.",
                ephemeral=True,
            )
            return None
        latest = await self._repo.get_latest_snapshot(tag)
        if latest is None:
            await interaction.followup.send(
                "Pas encore de snapshot pour ton compte. Reviens dans "
                "quelques minutes.",
                ephemeral=True,
            )
            return None
        return tag, tier, latest
