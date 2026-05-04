"""Billing / Subscription service — Stripe Checkout + entitlement.

Architecture:
- ``BillingService`` owns subscription state (Subscription model) and exposes
  ``is_entitled`` + ``start_trial`` + ``start_checkout`` + ``apply_webhook_event``.
- All Stripe interactions go through this module; cogs only call high-level
  methods so the rest of the bot stays Stripe-agnostic.
- ``apply_webhook_event`` is invoked by ``services.stripe_webhook`` after
  signature verification — it never raises (returns False on unknown events).

Design notes
------------
- The trial is granted automatically at ``/setup`` / ``/premium`` and is
  idempotent: any subsequent attempt is a no-op (the ``trial_used`` flag
  persists forever). Duration is ``PREMIUM_TRIAL_DAYS`` by default, or longer
  on guilds listed in ``extended_trial_guild_ids`` (env).
- We never trust the client for billing state — the only writes from outside
  the webhook are: trial grant (one-shot) and customer-id binding (on first
  Checkout session).
- The Stripe library is imported lazily so the bot still starts when Stripe
  isn't configured (the Free tier remains fully functional).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any

from constants import PREMIUM_TRIAL_DAYS
from models import Subscription, SubscriptionPlan, SubscriptionStatus
from services.db import Repository

log = logging.getLogger(__name__)


def subscription_trial_window_days(sub: Subscription) -> int:
    """Jours accordés sur l'essai en cours (fin − début), sinon défaut global."""
    if sub.trial_started_at is not None and sub.current_period_end is not None:
        d = (sub.current_period_end - sub.trial_started_at).days
        if d >= 1:
            return d
    return PREMIUM_TRIAL_DAYS


class BillingService:
    """Stripe Checkout + trial lifecycle, persisted in ``subscriptions`` table.

    Stripe is **optional**: when ``stripe_api_key`` is None, ``start_checkout``
    raises ``BillingNotConfigured`` and ``apply_webhook_event`` is unreachable
    (the webhook server is also disabled by ``main.py``).
    """

    def __init__(
        self,
        repository: Repository,
        stripe_api_key: str | None,
        stripe_price_id_monthly: str | None,
        stripe_success_url: str | None,
        stripe_cancel_url: str | None,
        lifetime_entitled_discord_ids: frozenset[int] | None = None,
        extended_trial_guild_ids: frozenset[int] | None = None,
        extended_trial_days: int = 60,
    ) -> None:
        self._repo = repository
        self._lifetime_ids: frozenset[int] = lifetime_entitled_discord_ids or frozenset()
        self._extended_trial_guild_ids: frozenset[int] = (
            extended_trial_guild_ids or frozenset()
        )
        self._extended_trial_days: int = max(1, int(extended_trial_days))
        self._api_key = stripe_api_key
        self._price_id = stripe_price_id_monthly
        self._success_url = stripe_success_url or "https://discord.com/channels/@me"
        self._cancel_url = stripe_cancel_url or "https://discord.com/channels/@me"
        self._stripe: ModuleType | None
        if stripe_api_key:
            import stripe  # local import → optional dep

            stripe.api_key = stripe_api_key
            self._stripe = stripe
        else:
            self._stripe = None

    @property
    def is_configured(self) -> bool:
        """True iff Stripe credentials are present and Checkout will work."""
        return self._stripe is not None and bool(self._price_id)

    # ── entitlement ──────────────────────────────────────────────────────
    def is_lifetime_entitled(self, discord_user_id: int) -> bool:
        """IDs listés dans ``LIFETIME_ENTITLED_DISCORD_IDS`` → Premium sans Stripe."""
        return discord_user_id in self._lifetime_ids

    async def is_entitled(self, discord_user_id: int) -> bool:
        """Convenience wrapper used by ``/ping`` and friends."""
        if self.is_lifetime_entitled(discord_user_id):
            return True
        sub = await self._repo.get_subscription(discord_user_id)
        return sub.is_entitled(datetime.now(timezone.utc))

    async def get_subscription(self, discord_user_id: int) -> Subscription:
        """Pass-through to repo — exposed for cogs that build embeds."""
        return await self._repo.get_subscription(discord_user_id)

    def trial_duration_days(self, guild_id: int | None) -> int:
        """Jours d'essai accordés au premier grant (setup/premium) selon le serveur."""
        if guild_id is not None and guild_id in self._extended_trial_guild_ids:
            return self._extended_trial_days
        return PREMIUM_TRIAL_DAYS

    # ── trial (one-shot, idempotent) ─────────────────────────────────────
    async def start_trial(
        self,
        discord_user_id: int,
        *,
        guild_id: int | None = None,
    ) -> Subscription:
        """Grant the Premium trial **once** per Discord user.

        Duration is ``PREMIUM_TRIAL_DAYS`` by default, or ``extended_trial_days``
        when ``guild_id`` is listed in ``extended_trial_guild_ids`` (env).

        Idempotent: a second invocation is a no-op and returns the existing
        subscription unchanged. The window is anchored on first call only.
        """
        sub = await self._repo.get_subscription(discord_user_id)
        if sub.trial_used:
            return sub
        now = datetime.now(timezone.utc)
        days = self.trial_duration_days(guild_id)
        sub.plan = SubscriptionPlan.TRIAL
        sub.status = SubscriptionStatus.TRIALING
        sub.trial_used = True
        sub.trial_started_at = now
        sub.current_period_end = now + timedelta(days=days)
        await self._repo.upsert_subscription(sub)
        log.info(
            "Trial (%d d) granted to %d until %s (guild_id=%r)",
            days,
            discord_user_id,
            sub.current_period_end,
            guild_id,
        )
        return sub

    # ── Stripe Checkout ──────────────────────────────────────────────────
    async def start_checkout(self, discord_user_id: int) -> str:
        """Create a Stripe Checkout Session and return its URL.

        Raises:
            BillingNotConfigured: Stripe isn't set up (``/premium`` should
                hide the Checkout path in that case).
        """
        if self._stripe is None or not self._price_id:
            raise BillingNotConfigured(
                "Stripe n'est pas configuré (STRIPE_API_KEY ou STRIPE_PRICE_ID_MONTHLY manquant).",
            )
        sub = await self._repo.get_subscription(discord_user_id)
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": self._price_id, "quantity": 1}],
            "success_url": self._success_url,
            "cancel_url": self._cancel_url,
            # ``client_reference_id`` is the canonical mapping key we use in
            # the webhook to know which Discord user just paid.
            "client_reference_id": str(discord_user_id),
            # Persist the binding on first checkout so future events resolve
            # via ``stripe_customer_id`` (cheaper than scanning by metadata).
            "metadata": {"discord_user_id": str(discord_user_id)},
        }
        if sub.stripe_customer_id:
            params["customer"] = sub.stripe_customer_id
        else:
            # Stripe will create a new customer automatically; we capture
            # the id in the ``checkout.session.completed`` webhook.
            params["customer_creation"] = "always"

        # ``stripe.checkout.Session.create`` is sync (the python lib uses
        # blocking I/O); offload to a thread to keep the event loop alive.
        import asyncio

        session = await asyncio.to_thread(
            self._stripe.checkout.Session.create,
            **params,
        )
        return str(session.url)

    # ── Webhook events (Stripe → us) ─────────────────────────────────────
    async def apply_webhook_event(self, event: dict[str, Any]) -> bool:
        """Mutate the local subscription based on a verified Stripe event.

        Returns True if the event led to a write, False if ignored. Never
        raises: webhook delivery has retry semantics, but our policy is to
        log and absorb so a single bad event doesn't poison the queue.
        """
        try:
            event_type = str(event.get("type", ""))
            data_object: dict[str, Any] = event.get("data", {}).get("object", {})
            if event_type == "checkout.session.completed":
                return await self._on_checkout_completed(data_object)
            if event_type in {
                "customer.subscription.created",
                "customer.subscription.updated",
            }:
                return await self._on_subscription_updated(data_object)
            if event_type == "customer.subscription.deleted":
                return await self._on_subscription_deleted(data_object)
            log.debug("Webhook event ignored: %s", event_type)
            return False
        except Exception:  # noqa: BLE001
            log.exception("Webhook handler failed for event %r", event.get("id"))
            return False

    async def _on_checkout_completed(self, obj: dict[str, Any]) -> bool:
        ref = obj.get("client_reference_id")
        if not ref:
            log.warning("Checkout session without client_reference_id; ignoring")
            return False
        try:
            user_id = int(str(ref))
        except ValueError:
            log.warning("Invalid client_reference_id: %r", ref)
            return False
        customer_id = obj.get("customer")
        sub_id = obj.get("subscription")
        sub = await self._repo.get_subscription(user_id)
        if customer_id:
            sub.stripe_customer_id = str(customer_id)
        if sub_id:
            sub.stripe_subscription_id = str(sub_id)
        # Don't activate yet — wait for ``customer.subscription.updated`` which
        # carries the authoritative ``current_period_end``. We just bind ids.
        await self._repo.upsert_subscription(sub)
        log.info("Checkout completed for user %d", user_id)
        return True

    async def _on_subscription_updated(self, obj: dict[str, Any]) -> bool:
        customer_id = obj.get("customer")
        if not customer_id:
            return False
        sub = await self._repo.get_subscription_by_stripe_customer(str(customer_id))
        if sub is None:
            log.warning(
                "Subscription update for unknown customer %s — ignoring",
                customer_id,
            )
            return False
        status_raw = str(obj.get("status", "active"))
        try:
            status = SubscriptionStatus(status_raw)
        except ValueError:
            status = SubscriptionStatus.ACTIVE
        sub.status = status
        sub.plan = (
            SubscriptionPlan.PREMIUM
            if status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING}
            else SubscriptionPlan.FREE
        )
        sub.stripe_subscription_id = str(obj.get("id") or sub.stripe_subscription_id)
        period_end_ts = obj.get("current_period_end")
        if period_end_ts is not None:
            sub.current_period_end = datetime.fromtimestamp(
                int(period_end_ts),
                tz=timezone.utc,
            )
        await self._repo.upsert_subscription(sub)
        log.info(
            "Subscription updated for user %d: status=%s end=%s",
            sub.discord_user_id,
            sub.status.value,
            sub.current_period_end,
        )
        return True

    async def _on_subscription_deleted(self, obj: dict[str, Any]) -> bool:
        customer_id = obj.get("customer")
        if not customer_id:
            return False
        sub = await self._repo.get_subscription_by_stripe_customer(str(customer_id))
        if sub is None:
            return False
        sub.status = SubscriptionStatus.CANCELED
        sub.plan = SubscriptionPlan.FREE
        await self._repo.upsert_subscription(sub)
        log.info("Subscription cancelled for user %d", sub.discord_user_id)
        return True


class BillingNotConfigured(RuntimeError):
    """Raised when /premium is invoked but Stripe isn't configured.

    Cogs catch this and reply with a Free-tier-only message so the bot
    keeps working when running without Stripe creds (dev / self-hosted).
    """
