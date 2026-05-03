"""Tests unitaires du moteur de patterns / agrégats du Carnet d'Erreurs."""
from __future__ import annotations

from datetime import datetime, timezone

from constants import LeagueType
from models import DefenseLog
from services.notebook import ErrorNotebookService


def _row(hour: int, attack_count: int = 1) -> DefenseLog:
    return DefenseLog(
        id=hour,
        player_tag="#X",
        trophies_lost=32,
        opponent_tag="#OPP",
        opponent_trophies=5800,
        attack_count=attack_count,
        malchance_score=0.5,
        league_type=LeagueType.LEGEND_II,
        season_week=18,
        logged_at=datetime(2026, 5, 3, hour, 0, 0, tzinfo=timezone.utc),
    )


def test_dominant_hour_window_detects_cluster() -> None:
    svc = ErrorNotebookService(repository=None)  # type: ignore[arg-type]
    defenses = [_row(2), _row(3), _row(3), _row(4), _row(5), _row(13)]
    out = svc._dominant_hour_window(defenses)
    assert out is not None
    start_h, end_h, share = out
    assert 2 <= start_h <= 5
    assert share >= 0.4
    assert end_h == (start_h + 4) % 24


def test_pile_on_pattern_in_recommendations() -> None:
    svc = ErrorNotebookService(repository=None)  # type: ignore[arg-type]
    defenses = [_row(10, attack_count=3) for _ in range(5)]
    patterns = svc._detect_patterns(defenses)
    assert any("attaques multiples" in p for p in patterns)


def test_no_patterns_when_empty() -> None:
    svc = ErrorNotebookService(repository=None)  # type: ignore[arg-type]
    assert svc._detect_patterns([]) == []
