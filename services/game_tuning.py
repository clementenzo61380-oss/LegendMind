"""Paramètres Legend — défauts ``constants``, surcharge via JSON distant.

Supercell ne publie pas d'API machine-readable pour les patch notes. Le flux
supporté ici :

1. Tu lis les notes / le blog officiel.
2. Tu mets à jour un fichier JSON (gist, raw GitHub, S3, etc.) listé dans
   ``GAME_TUNING_URL``.
3. Le bot appelle ``apply_tuning_patch`` après chaque fetch réussi — quotas,
   heures de reset, bornes trophées, polling, etc. sont pris en compte sans
   redéployer le code.

Les clés non reconnues sont ignorées (log DEBUG). Les valeurs hors bornes
sont rejetées (log WARNING).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Final, Mapping

from constants import (
    COC_LEGEND_LEAGUE_ID,
    LEGEND_DAILY_RESET_HOUR_UTC,
    LEGEND_I_DAILY_BATTLES,
    LEGEND_I_PACE_CRITICAL_REMAINING,
    LEGEND_I_PACE_WARNING_REMAINING,
    LEGEND_II_WEEKLY_BATTLES,
    LEGEND_III_WEEKLY_BATTLES,
    LEGEND_TOTAL_PLAYERS_ESTIMATE,
    LEAGUE_LOWER_BOUND,
    POLL_INTERVAL_LEGEND_I_SECONDS,
    POLL_INTERVAL_LEGEND_II_III_SECONDS,
    WEEKLY_RECAP_DAY_OF_WEEK,
    WEEKLY_RECAP_HOUR_UTC,
    LeagueType,
)

log = logging.getLogger(__name__)

# Clés JSON autorisées (snake_case) → (attribut snapshot, min, max).
_NUMERIC_PATCH_FIELDS: Final[dict[str, tuple[str, int, int]]] = {
    "legend_i_daily_battles": ("legend_i_daily_battles", 1, 32),
    "legend_ii_weekly_battles": ("legend_ii_weekly_battles", 1, 64),
    "legend_iii_weekly_battles": ("legend_iii_weekly_battles", 1, 64),
    "legend_daily_reset_hour_utc": ("legend_daily_reset_hour_utc", 0, 23),
    "legend_i_pace_warning_remaining": ("legend_i_pace_warning_remaining", 1, 16),
    "legend_i_pace_critical_remaining": ("legend_i_pace_critical_remaining", 1, 16),
    "poll_interval_legend_i_seconds": ("poll_interval_legend_i_seconds", 60, 3600),
    "poll_interval_legend_ii_iii_seconds": (
        "poll_interval_legend_ii_iii_seconds", 120, 7200,
    ),
    "weekly_recap_day_of_week": ("weekly_recap_day_of_week", 0, 6),
    "weekly_recap_hour_utc": ("weekly_recap_hour_utc", 0, 23),
    "coc_legend_league_id": ("coc_legend_league_id", 1, 999_999_999),
    "legend_total_players_estimate": ("legend_total_players_estimate", 1_000, 10_000_000),
    "lower_legend_iii": ("lower_legend_iii", 3000, 7000),
    "lower_legend_ii": ("lower_legend_ii", 3000, 8000),
    "lower_legend_i": ("lower_legend_i", 4000, 9000),
}


@dataclass(frozen=True, slots=True)
class GameTuningSnapshot:
    """Instantané thread-safe en lecture (remplacé atomiquement par ``replace``)."""

    legend_i_daily_battles: int
    legend_ii_weekly_battles: int
    legend_iii_weekly_battles: int
    legend_daily_reset_hour_utc: int
    legend_i_pace_warning_remaining: int
    legend_i_pace_critical_remaining: int
    poll_interval_legend_i_seconds: int
    poll_interval_legend_ii_iii_seconds: int
    weekly_recap_day_of_week: int
    weekly_recap_hour_utc: int
    coc_legend_league_id: int
    legend_total_players_estimate: int
    lower_legend_iii: int
    lower_legend_ii: int
    lower_legend_i: int
    remote_version: str = ""
    last_applied_at: datetime | None = None

    @staticmethod
    def from_constants() -> GameTuningSnapshot:
        return GameTuningSnapshot(
            legend_i_daily_battles=LEGEND_I_DAILY_BATTLES,
            legend_ii_weekly_battles=LEGEND_II_WEEKLY_BATTLES,
            legend_iii_weekly_battles=LEGEND_III_WEEKLY_BATTLES,
            legend_daily_reset_hour_utc=LEGEND_DAILY_RESET_HOUR_UTC,
            legend_i_pace_warning_remaining=LEGEND_I_PACE_WARNING_REMAINING,
            legend_i_pace_critical_remaining=LEGEND_I_PACE_CRITICAL_REMAINING,
            poll_interval_legend_i_seconds=POLL_INTERVAL_LEGEND_I_SECONDS,
            poll_interval_legend_ii_iii_seconds=POLL_INTERVAL_LEGEND_II_III_SECONDS,
            weekly_recap_day_of_week=WEEKLY_RECAP_DAY_OF_WEEK,
            weekly_recap_hour_utc=WEEKLY_RECAP_HOUR_UTC,
            coc_legend_league_id=COC_LEGEND_LEAGUE_ID,
            legend_total_players_estimate=LEGEND_TOTAL_PLAYERS_ESTIMATE,
            lower_legend_iii=LEAGUE_LOWER_BOUND[LeagueType.LEGEND_III],
            lower_legend_ii=LEAGUE_LOWER_BOUND[LeagueType.LEGEND_II],
            lower_legend_i=LEAGUE_LOWER_BOUND[LeagueType.LEGEND_I],
        )

    def lower_bound(self, league: LeagueType) -> int:
        return {
            LeagueType.LEGEND_III: self.lower_legend_iii,
            LeagueType.LEGEND_II: self.lower_legend_ii,
            LeagueType.LEGEND_I: self.lower_legend_i,
            LeagueType.UNKNOWN: 0,
        }[league]

    @property
    def legend_i_daily_attack_quota(self) -> int:
        """Alias aligné sur l'ancien nom ``LEGEND_I_DAILY_ATTACK_QUOTA``."""
        return self.legend_i_daily_battles


_snapshot: GameTuningSnapshot = GameTuningSnapshot.from_constants()


def get_tuning() -> GameTuningSnapshot:
    return _snapshot


def _coerce_int(val: Any, lo: int, hi: int) -> int | None:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return None
    if n < lo or n > hi:
        return None
    return n


def apply_tuning_patch(raw: Mapping[str, Any]) -> tuple[bool, str]:
    """Fusionne un dict JSON dans le snapshot courant.

    Retourne ``(succès, message)``. Les clés inconnues sont ignorées.
    """
    global _snapshot
    if not isinstance(raw, Mapping):
        return False, "le document doit être un objet JSON"

    cur = _snapshot
    updates: dict[str, Any] = {}
    for json_key, (field, lo, hi) in _NUMERIC_PATCH_FIELDS.items():
        if json_key not in raw:
            continue
        coerced = _coerce_int(raw[json_key], lo, hi)
        if coerced is None:
            log.warning(
                "game_tuning: valeur invalide ou hors bornes pour %s (%r)",
                json_key, raw[json_key],
            )
            continue
        updates[field] = coerced

    meta_version = raw.get("version")
    now = datetime.now(timezone.utc)
    if meta_version is not None:
        updates["remote_version"] = str(meta_version)[:128]
    if updates or meta_version is not None:
        updates["last_applied_at"] = now

    if not updates:
        return False, "aucune clé de tuning reconnue"

    _snapshot = replace(cur, **updates)
    applied = [k for k in updates if k not in ("remote_version", "last_applied_at")]
    log.info(
        "game_tuning: snapshot mis à jour (champs: %s, version=%r)",
        applied or ["(métadonnées)"],
        _snapshot.remote_version,
    )
    return True, f"{len(applied)} champ(s) numériques appliqué(s)"


def reset_tuning_to_defaults() -> None:
    """Réinitialise aux constantes embarquées (tests / admin futur)."""
    global _snapshot
    _snapshot = GameTuningSnapshot.from_constants()
