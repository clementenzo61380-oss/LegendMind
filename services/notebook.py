"""Carnet d'Erreurs — defense analytics & weekly reports.

Owns nothing: stateless service that reads/writes via Repository and
calls into pure logic for scoring. Pattern detection is local
heuristics (clustering, opponent-strength distribution, multi-attack
correlation) — kept simple and explainable, not ML.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from statistics import mean

from constants import (
    MALCHANCE_HIGH_THRESHOLD,
    MALCHANCE_OPPONENT_GAP_TOLERANCE,
    LeagueType,
)
from models import DefenseData, DefenseLog, NotebookReport
from services.db import Repository
from services.logic import get_malchance_score

log = logging.getLogger(__name__)


class ErrorNotebookService:
    """Aggregates and analyses defenses for a single player.

    Public surface is intentionally narrow: log a defense, get a weekly
    report, get a malchance trend. Pattern detection lives behind a
    private method so it can evolve without breaking callers.
    """

    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    async def log_defense(
        self,
        player_tag: str,
        defense: DefenseData,
        league: LeagueType,
        season_week: int | None = None,
    ) -> int:
        """Persist a defense with its computed malchance score.

        Returns the new defense_log row id (useful for dedup in upstream
        pipelines that may receive the same event twice).
        """
        score = get_malchance_score(defense, league)
        return await self._repo.insert_defense(
            player_tag=player_tag,
            trophies_lost=defense.trophies_lost,
            opponent_tag=defense.opponent_tag,
            opponent_trophies=defense.opponent_trophies,
            attack_count=defense.attack_count,
            malchance_score=score,
            league=league,
            season_week=season_week,
        )

    async def get_weekly_report(
        self,
        player_tag: str,
        week_anchor: datetime | None = None,
    ) -> NotebookReport:
        """Build the report for the ISO week containing `week_anchor`.

        Defaults to the current week (UTC). The window is [Mon 00:00, next
        Mon 00:00). Empty weeks return an all-zeros report rather than None
        so the Discord embed always has something to show.
        """
        anchor = week_anchor or datetime.now(timezone.utc)
        start, end = _iso_week_bounds_utc(anchor)
        defenses = await self._repo.get_defenses_between(player_tag, start, end)
        worst = await self._repo.get_worst_defense_between(player_tag, start, end)

        if not defenses:
            return NotebookReport(
                player_tag=player_tag,
                week_start=start.date(),
                week_end=(end - timedelta(seconds=1)).date(),
                avg_malchance_score=0.0,
                worst_defense=None,
            )

        avg = round(mean(d.malchance_score for d in defenses), 3)
        bad_luck_loss = sum(
            d.trophies_lost
            for d in defenses
            if d.malchance_score >= MALCHANCE_HIGH_THRESHOLD
        )
        patterns = self._detect_patterns(defenses)
        recommendations = self._build_recommendations(defenses, patterns)

        return NotebookReport(
            player_tag=player_tag,
            week_start=start.date(),
            week_end=(end - timedelta(seconds=1)).date(),
            avg_malchance_score=avg,
            worst_defense=worst,
            patterns=patterns,
            recommendations=recommendations,
            total_trophies_lost_to_bad_luck=bad_luck_loss,
        )

    async def get_malchance_trend(
        self, player_tag: str, days: int = 7,
    ) -> list[float]:
        """Daily averages of malchance score over the last `days` UTC days.

        Length is always `days`. Days with no defenses get 0.0 (not None)
        so the result is plot-ready without further branching.
        """
        if days <= 0:
            return []
        end = _start_of_utc_day(datetime.now(timezone.utc)) + timedelta(days=1)
        start = end - timedelta(days=days)
        defenses = await self._repo.get_defenses_between(player_tag, start, end)
        buckets: dict[int, list[float]] = {i: [] for i in range(days)}
        for d in defenses:
            offset = (d.logged_at - start).days
            if 0 <= offset < days:
                buckets[offset].append(d.malchance_score)
        return [
            round(mean(values), 3) if values else 0.0
            for values in (buckets[i] for i in range(days))
        ]

    # ── pattern detection ────────────────────────────────────────────────
    def _detect_patterns(self, defenses: list[DefenseLog]) -> list[str]:
        """Heuristics over the week's defenses.

        - Hour clustering: if ≥40% of defenses fall in a 4-hour window,
          flag that window as "vulnérabilité horaire".
        - Opponent strength: if median opponent is ≥ tolerance below the
          defender, flag "adversaires plus faibles".
        - Pile-on rate: if ≥30% of defenses have attack_count ≥ 2.
        """
        if not defenses:
            return []
        out: list[str] = []

        hour_window = self._dominant_hour_window(defenses)
        if hour_window is not None:
            start_h, end_h, share = hour_window
            out.append(
                f"⏰ {int(share * 100)}% de tes défenses entre "
                f"{start_h:02d}h et {end_h:02d}h UTC."
            )

        weak_opponents = sum(
            1
            for d in defenses
            if d.opponent_trophies is not None
            and d.opponent_trophies < MALCHANCE_OPPONENT_GAP_TOLERANCE * 30
        )
        if weak_opponents and weak_opponents / len(defenses) >= 0.4:
            out.append(
                "⚖️ Tu reçois souvent des attaques d'adversaires moins gradés."
            )

        pile_on = sum(1 for d in defenses if d.attack_count >= 2)
        if pile_on / len(defenses) >= 0.30:
            out.append(
                "🔁 Plusieurs défenses subissent des attaques multiples."
            )

        return out

    def _dominant_hour_window(
        self, defenses: list[DefenseLog],
    ) -> tuple[int, int, float] | None:
        """Return (start_h, end_h_exclusive, share) if a 4h window holds ≥40%.

        Sliding 4-hour windows over UTC hours; ties resolved by earliest start.
        """
        hour_counts = Counter(d.logged_at.hour for d in defenses)
        total = len(defenses)
        best: tuple[int, int, float] | None = None
        for start_h in range(24):
            count = sum(
                hour_counts[(start_h + offset) % 24] for offset in range(4)
            )
            share = count / total
            if share >= 0.40 and (best is None or share > best[2]):
                best = (start_h, (start_h + 4) % 24, round(share, 2))
        return best

    def _build_recommendations(
        self, defenses: list[DefenseLog], patterns: list[str],
    ) -> list[str]:
        """At most 3 actionable recommendations, prioritised by signal strength."""
        recs: list[str] = []
        if any("vulnérabilité" in p or "défenses entre" in p for p in patterns):
            recs.append(
                "Place ton bouclier ou attaque juste avant la fenêtre "
                "horaire où tu perds le plus."
            )
        avg_loss = mean(d.trophies_lost for d in defenses)
        if avg_loss > 35:
            recs.append(
                "Renforce ta base : ton coût défensif moyen est élevé "
                f"({avg_loss:.0f} trophées par défense)."
            )
        if any("attaques multiples" in p for p in patterns):
            recs.append(
                "Vide ton bouclier en attaquant — tu attires les pile-ons "
                "quand tu restes attaquable trop longtemps."
            )
        return recs[:3]


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _start_of_utc_day(when: datetime) -> datetime:
    return datetime.combine(when.date(), time(0), tzinfo=timezone.utc)


def _iso_week_bounds_utc(anchor: datetime) -> tuple[datetime, datetime]:
    """Half-open [Monday 00:00, next Monday 00:00) UTC bounds containing anchor."""
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    start_date = anchor.date() - timedelta(days=anchor.weekday())
    start = datetime.combine(start_date, time(0), tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


# Compatibility shim for callers that prefer keyword construction.
def replace_report(report: NotebookReport, **changes) -> NotebookReport:  # type: ignore[no-untyped-def]
    return replace(report, **changes)
