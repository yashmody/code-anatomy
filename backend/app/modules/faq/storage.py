"""FAQ database storage functions."""
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.db import get_session
from app.core.models import FAQCategory, FAQItem


def get_all_categories() -> List[Dict[str, Any]]:
    """Retrieve all FAQ categories from the database, calculating question counts."""
    with get_session() as s:
        categories = s.scalars(
            select(FAQCategory).order_by(FAQCategory.id)
        ).all()
        
        result = []
        for c in categories:
            q_count = s.scalar(
                select(func.count(FAQItem.id)).where(FAQItem.category_id == c.id)
            )
            result.append({
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "status": c.status,
                "audience": c.audience,
                "source": c.source,
                "reviewed_at": c.reviewed_at,
                "q_count": q_count or 0
            })
        return result


def get_category_detail(category_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve detail for a single FAQ category including all associated items."""
    with get_session() as s:
        category = s.scalars(
            select(FAQCategory)
            .where(FAQCategory.id == category_id)
            .options(selectinload(FAQCategory.items))
        ).first()
        
        if not category:
            return None
            
        items = sorted(category.items, key=lambda x: x.q_num)
        
        return {
            "category": {
                "id": category.id,
                "title": category.title,
                "description": category.description,
                "status": category.status,
                "audience": category.audience,
                "source": category.source,
                "reviewed_at": category.reviewed_at,
                "q_count": len(items)
            },
            "items": [
                {
                    "id": item.id,
                    "q_num": item.q_num,
                    "question": item.question,
                    "answer": item.answer,
                    "tags": item.tags if isinstance(item.tags, list) else []
                }
                for item in items
            ]
        }
