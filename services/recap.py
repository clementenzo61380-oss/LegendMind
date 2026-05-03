"""Weekly recap service — Legend II/III digest sent every Sunday 22h UTC.

Why a dedicated service?
------------------------
Avril 2026 — Supercell a découpé Legend League en 3 tiers :

  * Legend I  → 8 batailles/jour, alertes en quasi-temps réel (existant).
  * Legend II → 30 batailles/semaine, tournoi hebdo (PAS de reset daily).
  * Legend III → 24 batailles/semaine, tournoi hebdo (PAS de reset daily).

Pour Legend II/III, marteler des DM "défense subie" toutes les 3 minutes
n'a aucun sens : le score se joue sur la semaine. À la place, on agrège
les snapshots des 7 derniers jours et on envoie UN SEUL DM digest le
dimanche soir UTC, juste avant le reset hebdo.

L'envoi est :
  * idempotent par (tag, semaine) → pas de double DM si le scheduler
    redémarre dans la même fenêtre,
  * gated par ``UserPreferences.alert_on_defense`` (même opt-in que
    /ping pour Legend I, comportement cohérent).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord

from constants import COLOR_INFO, LeagueType
from models import LegendSnapshot
from services.db import Repository
from services.game_tuning import get_tuning

log = logging.getLogger(__name__)

# Cooldown table key reused so re-scheduling within the same week is a no-op.
_RECAP_ALERT_KEY = "weekly_recap"


@dataclass(frozen=True, slots=True)
class _RecapDigest:
    """Aggregated week stats for a single tag."""
    player_tag: str
    discord_user_id: int
    name: str | None
    tier: LeagueType
    snapshots: list[LegendSnapshot]

    @property
    def first(self) -> LegendSnapshot:
        return self.snapshots[0]

    @property
    def last(self) -> LegendSnapshot:
        return self.snapshots[-1]

    @property
    def trophies_delta(self) -> int:
        return self.last.trophies - self.first.trophies

    @property
    def trophies_won(self) -> int:
        return max(0, self.last.trophies_gained - self.first.trophies_gained)

    @property
    def trophies_lost(self) -> int:
        return max(0, self.last.trophies_lost - self.first.trophies_lost)

    @property
    def attacks_done(self) -> int:
        # Both fields reset to 0 on the season boundary; if the week spans
        # the rollover, we use the max instead of last-minus-first.
        if self.last.attacks_done >= self.first.attacks_done:
            return self.last.attacks_done - self.first.attacks_done
        return self.last.attacks_done

    @property
    def quota(self) -> int:
        return _weekly_quota(self.tier)


def _weekly_quota(tier: LeagueType) -> int:
    tun = get_tuning()
    if tier is LeagueType.LEGEND_II:
        return tun.legend_ii_weekly_battles
    if tier is LeagueType.LEGEND_III:
        return tun.legend_iii_weekly_battles
    return 0  # Legend I a un quota daily, pas hebdo.


class WeeklyRecapService:
    """Builds and sends the Sunday 22h UTC digest for Legend II/III players.

    Stateless beyond cooldown bookkeeping (recorded in ``alert_history``
    via ``Repository.record_alert`` with type ``weekly_recap``).
    """

    def __init__(self, bot: discord.Client, repository: Repository) -> None:
        self._bot = bot
        self._repo = repository

    async def run(self, *, lookback: timedelta = timedelta(days=7)) -> int:
        """Scan Legend II/III, build digests, send DMs.

        Returns the number of digests successfully sent. Safe to call
        multiple times in the same week — sends are idempotent per tag
        thanks to the cooldown gate (``alert_history`` lookup).
        """
        now = datetime.now(timezone.utc)
        since = now - lookback
        sent = 0
        candidates = await self._repo.list_active_legend_players_in_tier(
            LeagueType.LEGEND_II, LeagueType.LEGEND_III,
        )
        for tag, discord_user_id, name, tier in candidates:
            prefs = await self._repo.get_preferences(discord_user_id)
            if not prefs.enable_alerts or not prefs.alert_on_defense:
                continue
            if await self._already_sent_this_week(tag, now):
                continue
            snapshots = await self._repo.get_snapshots_since(tag, since)
            if len(snapshots) < 2:
                continue
            digest = _RecapDigest(
                player_tag=tag,
                discord_user_id=discord_user_id,
                name=name,
                tier=tier,
                snapshots=snapshots,
            )
            if await self._send(digest):
                sent += 1
        return sent

    # ── internals ────────────────────────────────────────────────────────
    async def _already_sent_this_week(
        self, tag: str, now: datetime,
    ) -> bool:
        """True when a recap was already dispatched in the past 6 days."""
        last_at = await self._repo.get_last_alert_at(tag, _RECAP_ALERT_KEY)
        if last_at is None:
            return False
        return (now - last_at) < timedelta(days=6)

    async def _send(self, digest: _RecapDigest) -> bool:
        user: discord.User | discord.Member | None = (
            self._bot.get_user(digest.discord_user_id)
        )
        if user is None:
            try:
                user = await self._bot.fetch_user(digest.discord_user_id)
            except (discord.NotFound, discord.HTTPException):
                log.info(
                    "Recap target user %d not reachable (tag %s)",
                    digest.discord_user_id, digest.player_tag,
                )
                return False
        embed = _build_embed(digest)
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            log.info(
                "Recap DM blocked for user %d (tag %s)",
                digest.discord_user_id, digest.player_tag,
            )
            return False
        except discord.HTTPException:
            log.exception(
                "Failed to DM weekly recap to %d", digest.discord_user_id,
            )
            return False
        await self._repo.record_alert(
            digest.player_tag, _RECAP_ALERT_KEY,
            digest.discord_user_id,
            f"Recap envoyé : Δ={digest.trophies_delta:+d} trophies, "
            f"{digest.attacks_done}/{digest.quota} batailles",
        )
        return True


def _build_embed(digest: _RecapDigest) -> discord.Embed:
    tier_label = "Légende II" if digest.tier is LeagueType.LEGEND_II else "Légende III"
    title = f"📊 Récap hebdo — {tier_label}"
    if digest.name:
        title += f" — {digest.name}"
    delta = digest.trophies_delta
    delta_emoji = "🟢" if delta >= 0 else "🔴"
    embed = discord.Embed(
        title=title,
        description=(
            f"`{digest.player_tag}` — semaine du "
            f"{digest.first.captured_at.strftime('%d/%m')} au "
            f"{digest.last.captured_at.strftime('%d/%m')}."
        ),
        color=COLOR_INFO,
    )
    embed.add_field(
        name="🏆 Trophies",
        value=(
            f"{digest.last.trophies}\n{delta_emoji} **{delta:+d}** sur la semaine"
        ),
        inline=True,
    )
    embed.add_field(
        name="⚔️ Batailles",
        value=f"**{digest.attacks_done}/{digest.quota}** utilisées",
        inline=True,
    )
    embed.add_field(
        name="📈 Bilan trophies",
        value=(
            f"+{digest.trophies_won} gagnés / -{digest.trophies_lost} perdus"
        ),
        inline=False,
    )
    if digest.attacks_done < digest.quota:
        remaining = digest.quota - digest.attacks_done
        embed.add_field(
            name="⏳ Reset hebdo proche",
            value=(
                f"Il te reste **{remaining} batailles** à utiliser avant le "
                "reset (lundi début de semaine UTC)."
            ),
            inline=False,
        )
    embed.set_footer(text="Récap envoyé chaque dimanche 22h UTC pour Legend II/III.")
    return embed
