"""Tests for QuotaService — Free 50/mois, illimité Premium / Trial."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from constants import PING_QUOTA_FREE_MONTHLY
from models import (
    PingQuotaState,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from services.quota import ConsumeResult, QuotaService


class _FakeRepo:
    def __init__(self, used: int = 0, warned: bool = False) -> None:
        self.used = used
        self.warned = warned
        self.warn_marked = 0
        self.increment_calls = 0

    async def get_ping_quota(self, _user_id: int, _ym: str) -> PingQuotaState:
        return PingQuotaState(
            discord_user_id=42,
            year_month=_ym,
            used=self.used,
            warned_full=self.warned,
        )

    async def increment_ping_quota(self, _user_id: int, _ym: str) -> int:
        self.used += 1
        self.increment_calls += 1
        return self.used

    async def mark_ping_quota_warned(self, _user_id: int, _ym: str) -> None:
        self.warn_marked += 1
        self.warned = True


class _FakeBilling:
    def __init__(self, entitled: bool) -> None:
        self.entitled = entitled

    async def is_entitled(self, _user_id: int) -> bool:
        return self.entitled

    async def get_subscription(self, user_id: int) -> Subscription:
        return Subscription(
            discord_user_id=user_id,
            plan=(SubscriptionPlan.PREMIUM if self.entitled else SubscriptionPlan.FREE),
            status=(SubscriptionStatus.ACTIVE if self.entitled else SubscriptionStatus.INACTIVE),
            current_period_end=(
                datetime(2099, 1, 1, tzinfo=timezone.utc) if self.entitled else None
            ),
        )


@pytest.mark.asyncio
async def test_premium_user_unlimited() -> None:
    repo = _FakeRepo(used=PING_QUOTA_FREE_MONTHLY + 1000)
    billing = _FakeBilling(entitled=True)
    qsvc = QuotaService(repo, billing)  # type: ignore[arg-type]
    assert await qsvc.consume_ping(42) == ConsumeResult.UNLIMITED
    assert repo.increment_calls == 0
    assert await qsvc.remaining(42) is None


@pytest.mark.asyncio
async def test_free_user_within_quota_increments() -> None:
    repo = _FakeRepo(used=10)
    billing = _FakeBilling(entitled=False)
    qsvc = QuotaService(repo, billing)  # type: ignore[arg-type]
    assert await qsvc.consume_ping(42) == ConsumeResult.OK
    assert repo.increment_calls == 1
    assert await qsvc.remaining(42) == PING_QUOTA_FREE_MONTHLY - 11


@pytest.mark.asyncio
async def test_free_user_exhausted() -> None:
    repo = _FakeRepo(used=PING_QUOTA_FREE_MONTHLY)
    billing = _FakeBilling(entitled=False)
    qsvc = QuotaService(repo, billing)  # type: ignore[arg-type]
    assert await qsvc.consume_ping(42) == ConsumeResult.EXHAUSTED
    assert repo.increment_calls == 0


@pytest.mark.asyncio
async def test_should_warn_full_only_once() -> None:
    repo = _FakeRepo(used=PING_QUOTA_FREE_MONTHLY, warned=False)
    billing = _FakeBilling(entitled=False)
    qsvc = QuotaService(repo, billing)  # type: ignore[arg-type]
    assert await qsvc.should_warn_full(42) is True
    # Second call: simulate the row now reflects warned=True.
    repo.warned = True
    assert await qsvc.should_warn_full(42) is False


@pytest.mark.asyncio
async def test_should_warn_full_premium_never_warns() -> None:
    repo = _FakeRepo(used=PING_QUOTA_FREE_MONTHLY, warned=False)
    billing = _FakeBilling(entitled=True)
    qsvc = QuotaService(repo, billing)  # type: ignore[arg-type]
    assert await qsvc.should_warn_full(42) is False
