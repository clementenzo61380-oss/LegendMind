"""Fenêtre « journée Légende » (reset UTC issu du tuning) et agrégation stats."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from models import LegendSnapshot


@dataclass(frozen=True, slots=True)
class LegendDayWindow:
    """Demi-intervalle [start_utc, end_utc) aligné sur les resets journaliers Légende."""

    start_utc: datetime
    end_utc: datetime


def last_completed_legend_day_end(now_utc: datetime, reset_hour_utc: int) -> datetime:
    """Instant UTC du reset qui termine la journée Légende la plus récente déjà close.

    Ex. reset 18h UTC : à 18h05 on renvoie aujourd'hui 18h00 ; à 17h59 on renvoie hier 18h00.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    r = now_utc.replace(hour=reset_hour_utc, minute=0, second=0, microsecond=0)
    if now_utc >= r:
        return r
    return r - timedelta(days=1)


def completed_legend_day_window(now_utc: datetime, reset_hour_utc: int) -> LegendDayWindow:
    """Journée Légende terminée au dernier reset strictement passé (ou en cours à cet instant)."""
    end = last_completed_legend_day_end(now_utc, reset_hour_utc)
    start = end - timedelta(days=1)
    return LegendDayWindow(start_utc=start, end_utc=end)


@dataclass(slots=True)
class LegendDayStats:
    player_tag: str
    player_name: str | None
    legend_day_end_utc: datetime
    attacks: int
    defenses: int
    net_battles: int
    net_trophies: int
    trophies_end: int


def compute_legend_day_stats(
    tag: str,
    name: str | None,
    window: LegendDayWindow,
    start_snap: LegendSnapshot | None,
    end_snap: LegendSnapshot | None,
    defense_count: int,
) -> LegendDayStats | None:
    """Agrège attaques, défenses (log), net trophées et trophées finaux pour une fenêtre.

    ``start_snap`` / ``end_snap`` = dernier snapshot strictement avant ``start_utc`` /
    ``end_utc``. Sans ``end_snap`` ou sans aucune lecture dans la fenêtre, retourne None.
    """
    if end_snap is None:
        return None
    if end_snap.captured_at < window.start_utc:
        return None

    if start_snap is not None:
        attacks = max(0, end_snap.attacks_done - start_snap.attacks_done)
        net_trophies = end_snap.trophies - start_snap.trophies
    else:
        attacks = max(0, end_snap.attacks_done)
        net_trophies = end_snap.trophies_gained - end_snap.trophies_lost

    return LegendDayStats(
        player_tag=tag,
        player_name=name,
        legend_day_end_utc=window.end_utc,
        attacks=attacks,
        defenses=defense_count,
        net_battles=attacks - defense_count,
        net_trophies=net_trophies,
        trophies_end=end_snap.trophies,
    )
