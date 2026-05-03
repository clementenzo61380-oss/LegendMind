"""HTTP server (aiohttp) — receives Stripe webhook events.

Single endpoint: ``POST /stripe/webhook``. Verifies the Stripe-Signature
header against ``STRIPE_WEBHOOK_SECRET`` then forwards the event to
``BillingService.apply_webhook_event``.

Lifecycle is owned by ``main.py`` via ``start()`` / ``stop()``. When Stripe
isn't configured the server still starts but only exposes a 503 endpoint
(useful for healthcheck probes from the reverse proxy).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from services.billing import BillingService

log = logging.getLogger(__name__)


class StripeWebhookServer:
    """Tiny aiohttp app dedicated to Stripe webhook delivery.

    Runs in the same event loop as the Discord bot — billing throughput is
    sub-1 RPS so a separate process is overkill.
    """

    def __init__(
        self,
        billing: "BillingService",
        webhook_secret: str | None,
        host: str,
        port: int,
    ) -> None:
        self._billing = billing
        self._secret = webhook_secret
        self._host = host
        self._port = port
        self._app = web.Application()
        self._app.router.add_post("/stripe/webhook", self._handle_webhook)
        self._app.router.add_get("/health", self._handle_health)
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Bind the listening socket. Idempotent."""
        if self._runner is not None:
            return
        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        log.info(
            "Stripe webhook server listening on http://%s:%d/stripe/webhook",
            self._host, self._port,
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Verify signature, decode event, delegate to BillingService."""
        if not self._billing.is_configured or not self._secret:
            log.warning("Webhook hit but Stripe is not configured; returning 503")
            return web.Response(status=503, text="stripe not configured")
        sig_header = request.headers.get("Stripe-Signature", "")
        body = await request.read()
        # Lazy import to keep ``stripe`` an optional dep at import time.
        import stripe

        try:
            event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
                payload=body, sig_header=sig_header, secret=self._secret,
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            log.warning("Stripe webhook signature verification failed")
            return web.Response(status=400, text="invalid signature")
        applied = await self._billing.apply_webhook_event(event)
        return web.json_response({"received": True, "applied": applied})
