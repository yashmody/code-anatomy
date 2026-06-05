"""Shared FastAPI dependencies — single source of truth for request-scoped helpers.

Re-exports `require_role` from `core.auth` so every router imports from one
place. Hosts the request-level helpers that were inline in the legacy
monolithic main.py (lines 79-134): `require_user`, `require_user_with_role`,
`refresh_session_user`, and the AES-GCM request/response payload bridges.

The Jinja `_template()` helper deliberately stays in `quiz/routes.py` —
templates are owned by the quiz module (every HTML page is its page).
"""
from typing import Dict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core import config, encryption, users
from app.core.auth import require_role  # re-export — every module imports via core.deps

__all__ = [
    "require_role",
    "require_user",
    "require_user_with_role",
    "refresh_session_user",
    "decrypt_request_payload",
    "encrypt_response_payload",
]


def require_user(request: Request) -> Dict:
    """Return the session user, or raise a 302 to /login."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


def require_user_with_role(request: Request) -> Dict:
    """Like require_user, but also redirect to onboarding if role is unset."""
    user = require_user(request)
    if not user.get("role"):
        raise HTTPException(status_code=302, headers={"Location": "/onboarding/role"})
    return user


def refresh_session_user(request: Request, email: str) -> Dict:
    """Pull fresh user data (incl. role) from the DB into the session."""
    db_user = users.get_user(email) or {}
    session_user = request.session.get("user", {})
    session_user.update({
        "email": db_user.get("email", session_user.get("email")),
        "name": db_user.get("name") or session_user.get("name"),
        "picture": db_user.get("picture") or session_user.get("picture"),
        "role": db_user.get("role"),
        "provider": db_user.get("provider") or session_user.get("provider"),
    })
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
