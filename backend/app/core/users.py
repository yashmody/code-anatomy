"""User helpers — shared across every plane.

Every module (auth, quiz, feed, media, moderation) reads the user table,
so user lookups live in core rather than under any one module's storage.

v2 Phase 2b adds the role-membership read/write helpers
(`roles_for` / `grant_role` / `revoke_role` / `ensure_first_admin`) and
removes the dev-mode auto-elevation that used to hand every local user
`QuizManager`. New users now land with the learner-floor only.

Extracted from the old monolithic app/storage.py:68-114 during v2 Phase 1.
"""
import os
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import select

from app.core import config
from app.core.db import get_session
from app.core.models import AuthAudit, Role, User, UserRole


# Roles known to the runtime. Mirror of the canonical set seeded by the
# 0005_seed_data migration. Used to validate `grant_role(role_key=…)` cheaply
# without a roundtrip when the key is obviously bogus.
KNOWN_ROLE_KEYS = {
    "learner", "feed_contributor", "content_author",
    "quiz_admin", "feed_moderator", "platform_admin",
}


# ── User CRUD ────────────────────────────────────────────────────────────────


def upsert_user(
    email: str,
    name: Optional[str] = None,
    picture: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict:
    """Insert a new user or update display fields on an existing row.

    v2 (Phase 2b): dev auto-elevation is REMOVED. Every new user — dev or
    prod — gets `users.role=None` plus a `user_roles` row for `learner` (the
    runtime floor). Elevated grants are deliberate, via `grant_role` or the
    `ADMIN_EMAILS` seed (see `ensure_first_admin`).
    """
    email = email.strip().lower()
    with get_session() as s:
        u = s.get(User, email)
        is_new = u is None
        if u is None:
            u = User(
                email=email,
                name=name,
                picture=picture,
                provider=provider,
                role=None,         # legacy column — never written by v2 code.
            )
            s.add(u)
        else:
            if name is not None:
                u.name = name
            if picture is not None:
                u.picture = picture
            if provider is not None:
                u.provider = provider
        s.commit()
        s.refresh(u)

        # Ensure the learner floor for every authenticated user.
        _ensure_role_membership(s, email, "learner",
                                granted_by="system:upsert")
        s.commit()

        if is_new:
            _write_audit(
                s,
                actor="system:upsert",
                action="user.create",
                target=email,
                after={"email": email, "provider": provider},
            )
            s.commit()

        return _user_to_dict(u)


def set_user_persona(email: str, persona: str) -> None:
    """Write the user's persona (job family) — drives quiz-level recommendation only."""
    with get_session() as s:
        u = s.get(User, email.lower())
        if u is None:
            raise ValueError(f"No user for {email}")
        u.persona = persona
        s.commit()


def get_user(email: str) -> Optional[Dict]:
    with get_session() as s:
        u = s.get(User, email.lower())
        return _user_to_dict(u) if u else None


def needs_onboarding(email: str) -> bool:
    """True if the user has no persona set. Read by main.py / quiz routes."""
    u = get_user(email)
    return bool(u) and not u.get("persona")


def _user_to_dict(u: User) -> Dict:
    return {
        "email": u.email,
        "name": u.name,
        "picture": u.picture,
        # Legacy capability column. Surfaced for diagnostic/migration callers
        # only; runtime authorisation reads `roles_for(email)` instead.
        "role": u.role,
        "persona": u.persona,
        "provider": u.provider,
        "preferences": u.preferences or {},
    }


# ── Role-membership read ─────────────────────────────────────────────────────


def roles_for(email: str) -> Set[str]:
    """Return the role-key set the user holds. Always includes `learner` for
    any known user (the runtime floor). Returns an empty set for unknown
    emails — callers should have already authenticated the user.
    """
    email = (email or "").strip().lower()
    if not email:
        return set()
    with get_session() as s:
        # Confirm the user exists at all.
        if s.get(User, email) is None:
            return set()
        keys = {
            k for (k,) in s.execute(
                select(Role.key)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_email == email)
            ).all()
        }
        # Belt-and-braces: learner is always implied.
        keys.add("learner")
        return keys


# ── Role-membership writes (audited) ─────────────────────────────────────────


def grant_role(email: str, role_key: str, granted_by: Optional[str] = None) -> bool:
    """Grant a capability role. Idempotent. Returns True if a row was added.

    Audited via `auth_audit`. `granted_by` is the actor email (or a system
    tag like `system:bootstrap`) so the audit trail names a principal.
    """
    email = email.strip().lower()
    if role_key not in KNOWN_ROLE_KEYS:
        raise ValueError(
            f"Unknown role_key '{role_key}'. Known: {sorted(KNOWN_ROLE_KEYS)}"
        )
    with get_session() as s:
        if s.get(User, email) is None:
            raise ValueError(f"No user for {email}")
        added = _ensure_role_membership(s, email, role_key, granted_by=granted_by)
        if added:
            _write_audit(
                s,
                actor=granted_by,
                action="role.grant",
                target=email,
                target_role=role_key,
                after={"role": role_key},
            )
        s.commit()
        return added


def revoke_role(email: str, role_key: str, revoked_by: Optional[str] = None) -> bool:
    """Revoke a capability role. Idempotent. Returns True if a row was removed.

    `learner` cannot be revoked — it is the floor every authenticated user
    holds. Audited.
    """
    email = email.strip().lower()
    if role_key not in KNOWN_ROLE_KEYS:
        raise ValueError(
            f"Unknown role_key '{role_key}'. Known: {sorted(KNOWN_ROLE_KEYS)}"
        )
    if role_key == "learner":
        raise ValueError("Cannot revoke the learner floor — it is implicit.")
    with get_session() as s:
        role = s.execute(select(Role).where(Role.key == role_key)).scalar_one_or_none()
        if role is None:
            return False
        ur = s.execute(
            select(UserRole)
            .where(UserRole.user_email == email)
            .where(UserRole.role_id == role.id)
        ).scalar_one_or_none()
        if ur is None:
            return False
        s.delete(ur)
        _write_audit(
            s,
            actor=revoked_by,
            action="role.revoke",
            target=email,
            target_role=role_key,
            before={"role": role_key},
        )
        s.commit()
        return True


# Staff roles owned by the Directus plane and reconciled by the role mirror
# (04 §7.2). `learner` (the floor) and `feed_contributor` (learner-plane,
# app-owned via /api/admin/roles) are NEVER added or removed by the mirror.
STAFF_ROLE_KEYS = {
    "content_author", "quiz_admin", "feed_moderator", "platform_admin",
}


def sync_staff_roles(
    email: str, role_key: Optional[str], actor: str = "directus:roles-sync",
) -> Set[str]:
    """Reconcile a user's *staff* roles to a single authoritative Directus role.

    The Directus -> FastAPI mirror (04 §7.2). Directus owns the four staff
    roles; `role_key` is the user's current Directus staff role, or None when
    they hold a non-staff / no role or are deactivated.

    One-way + authoritative + bounded to staff: grant `role_key` when it is a
    staff key, and revoke any OTHER staff role the user still holds. `learner`
    and `feed_contributor` are never touched. Idempotent.

    A staff member may never have logged into the app, so there is no `users`
    row for the `user_roles` FK — we create one (provider `directus-mirror`)
    before granting. Returns the user's full role-key set after reconciliation.
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email is required")

    # Only a staff key is a valid target; None/learner/feed_contributor/unknown
    # all mean "this user holds no staff role".
    target = role_key if role_key in STAFF_ROLE_KEYS else None

    # Ensure the FK target exists (grant_role raises "No user for …" otherwise).
    if get_user(email) is None:
        upsert_user(email, provider="directus-mirror")

    held_staff = roles_for(email) & STAFF_ROLE_KEYS
    for stale in held_staff - ({target} if target else set()):
        revoke_role(email, stale, revoked_by=actor)
    if target and target not in held_staff:
        grant_role(email, target, granted_by=actor)

    return roles_for(email)


def ensure_first_admin() -> List[str]:
    """Seed `platform_admin` for every email in the `ADMIN_EMAILS` env var.

    Idempotent. The env var is comma-separated. Returns the list of emails
    that were newly granted (or already held) `platform_admin`. Emails not
    yet present in `users` are skipped — they get the grant the moment they
    sign in (the caller can also wire this into login; today we only run it
    at seed time so admin grants need an existing user row).
    """
    raw = os.getenv("ADMIN_EMAILS", "") or ""
    emails = [e.strip().lower() for e in raw.split(",") if e.strip()]
    if not emails:
        return []
    granted: List[str] = []
    with get_session() as s:
        for email in emails:
            u = s.get(User, email)
            if u is None:
                # No user row yet — defer. (Add a placeholder if you want
                # the grant to land before first login; we deliberately do
                # NOT create empty user rows here.)
                continue
            added = _ensure_role_membership(
                s, email, "platform_admin",
                granted_by="system:ensure_first_admin",
            )
            if added:
                _write_audit(
                    s,
                    actor="system:ensure_first_admin",
                    action="role.grant",
                    target=email,
                    target_role="platform_admin",
                    after={"role": "platform_admin", "source": "ADMIN_EMAILS"},
                )
            granted.append(email)
        s.commit()
    return granted


# ── Internal helpers ─────────────────────────────────────────────────────────


def _ensure_role_membership(
    s, email: str, role_key: str, granted_by: Optional[str] = None,
) -> bool:
    """Add a `user_roles` row if it isn't already present. Returns True if
    inserted. Does NOT commit — the caller owns the transaction boundary.
    """
    role = s.execute(select(Role).where(Role.key == role_key)).scalar_one_or_none()
    if role is None:
        # The roles table is seeded by Alembic 0005; if a key is missing
        # we want a loud error rather than silently dropping the grant.
        raise RuntimeError(
            f"Role '{role_key}' not present in the roles table. "
            "Run `alembic upgrade head` to seed."
        )
    existing = s.execute(
        select(UserRole)
        .where(UserRole.user_email == email)
        .where(UserRole.role_id == role.id)
    ).scalar_one_or_none()
    if existing is not None:
        return False
    s.add(UserRole(user_email=email, role_id=role.id, granted_by=granted_by))
    return True


def _write_audit(
    s,
    actor: Optional[str],
    action: str,
    target: Optional[str] = None,
    target_role: Optional[str] = None,
    before: Optional[Dict] = None,
    after: Optional[Dict] = None,
) -> None:
    """Append an auth_audit row. Caller owns the commit."""
    s.add(AuthAudit(
        actor_email=actor,
        action=action,
        target_email=target,
        target_role=target_role,
        before=before,
        after=after,
    ))
