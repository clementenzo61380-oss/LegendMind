"""Tests for BillingService — trial idempotency + entitlement window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from constants import PREMIUM_TRIAL_DAYS
from models import Subscription, SubscriptionPlan, SubscriptionStatus
from services.billing import BillingService, subscription_trial_window_days


class _FakeRepo:
    def __init__(self) -> None:
        self.store: dict[int, Subscription] = {}
        self.upserts = 0

    async def get_subscription(self, user_id: int) -> Subscription:
        return self.store.get(user_id, Subscription(discord_user_id=user_id))

    async def upsert_subscription(self, sub: Subscription) -> None:
        self.upserts += 1
        # Mimic the real ON CONFLICT rule: trial_used is sticky.
        existing = self.store.get(sub.discord_user_id)
        if existing is not None:
            sub.trial_used = sub.trial_used or existing.trial_used
        self.store[sub.discord_user_id] = sub

    async def get_subscription_by_stripe_customer(
        self,
        _customer_id: str,
    ) -> Subscription | None:
        return None


def _make_billing(
    repo: _FakeRepo,
    *,
    lifetime: frozenset[int] | None = None,
    extended_guilds: frozenset[int] | None = None,
    extended_days: int = 60,
) -> BillingService:
    return BillingService(
        repository=repo,  # type: ignore[arg-type]
        stripe_api_key=None,
        stripe_price_id_monthly=None,
        stripe_success_url=None,
        stripe_cancel_url=None,
        lifetime_entitled_discord_ids=lifetime,
        extended_trial_guild_ids=extended_guilds,
        extended_trial_days=extended_days,
    )


@pytest.mark.asyncio
async def test_start_trial_grants_seven_days_first_call() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo)
    sub = await svc.start_trial(42)
    assert sub.trial_used is True
    assert sub.plan is SubscriptionPlan.TRIAL
    assert sub.status is SubscriptionStatus.TRIALING
    assert sub.current_period_end is not None
    delta = sub.current_period_end - datetime.now(timezone.utc)
    assert timedelta(days=PREMIUM_TRIAL_DAYS) - timedelta(seconds=5) < delta
    assert delta < timedelta(days=PREMIUM_TRIAL_DAYS) + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_start_trial_extended_guild_uses_configured_days() -> None:
    repo = _FakeRepo()
    guild_id = 1241142693464248470
    svc = _make_billing(
        repo,
        extended_guilds=frozenset({guild_id}),
        extended_days=60,
    )
    sub = await svc.start_trial(7, guild_id=guild_id)
    assert sub.trial_used is True
    assert sub.current_period_end is not None
    delta = sub.current_period_end - datetime.now(timezone.utc)
    assert timedelta(days=59) - timedelta(seconds=5) < delta
    assert delta < timedelta(days=61) + timedelta(seconds=5)
    assert subscription_trial_window_days(sub) == 60


@pytest.mark.asyncio
async def test_start_trial_idempotent_no_second_grant() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo)
    await svc.start_trial(42)
    first_end = repo.store[42].current_period_end
    # Even after expiration, a second call must not extend the trial.
    repo.store[42].current_period_end = datetime.now(timezone.utc) - timedelta(days=1)
    sub = await svc.start_trial(42)
    assert sub.trial_used is True
    assert sub.current_period_end != first_end  # we forced it back; not bumped
    # Critical: the upsert wasn't called a second time.
    assert repo.upserts == 1


@pytest.mark.asyncio
async def test_is_entitled_during_active_period() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo)
    repo.store[42] = Subscription(
        discord_user_id=42,
        plan=SubscriptionPlan.PREMIUM,
        status=SubscriptionStatus.ACTIVE,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert await svc.is_entitled(42) is True


@pytest.mark.asyncio
async def test_not_entitled_after_period_end() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo)
    repo.store[42] = Subscription(
        discord_user_id=42,
        plan=SubscriptionPlan.PREMIUM,
        status=SubscriptionStatus.ACTIVE,
        current_period_end=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert await svc.is_entitled(42) is False


@pytest.mark.asyncio
async def test_free_default_not_entitled() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo)
    assert await svc.is_entitled(42) is False


@pytest.mark.asyncio
async def test_lifetime_list_entitled_without_subscription() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo, lifetime=frozenset({42, 99}))
    assert svc.is_lifetime_entitled(42) is True
    assert svc.is_lifetime_entitled(7) is False
    assert await svc.is_entitled(42) is True
    assert await svc.is_entitled(99) is True


@pytest.mark.asyncio
async def test_lifetime_entitled_overrides_expired_premium() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo, lifetime=frozenset({42}))
    repo.store[42] = Subscription(
        discord_user_id=42,
        plan=SubscriptionPlan.FREE,
        current_period_end=None,
    )
    assert await svc.is_entitled(42) is True


@pytest.mark.asyncio
async def test_apply_subscription_updated_event() -> None:
    repo = _FakeRepo()
    svc = _make_billing(repo)
    repo.store[42] = Subscription(
        discord_user_id=42,
        stripe_customer_id="cus_42",
    )

    async def fake_lookup(cid: str) -> Subscription | None:
        return repo.store.get(42) if cid == "cus_42" else None

    repo.get_subscription_by_stripe_customer = fake_lookup  # type: ignore[assignment]

    period_end = datetime(2099, 5, 1, tzinfo=timezone.utc)
    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_xyz",
                "customer": "cus_42",
                "status": "active",
                "current_period_end": int(period_end.timestamp()),
            },
        },
    }
    applied = await svc.apply_webhook_event(event)
    assert applied is True
    sub = repo.store[42]
    assert sub.plan is SubscriptionPlan.PREMIUM
    assert sub.status is SubscriptionStatus.ACTIVE
    assert sub.current_period_end == period_end
    assert sub.stripe_subscription_id == "sub_xyz"
