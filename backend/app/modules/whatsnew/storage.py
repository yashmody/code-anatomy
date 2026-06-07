"""What's New storage — whats_new_items reads/writes.

Service orchestrates; this module owns the small relational surface.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import WhatsNewItem


def source_url_exists(source_url: str) -> bool:
    """Dedup check — has this exact item (by source_url) been ingested before?"""
    with get_session() as s:
        return s.scalar(
            select(WhatsNewItem.id).where(WhatsNewItem.source_url == source_url)
        ) is not None


def insert_item(
    *, id: str, source: str, source_url: str, product: str, title: str,
    summary: Optional[str], related_chapter: Optional[str],
    published_at: Optional[datetime], status: str = "new",
) -> None:
    """Insert one item. Caller guarantees source_url is new (see source_url_exists)."""
    with get_session() as s:
        s.add(WhatsNewItem(
            id=id, source=source, source_url=source_url, product=product,
            title=title, summary=summary, related_chapter=related_chapter,
            published_at=published_at, fetched_at=datetime.utcnow(), status=status,
        ))
        s.commit()


def list_recent(limit: int = 100) -> List[dict]:
    """Recent, visible items as plain dicts (session closed before serialisation).

    Ordered newest-first by published_at then fetched_at. Excludes archived/held.
    """
    with get_session() as s:
        rows = s.execute(
            select(WhatsNewItem)
            .where(WhatsNewItem.status.in_(("new", "published")))
            .order_by(
                WhatsNewItem.published_at.desc().nullslast(),
                WhatsNewItem.fetched_at.desc(),
            )
            .limit(limit)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "source": r.source,
                "product": r.product,
                "title": r.title,
                "summary": r.summary,
                "source_url": r.source_url,
                "related_chapter": r.related_chapter,
                "published_at": r.published_at.isoformat() if r.published_at else None,
            }
            for r in rows
        ]
