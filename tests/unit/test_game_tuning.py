"""Tests pour ``services.game_tuning`` (snapshot global)."""

from __future__ import annotations

import pytest

from services.game_tuning import (
    apply_tuning_patch,
    get_tuning,
    reset_tuning_to_defaults,
)


@pytest.fixture(autouse=True)
def _restore_tuning_after_test() -> object:
    yield
    reset_tuning_to_defaults()


def test_apply_updates_numeric_field() -> None:
    reset_tuning_to_defaults()
    ok, _ = apply_tuning_patch({"legend_ii_weekly_battles": 28, "version": "t1"})
    assert ok
    assert get_tuning().legend_ii_weekly_battles == 28


def test_apply_rejects_out_of_range() -> None:
    reset_tuning_to_defaults()
    ref = get_tuning().legend_ii_weekly_battles
    ok, _ = apply_tuning_patch({"legend_ii_weekly_battles": 999})
    assert not ok
    assert get_tuning().legend_ii_weekly_battles == ref


def test_apply_ignores_unknown_keys() -> None:
    reset_tuning_to_defaults()
    ok, _ = apply_tuning_patch({"supercell_said_hello": True, "legend_i_daily_battles": 8})
    assert ok
    assert get_tuning().legend_i_daily_battles == 8


def test_version_only_updates_metadata() -> None:
    reset_tuning_to_defaults()
    ok, _ = apply_tuning_patch({"version": "meta-only"})
    assert ok
    assert get_tuning().remote_version == "meta-only"
