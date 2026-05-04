"""Unit tests `MetricsCollector` — flush horaire + p95."""

from __future__ import annotations

import pytest

from services.metrics import MetricsCollector


@pytest.mark.asyncio
async def test_summary_empty_state() -> None:
    m = MetricsCollector()
    s = await m.summary()
    assert s["polls_ok"] == 0 and s["polls_fail"] == 0
    assert s["p95_latency_ms"] == 0.0


@pytest.mark.asyncio
async def test_record_poll_increments_counters() -> None:
    m = MetricsCollector()
    await m.record_poll(120.0, success=True)
    await m.record_poll(80.0, success=False, is_429=True)
    s = await m.summary()
    assert s["polls_ok"] == 1 and s["polls_fail"] == 1 and s["api_429"] == 1
    assert s["p95_latency_ms"] >= 80.0


@pytest.mark.asyncio
async def test_prepare_then_commit_resets_baseline() -> None:
    m = MetricsCollector()
    await m.record_poll(100.0, success=True)
    await m.record_poll(150.0, success=False)
    await m.record_alert_sent()
    chunk1 = await m.prepare_hourly_flush()
    assert chunk1["polls_total"] == 2
    assert chunk1["errors_total"] == 1
    assert chunk1["alerts_sent"] == 1
    await m.commit_hourly_flush()
    chunk2 = await m.prepare_hourly_flush()
    assert chunk2["polls_total"] == 0 and chunk2["errors_total"] == 0
    assert chunk2["alerts_sent"] == 0


@pytest.mark.asyncio
async def test_queue_depth_is_clamped_at_zero() -> None:
    m = MetricsCollector()
    await m.set_queue_depth(-5)
    s = await m.summary()
    assert s["queue_depth"] == 0
