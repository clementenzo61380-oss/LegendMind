"""Per-user monthly quota for the /ping defense alert.

Free users get ``PING_QUOTA_FREE_MONTHLY`` defense DMs per calendar month.
Trial + Premium users are unlimited (gate via ``BillingService.is_entitled``).

The quota is enforced at *send time* in ``AlertManager._dispatch_one`` for
``AlertType.DEFENSE_TAKEN`` only — every other alert type is unrestricted.
"""

from __future__ import annotations

import enum
import logging
from datetime import datetime, timezone

from constants import PING_QUOTA_FREE_MONTHLY
from services.billing import BillingService
from services.db import Repository

log = logging.getLogger(__name__)


class ConsumeResult(str, enum.Enum):
    """Three-state outcome returned by ``QuotaService.consume_ping``."""

    UNLIMITED = "unlimited"  # Premium / Trial : no counter touched.
    OK = "ok"  # Free, +1 consumed, room remaining.
    EXHAUSTED = "exhausted"  # Free, monthly cap already hit, send blocked.


class QuotaService:
    """Stateless service: every operation hits the DB (no in-memory cache).

    Caching here would make the 50/month limit fuzzy across restarts and
    isn't worth the complexity at our throughput (one ping per defense).
    """

    def __init__(self, repository: Repository, billing: BillingService) -> None:
        self._repo = repository
        self._billing = billing

    async def consume_ping(self, discord_user_id: int) -> ConsumeResult:
        """Try to spend one ping. ``EXHAUSTED`` ⇒ caller MUST NOT send."""
        if await self._billing.is_entitled(discord_user_id):
            return ConsumeResult.UNLIMITED
        bucket = _current_bucket()
        state = await self._repo.get_ping_quota(discord_user_id, bucket)
        if state.used >= PING_QUOTA_FREE_MONTHLY:
            return ConsumeResult.EXHAUSTED
        await self._repo.increment_ping_quota(discord_user_id, bucket)
        return ConsumeResult.OK

    async def remaining(self, discord_user_id: int) -> int | None:
        """Slots left this month, or ``None`` for unlimited entitlement."""
        if await self._billing.is_entitled(discord_user_id):
            return None
        bucket = _current_bucket()
        state = await self._repo.get_ping_quota(discord_user_id, bucket)
        return max(0, PING_QUOTA_FREE_MONTHLY - state.used)

    async def should_warn_full(self, discord_user_id: int) -> bool:
        """True the first time the user hits zero this month (idempotent)."""
        if await self._billing.is_entitled(discord_user_id):
            return False
        bucket = _current_bucket()
        state = await self._repo.get_ping_quota(discord_user_id, bucket)
        if state.used < PING_QUOTA_FREE_MONTHLY:
            return False
        if state.warned_full:
            return False
        await self._repo.mark_ping_quota_warned(discord_user_id, bucket)
        return True


def _current_bucket() -> str:
    """UTC ``YYYY-MM`` bucket key matching the ``ping_quota.year_month`` column."""
    return datetime.now(timezone.utc).strftime("%Y-%m")
