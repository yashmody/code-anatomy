"""Auth-module storage — auth_audit writes + (admin-only) audit reads.

The role-membership writes themselves live in `core/users.py` (since every
plane reads/writes the same table). This module is the seam for *audit*
events that the auth module emits: login success, logout, dev-mode login,
and any future SSO event class (failed-state, replay-detect, …).

Read side (`list_audit`) is admin-only — guarded by the route layer, not
here.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select

from app.core.db import get_session
from app.core.models import AuthAudit


def write_audit(
    actor: Optional[str],
    action: str,
    target: Optional[str] = None,
    target_role: Optional[str] = None,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> None:
    """Append an `auth_audit` row.

    `actor` is the email of whoever caused the event (or a `system:…` tag
    for system actions). All fields except `action` are optional.
    """
    with get_session() as s:
        s.add(AuthAudit(
            actor_email=actor,
            action=action,
            target_email=target,
            target_role=target_role,
            before=before,
            after=after,
        ))
        s.commit()


def list_audit(
    limit: int = 100,
    action_prefix: Optional[str] = None,
    target: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read the most recent audit rows. Admin-only — gate at the route.

    Filters are optional and AND-combined. Returns dicts (not ORM rows) so
    callers don't need to manage the session.
    """
    with get_session() as s:
        q = select(AuthAudit).order_by(desc(AuthAudit.occurred_at))
        if action_prefix:
            q = q.where(AuthAudit.action.like(f"{action_prefix}%"))
        if target:
            q = q.where(AuthAudit.target_email == target.lower())
        q = q.limit(max(1, min(limit, 1000)))
        return [_row_to_dict(r) for r in s.execute(q).scalars().all()]


def _row_to_dict(r: AuthAudit) -> Dict[str, Any]:
    return {
        "id": r.id,
        "actor_email": r.actor_email,
        "action": r.action,
        "target_email": r.target_email,
        "target_role": r.target_role,
        "before": r.before,
        "after": r.after,
        "occurred_at": _iso(r.occurred_at),
    }


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None
