"""Runbooks — DB access layer.

All writes are idempotent on slug: uploading the same Excel twice updates
the existing row rather than creating a duplicate (upsert semantics).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import Runbook
from app.modules.runbooks.schemas import RunbookCreate

logger = logging.getLogger(__name__)


def upsert_runbook(data: RunbookCreate, created_by: Optional[str] = None) -> Runbook:
    """Insert or update a runbook by slug. Returns the saved ORM object."""
    phases_json = [p.model_dump() for p in data.phases]
    with get_session() as s:
        existing = s.execute(
            select(Runbook).where(Runbook.slug == data.slug)
        ).scalar_one_or_none()

        if existing:
            existing.title = data.title
            existing.role = data.role
            existing.domain = data.domain
            existing.runbook_type = data.type
            existing.description = data.description
            existing.status = data.status
            existing.phases = phases_json
            existing.meta = data.meta
            rb = existing
            logger.info("[runbooks] updated slug=%s", data.slug)
        else:
            rb = Runbook(
                slug=data.slug,
                title=data.title,
                role=data.role,
                domain=data.domain,
                runbook_type=data.type,
                description=data.description,
                status=data.status,
                phases=phases_json,
                meta=data.meta,
                created_by=created_by,
            )
            s.add(rb)
            logger.info("[runbooks] inserted slug=%s", data.slug)

        s.commit()
        s.refresh(rb)
        return rb


def list_runbooks(
    role: Optional[str] = None,
    domain: Optional[str] = None,
    status: str = "published",
    include_draft: bool = False,
) -> List[Runbook]:
    """Return runbooks, optionally filtered by role/domain/status."""
    with get_session() as s:
        q = select(Runbook)
        if not include_draft:
            q = q.where(Runbook.status == status)
        if role:
            q = q.where(Runbook.role == role)
        if domain:
            q = q.where(Runbook.domain == domain)
        q = q.order_by(Runbook.role, Runbook.domain, Runbook.id)
        return list(s.execute(q).scalars().all())


def get_runbook(slug: str) -> Optional[Runbook]:
    """Fetch a single runbook by slug."""
    with get_session() as s:
        return s.execute(
            select(Runbook).where(Runbook.slug == slug)
        ).scalar_one_or_none()


def delete_runbook(slug: str) -> bool:
    """Hard-delete a runbook. Returns True if it existed."""
    with get_session() as s:
        rb = s.execute(
            select(Runbook).where(Runbook.slug == slug)
        ).scalar_one_or_none()
        if not rb:
            return False
        s.delete(rb)
        s.commit()
        return True
