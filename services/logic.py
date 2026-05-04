"""Pure business logic — no I/O, no Discord, no DB.

Everything here is synchronous and deterministic so it can be unit-tested
without fixtures. The functions take dataclasses, return dataclasses or
primitives, and never log at INFO level (caller's job).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from constants import (
    MALCHANCE_OPPONENT_GAP_TOLERANCE,
    MALCHANCE_TROPHY_LOSS_NORMAL,
    PACE_PROJECTION_WINDOW_DAYS,
    PACE_REGRESSION_MIN_SAMPLES,
    PROMOTION_PROXIMITY_TROPHIES,
    RELEGATION_PROXIMITY_TROPHIES,
    LeagueType,
)
from models import DefenseData, LegendSnapshot
from services.game_tuning import get_tuning


# ─────────────────────────────────────────────────────────────────────────────
# League detection
# ─────────────────────────────────────────────────────────────────────────────
def detect_league(trophies: int) -> LeagueType:
    """Map a trophy count to its **trophy-band** label (legacy display only).

    ⚠️ Avril 2026 — Refonte Ranked Mode Supercell : le tier Legend (I/II/III)
    n'est PLUS dérivé des trophées. Cette fonction reste disponible pour
    l'affichage trophy-based (barres de progression, snapshots historiques)
    mais ne reflète pas le tier officiel du joueur. La source de vérité est
    ``players.legend_tier`` (déclarée au /setup, modifiable via /tier).

    Below 5000 trophies the player isn't in Legend yet → UNKNOWN.
    """
    tun = get_tuning()
    if trophies >= tun.lower_bound(LeagueType.LEGEND_I):
        return LeagueType.LEGEND_I
    if trophies >= tun.lower_bound(LeagueType.LEGEND_II):
        return LeagueType.LEGEND_II
    if trophies >= tun.lower_bound(LeagueType.LEGEND_III):
        return LeagueType.LEGEND_III
    return LeagueType.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# Threshold checks (relegation / promotion proximity)
# ─────────────────────────────────────────────────────────────────────────────
def check_threshold(snapshot: LegendSnapshot) -> str | None:
    """Return a threshold tag if the player is near a league boundary.

    - "relegation_imminent" when < RELEGATION_PROXIMITY_TROPHIES above
      the current league's lower bound.
    - "promotion_possible" when < PROMOTION_PROXIMITY_TROPHIES below the
      next league's lower bound.
    - None otherwise (or when league is UNKNOWN).
    """
    league = snapshot.league_type
    if league == LeagueType.UNKNOWN:
        return None

    lower = get_tuning().lower_bound(league)
    distance_above_floor = snapshot.trophies - lower
    if distance_above_floor < RELEGATION_PROXIMITY_TROPHIES:
        return "relegation_imminent"

    next_league = _next_league(league)
    if next_league is not None:
        next_floor = get_tuning().lower_bound(next_league)
        if next_floor - snapshot.trophies <= PROMOTION_PROXIMITY_TROPHIES:
            return "promotion_possible"

    return None


def _next_league(league: LeagueType) -> LeagueType | None:
    if league == LeagueType.LEGEND_III:
        return LeagueType.LEGEND_II
    if league == LeagueType.LEGEND_II:
        return LeagueType.LEGEND_I
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Attack pace (Legend I — daily quota)
# ─────────────────────────────────────────────────────────────────────────────
def check_attack_pace(
    attacks_done_today: int,
    league: LeagueType,
    now_utc: datetime | None = None,
) -> str | None:
    """Evaluate the daily attack pace for a Legend I player.

    Returns one of `pace_critical`, `pace_warning`, or None. League II/III
    return None (different mechanic, handled elsewhere).
    """
    if league != LeagueType.LEGEND_I:
        return None
    return _check_attack_pace_legend_i(attacks_done_today, now_utc or datetime.now(timezone.utc))


def _check_attack_pace_legend_i(
    attacks_done_today: int,
    now_utc: datetime,
) -> str | None:
    tun = get_tuning()
    quota = tun.legend_i_daily_attack_quota
    remaining_attacks = quota - attacks_done_today
    if remaining_attacks <= 0:
        return None  # quota already met → no pace concern

    hours_until_reset = _hours_until_daily_reset(now_utc)
    # If we still have plenty of clock time, no warning regardless of count.
    # Trigger only when remaining_attacks is high vs. remaining time.
    if hours_until_reset > 6:
        return None

    warn = tun.legend_i_pace_warning_remaining
    crit = tun.legend_i_pace_critical_remaining
    if remaining_attacks >= warn and hours_until_reset <= 6:
        if remaining_attacks >= warn + 2:
            return "pace_critical"
        return "pace_warning"
    if remaining_attacks >= crit and hours_until_reset <= 2:
        return "pace_critical"
    return None


def _hours_until_daily_reset(now_utc: datetime) -> float:
    reset_today = now_utc.replace(
        hour=get_tuning().legend_daily_reset_hour_utc,
        minute=0,
        second=0,
        microsecond=0,
    )
    if reset_today <= now_utc:
        reset_today = reset_today + timedelta(days=1)
    return (reset_today - now_utc).total_seconds() / 3600.0


# ─────────────────────────────────────────────────────────────────────────────
# Malchance (bad-luck) score
# ─────────────────────────────────────────────────────────────────────────────
def get_malchance_score(defense: DefenseData, league: LeagueType) -> float:
    """Score a single defense in [0.0, 1.0]; higher = more bad luck.

    Components (weighted, summed, clamped):
    - Excess trophies lost above the league-typical loss.
    - Opponent strength gap (opponent significantly weaker than us).
    - Pile-on factor (multiple attacks in one defense window).
    """
    if league == LeagueType.UNKNOWN:
        return 0.0

    excess_loss = max(
        0,
        defense.trophies_lost - MALCHANCE_TROPHY_LOSS_NORMAL,
    )
    loss_factor = min(1.0, excess_loss / 25.0)  # 25+ excess → fully bad

    pile_on_factor = min(1.0, max(0, defense.attack_count - 1) / 3.0)

    gap_factor = 0.0
    if defense.opponent_trophies is not None:
        # Opponent well below our league floor ⇒ weak attacker taking many cups.
        floor = get_tuning().lower_bound(league)
        margin = floor - defense.opponent_trophies
        if margin > MALCHANCE_OPPONENT_GAP_TOLERANCE:
            gap_factor = min(1.0, (margin - MALCHANCE_OPPONENT_GAP_TOLERANCE) / 400.0)

    score = (loss_factor * 0.55) + (pile_on_factor * 0.25) + (gap_factor * 0.20)
    return round(min(1.0, max(0.0, score)), 3)


# ─────────────────────────────────────────────────────────────────────────────
# Defense outcome inference (stars + destruction from trophy loss)
# ─────────────────────────────────────────────────────────────────────────────
def infer_defense_outcome(lost_delta: int) -> tuple[str, str]:
    """Estimate the attacker's stars + destruction from trophy loss.

    The Clash of Clans **public** API does NOT expose individual defense
    details (no attacker tag, no star count, no destruction %). The only
    observable signal is the cumulative ``trophies_lost`` counter.

    In Legend League the matchmaking spread is ±50 trophies and the swing
    formula is dominated by stars + destruction %. This helper buckets the
    most likely outcome from the trophy delta. Treat it as a HINT — bands
    are calibrated against Supercell's published trophy formula but the
    exact swing also depends on the (hidden) trophy gap with the attacker.

    Returns ``(stars_label, destruction_hint)`` ready for display.
    """
    if lost_delta <= 0:
        return ("0⭐", "défense réussie")
    if lost_delta <= 14:
        return ("≈ 1⭐", "destruction faible")
    if lost_delta <= 24:
        return ("≈ 2⭐", "destruction < 50 %")
    if lost_delta <= 34:
        return ("≈ 2⭐", "destruction 50–80 %")
    return ("≈ 3⭐", "destruction ≥ 80 % (proche perfect)")


def aggregate_malchance(
    defenses: list[DefenseData],
    league: LeagueType,
) -> float:
    """Aggregate malchance across multiple defenses (e.g. one day or week).

    Uses a weighted average where larger losses weigh proportionally more.
    """
    if not defenses:
        return 0.0
    total_weight = 0.0
    weighted_sum = 0.0
    for d in defenses:
        w = max(1, d.trophies_lost)
        total_weight += w
        weighted_sum += w * get_malchance_score(d, league)
    return round(weighted_sum / total_weight, 3) if total_weight > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Pace score & end-of-season projection
# ─────────────────────────────────────────────────────────────────────────────
def calculate_pace_score(
    snapshots: list[LegendSnapshot],
    league: LeagueType,
) -> float:
    """Compute a [-1, +1] tendency score over the recent snapshot window.

    Positive → climbing. Zero → flat. Negative → falling.
    Uses the slope of a simple linear regression on (timestamp, trophies),
    normalised by the league's lower bound width.
    """
    if league == LeagueType.UNKNOWN:
        return 0.0
    if len(snapshots) < PACE_REGRESSION_MIN_SAMPLES:
        return 0.0

    slope_per_day = _trophies_slope_per_day(snapshots)
    # Normalise: a slope of ±100 trophies/day saturates the score.
    return round(max(-1.0, min(1.0, slope_per_day / 100.0)), 3)


def predict_end_of_season_trophies(
    snapshots: list[LegendSnapshot],
    league: LeagueType,
    season_end: datetime | None = None,
) -> int:
    """Project where the player will land at season end.

    Uses the slope of the last `PACE_PROJECTION_WINDOW_DAYS` of snapshots.
    Falls back to the latest known trophy count when data is too thin.
    """
    if not snapshots:
        return 0
    latest = snapshots[-1]
    if league == LeagueType.UNKNOWN or len(snapshots) < PACE_REGRESSION_MIN_SAMPLES:
        return latest.trophies

    cutoff = latest.captured_at - timedelta(days=PACE_PROJECTION_WINDOW_DAYS)
    window = [s for s in snapshots if s.captured_at >= cutoff]
    if len(window) < PACE_REGRESSION_MIN_SAMPLES:
        window = snapshots[-PACE_REGRESSION_MIN_SAMPLES:]

    slope_per_day = _trophies_slope_per_day(window)
    if season_end is None:
        season_end = _default_season_end(latest.captured_at)
    days_remaining = max(0.0, (season_end - latest.captured_at).total_seconds() / 86400.0)
    projected = latest.trophies + slope_per_day * days_remaining
    return int(round(projected))


def _trophies_slope_per_day(snapshots: list[LegendSnapshot]) -> float:
    """Least-squares slope of trophies vs. time, in trophies/day."""
    n = len(snapshots)
    if n < 2:
        return 0.0
    base_t = snapshots[0].captured_at
    xs = [(s.captured_at - base_t).total_seconds() / 86400.0 for s in snapshots]
    ys = [float(s.trophies) for s in snapshots]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0 or math.isclose(den, 0.0):
        return 0.0
    return num / den


def utc_hour_floor(dt: datetime) -> datetime:
    """Truncate to the start of the hour in UTC (matches SQL `date_trunc`)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


def season_month_label(at_utc: datetime) -> str:
    """`YYYY-MM` label for the monthly Legend season containing `at_utc`."""
    at_utc = at_utc.astimezone(timezone.utc)
    return f"{at_utc.year:04d}-{at_utc.month:02d}"


def _default_season_end(now: datetime) -> datetime:
    """First day of next month, at the daily reset hour, UTC.

    CoC seasons end at the start of the next calendar month; this matches
    the public Legend reset cadence for the projection horizon.
    """
    rh = get_tuning().legend_daily_reset_hour_utc
    if now.month == 12:
        return datetime(
            now.year + 1,
            1,
            1,
            rh,
            0,
            0,
            tzinfo=timezone.utc,
        )
    return datetime(
        now.year,
        now.month + 1,
        1,
        rh,
        0,
        0,
        tzinfo=timezone.utc,
    )


def legend_projection_horizon(now: datetime) -> datetime:
    """Month-boundary horizon used for dashboards and `/saison` hints."""
    return _default_season_end(now)


# ─────────────────────────────────────────────────────────────────────────────
# Legend Consistency Score & optimal attack hour (used by /score and /daily)
# ─────────────────────────────────────────────────────────────────────────────
def legend_consistency_score(
    snapshots: list[LegendSnapshot],
    days: int = 30,
) -> tuple[float, int, int]:
    """Pourcentage de jours où le quota Legend I (8/8) a été atteint.

    Returns:
        ``(ratio, full_days, total_days)`` — ``ratio`` est arrondi à 3
        décimales et borné dans ``[0, 1]``. ``total_days`` correspond aux
        jours uniques avec au moins un snapshot dans la fenêtre.

    Conçu pour Legend I — pour les autres ligues le quota n'a pas de sens
    quotidien, mais la fonction reste correcte (elle compte simplement les
    jours où la valeur max d'``attacks_done`` a atteint 8).
    """
    if not snapshots:
        return 0.0, 0, 0
    cutoff = snapshots[-1].captured_at - timedelta(days=days)
    by_day: dict[str, int] = {}
    for s in snapshots:
        if s.captured_at < cutoff:
            continue
        key = s.captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        prev = by_day.get(key, -1)
        if s.attacks_done > prev:
            by_day[key] = s.attacks_done
    if not by_day:
        return 0.0, 0, 0
    total = len(by_day)
    full = sum(1 for v in by_day.values() if v >= get_tuning().legend_i_daily_attack_quota)
    return round(full / total, 3), full, total


def optimal_attack_hour(
    snapshots: list[LegendSnapshot],
    lookback_days: int = 14,
) -> int | None:
    """Heure UTC (0–23) la plus fréquente pour les attaques de l'utilisateur.

    Implémentation : pour chaque paire de snapshots consécutifs où
    ``attacks_done`` augmente strictement, on incrémente le compteur de
    l'heure de fin (``current.captured_at``). Le mode est retourné, ou
    ``None`` si moins de 3 attaques observées dans la fenêtre.

    Avertissement statistique : c'est une **heuristique** sur les
    habitudes du joueur, pas une recommandation tactique. À présenter
    comme « heure favorite », pas « heure idéale ».
    """
    if len(snapshots) < 2:
        return None
    cutoff = snapshots[-1].captured_at - timedelta(days=lookback_days)
    counts: dict[int, int] = {}
    observed = 0
    for prev, cur in zip(snapshots, snapshots[1:]):
        if cur.captured_at < cutoff:
            continue
        # Reset boundary (new day) ⇒ attacks_done drops; ignore those rows.
        if cur.attacks_done <= prev.attacks_done:
            continue
        # Multiple attacks within one snapshot interval all credited to the
        # final hour — close enough at our 3-min poll cadence.
        delta = cur.attacks_done - prev.attacks_done
        hour = cur.captured_at.astimezone(timezone.utc).hour
        counts[hour] = counts.get(hour, 0) + delta
        observed += delta
    if observed < 3:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]
