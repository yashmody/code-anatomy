"""Tier-2 config reader (Phase 2d).

A thin typed reader over the `app_config` table — per
`docs/architecture/v2/05-config-cms.md §7.2`. Caching is delegated to
`app.core.cache` so the read-path stays uniform with Tier-3 content reads;
this module only knows how to *load one row* and *name its cache key*.

Read-path:

    cfg("quiz.duration_min")
        │
        ▼
    cache.get_or_compute(
        "app_config:quiz.duration_min",
        ttl=settings.cache_ttl_app_config,   # 60s by default
        loader=lambda: _load_from_db("quiz.duration_min"),
    )
        │ (miss)
        ▼
    SELECT value, value_type FROM app_config WHERE key = :k
        │
        ▼
    _coerce(value, value_type)  →  return

Invalidation is fired from `modules/cms/routes.py` on the loopback Directus
webhook — `cache.invalidate("app_config:" + key)`.

Fallback: if the DB row is absent **and** the key has a compiled-in default
in `DEFAULTS`, return that default. If neither exists, raise `KeyError`. This
preserves "empty `app_config` table behaves like today's hardcoded defaults"
(05 §2.1).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core import cache, config, db
from app.core.models import AppConfig


# ─────────────────────────────────────────────────────────────────────────────
# Compiled-in fallback defaults
# Per 05 §2.1. These are the values today's hardcoded constants resolve to;
# they exist so that a fresh DB (with an empty app_config table) renders
# byte-identically to the v1 build.
# ─────────────────────────────────────────────────────────────────────────────


DEFAULTS: dict[str, Any] = {
    # Quiz behaviour
    "quiz.cooldown_days":            7,
    "quiz.duration_min":             45,
    "quiz.questions_per_quiz":       30,
    "quiz.pass_mark_correct":        25,
    # Media limits
    "media.max_video_size_mb":       30,
    "media.max_image_size_mb":       2.5,
    "media.max_video_duration_sec":  60,
    # Feed moderation
    "feed.flag_threshold":           1,
    "feed.require_review_on_post":   True,
    # Auth
    "auth.allowed_domain":           "deptagency.com",
    # Mail
    "mail.from_email":               "no-reply@deptagency.com",
    "mail.from_name":                "DEPT® Academy",
    # Feature flags
    "features.llm.enabled":          False,
    "features.llm.quiz_explainer":   False,
    "features.llm.feed_summary":     False,
    # LLM model selection
    "llm.provider":                  "none",
    "llm.model":                     "",
    "llm.temperature":               0.2,
    # Environment label (display only)
    "env.label":                     "development",
}


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


# Sentinel so we can distinguish "row absent" from "row exists with value None".
_MISSING = object()


def _coerce(value: Any, value_type: str) -> Any:
    """Cast a DB-stored value into its declared type.

    `app_config.value` is JSONB on Postgres (SQLite JSON shim falls back to
    JSON-as-text). Most types come back already-coerced; we belt-and-brace
    the int/bool/float branches because a JSON value of `"42"` (string)
    should not silently survive.
    """
    if value is None:
        return None
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)
    if value_type == "string":
        return str(value)
    # 'json' (or anything else) — pass through unchanged.
    return value


def _load_from_db(key: str) -> Any:
    """SQL loader called on cache miss. Returns the value or _MISSING."""
    session = db.get_session()
    try:
        row = session.execute(
            select(AppConfig).where(AppConfig.key == key)
        ).scalar_one_or_none()
        if row is None:
            return _MISSING
        return _coerce(row.value, row.value_type)
    finally:
        session.close()


def _cache_key(key: str) -> str:
    return "app_config:" + key


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def cfg(key: str) -> Any:
    """Read a Tier-2 config value through the shared cache.

    Resolution order:
      1. Cached value (TTL window per `settings.cache_ttl_app_config`).
      2. `app_config` DB row (if present).
      3. `DEFAULTS[key]` (compiled-in fallback).
      4. Raise `KeyError(key)` if no default exists.

    Note that step 1 caches the *resolved* result — including the
    DEFAULT-fallback path — so a missing-row lookup is itself cheap on
    repeat calls. Webhook-driven invalidation works exactly the same: an
    operator adding a row to Directus fires the webhook, the cache drops
    the key, and the next read goes back to the DB.
    """
    ttl = config.settings.cache_ttl_app_config

    def _resolve() -> Any:
        loaded = _load_from_db(key)
        if loaded is not _MISSING:
            return loaded
        if key in DEFAULTS:
            return DEFAULTS[key]
        raise KeyError(key)

    return cache.get_or_compute(_cache_key(key), ttl=ttl, loader=_resolve)


def invalidate(key: str) -> bool:
    """Drop the cached entry for `key`. Mirrors `cache.invalidate`.

    Re-exported here so `modules/cms/routes.py` and admin scripts can
    `from app.core import cms_client; cms_client.invalidate("quiz.…")`
    without depending on the lower-level cache module directly.
    """
    return cache.invalidate(_cache_key(key))


def known_keys() -> list[str]:
    """Return the union of DEFAULTS keys + any in-flight cached keys.

    Used by ops scripts and the `/api/cms/health` endpoint.
    """
    cached = [k[len("app_config:"):] for k in cache.cache.keys() if k.startswith("app_config:")]
    return sorted(set(DEFAULTS) | set(cached))
