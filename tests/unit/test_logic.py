"""Unit tests for `services.logic` — couvre les chemins critiques (prompt §9.2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from constants import (
    LEAGUE_LOWER_BOUND,
    LEGEND_DAILY_RESET_HOUR_UTC,
    LEGEND_I_DAILY_ATTACK_QUOTA,
    LeagueType,
)
from models import DefenseData, LegendSnapshot
from services.logic import (
    _check_attack_pace_legend_i,
    _hours_until_daily_reset,
    aggregate_malchance,
    calculate_pace_score,
    check_attack_pace,
    check_threshold,
    detect_league,
    get_malchance_score,
    infer_defense_outcome,
    legend_projection_horizon,
    predict_end_of_season_trophies,
    season_month_label,
    utc_hour_floor,
)


# ─────────────────────────────────────────────────────────────────────────────
# detect_league — 5 cas (chaque ligue + bornes)
# ─────────────────────────────────────────────────────────────────────────────
def test_detect_league_unknown_below_5000() -> None:
    assert detect_league(4999) == LeagueType.UNKNOWN


def test_detect_league_legend_iii_lower_bound() -> None:
    assert detect_league(LEAGUE_LOWER_BOUND[LeagueType.LEGEND_III]) == LeagueType.LEGEND_III


def test_detect_league_legend_iii_upper_bound() -> None:
    assert detect_league(LEAGUE_LOWER_BOUND[LeagueType.LEGEND_II] - 1) == LeagueType.LEGEND_III


def test_detect_league_legend_ii_inclusive() -> None:
    assert detect_league(LEAGUE_LOWER_BOUND[LeagueType.LEGEND_II]) == LeagueType.LEGEND_II
    assert detect_league(LEAGUE_LOWER_BOUND[LeagueType.LEGEND_I] - 1) == LeagueType.LEGEND_II


def test_detect_league_legend_i_open_ended() -> None:
    assert detect_league(LEAGUE_LOWER_BOUND[LeagueType.LEGEND_I]) == LeagueType.LEGEND_I
    assert detect_league(7777) == LeagueType.LEGEND_I


# ─────────────────────────────────────────────────────────────────────────────
# check_threshold
# ─────────────────────────────────────────────────────────────────────────────
def _snap(trophies: int, league: LeagueType) -> LegendSnapshot:
    return LegendSnapshot(
        player_tag="#X",
        trophies=trophies,
        league_type=league,
        attacks_done=0,
        trophies_gained=0,
        trophies_lost=0,
        captured_at=datetime.now(timezone.utc),
    )


def test_check_threshold_relegation_imminent() -> None:
    assert check_threshold(_snap(5005, LeagueType.LEGEND_III)) == "relegation_imminent"


def test_check_threshold_promotion_possible() -> None:
    # 5499 → distance to L_II floor (5500) is 1, PROMOTION_PROXIMITY_TROPHIES = 50
    assert check_threshold(_snap(5499, LeagueType.LEGEND_III)) == "promotion_possible"


def test_check_threshold_none_for_unknown() -> None:
    assert check_threshold(_snap(4000, LeagueType.UNKNOWN)) is None


def test_check_threshold_legend_i_no_promotion() -> None:
    # Plus de ligue au-dessus de Légende I
    snap = _snap(6500, LeagueType.LEGEND_I)
    assert check_threshold(snap) is None


# ─────────────────────────────────────────────────────────────────────────────
# attack pace
# ─────────────────────────────────────────────────────────────────────────────
def test_check_attack_pace_only_for_legend_i() -> None:
    assert check_attack_pace(0, LeagueType.LEGEND_II) is None
    assert check_attack_pace(0, LeagueType.LEGEND_III) is None


def test_pace_zero_attacks_with_time_left() -> None:
    long_before = datetime(2026, 5, 3, 6, 0, tzinfo=timezone.utc)
    assert _check_attack_pace_legend_i(0, long_before) is None


def test_pace_warning_with_4_attacks_left_at_two_hours() -> None:
    soon = datetime(
        2026, 5, 3, (LEGEND_DAILY_RESET_HOUR_UTC - 2) % 24, 0, tzinfo=timezone.utc,
    )
    assert _check_attack_pace_legend_i(LEGEND_I_DAILY_ATTACK_QUOTA - 4, soon) is not None


def test_pace_critical_with_full_quota_remaining_close_to_reset() -> None:
    soon = datetime(
        2026, 5, 3, (LEGEND_DAILY_RESET_HOUR_UTC - 1) % 24, 0, tzinfo=timezone.utc,
    )
    assert _check_attack_pace_legend_i(0, soon) == "pace_critical"


def test_pace_done_returns_none() -> None:
    soon = datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc)
    assert _check_attack_pace_legend_i(LEGEND_I_DAILY_ATTACK_QUOTA, soon) is None


def test_hours_until_daily_reset_positive() -> None:
    assert _hours_until_daily_reset(
        datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
    ) > 0


# ─────────────────────────────────────────────────────────────────────────────
# malchance
# ─────────────────────────────────────────────────────────────────────────────
def test_malchance_unknown_league_returns_zero() -> None:
    d = DefenseData(trophies_lost=40, opponent_tag=None, opponent_trophies=None)
    assert get_malchance_score(d, LeagueType.UNKNOWN) == 0.0


def test_malchance_normal_loss_low_score() -> None:
    d = DefenseData(trophies_lost=32, opponent_tag="#A", opponent_trophies=5800)
    assert get_malchance_score(d, LeagueType.LEGEND_II) <= 0.2


def test_malchance_high_loss_increases_score() -> None:
    d = DefenseData(trophies_lost=60, opponent_tag="#A", opponent_trophies=5800)
    assert get_malchance_score(d, LeagueType.LEGEND_II) > 0.4


def test_malchance_pile_on_increases_score() -> None:
    base = DefenseData(trophies_lost=32, opponent_tag="#A", opponent_trophies=5800)
    multi = DefenseData(
        trophies_lost=32, opponent_tag="#A", opponent_trophies=5800, attack_count=4,
    )
    assert get_malchance_score(multi, LeagueType.LEGEND_II) > get_malchance_score(
        base, LeagueType.LEGEND_II,
    )


def test_malchance_unknown_opponent_no_gap_factor() -> None:
    d = DefenseData(trophies_lost=40, opponent_tag=None, opponent_trophies=None)
    s = get_malchance_score(d, LeagueType.LEGEND_III)
    assert 0.0 <= s <= 1.0


def test_aggregate_malchance_empty() -> None:
    assert aggregate_malchance([], LeagueType.LEGEND_I) == 0.0


def test_aggregate_malchance_weighted_by_loss() -> None:
    big = DefenseData(trophies_lost=50, opponent_tag="#A", opponent_trophies=4500)
    small = DefenseData(trophies_lost=10, opponent_tag="#B", opponent_trophies=5800)
    s = aggregate_malchance([big, small], LeagueType.LEGEND_III)
    s_big = get_malchance_score(big, LeagueType.LEGEND_III)
    s_small = get_malchance_score(small, LeagueType.LEGEND_III)
    assert min(s_big, s_small) <= s <= max(s_big, s_small)
    assert abs(s - s_big) < abs(s - s_small)


# ─────────────────────────────────────────────────────────────────────────────
# infer_defense_outcome — bandes calibrées sur la formule trophy Supercell.
# L'API CoC publique n'expose pas les détails par défense, on s'appuie sur
# le delta de trophées perdus comme proxy pour stars + destruction.
# ─────────────────────────────────────────────────────────────────────────────
def test_infer_defense_outcome_zero_or_negative_means_successful_defense() -> None:
    stars, destruction = infer_defense_outcome(0)
    assert stars == "0⭐"
    assert "réussie" in destruction
    assert infer_defense_outcome(-5) == ("0⭐", "défense réussie")


def test_infer_defense_outcome_one_star_band() -> None:
    for delta in (1, 7, 14):
        stars, destruction = infer_defense_outcome(delta)
        assert stars == "≈ 1⭐"
        assert "faible" in destruction


def test_infer_defense_outcome_two_star_band() -> None:
    for delta in (15, 20, 24):
        stars, destruction = infer_defense_outcome(delta)
        assert stars == "≈ 2⭐"
        assert "< 50" in destruction


def test_infer_defense_outcome_two_star_heavy_destruction_band() -> None:
    """25–34 cups lost → 2⭐ avec forte destruction (50–80 %), pas 3⭐."""
    for delta in (25, 30, 34):
        stars, destruction = infer_defense_outcome(delta)
        assert stars == "≈ 2⭐"
        assert "50–80" in destruction


def test_infer_defense_outcome_three_star_perfect_band() -> None:
    for delta in (35, 40, 50):
        stars, destruction = infer_defense_outcome(delta)
        assert stars == "≈ 3⭐"
        assert "≥ 80" in destruction


def test_infer_defense_outcome_band_boundaries_are_monotonic() -> None:
    """Higher trophy loss must never downgrade the inferred severity."""
    severity_rank = {
        ("0⭐", "défense réussie"): 0,
        ("≈ 1⭐", "destruction faible"): 1,
        ("≈ 2⭐", "destruction < 50 %"): 2,
        ("≈ 2⭐", "destruction 50–80 %"): 3,
        ("≈ 3⭐", "destruction ≥ 80 % (proche perfect)"): 4,
    }
    last_rank = -1
    for delta in range(0, 60):
        rank = severity_rank[infer_defense_outcome(delta)]
        assert rank >= last_rank, f"regression at delta={delta}"
        last_rank = rank


# ─────────────────────────────────────────────────────────────────────────────
# pace + projection
# ─────────────────────────────────────────────────────────────────────────────
def _series(start: int, deltas: list[int]) -> list[LegendSnapshot]:
    base = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    out: list[LegendSnapshot] = []
    cur = start
    for i, d in enumerate(deltas):
        cur += d
        out.append(
            LegendSnapshot(
                player_tag="#X",
                trophies=cur,
                league_type=LeagueType.LEGEND_II,
                attacks_done=0,
                trophies_gained=0,
                trophies_lost=0,
                captured_at=base + timedelta(days=i),
            ),
        )
    return out


def test_pace_score_uptrend_positive() -> None:
    snaps = _series(5500, [10, 15, 20, 25, 30])
    assert calculate_pace_score(snaps, LeagueType.LEGEND_II) > 0


def test_pace_score_downtrend_negative() -> None:
    snaps = _series(5800, [-10, -15, -20, -25, -30])
    assert calculate_pace_score(snaps, LeagueType.LEGEND_II) < 0


def test_pace_score_unknown_league_zero() -> None:
    snaps = _series(4500, [10, 10, 10, 10, 10])
    assert calculate_pace_score(snaps, LeagueType.UNKNOWN) == 0.0


def test_predict_end_of_season_uses_latest_when_thin() -> None:
    snaps = _series(5500, [5, 5])
    proj = predict_end_of_season_trophies(snaps, LeagueType.LEGEND_II)
    assert proj == snaps[-1].trophies


def test_predict_end_of_season_extrapolates() -> None:
    snaps = _series(5500, [10, 10, 10, 10, 10])
    proj = predict_end_of_season_trophies(snaps, LeagueType.LEGEND_II)
    assert proj > snaps[-1].trophies


def test_predict_end_of_season_empty() -> None:
    assert predict_end_of_season_trophies([], LeagueType.LEGEND_II) == 0


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def test_season_month_label() -> None:
    dt = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    assert season_month_label(dt) == "2026-05"


def test_utc_hour_floor() -> None:
    dt = datetime(2026, 5, 3, 14, 37, 22, tzinfo=timezone.utc)
    assert utc_hour_floor(dt) == datetime(2026, 5, 3, 14, 0, 0, tzinfo=timezone.utc)


def test_utc_hour_floor_naive_input_treated_as_utc() -> None:
    naive = datetime(2026, 5, 3, 14, 37, 22)
    assert utc_hour_floor(naive) == datetime(2026, 5, 3, 14, 0, 0, tzinfo=timezone.utc)


def test_legend_projection_horizon_month_roll() -> None:
    nov = datetime(2026, 11, 15, tzinfo=timezone.utc)
    end = legend_projection_horizon(nov)
    assert end.year == 2026 and end.month == 12 and end.day == 1


def test_legend_projection_horizon_december_roll_to_next_year() -> None:
    dec = datetime(2026, 12, 15, tzinfo=timezone.utc)
    end = legend_projection_horizon(dec)
    assert end.year == 2027 and end.month == 1 and end.day == 1
