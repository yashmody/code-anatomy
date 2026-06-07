"""Feed routes — list/create/flag feed items + moderation queue + actions.

Mounted under `/api` by main.py, so routes register as `/api/feed`,
`/api/feed/flag`, `/api/moderate/queue`, `/api/moderate/action`.

Scenario-typed feed items fan out into the question bank as
`pending_review` rows that a Moderator must approve before they hit the
quiz pool. That fan-out lives inline here today; the service.py extraction
is a Phase 2 follow-up (kept inline now to land Slice A without changing
behaviour).
"""
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import config
from app.core.cache import cache
from app.core.db import get_session
from app.core.models import FeedItem, Question
from app.core.deps import require_permission
from app.modules.feed import storage as feed_storage
from app.modules.feed.schemas import FlagFeedPayload, ModActionPayload
from app.modules.quiz import storage as quiz_storage
from app.modules.auth.storage import write_audit


router = APIRouter()


# ── Feed list / create / flag ────────────────────────────────────────────────

@router.get("/feed")
async def get_feed(request: Request):
    """Retrieve all published feed items."""
    # The published feed is the single hottest read (every feed mount hits it).
    # Memoise it for cache_ttl_feed (default 30s) under the `feed_items:` prefix
    # so the write paths below — and the Directus webhook — drop it on change.
    # The short TTL keeps the UGC stream fresh even if an invalidation is missed.
    feed = cache.get_or_compute(
        "feed_items:published",
        ttl=config.settings.cache_ttl_feed,
        loader=feed_storage.get_feed_items,
    )
    return {"feed": feed}


@router.post("/feed/flag")
async def flag_feed_item(
    payload: FlagFeedPayload,
    user=Depends(require_permission("feed.flag")),
):
    """Flag a feed item by incrementing its flag count. Marks as flagged if it reaches threshold."""
    with get_session() as s:
        item = s.get(FeedItem, payload.item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Feed item not found")

        item_data = dict(item.data)
        moderation = item_data.get("moderation", {})
        flag_count = moderation.get("flagCount", 0) + 1

        moderation["flagCount"] = flag_count
        item_data["moderation"] = moderation

        # Auto flag if threshold is reached
        if flag_count >= 1:
            item.status = "flagged"
            item_data["status"] = "flagged"

        item.data = item_data
        s.commit()

    # A flag can flip status to "flagged", changing what the published feed
    # list returns — drop the cached list so the change is visible at once.
    cache.invalidate_prefix("feed_items:")

    return {"status": "success", "flagCount": flag_count, "itemStatus": item.status}


@router.post("/feed")
async def post_feed(
    request: Request,
    item: dict,
    user=Depends(require_permission("feed.create")),
):
    """Create a new feed item. If type is 'scenario', registers it as a pending quiz question."""
    if "id" not in item:
        item["id"] = f"post.{secrets.token_hex(4)}"
    item["createdAt"] = datetime.utcnow().isoformat() + "Z"
    item["status"] = "published"  # defaults to published for FeedCreators

    # Scenarios fan out into the question bank — Moderator must approve
    # before the question hits the quiz pool.
    if item.get("type") == "scenario":
        payload = item.get("scenario", {})
        question_data = {
            "id": f"q.ugc.{item['id']}",
            "topic": item.get("topics", ["general"])[0],
            "difficulty": "intermediate",  # default for UGC scenarios
            "question": payload.get("prompt", "Scenario prompt missing"),
            "options": payload.get("options", []),
            "correct_index": payload.get("correct", 0),
            "explanation": payload.get("reveal", ""),
            "status": "pending_review",  # needs Moderator approval
            "author_id": user["email"],
            "is_user_submitted": True,
        }
        quiz_storage.save_question(question_data)
        item["status"] = "pending-review"  # force post state if containing a question

    feed_storage.save_feed_item(item)
    # New post → invalidate the cached published list so the author (and
    # everyone else) sees it immediately rather than after a TTL window.
    cache.invalidate_prefix("feed_items:")
    return {"status": "success", "id": item["id"]}


# ── Moderation ───────────────────────────────────────────────────────────────

@router.get("/moderate/queue")
async def get_moderation_queue(user=Depends(require_permission("moderate.view"))):
    """View all items pending review or flagged for removal."""
    return feed_storage.get_moderation_queue()


@router.post("/moderate/action")
async def moderate_action(
    payload: ModActionPayload,
    user=Depends(require_permission("moderate.action")),
):
    """Approve or reject/flag content."""
    action = payload.action.lower()
    actor = user.get("email") if isinstance(user, dict) else None
    before_status = after_status = None

    if payload.item_type == "feed":
        with get_session() as s:
            item = s.get(FeedItem, payload.item_id)
            if not item:
                raise HTTPException(status_code=404, detail="Feed item not found")
            before_status = item.status
            if action == "approve":
                item.status = "published"
            elif action == "flag":
                item.status = "flagged"
            elif action == "remove":
                item.status = "removed"
            after_status = item.status
            s.commit()
        # The status flip changes what the feed list / moderation queue return.
        # This write lands in the FastAPI plane, bypassing the Directus
        # cache-invalidation webhook, so we invalidate the same `feed_items:`
        # prefix the webhook uses (modules/cms/routes.py) to keep reads fresh.
        cache.invalidate_prefix("feed_items:")

    elif payload.item_type == "question":
        with get_session() as s:
            q = s.get(Question, payload.item_id)
            if not q:
                raise HTTPException(status_code=404, detail="Question not found")
            before_status = q.status
            if action == "approve":
                q.status = "published"
            elif action == "flag":
                q.status = "draft"
            elif action == "remove":
                q.status = "archived"
            after_status = q.status
            s.commit()
        # Same rationale as feed above — invalidate the `questions:` prefix so
        # the quiz pool / moderation queue see the new status immediately.
        cache.invalidate_prefix("questions:")

    # Audit the moderation decision (V2-F-05). Best-effort: the status change is
    # the primary effect, so an audit hiccup must never 500 the action. Role
    # grants + logins are already audited; this closes the moderation gap.
    try:
        write_audit(
            actor=actor,
            action=f"moderate.{payload.item_type}.{action}",
            target=payload.item_id,
            before={"status": before_status},
            after={"status": after_status},
        )
    except Exception as exc:  # noqa: BLE001 — audit is secondary to the action
        import logging
        logging.getLogger("app.moderate").warning("audit write failed: %s", exc)

    return {"status": "success"}
