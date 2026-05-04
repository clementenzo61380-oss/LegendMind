"""Daily digest — envoie automatiquement l'équivalent de /daily + /predict + /score.

Un seul message Discord par jour et par utilisateur (heure UTC configurable
via ``/digest``). Gratuit pour tous les comptes liés : ce n'est pas soumis
au quota ``/ping``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord

from constants import LeagueType
from services import coach_briefing as briefing
from services.db import Repository
from services.logic import legend_consistency_score
from services.rank_predictor import RankPredictor

log = logging.getLogger(__name__)

_DISCORD_MAX_EMBEDS = 10


class DailyDigestService:
    def __init__(
        self,
        bot: discord.Client,
        repository: Repository,
        rank_predictor: RankPredictor,
    ) -> None:
        self._bot = bot
        self._repo = repository
        self._rank = rank_predictor

    async def run_tick(self, now: datetime) -> int:
        """Dispatch due digests for ``now``'s UTC hour. Returns users notified."""
        today = now.date()
        hour = now.hour
        user_ids = await self._repo.list_digest_due_user_ids(hour, today)
        sent = 0
        for uid in user_ids:
            embeds, burn_day_without_dm = await self._build_embeds_for_user(uid)
            if not embeds:
                if burn_day_without_dm:
                    await self._repo.mark_digest_sent(uid, today)
                continue
            if len(embeds) > _DISCORD_MAX_EMBEDS:
                embeds = embeds[:_DISCORD_MAX_EMBEDS]
            embeds[0].title = f"🤖 Digest auto — {embeds[0].title}"
            ok = await self._dm_embeds(uid, embeds)
            if ok:
                await self._repo.mark_digest_sent(uid, today)
                sent += 1
        return sent

    async def _build_embeds_for_user(
        self,
        discord_user_id: int,
    ) -> tuple[list[discord.Embed], bool]:
        """Returns ``(embeds, burn_today)``.

        When ``burn_today`` is True and ``embeds`` is empty, the scheduler
        should mark the day consumed (e.g. all tiers still UNKNOWN).
        """
        accounts = await self._repo.list_active_accounts(discord_user_id)
        if not accounts:
            return [], True
        embeds: list[discord.Embed] = []
        any_declared_tier = False
        for tag, _name, tier in accounts:
            if tier is LeagueType.UNKNOWN:
                continue
            any_declared_tier = True
            embeds.extend(await self._embeds_for_tag(tag, tier))
        if not any_declared_tier:
            return [], True
        return embeds, False

    async def _embeds_for_tag(
        self,
        tag: str,
        tier: LeagueType,
    ) -> list[discord.Embed]:
        out: list[discord.Embed] = []
        latest = await self._repo.get_latest_snapshot(tag)
        if latest is None:
            return out
        if tier is LeagueType.LEGEND_I:
            since = datetime.now(timezone.utc) - timedelta(days=14)
            snapshots = await self._repo.get_snapshots_since(tag, since)
            out.append(briefing.daily_embed_legend_i(tag, latest, snapshots))
            out.append(
                briefing.predict_embed_legend_i(
                    tag,
                    latest,
                    snapshots,
                    self._rank,
                ),
            )
            since30 = datetime.now(timezone.utc) - timedelta(days=35)
            snaps30 = await self._repo.get_snapshots_since(tag, since30)
            ratio, full_d, total_d = legend_consistency_score(snaps30, days=30)
            if total_d > 0:
                out.append(
                    briefing.consistency_embed_daily(
                        tag,
                        ratio,
                        full_d,
                        total_d,
                    ),
                )
        else:
            q = briefing.weekly_quota(tier)
            since8 = datetime.now(timezone.utc) - timedelta(days=8)
            snaps8 = await self._repo.get_snapshots_since(tag, since8)
            out.append(briefing.weekly_embed(tag, tier, latest, snaps8, q))
            since14 = datetime.now(timezone.utc) - timedelta(days=14)
            snaps14 = await self._repo.get_snapshots_since(tag, since14)
            out.append(
                briefing.weekly_predict_embed(
                    tag,
                    tier,
                    latest,
                    snaps14,
                    q,
                    self._rank,
                ),
            )
            since29 = datetime.now(timezone.utc) - timedelta(days=29)
            snaps29 = await self._repo.get_snapshots_since(tag, since29)
            full_w, total_w, ratio = briefing.weekly_consistency(snaps29, q)
            if total_w > 0:
                out.append(
                    briefing.consistency_embed_weekly(
                        tag,
                        tier,
                        ratio,
                        full_w,
                        total_w,
                        q,
                    ),
                )
        return out

    async def _dm_embeds(self, discord_user_id: int, embeds: list[discord.Embed]) -> bool:
        user: discord.User | discord.Member | None = self._bot.get_user(discord_user_id)
        if user is None:
            try:
                user = await self._bot.fetch_user(discord_user_id)
            except (discord.NotFound, discord.HTTPException):
                log.info("Digest: user %s introuvable", discord_user_id)
                return False
        try:
            await user.send(embeds=embeds)
        except discord.Forbidden:
            log.info("Digest: DM bloqué pour user %s", discord_user_id)
            return False
        except discord.HTTPException:
            log.exception("Digest: échec DM user %s", discord_user_id)
            return False
        return True
