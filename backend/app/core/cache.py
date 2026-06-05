"""Application cache seam (Phase 2d backbone, Phase 3 pluggable backend).

A small TTL cache with explicit invalidation. This is the single cache surface
for both Tier-2 config reads (`core.cms_client.cfg`) and Tier-3 content reads
(`modules/{content,feed,quiz}/`). Per
`docs/architecture/v2/06-caching-performance.md` §4, the *backing store* is
pluggable behind the `AppCache` facade — Phase 3 adds a Redis backend without
changing any caller. `get_or_compute` / `invalidate` / `invalidate_prefix` /
`size` / `keys` are the only public surface, and they are byte-for-byte the same
across both backends.

Architecture (Phase 3):

    callers ──► AppCache (facade: get_or_compute, invalidate, …)
                   │
                   ├─ MemoryBackend   (default — dict + RLock, the 2d behaviour)
                   └─ RedisBackend    (opt-in via CACHE_BACKEND=redis)

Design choices carried from Phase 2d:

- **In-process dict + `threading.RLock` (MemoryBackend).** uvicorn runs one
  Python process per worker; per-worker caches are correct because the webhook
  receiver in `modules/cms/routes.py` invalidates inside the receiving worker
  only — the 60-second default TTL (settings.cache_ttl_app_config) bounds the
  cross-worker drift. The Redis swap removes that bound.
- **No LRU eviction yet.** The keyspace is tiny.
- **`get_or_compute` returns the value, never a wrapper.**
- **`etag` slot on every entry.** Cheap support for HTTP conditional responses.

Phase 3 additions:

- **Backend selection from settings.** `AppCache()` reads
  `settings.cache_backend` ("memory" | "redis") at construction. The
  process-wide singleton therefore honours `CACHE_BACKEND` from the
  environment.
- **Graceful degradation.** `RedisBackend` imports `redis` LAZILY and only
  pings on first use. If the import fails OR the server is unreachable, it logs
  a warning and the facade transparently falls back to a `MemoryBackend` — the
  app never fails to boot because redis is absent. This is what makes the local
  "no redis installed" environment safe.

The module exports both the class (`AppCache`) for tests and a process-wide
singleton (`cache = AppCache()`) for normal callers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Protocol

logger = logging.getLogger("app.core.cache")


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


# ─────────────────────────────────────────────────────────────────────────────
# Backend protocol — the pluggable storage seam (06 §4.2)
# ─────────────────────────────────────────────────────────────────────────────
#
# A backend stores `CacheEntry` objects keyed by string. It owns nothing about
# TTL *policy* (the facade decides expiry timestamps) beyond honouring the
# `expires_at` it is handed; MemoryBackend checks expiry on read, RedisBackend
# delegates expiry to redis EX. The facade (`AppCache`) is the single place that
# computes ETags and expiry, so both backends behave identically to callers.


class CacheBackend(Protocol):
    """The storage primitives every backend implements.

    Implementations must be thread-safe; uvicorn calls into the cache from a
    thread pool. They store and return `CacheEntry` objects so the ETag and
    expiry travel with the value.
    """

    name: str

    def get_entry(self, key: str) -> Optional[CacheEntry]: ...

    def set_entry(self, key: str, entry: CacheEntry, ttl: int) -> None: ...

    def delete(self, key: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def iter_keys(self) -> List[str]: ...

    def clear(self) -> None: ...

    @property
    def size(self) -> int: ...


class MemoryBackend:
    """In-process dict + RLock. The Phase-2d behaviour, now a backend.

    Expiry is enforced on read (lazy) against `time.monotonic()` — the same
    semantics the 2d AppCache had. There is no background sweep; expired keys
    are dropped the next time they are read or listed.
    """

    name = "memory"

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

    def get_entry(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at > 0 and time.monotonic() >= entry.expires_at:
                del self._store[key]
                return None
            return entry

    def set_entry(self, key: str, entry: CacheEntry, ttl: int) -> None:
        # ttl is informational here — MemoryBackend reads expiry off the entry.
        with self._lock:
            self._store[key] = entry

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def delete_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)

    def iter_keys(self) -> List[str]:
        with self._lock:
            # Drop expired keys while we're walking so `keys()`/`size` don't
            # over-report. Cheap at this keyspace size.
            now = time.monotonic()
            live = []
            expired = []
            for k, e in self._store.items():
                if e.expires_at > 0 and now >= e.expires_at:
                    expired.append(k)
                else:
                    live.append(k)
            for k in expired:
                del self._store[k]
            return live

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        return len(self.iter_keys())


class RedisBackend:
    """Redis-backed store (06 §4.2 swap; opt-in via CACHE_BACKEND=redis).

    Connection is LAZY: `redis` is imported and the client connected on first
    use, not at construction, so importing this module never requires the
    `redis` package. If the import fails or the first ping fails, the backend
    marks itself dead and the AppCache facade falls back to MemoryBackend — the
    app must never fail to boot because redis is absent.

    Wire format: each entry is stored as a JSON envelope
    `{"value": <json>, "etag": <str>}`. TTL is enforced by redis itself via
    `SET ... EX <ttl>` (ttl<=0 → no expiry). The ETag is recomputed on read
    from the deserialised value so callers see a stable ETag whichever backend
    served the read.

    `delete_prefix` uses `SCAN` + `DEL`. **O(n) caveat:** SCAN walks the whole
    keyspace under the namespace cursor; at our keyspace size (dozens of keys)
    this is negligible, but on a shared redis with millions of keys it would be
    expensive. Our keys are namespaced under `aoc:` so SCAN only ever matches
    our own. If the keyspace ever grows large, replace prefix-invalidation with
    a tagged-set scheme.
    """

    name = "redis"

    _NS = "aoc:"  # namespace prefix so SCAN/MATCH only touches our keys

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = None          # lazily connected redis.Redis
        self._dead = False           # True once we've given up on redis
        self._lock = threading.RLock()

    # ── connection lifecycle ────────────────────────────────────────────────

    def _connect(self):
        """Return a live client, or None if redis is unavailable.

        Idempotent and cheap after the first call. On any failure (import or
        connection) it sets `_dead` so subsequent calls short-circuit; the
        facade then routes to the memory fallback.
        """
        if self._dead:
            return None
        if self._client is not None:
            return self._client
        with self._lock:
            if self._dead:
                return None
            if self._client is not None:
                return self._client
            try:
                import redis  # lazy — only needed when CACHE_BACKEND=redis
            except Exception as exc:  # noqa: BLE001 — any import failure degrades
                logger.warning(
                    "cache: redis package not importable (%s); "
                    "falling back to in-process memory cache",
                    exc,
                )
                self._dead = True
                return None
            try:
                client = redis.Redis.from_url(
                    self._url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    decode_responses=True,
                )
                client.ping()
            except Exception as exc:  # noqa: BLE001 — connection refused, DNS, auth…
                logger.warning(
                    "cache: redis at %s unreachable (%s); "
                    "falling back to in-process memory cache",
                    self._url, exc,
                )
                self._dead = True
                return None
            self._client = client
            logger.info("cache: redis backend connected at %s", self._url)
            return client

    @property
    def available(self) -> bool:
        """True iff redis is usable. Triggers the lazy connect on first call."""
        return self._connect() is not None

    # ── envelope helpers ────────────────────────────────────────────────────

    def _k(self, key: str) -> str:
        return self._NS + key

    @staticmethod
    def _dump(entry: CacheEntry) -> Optional[str]:
        try:
            return json.dumps({"value": entry.value, "etag": entry.etag})
        except (TypeError, ValueError):
            # Value isn't JSON-serialisable — refuse to cache it in redis
            # rather than crash. The facade treats a failed set as a miss.
            return None

    @staticmethod
    def _load(raw: str) -> Optional[CacheEntry]:
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError):
            return None
        value = obj.get("value")
        # Recompute the ETag on read so it's stable across backends and never
        # trusts a stored etag that drifted from the value.
        return CacheEntry(value=value, etag=_make_etag(value), expires_at=0.0)

    # ── CacheBackend surface ────────────────────────────────────────────────

    def get_entry(self, key: str) -> Optional[CacheEntry]:
        client = self._connect()
        if client is None:
            return None
        try:
            raw = client.get(self._k(key))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: redis GET failed (%s); treating as miss", exc)
            return None
        if raw is None:
            return None
        return self._load(raw)

    def set_entry(self, key: str, entry: CacheEntry, ttl: int) -> None:
        client = self._connect()
        if client is None:
            return
        payload = self._dump(entry)
        if payload is None:
            return
        try:
            if ttl > 0:
                client.set(self._k(key), payload, ex=ttl)
            else:
                client.set(self._k(key), payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: redis SET failed (%s); value not cached", exc)

    def delete(self, key: str) -> bool:
        client = self._connect()
        if client is None:
            return False
        try:
            return bool(client.delete(self._k(key)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: redis DEL failed (%s)", exc)
            return False

    def delete_prefix(self, prefix: str) -> int:
        client = self._connect()
        if client is None:
            return 0
        match = self._k(prefix) + "*"
        removed = 0
        try:
            # SCAN + DEL — O(n) over our namespace (see class docstring).
            for raw_key in client.scan_iter(match=match, count=200):
                if client.delete(raw_key):
                    removed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: redis SCAN/DEL failed (%s)", exc)
        return removed

    def iter_keys(self) -> List[str]:
        client = self._connect()
        if client is None:
            return []
        out: List[str] = []
        nslen = len(self._NS)
        try:
            for raw_key in client.scan_iter(match=self._NS + "*", count=200):
                out.append(raw_key[nslen:])
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: redis SCAN failed (%s)", exc)
        return out

    def clear(self) -> None:
        client = self._connect()
        if client is None:
            return
        try:
            for raw_key in client.scan_iter(match=self._NS + "*", count=200):
                client.delete(raw_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: redis clear failed (%s)", exc)

    @property
    def size(self) -> int:
        return len(self.iter_keys())


def _build_backend(backend: Optional[str], redis_url: str) -> CacheBackend:
    """Construct the backend, with graceful fallback to memory.

    `backend` is "memory" | "redis" (case-insensitive). An unknown value, an
    unavailable redis, or a missing `redis` package all resolve to a
    MemoryBackend so the app always has a working cache.
    """
    name = (backend or "memory").strip().lower()
    if name != "redis":
        return MemoryBackend()
    rb = RedisBackend(redis_url)
    if rb.available:
        return rb
    # rb logged its own warning during the failed connect; degrade to memory.
    logger.warning(
        "cache: CACHE_BACKEND=redis requested but redis is unavailable; "
        "using in-process memory backend instead"
    )
    return MemoryBackend()


class AppCache:
    """Thread-safe TTL cache with a pluggable backing store.

    Usage (unchanged from Phase 2d):
        cache.get_or_compute("app_config:quiz.duration_min", ttl=60,
                              loader=lambda: _load_from_db(...))

    The backend is selected at construction:
      - `AppCache()` reads `settings.cache_backend` / `settings.redis_url`.
      - `AppCache(backend="redis", redis_url=...)` forces a backend (tests).

    If redis is selected but unavailable, the constructor degrades to the
    in-process memory backend — the app never fails to boot.
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        redis_url: Optional[str] = None,
    ) -> None:
        # Read settings lazily so importing this module doesn't force a Settings
        # construction order; both args default to the live settings values.
        if backend is None or redis_url is None:
            from app.core.config import settings
            if backend is None:
                backend = settings.cache_backend
            if redis_url is None:
                redis_url = settings.redis_url
        self._backend: CacheBackend = _build_backend(backend, redis_url)

    # ── Introspection of the active backend (diagnostics) ───────────────────

    @property
    def backend_name(self) -> str:
        """'memory' or 'redis' — the *active* backend after fallback."""
        return getattr(self._backend, "name", "memory")

    # ── Reads ──────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[CacheEntry]:
        """Return the entry if present and not expired; else None.

        Does not refresh expired entries — that is `get_or_compute`'s job.
        """
        return self._backend.get_entry(key)

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

        The loader is called outside any lock — a slow DB read does not block
        other keys — but the resulting set is atomic in the backend. A second
        caller that arrived during the load may end up re-running the loader;
        we accept that to avoid holding a lock across IO.
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
        self._backend.set_entry(key, entry, ttl)
        return entry

    def invalidate(self, key: str) -> bool:
        """Drop `key` from the cache. Returns True iff a value was removed.

        Called by the loopback CMS webhook (`modules/cms/routes.py`) on
        Directus writes. Idempotent — invalidating a non-cached key is a
        no-op.
        """
        return self._backend.delete(key)

    def invalidate_prefix(self, prefix: str) -> int:
        """Drop every key starting with `prefix`. Returns the count.

        Useful for collection-wide invalidations (e.g. a feed status flip
        that invalidates every filter that could have included the item).

        On the redis backend this is a SCAN + DEL — O(n) over our namespace;
        see `RedisBackend.delete_prefix`.
        """
        return self._backend.delete_prefix(prefix)

    def clear(self) -> None:
        """Drop every entry. Test helper; do not call in request handlers."""
        self._backend.clear()

    # ── Introspection ──────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return self._backend.size

    def keys(self) -> list[str]:
        return list(self._backend.iter_keys())


# Process-wide singleton. Callers should `from app.core import cache` and use
# `cache.cache.get_or_compute(...)`, or `from app.core.cache import cache`.
# Constructing it here reads settings.cache_backend; with the default
# (memory) this is the exact Phase-2d behaviour, and with CACHE_BACKEND=redis
# it connects redis (or degrades to memory if redis is down).
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
