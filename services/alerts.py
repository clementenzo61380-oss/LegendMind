"""Alert evaluation, deduplication, and dispatch.

`AlertManager` is the only object Discord cogs talk to for alerts. It:
  1. evaluates an `AttackDelta` against user prefs → list[Alert]
  2. filters out alerts on cooldown or in quiet hours
  3. dispatches survivors as Discord embeds and records them

Cooldown state is persisted in `alert_history` (no Redis required).
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord

from constants import (
    ALERT_COMEBACK_DELTA,
    ALERT_COOLDOWN_SECONDS,
    ALERT_STREAK_LENGTH,
    COLOR_DANGER,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARNING,
    LeagueType,
)
from models import AttackDelta, LegendSnapshot, UserPreferences
from services.game_tuning import get_tuning
# LeagueType is imported lazily to avoid pulling constants into the public surface.
from services.db import Repository
from services.logic import (
    check_attack_pace,
    check_threshold,
    infer_defense_outcome,
)
from services.metrics_collector import MetricsCollector
from services.quota import ConsumeResult, QuotaService

log = logging.getLogger(__name__)


class AlertType(str, enum.Enum):
    RELEGATION_IMMINENT = "relegation_imminent"
    PROMOTION_POSSIBLE = "promotion_possible"
    PACE_CRITICAL = "pace_critical"
    PACE_WARNING = "pace_warning"
    STREAK_POSITIVE = "streak_positive"
    STREAK_NEGATIVE = "streak_negative"
    SEASON_BEST_BROKEN = "season_best_broken"
    DAILY_GOAL_REACHED = "daily_goal_reached"
    COMEBACK_DETECTED = "comeback_detected"
    DEFENSE_TAKEN = "defense_taken"


@dataclass(frozen=True, slots=True)
class Alert:
    """A single alert ready to be sent.

    Cogs treat these as opaque — only `AlertManager.dispatch` builds the
    Discord embed and writes to alert_history.
    """
    type: AlertType
    player_tag: str
    discord_user_id: int
    title: str
    description: str
    color: int
    cta: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Per-type styling — keeps embed construction declarative.
# ─────────────────────────────────────────────────────────────────────────────
_STYLE: dict[AlertType, tuple[str, int, str | None]] = {
    AlertType.RELEGATION_IMMINENT: (
        "⚠️ Relégation imminente",
        COLOR_DANGER,
        "Lance une attaque maintenant pour défendre ta ligue !",
    ),
    AlertType.PROMOTION_POSSIBLE: (
        "🚀 Promotion à portée",
        COLOR_SUCCESS,
        "Quelques victoires de plus et tu changes de ligue.",
    ),
    AlertType.PACE_CRITICAL: (
        "🔥 Rythme critique",
        COLOR_DANGER,
        "Reset bientôt, attaques restantes en retard.",
    ),
    AlertType.PACE_WARNING: (
        "🟠 Rythme insuffisant",
        COLOR_WARNING,
        "Pense à faire tes attaques avant le reset.",
    ),
    AlertType.STREAK_POSITIVE: (
        "🔥 Série gagnante",
        COLOR_SUCCESS,
        None,
    ),
    AlertType.STREAK_NEGATIVE: (
        "❄️ Série perdante",
        COLOR_WARNING,
        "Souffle, change de cible, et reviens en forme.",
    ),
    AlertType.SEASON_BEST_BROKEN: (
        "🏆 Nouveau record de saison",
        COLOR_SUCCESS,
        None,
    ),
    AlertType.DAILY_GOAL_REACHED: (
        "🎯 Objectif du jour atteint",
        COLOR_INFO,
        None,
    ),
    AlertType.COMEBACK_DETECTED: (
        "📈 Belle remontée",
        COLOR_INFO,
        None,
    ),
    AlertType.DEFENSE_TAKEN: (
        "🛡️ Défense subie",
        COLOR_WARNING,
        "Désactive cette notification avec `/ping actif:False`.",
    ),
}


class AlertManager:
    """Evaluate, deduplicate, and dispatch Legend alerts.

    Stateless beyond the persisted cooldown table. Constructed once at
    boot and reused for every delta produced by the poller.
    """

    def __init__(
        self,
        bot: discord.Client,
        repository: Repository,
        default_cooldown_seconds: int,
        metrics_collector: MetricsCollector | None = None,
        quota_service: QuotaService | None = None,
    ) -> None:
        self._bot = bot
        self._repo = repository
        self._default_cooldown = default_cooldown_seconds
        self._metrics = metrics_collector
        self._quota = quota_service

    # ── public API ───────────────────────────────────────────────────────
    async def evaluate_and_dispatch(
        self,
        delta: AttackDelta,
        prefs: UserPreferences,
    ) -> list[Alert]:
        """One-shot: build candidates, filter by cooldown, send. Returns sent."""
        if not prefs.enable_alerts:
            return []
        candidates = await self.evaluate(delta, prefs)
        if not candidates:
            return []
        sent: list[Alert] = []
        for alert in candidates:
            if not await self._can_send(alert):
                continue
            await self._dispatch_one(alert)
            sent.append(alert)
        return sent

    async def evaluate(
        self, delta: AttackDelta, prefs: UserPreferences,
    ) -> list[Alert]:
        """Generate every alert candidate this delta justifies (no dedup yet)."""
        out: list[Alert] = []
        current = delta.current
        owner = prefs.discord_user_id

        # Avril 2026 Ranked refonte : Legend II/III sont sur tournoi
        # hebdomadaire (pas de reset daily, pas de seuils trophy de promo/
        # relégation, pas de quota 8/jour). Les alertes per-defense, pace
        # et threshold ne s'appliquent qu'à Legend I — les II/III reçoivent
        # un récapitulatif hebdo le dimanche soir UTC via WeeklyRecapService.
        is_legend_i = current.league_type is LeagueType.LEGEND_I

        # Per-defense push (opt-in via /ping). Detected when the cumulative
        # `trophies_lost` counter increases between two snapshots. The reset
        # boundary (counter resets to 0 on a new season) is excluded so we
        # never fire spuriously after Supercell rolls the season window.
        if is_legend_i and prefs.alert_on_defense:
            lost_delta = current.trophies_lost - delta.previous.trophies_lost
            if lost_delta > 0:
                # Per-defense detail (attacker tag, exact stars, destruction %)
                # is NOT exposed by the public CoC API. We inject a best-effort
                # estimate derived from the trophy swing — enough to gauge how
                # bad the defense was without pretending to know the truth.
                stars_hint, destruction_hint = infer_defense_outcome(lost_delta)
                out.append(self._build(
                    AlertType.DEFENSE_TAKEN, current.player_tag, owner,
                    description=(
                        f"Tu viens de perdre **{lost_delta}** trophées "
                        f"(passé de {delta.previous.trophies} à "
                        f"{current.trophies}).\n\n"
                        f"**Attaque estimée** : {stars_hint} • "
                        f"{destruction_hint}\n"
                        f"_Estimé d'après les trophées perdus — l'API CoC "
                        f"n'expose pas le détail des défenses subies._"
                    ),
                ))

        # Threshold (relegation / promotion) — Legend I uniquement.
        # Pour II/III, la promotion/rétrogradation est PAR GROUPE, gérée par
        # Supercell en fin de tournoi hebdo, pas par seuil trophy.
        threshold_tag = check_threshold(current) if is_legend_i else None
        if threshold_tag == "relegation_imminent":
            out.append(self._build(
                AlertType.RELEGATION_IMMINENT, current.player_tag, owner,
                description=(
                    f"Tu es à **{current.trophies}** trophées, juste au-dessus "
                    "du seuil de relégation. Une seule défense peut te faire "
                    "tomber."
                ),
            ))
        elif threshold_tag == "promotion_possible":
            out.append(self._build(
                AlertType.PROMOTION_POSSIBLE, current.player_tag, owner,
                description=(
                    f"Tu es à **{current.trophies}** trophées — la prochaine "
                    "ligue est à portée de main."
                ),
            ))

        # Pace (Legend I daily quota uniquement — II/III en hebdo).
        pace_tag = (
            check_attack_pace(current.attacks_done, current.league_type)
            if is_legend_i else None
        )
        q = get_tuning().legend_i_daily_attack_quota
        if pace_tag == "pace_critical":
            out.append(self._build(
                AlertType.PACE_CRITICAL, current.player_tag, owner,
                description=(
                    f"{current.attacks_done}/{q} attaques effectuées et le reset "
                    "approche."
                ),
            ))
        elif pace_tag == "pace_warning":
            out.append(self._build(
                AlertType.PACE_WARNING, current.player_tag, owner,
                description=(
                    f"{current.attacks_done}/{q} attaques aujourd'hui — il reste "
                    "du temps mais ne traîne pas."
                ),
            ))

        # Streaks: read recent snapshots and check sign-consistency.
        streak = await self._detect_streak(current.player_tag)
        if streak == AlertType.STREAK_POSITIVE:
            out.append(self._build(
                streak, current.player_tag, owner,
                description=(
                    f"{ALERT_STREAK_LENGTH} attaques gagnantes consécutives. "
                    "Continue !"
                ),
            ))
        elif streak == AlertType.STREAK_NEGATIVE:
            out.append(self._build(
                streak, current.player_tag, owner,
                description=(
                    f"{ALERT_STREAK_LENGTH} défenses perdantes consécutives. "
                    "Pense à attaquer pour casser le cycle."
                ),
            ))

        # 24h comeback.
        if await self._detect_comeback(current):
            out.append(self._build(
                AlertType.COMEBACK_DETECTED, current.player_tag, owner,
                description=(
                    f"+{ALERT_COMEBACK_DELTA} trophées ou plus en 24h. "
                    "Belle remontée !"
                ),
            ))

        # Season best.
        if await self._detect_season_best(current):
            out.append(self._build(
                AlertType.SEASON_BEST_BROKEN, current.player_tag, owner,
                description=(
                    f"Nouveau record personnel de saison : "
                    f"**{current.trophies}** trophées."
                ),
            ))

        # Daily goal reached (delegated — needs goal lookup).
        if await self._detect_daily_goal(delta):
            out.append(self._build(
                AlertType.DAILY_GOAL_REACHED, current.player_tag, owner,
                description="Tu as atteint ton objectif d'attaques du jour.",
            ))

        return out

    # ── cooldown / quiet hours ───────────────────────────────────────────
    async def _can_send(self, alert: Alert) -> bool:
        if await self._is_in_quiet_hours(alert.discord_user_id):
            return False
        last_at = await self._repo.get_last_alert_at(
            alert.player_tag, alert.type.value,
        )
        if last_at is None:
            return True
        cooldown = ALERT_COOLDOWN_SECONDS.get(
            alert.type.value, self._default_cooldown,
        )
        elapsed = (datetime.now(timezone.utc) - last_at).total_seconds()
        return elapsed >= cooldown

    async def _is_in_quiet_hours(self, discord_user_id: int) -> bool:
        prefs = await self._repo.get_preferences(discord_user_id)
        if prefs.quiet_hours_start is None or prefs.quiet_hours_end is None:
            return False
        now_h = datetime.now(timezone.utc).hour
        s, e = prefs.quiet_hours_start, prefs.quiet_hours_end
        if s == e:
            return False
        if s < e:
            return s <= now_h < e
        # Wraps midnight (e.g. 22 → 6).
        return now_h >= s or now_h < e

    # ── dispatch ─────────────────────────────────────────────────────────
    async def _dispatch_one(self, alert: Alert) -> None:
        # Quota gate: only the per-defense push is metered. Free users get
        # PING_QUOTA_FREE_MONTHLY/month; Premium + trial = unlimited.
        if alert.type is AlertType.DEFENSE_TAKEN and self._quota is not None:
            outcome = await self._quota.consume_ping(alert.discord_user_id)
            if outcome is ConsumeResult.EXHAUSTED:
                # Send the upsell DM at most once per month, then go silent.
                if await self._quota.should_warn_full(alert.discord_user_id):
                    await self._send_quota_exhausted_warning(alert.discord_user_id)
                return
        embed = _build_embed(alert)
        user: discord.User | discord.Member | None = self._bot.get_user(alert.discord_user_id)
        if user is None:
            try:
                user = await self._bot.fetch_user(alert.discord_user_id)
            except discord.NotFound:
                log.info("Alert target user %d not found", alert.discord_user_id)
                return
            except discord.HTTPException:
                log.exception(
                    "fetch_user failed for alert %s to %d",
                    alert.type.value, alert.discord_user_id,
                )
                return
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            log.info(
                "DM blocked for user %d (alert %s)",
                alert.discord_user_id, alert.type.value,
            )
        except discord.HTTPException:
            log.exception(
                "Failed to DM alert %s to %d",
                alert.type.value, alert.discord_user_id,
            )
            return
        await self._repo.record_alert(
            alert.player_tag, alert.type.value,
            alert.discord_user_id, alert.description,
        )
        if self._metrics:
            await self._metrics.record_alert_sent()

    async def _send_quota_exhausted_warning(self, discord_user_id: int) -> None:
        """One-time monthly DM telling the user their /ping quota is gone."""
        user: discord.User | discord.Member | None = self._bot.get_user(discord_user_id)
        if user is None:
            try:
                user = await self._bot.fetch_user(discord_user_id)
            except (discord.NotFound, discord.HTTPException):
                return
        embed = discord.Embed(
            title="🔕 Quota /ping atteint",
            description=(
                "Tu as utilisé tes **50 notifications de défense ce mois-ci**.\n"
                "Les prochaines défenses ne déclencheront pas de DM jusqu'à la "
                "fin du mois (UTC).\n\n"
                "🎁 Passe **Premium** avec `/premium` pour des notifications "
                "illimitées (et 3 comptes liés)."
            ),
            color=COLOR_WARNING,
        )
        try:
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            log.info("Quota warning DM blocked for user %d", discord_user_id)

    # ── detectors ────────────────────────────────────────────────────────
    async def _detect_streak(self, tag: str) -> AlertType | None:
        """Read the last `ALERT_STREAK_LENGTH + 1` snapshots and check signs.

        A streak fires when the deltas between every consecutive pair share
        the same non-zero sign.
        """
        n = ALERT_STREAK_LENGTH + 1
        # Convenience: pull a generous window and slice; one extra round-trip
        # avoids a dedicated DB method for now.
        since = datetime.now(timezone.utc) - timedelta(days=2)
        snapshots = await self._repo.get_snapshots_since(tag, since)
        if len(snapshots) < n:
            return None
        recent = snapshots[-n:]
        deltas = [
            recent[i + 1].trophies - recent[i].trophies
            for i in range(len(recent) - 1)
        ]
        if all(d > 0 for d in deltas):
            return AlertType.STREAK_POSITIVE
        if all(d < 0 for d in deltas):
            return AlertType.STREAK_NEGATIVE
        return None

    async def _detect_comeback(self, current: LegendSnapshot) -> bool:
        since = current.captured_at - timedelta(hours=24)
        snapshots = await self._repo.get_snapshots_since(
            current.player_tag, since,
        )
        if len(snapshots) < 2:
            return False
        baseline = snapshots[0].trophies
        return (current.trophies - baseline) >= ALERT_COMEBACK_DELTA

    async def _detect_season_best(self, current: LegendSnapshot) -> bool:
        """True when the current snapshot is the highest trophy count this season.

        Season is approximated as "since the start of the current calendar
        month UTC" — close enough for alerts; the season service will pin it
        precisely once that module lands.
        """
        if current.league_type == LeagueType.UNKNOWN:
            return False
        month_start = current.captured_at.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        snapshots = await self._repo.get_snapshots_since(
            current.player_tag, month_start,
        )
        if not snapshots:
            return False
        # `current` is already saved before we get here, so it's in the list.
        max_prev = max(
            (s.trophies for s in snapshots if s.captured_at < current.captured_at),
            default=0,
        )
        return current.trophies > max_prev > 0

    async def _detect_daily_goal(self, delta: AttackDelta) -> bool:
        goal = await self._repo.get_goal(delta.current.player_tag)
        if goal is None:
            return False
        # Only meaningful if the *new* attacks pushed the daily count to/past
        # the target *this cycle* — avoids re-firing on later polls of the same day.
        target = goal.target_attacks_per_day
        prev_done = delta.previous.attacks_done
        cur_done = delta.current.attacks_done
        # Reset boundary: if attacks_done dropped (new day), don't fire.
        if cur_done < prev_done:
            return False
        return prev_done < target <= cur_done

    # ── builders ─────────────────────────────────────────────────────────
    def _build(
        self,
        alert_type: AlertType,
        player_tag: str,
        discord_user_id: int,
        description: str,
    ) -> Alert:
        title, color, cta = _STYLE[alert_type]
        return Alert(
            type=alert_type,
            player_tag=player_tag,
            discord_user_id=discord_user_id,
            title=title,
            description=description,
            color=color,
            cta=cta,
        )


def _build_embed(alert: Alert) -> discord.Embed:
    embed = discord.Embed(
        title=alert.title,
        description=alert.description,
        color=alert.color,
    )
    if alert.cta:
        embed.add_field(name="​", value=f"➡️ {alert.cta}", inline=False)
    next_reset = _next_reset_utc()
    embed.set_footer(
        text=f"Prochain reset Legend : {next_reset.strftime('%H:%M UTC')}",
    )
    return embed


def _next_reset_utc() -> datetime:
    now = datetime.now(timezone.utc)
    today_reset = now.replace(
        hour=get_tuning().legend_daily_reset_hour_utc,
        minute=0, second=0, microsecond=0,
    )
    return today_reset if today_reset > now else today_reset + timedelta(days=1)
