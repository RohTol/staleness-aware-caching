"""
In-memory cache store.

Each entry stores the full API response plus the time it was cached.
TTL is checked on read — expired entries are treated as misses.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class CacheEntry:
    data: Dict[str, Any]   # full response from the API simulator
    cached_at: float        # time.time() when this was stored
    ttl_s: float            # how long this entry is valid


class Cache:
    def __init__(self) -> None:
        # key: (tool, frozenset of args items) → CacheEntry
        self._store: Dict[Tuple, CacheEntry] = {}
        self.hits: int = 0
        self.misses: int = 0

    def _make_key(self, tool: str, args: Dict[str, Any]) -> Tuple:
        return (tool, frozenset(args.items()))

    def get(self, tool: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = self._make_key(tool, args)
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        if time.time() - entry.cached_at > entry.ttl_s:
            # Expired — evict and treat as miss
            del self._store[key]
            self.misses += 1
            return None
        self.hits += 1
        return entry.data

    def set(self, tool: str, args: Dict[str, Any], data: Dict[str, Any], ttl_s: float) -> None:
        key = self._make_key(tool, args)
        self._store[key] = CacheEntry(data=data, cached_at=time.time(), ttl_s=ttl_s)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
