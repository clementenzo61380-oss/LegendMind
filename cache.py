"""Cache LRU in-process (prompt §5.2) — asyncio.Lock, TTL, préfixe."""

from __future__ import annotations

import asyncio
import fnmatch
import time
from collections import OrderedDict
from typing import Any, Final

_DEFAULT_TTL: Final[int] = 300
_MAX: Final[int] = 256


class InMemoryCache:
    """File d’attente ordonnée + expiration monotone (thread-safe via ``Lock``)."""

    def __init__(self, max_size: int = _MAX, default_ttl: int = _DEFAULT_TTL) -> None:
        self._max = max(16, max_size)
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def _prune_expired(self) -> None:
        now = time.monotonic()
        dead = [k for k, (_, exp) in self._data.items() if exp <= now]
        for k in dead:
            del self._data[k]

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            self._prune_expired()
            item = self._data.get(key)
            if item is None:
                return None
            val, exp = item
            if exp <= time.monotonic():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return val

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        sec = ttl if ttl is not None else self._default_ttl
        exp = time.monotonic() + max(1.0, float(sec))
        async with self._lock:
            self._prune_expired()
            if key in self._data:
                del self._data[key]
            self._data[key] = (value, exp)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def invalidate_prefix(self, prefix: str) -> None:
        async with self._lock:
            pattern = prefix + "*"
            for k in list(self._data.keys()):
                if fnmatch.fnmatch(k, pattern):
                    del self._data[k]
