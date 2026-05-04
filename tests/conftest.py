"""Pytest fixtures partagées (prompt §9.3).

Fournit des fabriques de snapshots et de défenses Legend reproductibles, sans
toucher à PostgreSQL ni Discord. Les tests d'intégration BDD utilisent
``DATABASE_URL_TEST`` (cf. ``tests/integration``) — ils sont skippés si la
variable n'est pas définie.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Permet d'importer `services`, `models`, etc. depuis la racine du projet
# sans installation pip — pratique pour pytest tournant en local ou en CI.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from constants import LeagueType  # noqa: E402
from models import DefenseData, LegendSnapshot  # noqa: E402


@pytest.fixture
def fixed_now() -> datetime:
    """Datetime déterministe pour des assertions reproductibles."""
    return datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def snap_factory(fixed_now: datetime):  # type: ignore[no-untyped-def]
    """Factory ``snap_factory(trophies, attacks=0, league=...)``."""

    def _make(
        trophies: int,
        *,
        attacks: int = 0,
        gained: int = 0,
        lost: int = 0,
        league: LeagueType | None = None,
        offset_seconds: int = 0,
        tag: str = "#TEST",
    ) -> LegendSnapshot:
        from services.logic import detect_league

        captured = (
            fixed_now.replace()
            if offset_seconds == 0
            else (
                fixed_now.fromtimestamp(
                    fixed_now.timestamp() + offset_seconds,
                    tz=timezone.utc,
                )
            )
        )
        return LegendSnapshot(
            player_tag=tag,
            trophies=trophies,
            league_type=league or detect_league(trophies),
            attacks_done=attacks,
            trophies_gained=gained,
            trophies_lost=lost,
            captured_at=captured,
        )

    return _make


@pytest.fixture
def defense_factory():  # type: ignore[no-untyped-def]
    """Factory ``defense_factory(trophies_lost=..., opponent_trophies=...)``."""

    def _make(
        *,
        trophies_lost: int = 32,
        opponent_trophies: int | None = 5500,
        attack_count: int = 1,
        opponent_tag: str | None = "#OPP",
    ) -> DefenseData:
        return DefenseData(
            trophies_lost=trophies_lost,
            opponent_tag=opponent_tag,
            opponent_trophies=opponent_trophies,
            attack_count=attack_count,
        )

    return _make


@pytest.fixture
def db_url_for_integration() -> str | None:
    """DSN PostgreSQL pour tests d'intégration (None ⇒ skip)."""
    return os.environ.get("DATABASE_URL_TEST")
