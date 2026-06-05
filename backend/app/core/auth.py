"""Auth — Google OAuth (production) or dev-mode email entry (development).

In DEV_MODE, any @ALLOWED_DOMAIN email is accepted on a simple form.
In production, Google OAuth via Authlib, with the same domain check applied
to the returned profile.

Includes lightweight RBAC dependencies checking Postgres dynamically.
"""
from typing import Optional, List
from urllib.parse import urlencode
import secrets
from fastapi import Request, HTTPException

from app.core import config
from app.core import users


def is_allowed_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@", 1)[1].lower()
    allowed = config.ALLOWED_DOMAIN.lower()
    if not allowed:  # empty means no domain restriction
        return True
    return domain == allowed


def derive_name(email: str) -> str:
    """Best-effort display name from email if Google name isn't available."""
    local = email.split("@")[0]
    # firstname.lastname → Firstname Lastname
    parts = [p for p in local.replace("_", ".").split(".") if p]
    return " ".join(p.capitalize() for p in parts) if parts else email


# --- Google OAuth (used when DEV_MODE=false) ---

_GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def google_authorize_url(state: str) -> str:
    """Build the Google OAuth authorization URL."""
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "hd": config.ALLOWED_DOMAIN,  # hint to Google to restrict to this hosted domain
        "prompt": "select_account",
    }
    return f"{_GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_user(code: str) -> Optional[dict]:
    """Exchange an OAuth code for the user's profile.

    Requires `requests` (in requirements). Falls back to httpx if needed.
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests not installed — `pip install requests`")

    token_resp = requests.post(
        _GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": config.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if token_resp.status_code != 200:
        return None
    access_token = token_resp.json().get("access_token")
    if not access_token:
        return None
    info = requests.get(
        _GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if info.status_code != 200:
        return None
    profile = info.json()
    email = profile.get("email")
    if not email or not is_allowed_email(email):
        return None
    return {
        "email": email,
        "name": profile.get("name") or derive_name(email),
        "picture": profile.get("picture"),
    }


def make_state() -> str:
    return secrets.token_urlsafe(24)


# --- RBAC Dependency ---

def require_role(allowed_roles: List[str]):
    """Dynamic role checker extracting user from session and verifying role in DB."""
    def dependency(request: Request) -> dict:
        user = request.session.get("user")
        if not user:
            # For JSON/API requests, return a JSON 401 instead of redirecting
            if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                raise HTTPException(status_code=401, detail="Authentication required")
            raise HTTPException(status_code=302, headers={"Location": "/login"})
            
        email = user.get("email")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid session")
            
        # Dynamic Postgres lookup
        db_user = users.get_user(email)
        if not db_user:
            raise HTTPException(status_code=403, detail="User account not found")
            
        user_role = db_user.get("role") or "User"
        
        # Admin / QuizManager bypasses all role checks
        if user_role == "QuizManager":
            return db_user
            
        if user_role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Operation forbidden: Insufficient permissions")
            
        return db_user
    return dependency
