"""Admin storage — a thin pass-through to `core.users`.

The role-assignment writer already lives in `core.users` (the single audited
writer of `user_roles`, per 04 §7.1). This module deliberately holds no SQL of
its own: it forwards to `core.users.grant_role` / `revoke_role` / `roles_for`
so there is exactly one place that mutates capability membership and one place
that writes `auth_audit`. Keeping the seam here (rather than calling
`core.users` straight from the route) lets the route stay HTTP-only and gives
us a place to add admin-specific read shaping later without touching core.
"""
from __future__ import annotations

from typing import List, Optional

from app.core import users as core_users


def grant(email: str, role_key: str, actor: Optional[str]) -> bool:
    """Grant `role_key` to `email`. Returns True if a new grant was written.

    Raises ValueError for an unknown role or an unknown user (surfaced as a
    400 by the route).
    """
    return core_users.grant_role(email, role_key, granted_by=actor)


def revoke(email: str, role_key: str, actor: Optional[str]) -> bool:
    """Revoke `role_key` from `email`. Returns True if a grant was removed.

    Raises ValueError for an unknown role or for `learner` (the floor, which
    cannot be revoked).
    """
    return core_users.revoke_role(email, role_key, revoked_by=actor)


def list_roles(email: str) -> List[str]:
    """Return the sorted role-key set the user holds (always includes learner).

    Returns an empty list for an unknown email — the route turns that into a
    404 so an admin doesn't silently grant against a typo'd address.
    """
    return sorted(core_users.roles_for(email))


def user_exists(email: str) -> bool:
    """True iff a user row exists for `email`."""
    return core_users.get_user(email) is not None
