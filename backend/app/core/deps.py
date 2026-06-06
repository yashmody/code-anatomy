"""Shared FastAPI dependencies — single source of truth for request-scoped helpers.

v2 Phase 2b ownership:
  - `require_permission(perm)` is the v2 way every route authorises.
  - `require_role(allowed)` is kept as a deprecated shim that maps the four
    legacy capability strings (`User`, `FeedCreator`, `Moderator`,
    `QuizManager`) onto the new permission vocabulary, so any straggler
    import keeps working until 2b's sweep is complete.

Permission vocabulary is the locked matrix from
`docs/architecture/v2/04-authz-model.md` §3 — *this file is the single
runtime source of truth* for it. Any new permission string lands in
`PERMISSION_GRANTS` here, then is referenced from a route. Roles are read
exclusively via `core.users.roles_for(email)`.
"""
from typing import Dict, List, Set

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core import config, encryption, users

__all__ = [
    "PERMISSION_GRANTS",
    "require_permission",
    "require_role",
    "require_user",
    "require_user_with_persona",
    "require_user_with_role",  # backward-compat alias
    "refresh_session_user",
    "decrypt_request_payload",
    "encrypt_response_payload",
]


# ── Locked permission matrix (04-authz-model §3) ─────────────────────────────
#
# permission -> set of roles that hold it (excluding `platform_admin`, the
# implicit global bypass). `learner` is the floor: every authenticated user
# holds it (see `users.roles_for`).
PERMISSION_GRANTS: Dict[str, Set[str]] = {
    "feed.create":     {"feed_contributor"},
    "feed.flag":       {"learner", "feed_contributor", "content_author",
                        "quiz_admin", "feed_moderator"},
    "moderate.view":   {"feed_moderator"},
    "moderate.action": {"feed_moderator", "quiz_admin"},  # quiz_admin for question UGC
    "question.write":  {"quiz_admin"},
    "media.upload":    {"feed_contributor", "content_author"},
    "attempts.view_all": {"quiz_admin"},
    "config.read":     set(),
    "config.write":    set(),
    "role.assign":     set(),
}


# Legacy capability string -> new permission(s) it formerly granted access to.
# Used only by the deprecated `require_role` shim.
_LEGACY_ROLE_TO_PERMISSION = {
    "User":         "feed.flag",
    "FeedCreator":  "feed.create",
    "Moderator":    "moderate.view",
    "QuizManager":  "question.write",
}


def _session_user_or_401(request: Request) -> Dict:
    """Pull session user; raise 401 (JSON) or 302→/login (HTML).

    Break-glass path: if session["superadmin"]["authenticated"] is True, return
    a synthetic user dict with _superadmin=True. This is completely independent
    of the Google OAuth learner plane and bypasses the users table lookup.
    require_permission() treats _superadmin as an unconditional platform_admin.
    """
    # ── Break-glass superadmin path ───────────────────────────────────────────
    sa_session = request.session.get("superadmin")
    if sa_session and sa_session.get("authenticated"):
        return {
            "email":      sa_session["email"],
            "name":       "Superadmin",
            "persona":    None,
            "provider":   "superadmin",
            "_superadmin": True,
        }

    # ── Normal Google OAuth / dev-login path ──────────────────────────────────
    user = request.session.get("user")
    if not user:
        if request.url.path.startswith("/api/") or \
                "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=401, detail="Authentication required")
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid session")
    db_user = users.get_user(email)
    if not db_user:
        raise HTTPException(status_code=403, detail="User account not found")
    return db_user


def require_permission(perm: str):
    """Dependency: require `perm` for the current session user.

    Logic (matches 04-authz-model §3.1 implementation sketch):
      1. Pull the authenticated user (401/redirect if absent).
      2. Read their role set via `users.roles_for(email)` — always contains
         at least `{learner}` for any authenticated user.
      3. `platform_admin` is the single global bypass — checked first.
      4. Otherwise the user must hold a role in `PERMISSION_GRANTS[perm]`.
    """
    if perm not in PERMISSION_GRANTS:
        raise RuntimeError(
            f"require_permission: unknown permission '{perm}' — add it to "
            "PERMISSION_GRANTS in core/deps.py."
        )

    def dependency(request: Request) -> Dict:
        db_user = _session_user_or_401(request)
        # Break-glass superadmin bypasses all permission checks — equivalent to
        # platform_admin without needing a users/user_roles row.
        if db_user.get("_superadmin"):
            return db_user
        held = users.roles_for(db_user["email"])
        if "platform_admin" in held:
            return db_user
        if held & PERMISSION_GRANTS[perm]:
            return db_user
        raise HTTPException(
            status_code=403,
            detail="Operation forbidden: Insufficient permissions",
        )

    return dependency


def require_role(allowed_roles: List[str]):
    """DEPRECATED — backward-compat shim for the legacy capability vocabulary.

    Maps `User`/`FeedCreator`/`Moderator`/`QuizManager` onto the v2
    permission set. New code MUST use `require_permission(<perm>)` directly.

    Allow-any-of-N semantics: a user passes if they satisfy ANY of the
    mapped permissions. `platform_admin` continues to bypass.
    """
    perms = []
    for role in allowed_roles:
        if role in _LEGACY_ROLE_TO_PERMISSION:
            perms.append(_LEGACY_ROLE_TO_PERMISSION[role])
        # Unknown legacy strings (none expected) silently fall through; the
        # platform_admin bypass below still works.

    def dependency(request: Request) -> Dict:
        db_user = _session_user_or_401(request)
        if db_user.get("_superadmin"):
            return db_user
        held = users.roles_for(db_user["email"])
        if "platform_admin" in held:
            return db_user
        for p in perms:
            if held & PERMISSION_GRANTS.get(p, set()):
                return db_user
        raise HTTPException(
            status_code=403,
            detail="Operation forbidden: Insufficient permissions",
        )

    return dependency


# ── Plain session helpers (no permission check) ─────────────────────────────

def require_user(request: Request) -> Dict:
    """Return the session user, or raise a 302 to /login."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


def require_user_with_persona(request: Request) -> Dict:
    """Like require_user, but also redirect to onboarding if persona is unset.

    v2 split: onboarding now collects *persona* (job family, e.g.
    `architect`), not a capability role. Persona drives quiz-level
    recommendation only — see 04-authz-model §5.
    """
    user = require_user(request)
    if not user.get("persona"):
        raise HTTPException(status_code=302, headers={"Location": "/onboarding/role"})
    return user


# Backward-compat alias. Old name preserved for any stragglers; semantics now
# key on persona, not the dead `role` field.
require_user_with_role = require_user_with_persona


def refresh_session_user(request: Request, email: str) -> Dict:
    """Pull fresh user data from the DB into the session.

    The v2 session payload deliberately omits the deprecated `role` field —
    capability is read per-request from `users.roles_for(email)`. `persona`
    is carried so templates and the home/quiz onboarding gates can drive
    quiz-level recommendation without a second DB hit.
    """
    db_user = users.get_user(email) or {}
    session_user = request.session.get("user", {})
    session_user.update({
        "email": db_user.get("email", session_user.get("email")),
        "name": db_user.get("name") or session_user.get("name"),
        "picture": db_user.get("picture") or session_user.get("picture"),
        "persona": db_user.get("persona"),
        "provider": db_user.get("provider") or session_user.get("provider"),
    })
    # Drop any pre-v2 `role` key so downstream code (and templates) cannot
    # read it accidentally.
    session_user.pop("role", None)
    request.session["user"] = session_user
    return session_user


def decrypt_request_payload(request_data: dict, session_key: str = None) -> dict:
    """Decrypt the incoming payload if encrypted using AES-GCM."""
    if "nonce" in request_data and "ciphertext" in request_data:
        try:
            return encryption.decrypt_payload(request_data, session_key)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Payload decryption failed: {e}")
    return request_data


def encrypt_response_payload(response_data: dict, request: Request) -> JSONResponse:
    """Encrypt the outgoing response payload if encryption is requested or active."""
    session_key = request.session.get("payload_key")
    # In prod, we force payload encryption; in dev, only when the client
    # explicitly sets X-Encrypt-Payload: true.
    if session_key and (request.headers.get("X-Encrypt-Payload") == "true" or not config.DEV_MODE):
        encrypted = encryption.encrypt_payload(response_data, session_key)
        return JSONResponse(encrypted)
    return JSONResponse(response_data)
