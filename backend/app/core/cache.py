"""Application cache seam (Phase 2d).

A small in-process TTL cache with explicit invalidation. This is the single
cache surface for both Tier-2 config reads (`core.cms_client.cfg`) and Tier-3
content reads (`modules/{content,feed,quiz}/`). Per
`docs/architecture/v2/06-caching-performance.md`, Phase 3b can swap the
backing store to Redis without changing any caller — `get_or_compute` /
`invalidate` are the only public surface.

Design choices for this Phase-2d implementation:

- **In-process dict + `threading.RLock`.** uvicorn runs one Python process
  per worker; per-worker caches are correct because the webhook receiver
  in `modules/cms/routes.py` invalidates inside the receiving worker only
  — but the 60-second default TTL (settings.cache_ttl_app_config) bounds
  the cross-worker drift. Phase 3b's Redis swap removes that bound.
- **No LRU eviction yet.** The keyspace is tiny (app_config has ~25 keys;
  content reads carry per-id keys but the working set is small). We add LRU
  when the working set actually grows past the dozens.
- **`get_or_compute` returns the value, never a wrapper.** Callers get
  back a plain object; the cache details stay private to this module.
- **`etag` slot on every entry.** Cheap-and-easy support for HTTP
  conditional responses; Phase 3a (HTTP cache headers) reads it.

The module exports both the class (`AppCache`) for tests and a process-wide
singleton (`cache = AppCache()`) for normal callers.
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class CacheEntry:
    """One cached value, with its ETag and a monotonic expiry."""

    value: Any
    etag: str
    expires_at: float  # time.monotonic() seconds; <=0 means "never expires"


def _make_etag(value: Any) -> str:
    """Deterministic short ETag for a value.

    Uses repr() — good enough for the JSON-ish values app_config holds and
    for the frozen content reads. The point is to detect "did the value
    change" cheaply, not to be a content-addressed hash.
    """
    raw = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:16]


class AppCache:
    """Thread-safe in-process TTL cache.

    Usage:
        cache.get_or_compute("app_config:quiz.duration_min", ttl=60,
                              loader=lambda: _load_from_db(...))
    """

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

    # ── Reads ──────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[CacheEntry]:
        """Return the entry if present and not expired; else None.

        Does not refresh expired entries — that is `get_or_compute`'s job.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at > 0 and time.monotonic() >= entry.expires_at:
                # Expired — drop it and miss.
                del self._store[key]
                return None
            return entry

    def get_or_compute(
        self,
        key: str,
        *,
        ttl: int,
        loader: Callable[[], Any],
    ) -> Any:
        """Return the cached value, or run `loader` and cache the result.

        `ttl` is in seconds. `ttl <= 0` means "cache forever" (still
        invalidatable by `invalidate`).

        The loader is called outside the lock — a slow DB read does not
        block other keys — but the resulting set is locked. A second
        caller that arrived during the load may end up re-running the
        loader; we accept that to avoid holding the lock across IO.
        """
        existing = self.get(key)
        if existing is not None:
            return existing.value

        value = loader()
        self.set(key, value, ttl=ttl)
        return value

    # ── Writes ─────────────────────────────────────────────────────────────

    def set(self, key: str, value: Any, *, ttl: int) -> CacheEntry:
        """Insert or replace `key` with `value`. Returns the new entry."""
        expires_at = (time.monotonic() + ttl) if ttl > 0 else 0.0
        entry = CacheEntry(value=value, etag=_make_etag(value), expires_at=expires_at)
        with self._lock:
            self._store[key] = entry
        return entry

    def invalidate(self, key: str) -> bool:
        """Drop `key` from the cache. Returns True iff a value was removed.

        Called by the loopback CMS webhook (`modules/cms/routes.py`) on
        Directus writes. Idempotent — invalidating a non-cached key is a
        no-op.
        """
        with self._lock:
            return self._store.pop(key, None) is not None

    def invalidate_prefix(self, prefix: str) -> int:
        """Drop every key starting with `prefix`. Returns the count.

        Useful for collection-wide invalidations (e.g. a feed status flip
        that invalidates every filter that could have included the item).
        """
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)

    def clear(self) -> None:
        """Drop every entry. Test helper; do not call in request handlers."""
        with self._lock:
            self._store.clear()

    # ── Introspection ──────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())


# Process-wide singleton. Callers should `from app.core import cache` and use
# `cache.cache.get_or_compute(...)`, or `from app.core.cache import cache`.
cache = AppCache()


# Convenience top-level functions so call-sites can do
#   `from app.core import cache` ; `cache.invalidate("foo")`
# (matches the snippet in 05 §7.3).
def get(key: str) -> Optional[CacheEntry]:
    return cache.get(key)


def get_or_compute(key: str, *, ttl: int, loader: Callable[[], Any]) -> Any:
    return cache.get_or_compute(key, ttl=ttl, loader=loader)


def set_(key: str, value: Any, *, ttl: int) -> CacheEntry:
    return cache.set(key, value, ttl=ttl)


def invalidate(key: str) -> bool:
    return cache.invalidate(key)


def invalidate_prefix(prefix: str) -> int:
    return cache.invalidate_prefix(prefix)


def clear() -> None:
    cache.clear()
