"""Tier-aware coaching embeds shared by ``CoachCog`` and ``DailyDigestService``.

Keeping builders here avoids ``services/*`` importing from ``cogs/*`` and lets
the automated digest reuse the exact same rendering as the slash commands.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord

from constants import (
    COLOR_INFO,
    COLOR_NEUTRAL,
    COLOR_SUCCESS,
    COLOR_WARNING,
    LeagueType,
)
from models import LegendSnapshot
from services.game_tuning import get_tuning
from services.logic import optimal_attack_hour, predict_end_of_season_trophies
from services.rank_predictor import RankPredictor, format_rank, rank_emoji


def daily_embed_legend_i(
    tag: str,
    latest: LegendSnapshot,
    snapshots: list[LegendSnapshot],
    *,
    defenses_today: int | None = None,
    avg_defense_loss_today: float | None = None,
) -> discord.Embed:
    quota = get_tuning().legend_i_daily_attack_quota
    embed = discord.Embed(
        title=f"📅 Briefing du jour — Légende I — {tag}",
        color=COLOR_INFO,
    )
    embed.add_field(
        name="🏆 Trophées",
        value=f"**{latest.trophies}**",
        inline=True,
    )
    remaining = max(0, quota - latest.attacks_done)
    embed.add_field(
        name="⚔️ Attaques restantes",
        value=f"{remaining}/{quota}",
        inline=True,
    )
    if latest.attacks_done > 0:
        avg_atk = latest.trophies_gained / max(1, latest.attacks_done)
        def_line = (
            f"{avg_defense_loss_today:.1f}"
            if avg_defense_loss_today is not None and defenses_today is not None and defenses_today > 0
            else "—"
        )
        def_n = defenses_today if defenses_today is not None else 0
        embed.add_field(
            name="📈 Moyennes (aujourd'hui)",
            value=(
                f"Attaque : **{avg_atk:.1f}** TR/attaque\n"
                f"Défense : **{def_line}** TR/défense ({def_n} déf.)"
            ),
            inline=False,
        )
    yesterday = yesterday_window(latest.captured_at, snapshots)
    if yesterday is not None:
        delta_t, attacks_y = yesterday
        sign = "+" if delta_t >= 0 else ""
        embed.add_field(
            name="📊 Hier",
            value=f"{sign}{delta_t} trophées · {attacks_y} attaques",
            inline=True,
        )
    hour = optimal_attack_hour(snapshots)
    if hour is not None:
        embed.add_field(
            name="🕐 Heure favorite (UTC)",
            value=(
                f"~ **{hour:02d}:00 UTC** _(estimée à partir de tes propres "
                "habitudes — pas une recommandation absolue)_"
            ),
            inline=False,
        )
    next_reset = next_reset_utc()
    embed.set_footer(
        text=f"Reset Legend I : {next_reset.strftime('%H:%M UTC')}",
    )
    return embed


def weekly_embed(
    tag: str,
    tier: LeagueType,
    latest: LegendSnapshot,
    snapshots: list[LegendSnapshot],
    quota: int,
) -> discord.Embed:
    """Hebdo briefing — utilisé par /daily pour Legend II/III."""
    week = current_week_window(snapshots)
    attacks_used = weekly_attacks_used(week, latest.attacks_done)
    delta_t = latest.trophies - week[0].trophies if week else 0
    embed = discord.Embed(
        title=f"📅 Briefing hebdo — {tier_label(tier)} — {tag}",
        color=COLOR_INFO,
    )
    embed.add_field(
        name="🏆 Trophées",
        value=f"**{latest.trophies}**",
        inline=True,
    )
    embed.add_field(
        name="⚔️ Batailles cette semaine",
        value=f"{attacks_used}/{quota}",
        inline=True,
    )
    if week:
        sign = "+" if delta_t >= 0 else ""
        embed.add_field(
            name="📊 Bilan trophy (semaine)",
            value=f"{sign}{delta_t} trophées",
            inline=True,
        )
    if attacks_used < quota:
        remaining = quota - attacks_used
        promo_line = (
            "Top 3 promus → Légende I"
            if tier is LeagueType.LEGEND_II
            else "Top 5 promus → Légende II"
        )
        embed.add_field(
            name="⏳ À faire avant le reset",
            value=(f"**{remaining} batailles** restantes. Tournoi hebdo : {promo_line}."),
            inline=False,
        )
    embed.set_footer(
        text=(
            "Format hebdomadaire — pas de reset daily. "
            "Récap envoyé dimanche 22h UTC si /ping activé."
        ),
    )
    return embed


def predict_embed_legend_i(
    _tag: str,
    latest: LegendSnapshot,
    snapshots: list[LegendSnapshot],
    rank_predictor: RankPredictor,
) -> discord.Embed:
    projected = predict_end_of_season_trophies(snapshots, LeagueType.LEGEND_I)
    current_rank = rank_predictor.estimate_current_rank(latest.trophies)
    projected_rank = rank_predictor.estimate_current_rank(projected)
    embed = discord.Embed(
        title="🔮 Projection fin de saison — Légende I",
        color=COLOR_INFO,
    )
    embed.add_field(
        name="🏆 Trophées actuels",
        value=f"**{latest.trophies}**",
        inline=True,
    )
    embed.add_field(
        name="📈 Projection (rythme actuel)",
        value=f"**{projected}**",
        inline=True,
    )
    embed.add_field(
        name=f"{rank_emoji(current_rank)} Rang mondial actuel",
        value=f"**{format_rank(current_rank)}**",
        inline=True,
    )
    if projected_rank is not None:
        embed.add_field(
            name=f"{rank_emoji(projected_rank)} Rang projeté fin de saison",
            value=f"**{format_rank(projected_rank)}**",
            inline=True,
        )
    attach_rank_quality_footer(embed, rank_predictor)
    return embed


def weekly_predict_embed(
    _tag: str,
    tier: LeagueType,
    latest: LegendSnapshot,
    snapshots: list[LegendSnapshot],
    quota: int,
    rank_predictor: RankPredictor,
) -> discord.Embed:
    week = current_week_window(snapshots)
    attacks_used = weekly_attacks_used(week, latest.attacks_done)
    days_into_week = max(1, days_since_week_start())
    daily_pace = (latest.trophies - week[0].trophies) / days_into_week if week else 0
    days_remaining = max(0, 7 - days_into_week)
    projected = int(round(latest.trophies + daily_pace * days_remaining))
    current_rank = rank_predictor.estimate_current_rank(latest.trophies)
    projected_rank = rank_predictor.estimate_current_rank(projected)

    embed = discord.Embed(
        title=f"🔮 Projection hebdo — {tier_label(tier)}",
        description=(
            "Format tournoi hebdomadaire — promotion par groupe. "
            "Le rang mondial est estimé via régression sur le leaderboard "
            "officiel Supercell (top 200 mesuré, extrapolé au-delà)."
        ),
        color=COLOR_INFO,
    )
    embed.add_field(
        name="🏆 Trophées actuels",
        value=f"**{latest.trophies}**",
        inline=True,
    )
    embed.add_field(
        name="⚔️ Batailles utilisées",
        value=f"{attacks_used}/{quota}",
        inline=True,
    )
    embed.add_field(
        name="📈 Projection fin de semaine",
        value=f"**{projected}** _(rythme actuel)_",
        inline=True,
    )
    embed.add_field(
        name=f"{rank_emoji(current_rank)} Rang mondial actuel (estimé)",
        value=f"**{format_rank(current_rank)}**",
        inline=True,
    )
    if projected_rank is not None:
        embed.add_field(
            name=f"{rank_emoji(projected_rank)} Rang projeté fin de semaine",
            value=f"**{format_rank(projected_rank)}**",
            inline=True,
        )
    if attacks_used < quota:
        remaining = quota - attacks_used
        avg_needed = remaining / max(1, days_remaining) if days_remaining else 0
        embed.add_field(
            name="Plan d'action",
            value=(
                f"Il te reste **{remaining}** batailles pour **{days_remaining}** "
                f"jours → ~{avg_needed:.1f} batailles/jour pour boucler le quota."
            ),
            inline=False,
        )
    attach_rank_quality_footer(embed, rank_predictor)
    return embed


def attach_rank_quality_footer(
    embed: discord.Embed,
    rank_predictor: RankPredictor,
) -> None:
    curve = rank_predictor.curve
    age_min = rank_predictor.leaderboard_age_minutes()
    if curve is None:
        embed.set_footer(
            text="Leaderboard mondial indisponible — réessaie dans quelques minutes.",
        )
        return
    quality = "fiable" if curve.r_squared >= 0.90 else "indicatif"
    embed.set_footer(
        text=(
            f"Régression log-linéaire sur {curve.sample_size} joueurs "
            f"(R²={curve.r_squared:.2f}, {quality}) · "
            f"Leaderboard MAJ il y a {age_min:.0f} min."
        ),
    )


def consistency_embed_daily(
    tag: str,
    ratio: float,
    full_days: int,
    total_days: int,
) -> discord.Embed:
    q = get_tuning().legend_i_daily_attack_quota
    pct = int(round(ratio * 100))
    color, label = score_color_and_label(ratio)
    embed = discord.Embed(
        title="📈 Legend Consistency Score — Légende I",
        description=f"**{pct} %** sur les {total_days} derniers jours actifs.",
        color=color,
    )
    embed.add_field(
        name="Détail",
        value=f"{full_days}/{total_days} jours avec {q}/{q} attaques",
        inline=False,
    )
    embed.add_field(name="Niveau", value=label, inline=True)
    embed.add_field(name="Compte", value=f"`{tag}`", inline=True)
    embed.set_footer(text="Calculé sur le quota daily Legend I.")
    return embed


def consistency_embed_weekly(
    tag: str,
    tier: LeagueType,
    ratio: float,
    full_weeks: int,
    total_weeks: int,
    quota: int,
) -> discord.Embed:
    pct = int(round(ratio * 100))
    color, label = score_color_and_label(ratio)
    embed = discord.Embed(
        title=f"📈 Score de consistance — {tier_label(tier)}",
        description=f"**{pct} %** sur les {total_weeks} dernières semaines actives.",
        color=color,
    )
    embed.add_field(
        name="Détail",
        value=f"{full_weeks}/{total_weeks} semaines avec {quota}/{quota} batailles",
        inline=False,
    )
    embed.add_field(name="Niveau", value=label, inline=True)
    embed.add_field(name="Compte", value=f"`{tag}`", inline=True)
    embed.set_footer(text=f"Calculé sur le quota hebdo {tier_label(tier)}.")
    return embed


def score_color_and_label(ratio: float) -> tuple[int, str]:
    if ratio >= 0.80:
        return COLOR_SUCCESS, "Élite (80 %+)"
    if ratio >= 0.50:
        return COLOR_WARNING, "Solide (50–79 %)"
    return COLOR_NEUTRAL, "Inconstant (< 50 %)"


def weekly_quota(tier: LeagueType) -> int:
    tun = get_tuning()
    if tier is LeagueType.LEGEND_II:
        return tun.legend_ii_weekly_battles
    if tier is LeagueType.LEGEND_III:
        return tun.legend_iii_weekly_battles
    return 0


def tier_label(tier: LeagueType) -> str:
    return {
        LeagueType.LEGEND_I: "Légende I",
        LeagueType.LEGEND_II: "Légende II",
        LeagueType.LEGEND_III: "Légende III",
        LeagueType.UNKNOWN: "Hors Légende",
    }[tier]


def next_reset_utc() -> datetime:
    now = datetime.now(timezone.utc)
    today_reset = now.replace(
        hour=get_tuning().legend_daily_reset_hour_utc,
        minute=0,
        second=0,
        microsecond=0,
    )
    return today_reset if today_reset > now else today_reset + timedelta(days=1)


def yesterday_window(
    now: datetime,
    snapshots: list[LegendSnapshot],
) -> tuple[int, int] | None:
    target_day = (now - timedelta(days=1)).astimezone(timezone.utc).date()
    same_day = [s for s in snapshots if s.captured_at.astimezone(timezone.utc).date() == target_day]
    if len(same_day) < 2:
        return None
    same_day.sort(key=lambda s: s.captured_at)
    delta_t = same_day[-1].trophies - same_day[0].trophies
    attacks = same_day[-1].attacks_done
    return delta_t, attacks


def current_week_window(
    snapshots: list[LegendSnapshot],
) -> list[LegendSnapshot]:
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return [s for s in snapshots if s.captured_at >= monday]


def days_since_week_start() -> int:
    return datetime.now(timezone.utc).weekday()


def weekly_attacks_used(
    week: list[LegendSnapshot],
    latest_attacks_done: int,
) -> int:
    if not week:
        return latest_attacks_done
    by_day: dict[object, int] = {}
    for snap in week:
        day = snap.captured_at.astimezone(timezone.utc).date()
        existing = by_day.get(day, 0)
        if snap.attacks_done > existing:
            by_day[day] = snap.attacks_done
    return sum(by_day.values())


def weekly_consistency(
    snapshots: list[LegendSnapshot],
    quota: int,
) -> tuple[int, int, float]:
    if not snapshots or quota <= 0:
        return 0, 0, 0.0
    by_week: dict[tuple[int, int], dict[object, int]] = {}
    for snap in snapshots:
        ts = snap.captured_at.astimezone(timezone.utc)
        iso_year, iso_week, _ = ts.isocalendar()
        key = (iso_year, iso_week)
        day = ts.date()
        bucket = by_week.setdefault(key, {})
        if snap.attacks_done > bucket.get(day, 0):
            bucket[day] = snap.attacks_done
    total = len(by_week)
    full = sum(1 for daily in by_week.values() if sum(daily.values()) >= quota)
    ratio = full / total if total else 0.0
    return full, total, ratio
