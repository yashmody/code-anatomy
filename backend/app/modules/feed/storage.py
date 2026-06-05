"""Feed storage — feed_items table CRUD + moderation queue.

The moderation queue reads BOTH feed_items and questions; per the 01-blueprint
storage-split map (§2.4), it lives here (feed-owned) and imports the Question
model from core.models. Cross-module *reads* via shared models are allowed;
cross-module *writes* go through the owning module's service.
"""
from typing import Dict, List

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import FeedItem, Question
from app.modules.quiz.storage import question_to_dict


def save_feed_item(item: Dict) -> str:
    fid = item["id"]
    with get_session() as s:
        existing = s.get(FeedItem, fid)
        author_id = item.get("author", {}).get("userId")
        if author_id and "@" not in author_id:
            author_id = f"{author_id}@deptagency.com"

        if existing:
            existing.status = item.get("status", existing.status)
            existing.data = item
        else:
            new_item = FeedItem(
                id=fid,
                type=item["type"],
                status=item.get("status", "published"),
                author_id=author_id.lower() if author_id else None,
                framework_ref=item.get("frameworkRef"),
                topics=item.get("topics", []),
                data=item
            )
            s.add(new_item)
        s.commit()
        return fid


def get_feed_items() -> List[Dict]:
    with get_session() as s:
        rows = s.scalars(
            select(FeedItem).where(FeedItem.status.in_(["published", "flagged"]))
                            .order_by(FeedItem.created_at.desc())
        ).all()
        return [r.data for r in rows]


def get_moderation_queue() -> Dict[str, List[Dict]]:
    """Retrieve all flagged or pending moderation items — feed AND questions."""
    with get_session() as s:
        feed_rows = s.scalars(
            select(FeedItem).where(FeedItem.status.in_(["pending_review", "flagged"]))
                            .order_by(FeedItem.created_at.desc())
        ).all()
        question_rows = s.scalars(
            select(Question).where(Question.status.in_(["pending_review", "draft"]))
                           .order_by(Question.created_at.desc())
        ).all()

        return {
            "feed_items": [r.data for r in feed_rows],
            "questions": [question_to_dict(q) for q in question_rows]
        }
