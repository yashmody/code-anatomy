"""User helpers — shared across every plane.

Every module (auth, quiz, feed, media, moderation) reads the user table,
so user lookups live in core rather than under any one module's storage.

Extracted from the old monolithic app/storage.py:68-114 during v2 Phase 1.
"""
from typing import Dict, Optional

from app.core import config
from app.core.db import get_session
from app.core.models import User


def upsert_user(
    email: str,
    name: Optional[str] = None,
    picture: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict:
    """Insert a new user or update display fields on an existing row.

    In DEV_MODE the first sign-in gets the `QuizManager` role automatically
    so local developers don't have to seed RBAC by hand.
    """
    email = email.strip().lower()
    with get_session() as s:
        u = s.get(User, email)
        if u is None:
            role = "QuizManager" if config.DEV_MODE else None
            u = User(email=email, name=name, picture=picture, provider=provider, role=role)
            s.add(u)
        else:
            if name is not None:
                u.name = name
            if picture is not None:
                u.picture = picture
            if provider is not None:
                u.provider = provider
            if config.DEV_MODE and not u.role:
                u.role = "QuizManager"
        s.commit()
        s.refresh(u)
        return _user_to_dict(u)


def set_user_role(email: str, role: str) -> None:
    with get_session() as s:
        u = s.get(User, email.lower())
        if u is None:
            raise ValueError(f"No user for {email}")
        u.role = role
        s.commit()


def get_user(email: str) -> Optional[Dict]:
    with get_session() as s:
        u = s.get(User, email.lower())
        return _user_to_dict(u) if u else None


def _user_to_dict(u: User) -> Dict:
    return {
        "email": u.email,
        "name": u.name,
        "picture": u.picture,
        "role": u.role,
        "provider": u.provider,
        "preferences": u.preferences or {},
    }
