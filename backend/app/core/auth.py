"""Auth — Google OAuth (production) or dev-mode email entry (development).

v2 Phase 2b hardens the Google flow with:
  - PKCE (RFC 7636) — code_verifier/code_challenge (S256).
  - Per-attempt `state` + `nonce`.
  - id_token verification via `google.oauth2.id_token.verify_oauth2_token`
    (issuer, audience, expiry, signature against Google's JWKS, nonce
    match). Identity is taken from the verified claims, not a second
    userinfo round-trip.
  - Server-side domain enforcement: `email_verified` MUST be true and the
    email domain (and Workspace `hd` claim when present) MUST match
    `ALLOWED_DOMAIN` in non-dev.
  - A short-lived signed pre-auth cookie (`aoc_preauth`) carrying the
    verifier/state/nonce across the OAuth round-trip — separate from the
    long-lived session cookie. itsdangerous serializer, 5-minute max-age,
    HttpOnly, SameSite=Lax, Secure outside DEV.

The legacy `require_role` shim lives in `core/deps.py` for backward-compat
during the 2b sweep. New routes import `require_permission` from there.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core import config


# ── Domain / name helpers ────────────────────────────────────────────────────

def is_allowed_email(email: str) -> bool:
    """Domain restriction. Fail-CLOSED in non-dev when `ALLOWED_DOMAIN` is
    empty (the legacy fail-open default is gone). Dev still accepts any
    domain when the config is empty.
    """
    if not email or "@" not in email:
        return False
    domain = email.split("@", 1)[1].lower()
    allowed = (config.ALLOWED_DOMAIN or "").lower()
    if not allowed:
        # In dev, blank ALLOWED_DOMAIN means no restriction (parity with v1).
        # In prod, treat empty as a hard deny — this is fail-closed.
        return bool(config.DEV_MODE)
    return domain == allowed


def derive_name(email: str) -> str:
    """Best-effort display name from email if Google name isn't available."""
    local = email.split("@")[0]
    parts = [p for p in local.replace("_", ".").split(".") if p]
    return " ".join(p.capitalize() for p in parts) if parts else email


# ── PKCE + state / nonce ─────────────────────────────────────────────────────

def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> Tuple[str, str]:
    """Return `(code_verifier, code_challenge)` per RFC 7636 S256.

    Verifier: 64 url-safe bytes (well within RFC's 43–128 char window).
    Challenge: base64url(SHA256(verifier)), no padding.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = _b64url_no_pad(digest)
    return verifier, challenge


def make_state() -> str:
    return secrets.token_urlsafe(24)


def make_nonce() -> str:
    return secrets.token_urlsafe(24)


# ── Pre-auth cookie ──────────────────────────────────────────────────────────

# Cookie name and lifetime are documented in 04-authz-model §6.1.
PREAUTH_COOKIE = "aoc_preauth"
PREAUTH_MAX_AGE = 300  # 5 minutes — only covers the OAuth round-trip
PREAUTH_PATH = "/auth/"  # cookie scoped to OAuth endpoints only
_PREAUTH_SALT = "aoc-preauth-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=config.SECRET_KEY, salt=_PREAUTH_SALT)


def pack_preauth(state: str, nonce: str, code_verifier: str) -> str:
    """Sign `{state, nonce, code_verifier}` into the pre-auth cookie value."""
    return _serializer().dumps({"s": state, "n": nonce, "v": code_verifier})


def unpack_preauth(token: Optional[str]) -> Optional[Dict[str, str]]:
    """Read+verify the pre-auth cookie. Returns the payload dict or None on
    signature / expiry failure. Never raises — callers treat None as "no
    valid pre-auth state, restart the flow".
    """
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=PREAUTH_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    if not all(k in data for k in ("s", "n", "v")):
        return None
    return {"state": data["s"], "nonce": data["n"], "code_verifier": data["v"]}


# ── Google OAuth (used when DEV_MODE=false) ──────────────────────────────────

_GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


def google_authorize_url(state: str, code_challenge: str, nonce: str) -> str:
    """Build the Google OAuth authorization URL with PKCE + nonce."""
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "hd": config.ALLOWED_DOMAIN,  # workspace hint (still verified server-side)
        "prompt": "select_account",
    }
    return f"{_GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_user(
    code: str, code_verifier: str, nonce: str,
) -> Optional[Dict[str, Any]]:
    """Exchange an OAuth `code` for the user's profile, verifying the
    returned `id_token` end-to-end.

    Returns `{email, name, picture}` on success, or None if any step fails
    (token exchange, JWT verification, domain check). All failure modes
    funnel through None — callers redirect to /login?error=…
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests not installed — `pip install requests`")

    # Lazy-import so dev installations without google-auth still boot the
    # app; the import only fires on a real Google login attempt.
    try:
        from google.oauth2 import id_token as google_id_token  # type: ignore
        from google.auth.transport import requests as google_requests  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-auth not installed — `pip install google-auth`. "
            f"(import error: {e})"
        )

    # 1. POST the code exchange with the PKCE verifier.
    token_resp = requests.post(
        _GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": config.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        timeout=20,
    )
    if token_resp.status_code != 200:
        return None
    tok = token_resp.json()
    id_token_str = tok.get("id_token")
    if not id_token_str:
        return None

    # 2. Verify the id_token (signature against Google's JWKS, issuer,
    #    audience, expiry). `verify_oauth2_token` raises on failure.
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            audience=config.GOOGLE_CLIENT_ID,
        )
    except Exception:
        return None

    if claims.get("iss") not in _GOOGLE_ISSUERS:
        return None
    if claims.get("aud") != config.GOOGLE_CLIENT_ID:
        return None
    if claims.get("nonce") != nonce:
        return None

    # 3. Identity comes from the verified claims — no second userinfo call.
    email = claims.get("email")
    if not email:
        return None
    if not claims.get("email_verified", False):
        return None
    if not is_allowed_email(email):
        return None

    # 4. Workspace `hd` claim — when ALLOWED_DOMAIN is set, demand the
    #    Google Workspace hint matches in non-dev environments. (Google
    #    only sets `hd` for managed Workspace accounts; consumer accounts
    #    don't, which is fine because they fail the email-domain check
    #    above.)
    if not config.DEV_MODE and config.ALLOWED_DOMAIN:
        hd = claims.get("hd")
        if hd and hd.lower() != config.ALLOWED_DOMAIN.lower():
            return None

    return {
        "email": email,
        "name": claims.get("name") or derive_name(email),
        "picture": claims.get("picture"),
    }


# ── Deprecated re-exports ────────────────────────────────────────────────────

# `core.deps` is now the single import path for permission/role helpers.
# Keep the names importable from this module too so any straggling caller
# (e.g. tests) keeps working through the cutover.
from app.core.deps import require_role  # noqa: E402,F401
