"""CMS webhook receiver (Phase 2d).

Per `docs/architecture/v2/05-config-cms.md §7.3`, Directus posts
invalidation events to FastAPI over **loopback only**. Network reachability
*is* the authentication — there is no HMAC, no shared secret, no nonce. The
defence:

1. uvicorn listens on `127.0.0.1`.
2. Apache `<Location "/api/cms/webhook">` is `Require ip 127.0.0.1`.
3. This handler rejects any request whose `request.client.host` is not
   loopback.

The receiver is in place for Phase 2d so that the cache-invalidation seam is
testable end-to-end before Directus actually exists; Phase 4a installs the
sender side. Until Phase 4a, the endpoint is exercised only by operator
curl calls (loopback) and the integration tests.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.core import cache, cms_client, users

router = APIRouter()


# Loopback addresses we accept. IPv4 + IPv6 + the rare ::ffff:127.0.0.1
# stack-translation form.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"})


def _is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    return host in _LOOPBACK_HOSTS


@router.post("/webhook")
async def cms_webhook(request: Request) -> dict:
    """Receive a Directus content/config change event and invalidate caches.

    Expected payload shape (Directus Hooks extension; documented in 4a):

        {
            "collection": "app_config" | "course_chapters" | "frameworks"
                          | "questions" | "feed_items",
            "keys": ["quiz.duration_min", ...]   # primary keys for the collection
        }

    For `app_config` the `keys` array contains the row keys; we invalidate
    `app_config:<key>` for each. For the four content collections we
    invalidate `<collection>:<id>` per id, matching the namespace 06 owns
    for content-cache reads. An empty `keys` array invalidates the whole
    collection prefix (`<collection>:`), since Directus may not include
    keys on bulk operations.
    """
    if request.client is None or not _is_loopback(request.client.host):
        # 403 over 401 because the rejection is policy, not credentials.
        raise HTTPException(status_code=403, detail="loopback only")

    try:
        event = await request.json()
    except Exception as exc:  # noqa: BLE001 — accept any JSON parse failure
        raise HTTPException(status_code=400, detail=f"invalid json: {exc}")

    collection = (event.get("collection") or event.get("table") or "").strip()
    if not collection:
        raise HTTPException(status_code=400, detail="missing collection")

    # Accept either "keys" (Directus standard) or a single "key"/"id".
    raw_keys = event.get("keys")
    if raw_keys is None:
        single = event.get("key") or event.get("id")
        raw_keys = [single] if single else []
    if not isinstance(raw_keys, list):
        raise HTTPException(status_code=400, detail="keys must be a list")

    invalidated = 0
    if collection == "app_config":
        if raw_keys:
            for k in raw_keys:
                if not k:
                    continue
                if cms_client.invalidate(str(k)):
                    invalidated += 1
        else:
            # Bulk wipe — Directus may post a collection-wide event.
            invalidated += cache.invalidate_prefix("app_config:")
    elif collection in ("course_chapters", "frameworks", "questions", "feed_items"):
        if raw_keys:
            for k in raw_keys:
                if not k:
                    continue
                if cache.invalidate(f"{collection}:{k}"):
                    invalidated += 1
        else:
            invalidated += cache.invalidate_prefix(f"{collection}:")
    else:
        # Unknown collection — return ok but invalidate nothing. Directus
        # sometimes posts events for collections we do not cache (e.g.
        # directus_files); silently ignoring is the right move.
        pass

    return {
        "ok": True,
        "collection": collection,
        "keys_seen": len(raw_keys),
        "invalidated": invalidated,
    }


@router.post("/roles-sync")
async def roles_sync(request: Request) -> dict:
    """Reconcile a user's staff roles from a Directus role change (04 §7.2).

    Loopback-only — same "network reachability is the authentication" model as
    `/webhook` (§7.3). The Directus `roles-sync` hook POSTs:

        { "email": "person@deptagency.com", "role": "content_author" | null }

    `role` is the user's *current* Directus staff role (one of
    `content_author` / `quiz_admin` / `feed_moderator` / `platform_admin`), or
    `null` when they hold a non-staff / no role or are deactivated. The
    reconcile is one-way and bounded to the staff roles — `learner` and
    `feed_contributor` are never touched.
    """
    if request.client is None or not _is_loopback(request.client.host):
        # 403 over 401 — rejection is policy, not credentials (matches /webhook).
        raise HTTPException(status_code=403, detail="loopback only")

    try:
        event = await request.json()
    except Exception as exc:  # noqa: BLE001 — accept any JSON parse failure
        raise HTTPException(status_code=400, detail=f"invalid json: {exc}")

    email = (event.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="missing email")

    role = event.get("role")  # staff role key, or null
    if role is not None and not isinstance(role, str):
        raise HTTPException(status_code=400, detail="role must be a string or null")

    try:
        roles = users.sync_staff_roles(email, role or None, actor="directus:roles-sync")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "email": email, "roles": sorted(roles)}


@router.get("/health")
async def cms_health() -> dict:
    """Trivial health endpoint for the CMS seam.

    Reports the in-process cache size so an operator can confirm Phase 2d's
    cache is alive without poking at process state. Safe to call from any
    origin — there is no secret data in the response.
    """
    return {
        "status": "ok",
        "cache_keys": cache.cache.size,
        "app_config_known_keys": len(cms_client.known_keys()),
    }
