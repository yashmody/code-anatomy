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

from app.core.db import get_session
from app.core.models import FeedItem, Question
from app.core.deps import require_role
from app.modules.feed import storage as feed_storage
from app.modules.feed.schemas import FlagFeedPayload, ModActionPayload
from app.modules.quiz import storage as quiz_storage


router = APIRouter()


# ── Feed list / create / flag ────────────────────────────────────────────────

@router.get("/feed")
async def get_feed(request: Request):
    """Retrieve all published feed items."""
    return {"feed": feed_storage.get_feed_items()}


@router.post("/feed/flag")
async def flag_feed_item(
    payload: FlagFeedPayload,
    user=Depends(require_role(["User", "FeedCreator", "Moderator", "QuizManager"])),
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

    return {"status": "success", "flagCount": flag_count, "itemStatus": item.status}


@router.post("/feed")
async def post_feed(
    request: Request,
    item: dict,
    user=Depends(require_role(["FeedCreator"])),
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
    return {"status": "success", "id": item["id"]}


# ── Moderation ───────────────────────────────────────────────────────────────

@router.get("/moderate/queue")
async def get_moderation_queue(user=Depends(require_role(["Moderator"]))):
    """View all items pending review or flagged for removal."""
    return feed_storage.get_moderation_queue()


@router.post("/moderate/action")
async def moderate_action(
    payload: ModActionPayload,
    user=Depends(require_role(["Moderator"])),
):
    """Approve or reject/flag content."""
    action = payload.action.lower()

    if payload.item_type == "feed":
        with get_session() as s:
            item = s.get(FeedItem, payload.item_id)
            if not item:
                raise HTTPException(status_code=404, detail="Feed item not found")
            if action == "approve":
                item.status = "published"
            elif action == "flag":
                item.status = "flagged"
            elif action == "remove":
                item.status = "removed"
            s.commit()

    elif payload.item_type == "question":
        with get_session() as s:
            q = s.get(Question, payload.item_id)
            if not q:
                raise HTTPException(status_code=404, detail="Question not found")
            if action == "approve":
                q.status = "published"
            elif action == "flag":
                q.status = "draft"
            elif action == "remove":
                q.status = "archived"
            s.commit()

    return {"status": "success"}
