"""Unit tests pour `services.alerts.AlertManager` (hors HTTP Discord)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from constants import ALERT_COOLDOWN_SECONDS, LeagueType
from models import AttackDelta, LegendSnapshot, UserPreferences
from services.alerts import Alert, AlertManager, AlertType


class _FakeRepo:
    """Repository minimal en mémoire pour AlertManager (cooldown + snapshots)."""

    def __init__(self) -> None:
        self.last_alerts: dict[tuple[str, str], datetime] = {}
        self.snapshots: dict[str, list[LegendSnapshot]] = {}
        self.recorded: list[tuple[str, str, int, str]] = []
        self.goal: Any = None
        self.prefs = UserPreferences(discord_user_id=42)

    async def get_last_alert_at(self, tag: str, alert_type: str) -> datetime | None:
        return self.last_alerts.get((tag, alert_type))

    async def record_alert(
        self,
        tag: str,
        alert_type: str,
        user_id: int,
        preview: str,
    ) -> None:
        self.recorded.append((tag, alert_type, user_id, preview))
        self.last_alerts[(tag, alert_type)] = datetime.now(timezone.utc)

    async def get_preferences(self, _user_id: int) -> UserPreferences:
        return self.prefs

    async def get_snapshots_since(
        self,
        tag: str,
        _since: datetime,
    ) -> list[LegendSnapshot]:
        return self.snapshots.get(tag, [])

    async def get_goal(self, _tag: str) -> Any:
        return self.goal


class _FakeBot:
    """Bot Discord stub : chaque dispatch est routé vers un user qui collecte."""

    def __init__(self) -> None:
        self.sent: list[Any] = []

    def get_user(self, _user_id: int) -> "_FakeUser":
        return _FakeUser(self.sent)


class _FakeUser:
    def __init__(self, sink: list[Any]) -> None:
        self._sink = sink

    async def send(self, embed: Any) -> None:
        self._sink.append(embed)


def _snap(tag: str, when: datetime, trophies: int) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag=tag,
        trophies=trophies,
        league_type=LeagueType.LEGEND_II,
        attacks_done=0,
        trophies_gained=0,
        trophies_lost=0,
        captured_at=when,
    )


@pytest.mark.asyncio
async def test_dispatch_blocked_by_cooldown() -> None:
    repo = _FakeRepo()
    bot = _FakeBot()
    mgr = AlertManager(
        bot=bot,  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    repo.last_alerts[("#X", AlertType.PROMOTION_POSSIBLE.value)] = datetime.now(
        timezone.utc,
    ) - timedelta(seconds=10)
    alert = Alert(
        type=AlertType.PROMOTION_POSSIBLE,
        player_tag="#X",
        discord_user_id=42,
        title="t",
        description="d",
        color=0,
    )
    sent = await mgr._can_send(alert)
    assert sent is False


@pytest.mark.asyncio
async def test_can_send_after_cooldown_expired() -> None:
    repo = _FakeRepo()
    bot = _FakeBot()
    mgr = AlertManager(
        bot=bot,  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    cd = ALERT_COOLDOWN_SECONDS["promotion_possible"]
    repo.last_alerts[("#X", AlertType.PROMOTION_POSSIBLE.value)] = datetime.now(
        timezone.utc,
    ) - timedelta(seconds=cd + 60)
    alert = Alert(
        type=AlertType.PROMOTION_POSSIBLE,
        player_tag="#X",
        discord_user_id=42,
        title="t",
        description="d",
        color=0,
    )
    assert await mgr._can_send(alert) is True


@pytest.mark.asyncio
async def test_quiet_hours_block_alerts_inside_window() -> None:
    repo = _FakeRepo()
    repo.prefs = UserPreferences(
        discord_user_id=42,
        quiet_hours_start=0,
        quiet_hours_end=23,
        enable_alerts=True,
    )
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    blocked = await mgr._is_in_quiet_hours(42)
    assert blocked is True


@pytest.mark.asyncio
async def test_streak_positive_detected() -> None:
    repo = _FakeRepo()
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    snaps = [_snap("#X", base + timedelta(minutes=i * 30), 5500 + i * 5) for i in range(6)]
    repo.snapshots["#X"] = snaps
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    streak = await mgr._detect_streak("#X")
    assert streak == AlertType.STREAK_POSITIVE


@pytest.mark.asyncio
async def test_streak_negative_detected() -> None:
    repo = _FakeRepo()
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    snaps = [_snap("#X", base + timedelta(minutes=i * 30), 5800 - i * 5) for i in range(6)]
    repo.snapshots["#X"] = snaps
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    streak = await mgr._detect_streak("#X")
    assert streak == AlertType.STREAK_NEGATIVE


@pytest.mark.asyncio
async def test_evaluate_skips_when_alerts_disabled() -> None:
    repo = _FakeRepo()
    repo.prefs = UserPreferences(discord_user_id=42, enable_alerts=False)
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    a = _snap("#X", base, 5500)
    b = _snap("#X", base + timedelta(minutes=5), 5520)
    delta = AttackDelta.between(a, b)
    sent = await mgr.evaluate_and_dispatch(delta, repo.prefs)
    assert sent == []


def _snap_lost(
    tag: str,
    when: datetime,
    trophies: int,
    lost: int,
    tier: LeagueType = LeagueType.LEGEND_I,
) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag=tag,
        trophies=trophies,
        league_type=tier,
        attacks_done=0,
        trophies_gained=0,
        trophies_lost=lost,
        captured_at=when,
    )


@pytest.mark.asyncio
async def test_defense_alert_fires_when_opt_in_and_loss_increases() -> None:
    """A new defense (trophies_lost ↑) emits a DEFENSE_TAKEN candidate.

    Avril 2026 Ranked refonte : DEFENSE_TAKEN ne se déclenche QUE pour
    Legend I (les II/III sont en format hebdo, gérés par le recap dimanche).
    """
    repo = _FakeRepo()
    repo.prefs = UserPreferences(discord_user_id=42, alert_on_defense=True)
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    prev = _snap_lost("#X", base, trophies=5600, lost=120)
    cur = _snap_lost("#X", base + timedelta(minutes=3), trophies=5572, lost=148)
    delta = AttackDelta.between(prev, cur)
    out = await mgr.evaluate(delta, repo.prefs)
    types = [a.type for a in out]
    assert AlertType.DEFENSE_TAKEN in types
    defense_alert = next(a for a in out if a.type == AlertType.DEFENSE_TAKEN)
    assert "28" in defense_alert.description  # 148 - 120 = 28 trophies lost
    # DM is intentionally kept minimal (no tips) — just the raw trophy loss.
    assert "5,600" in defense_alert.description   # previous trophies
    assert "5,572" in defense_alert.description   # current trophies


@pytest.mark.asyncio
async def test_defense_alert_skipped_when_opt_out() -> None:
    """Default-off path: alert_on_defense=False mutes the per-defense push."""
    repo = _FakeRepo()
    repo.prefs = UserPreferences(discord_user_id=42, alert_on_defense=False)
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    prev = _snap_lost("#X", base, trophies=5600, lost=120)
    cur = _snap_lost("#X", base + timedelta(minutes=3), trophies=5572, lost=148)
    delta = AttackDelta.between(prev, cur)
    out = await mgr.evaluate(delta, repo.prefs)
    assert all(a.type is not AlertType.DEFENSE_TAKEN for a in out)


@pytest.mark.asyncio
async def test_defense_alert_skipped_when_no_loss_delta() -> None:
    """No new defense (trophies_lost unchanged) ⇒ no DEFENSE_TAKEN candidate.

    Guards against firing on a season-reset edge case where ``trophies_lost``
    might roll back to 0 (the delta becomes negative, not positive).
    """
    repo = _FakeRepo()
    repo.prefs = UserPreferences(discord_user_id=42, alert_on_defense=True)
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    # Pure trophy gain (an attack), no defense.
    prev = _snap_lost("#X", base, trophies=5600, lost=120)
    cur = _snap_lost("#X", base + timedelta(minutes=3), trophies=5640, lost=120)
    delta = AttackDelta.between(prev, cur)
    out = await mgr.evaluate(delta, repo.prefs)
    assert all(a.type is not AlertType.DEFENSE_TAKEN for a in out)

    # Counter rolled back (season reset) — must not fire either.
    prev2 = _snap_lost("#X", base, trophies=5600, lost=200)
    cur2 = _snap_lost("#X", base + timedelta(seconds=1), trophies=5040, lost=0)
    delta2 = AttackDelta.between(prev2, cur2)
    out2 = await mgr.evaluate(delta2, repo.prefs)
    assert all(a.type is not AlertType.DEFENSE_TAKEN for a in out2)


@pytest.mark.asyncio
async def test_defense_alert_skipped_for_legend_ii_and_iii() -> None:
    """Avril 2026 : DEFENSE_TAKEN muet pour Legend II/III (format hebdo).

    Legend II/III players reçoivent un recap dimanche soir au lieu d'un DM
    par défense — confirmer que ``evaluate`` ne génère AUCUN candidate
    DEFENSE_TAKEN même quand ``alert_on_defense=True`` et qu'une perte
    réelle est observée.
    """
    repo = _FakeRepo()
    repo.prefs = UserPreferences(discord_user_id=42, alert_on_defense=True)
    mgr = AlertManager(
        bot=_FakeBot(),  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        default_cooldown_seconds=3600,
    )
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    for tier in (LeagueType.LEGEND_II, LeagueType.LEGEND_III):
        prev = _snap_lost("#X", base, trophies=5600, lost=120, tier=tier)
        cur = _snap_lost(
            "#X",
            base + timedelta(minutes=3),
            trophies=5572,
            lost=148,
            tier=tier,
        )
        delta = AttackDelta.between(prev, cur)
        out = await mgr.evaluate(delta, repo.prefs)
        assert all(a.type is not AlertType.DEFENSE_TAKEN for a in out), (
            f"DEFENSE_TAKEN must not fire for tier {tier!r} (weekly format)"
        )
