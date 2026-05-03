"""Observabilité polling + latences (prompt §8) — état en mémoire."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Any, Final

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

_P95_FRAC: Final[float] = 0.95
_LAT_MAX: Final[int] = 500


class PollingMetrics:
    """Métriques d’un cycle de refill (extension future)."""

    __slots__ = (
        "cycle_start",
        "cycle_duration_ms",
        "players_polled",
        "api_calls_made",
        "api_errors_429",
        "api_errors_other",
        "db_writes",
        "alerts_sent",
        "queue_depth_start",
        "queue_depth_end",
    )

    def __init__(
        self,
        cycle_start: datetime,
        cycle_duration_ms: float,
        players_polled: int,
        api_calls_made: int,
        api_errors_429: int,
        api_errors_other: int,
        db_writes: int,
        alerts_sent: int,
        queue_depth_start: int,
        queue_depth_end: int,
    ) -> None:
        self.cycle_start = cycle_start
        self.cycle_duration_ms = cycle_duration_ms
        self.players_polled = players_polled
        self.api_calls_made = api_calls_made
        self.api_errors_429 = api_errors_429
        self.api_errors_other = api_errors_other
        self.db_writes = db_writes
        self.alerts_sent = alerts_sent
        self.queue_depth_start = queue_depth_start
        self.queue_depth_end = queue_depth_end


class MetricsCollector:
    """Compteurs + latences pour `/bot_stats` et futures agrégations."""

    __slots__ = (
        "_lock",
        "_lat_ms",
        "_polls_ok",
        "_polls_fail",
        "_api_429",
        "_alerts_sent",
        "_started",
        "_queue_depth",
        "_lat_api",
        "_flush_ok",
        "_flush_fail",
        "_flush_429",
        "_flush_alerts",
    )

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._lat_ms: deque[float] = deque(maxlen=_LAT_MAX)
        self._polls_ok = 0
        self._polls_fail = 0
        self._api_429 = 0
        self._alerts_sent = 0
        self._started = time.monotonic()
        self._queue_depth = 0
        self._lat_api: deque[float] = deque(maxlen=_LAT_MAX)
        self._flush_ok = 0
        self._flush_fail = 0
        self._flush_429 = 0
        self._flush_alerts = 0

    async def record_poll(
        self,
        duration_ms: float,
        *,
        success: bool,
        is_429: bool = False,
    ) -> None:
        async with self._lock:
            self._lat_ms.append(max(0.0, duration_ms))
            if is_429:
                self._api_429 += 1
            if success:
                self._polls_ok += 1
            else:
                self._polls_fail += 1

    async def record_api_latency(self, _endpoint: str, latency_ms: float) -> None:
        async with self._lock:
            self._lat_api.append(max(0.0, latency_ms))

    async def record_alert_sent(self) -> None:
        async with self._lock:
            self._alerts_sent += 1

    async def set_queue_depth(self, n: int) -> None:
        async with self._lock:
            self._queue_depth = max(0, n)

    def get_p95_latency(self) -> float:
        return _percentile(list(self._lat_ms), _P95_FRAC)

    async def summary(self) -> dict[str, Any]:
        async with self._lock:
            lat = list(self._lat_ms)
            api_lat = list(self._lat_api)
            polls_ok = self._polls_ok
            polls_fail = self._polls_fail
            api_429 = self._api_429
            alerts = self._alerts_sent
            q = self._queue_depth
            uptime = time.monotonic() - self._started
        rss_mb = 0.0
        if psutil is not None:
            try:
                rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            except Exception:  # noqa: BLE001
                pass
        return {
            "uptime_s": round(uptime, 1),
            "polls_ok": polls_ok,
            "polls_fail": polls_fail,
            "api_429": api_429,
            "alerts_sent": alerts,
            "queue_depth": q,
            "p50_latency_ms": _percentile(lat, 0.50),
            "p95_latency_ms": _percentile(lat, 0.95),
            "p95_api_ms": _percentile(api_lat, 0.95),
            "rss_mb": round(rss_mb, 1),
        }

    async def prepare_hourly_flush(self) -> dict[str, float | int]:
        """Snapshot deltas since last successful `commit_hourly_flush` (for bot_metrics_hourly)."""
        async with self._lock:
            d_ok = self._polls_ok - self._flush_ok
            d_fail = self._polls_fail - self._flush_fail
            d_429 = self._api_429 - self._flush_429
            d_alerts = self._alerts_sent - self._flush_alerts
            lat = list(self._lat_ms)
        polls_delta = int(d_ok + d_fail)
        avg_lat = sum(lat) / len(lat) if lat else 0.0
        return {
            "polls_total": polls_delta,
            "errors_total": int(d_fail + d_429),
            "alerts_sent": int(d_alerts),
            "avg_latency_ms": round(avg_lat, 3),
            "p95_latency_ms": _percentile(lat, 0.95),
        }

    async def commit_hourly_flush(self) -> None:
        """Call after `Repository.merge_bot_metrics_hourly` succeeds."""
        async with self._lock:
            self._flush_ok = self._polls_ok
            self._flush_fail = self._polls_fail
            self._flush_429 = self._api_429
            self._flush_alerts = self._alerts_sent


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round((len(s) - 1) * q))))
    return round(s[idx], 2)
