"""Admin role-assignment routes (04 §7.2 — the deferred Q-3 admin-roles REST).

Mounted under `/api/admin` by main.py, so routes register as:

    POST   /api/admin/roles   {email, role_key}   grant a capability role
    DELETE /api/admin/roles   {email, role_key}   revoke a capability role
    GET    /api/admin/roles?email=…               list a user's roles

Every endpoint is gated by `require_permission("role.assign")`, which only
`platform_admin` holds (04 §3 — the role.assign grant set is empty, so the
single global `platform_admin` bypass is the only way in). All writes go through
`core.users` via `modules.admin.storage`, so each grant/revoke writes an
`auth_audit` row naming the acting admin.

Validation failures from `core.users` (unknown role, unknown user, attempting to
revoke the `learner` floor) raise `ValueError`; we translate those to 400 with
the original message so an admin sees exactly what went wrong.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.deps import require_permission
from app.modules.admin import storage as admin_storage


router = APIRouter()


class RoleAssignmentPayload(BaseModel):
    """Body for grant (POST) and revoke (DELETE).

    `email` is a plain string (not pydantic's `EmailStr`) deliberately — the
    backend slice does not pull in the optional `email-validator` dependency,
    and `core.users` already normalises/validates the address against the
    `users` table. Light shape-checking happens in the route.
    """

    email: str
    role_key: str


def _actor_email(admin: dict) -> str:
    """Pull the acting admin's email for the audit trail."""
    return admin.get("email") or "unknown-admin"


@router.post("/roles")
async def grant_role(
    payload: RoleAssignmentPayload,
    admin=Depends(require_permission("role.assign")),
):
    """Grant a capability role to a user. Idempotent.

    Returns `{email, role_key, granted, roles}` where `granted` is False if the
    user already held the role (no new audit row in that case).
    """
    email = str(payload.email).strip().lower()
    try:
        added = admin_storage.grant(email, payload.role_key, actor=_actor_email(admin))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "email": email,
        "role_key": payload.role_key,
        "granted": added,
        "roles": admin_storage.list_roles(email),
    }


@router.delete("/roles")
async def revoke_role(
    payload: RoleAssignmentPayload,
    admin=Depends(require_permission("role.assign")),
):
    """Revoke a capability role from a user. Idempotent.

    The `learner` floor cannot be revoked (core.users enforces this → 400).
    Returns `{email, role_key, revoked, roles}`.
    """
    email = str(payload.email).strip().lower()
    try:
        removed = admin_storage.revoke(email, payload.role_key, actor=_actor_email(admin))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "email": email,
        "role_key": payload.role_key,
        "revoked": removed,
        "roles": admin_storage.list_roles(email),
    }


@router.get("/roles")
async def list_roles(
    email: str = Query(..., description="Email of the user whose roles to list"),
    admin=Depends(require_permission("role.assign")),
):
    """List the capability roles a user holds.

    404 if the email matches no user row (so an admin doesn't reason about a
    typo'd address as though it had only the implicit learner floor).
    """
    email = email.strip().lower()
    if not admin_storage.user_exists(email):
        raise HTTPException(status_code=404, detail=f"No user for {email}")
    return {"email": email, "roles": admin_storage.list_roles(email)}
