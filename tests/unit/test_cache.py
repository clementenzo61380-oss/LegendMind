"""Tests InMemoryCache."""

from __future__ import annotations

import pytest

from services.cache import InMemoryCache


@pytest.mark.asyncio
async def test_cache_set_get_invalidate() -> None:
    c = InMemoryCache(max_size=8, default_ttl=1)
    await c.set("a", 42, ttl=60)
    assert await c.get("a") == 42
    await c.invalidate("a")
    assert await c.get("a") is None


@pytest.mark.asyncio
async def test_invalidate_prefix() -> None:
    c = InMemoryCache(max_size=32, default_ttl=300)
    await c.set("lb:1:10", [1], ttl=300)
    await c.set("lb:2:10", [2], ttl=300)
    await c.invalidate_prefix("lb:1:")
    assert await c.get("lb:1:10") is None
    assert await c.get("lb:2:10") == [2]
