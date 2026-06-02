"""Storage layer — SQLAlchemy-backed.

Same surface area as the old JSON-file implementation:
  save_attempt(record)               → persists and returns the test_code
  attempts_for(email)                → list of attempt dicts, newest first
  last_attempt(email)                → most recent attempt dict or None
  cooldown_remaining_days(email)     → int days still in cool-down
  has_passed(email)                  → True if any passing attempt
  all_attempts()                     → every attempt across users (admin)

User-specific helpers added for the role onboarding flow:
  upsert_user(email, name, picture, provider)
  set_user_role(email, role)
  get_user(email)

Records returned from attempt-reading helpers are plain dicts (the same shape
as before) so templates and review.py keep working without changes.
"""
import secrets
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select

from . import config
from .db import get_session, init_db  # noqa: F401 — re-export init_db
from .models import Attempt, User

# Confusable-free alphabet for human-readable test codes (no 0/O/1/I)
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ---------- test code ----------

def generate_test_code() -> str:
    """Format: AOC-YYYYMMDD-XXXXXX. Loop until unique (collisions vanishingly rare)."""
    date_part = datetime.utcnow().strftime("%Y%m%d")
    with get_session() as s:
        for _ in range(8):
            rand = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
            code = f"AOC-{date_part}-{rand}"
            if s.scalar(select(Attempt).where(Attempt.test_code == code)) is None:
                return code
    # Falling out of the loop would be astronomical — fail loudly if it ever does
    raise RuntimeError("Could not generate a unique test code after 8 tries")


# ---------- user helpers ----------

def upsert_user(email: str, name: Optional[str] = None, picture: Optional[str] = None,
                provider: Optional[str] = None) -> Dict:
    email = email.strip().lower()
    with get_session() as s:
        u = s.get(User, email)
        if u is None:
            u = User(email=email, name=name, picture=picture, provider=provider)
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
    }


# ---------- attempt save + read ----------

def save_attempt(record: Dict) -> str:
    """Persist a graded attempt. `record` carries the legacy dict shape used
    by main.py — user, quiz_id, difficulty, score, etc. plus questions and
    user_answers in the payload. Returns the test_code.

    If the record already has a test_code (re-save with cert path), update
    the existing row instead of inserting a duplicate.
    """
    email = record["user"]["email"].lower()
    existing_code = record.get("test_code")

    with get_session() as s:
        # Ensure user exists (in case save_attempt is hit without a prior upsert)
        if s.get(User, email) is None:
            s.add(User(
                email=email,
                name=record["user"].get("name"),
                picture=record["user"].get("picture"),
                provider=record["user"].get("provider"),
            ))

        att: Optional[Attempt] = None
        if existing_code:
            att = s.scalar(select(Attempt).where(Attempt.test_code == existing_code))

        if att is None:
            att = Attempt(
                test_code=existing_code or _generate_unique_code(s),
                quiz_id=record["quiz_id"],
                user_email=email,
                difficulty=record["difficulty"],
                score=float(record["score"]),
                correct=int(record["correct"]),
                total=int(record["total"]),
                passed=bool(record["passed"]),
                started_at=_parse_iso(record["started_at"]),
                submitted_at=_parse_iso(record["submitted_at"]),
                cert_id=record.get("cert_id"),
                certificate_path=record.get("certificate_path"),
                payload={
                    "questions": record.get("questions", []),
                    "user_answers": record.get("user_answers", {}),
                    "grading": record.get("grading", {}),
                },
            )
            s.add(att)
        else:
            # Update mutable fields (cert path on second save after PDF generation)
            att.cert_id = record.get("cert_id") or att.cert_id
            att.certificate_path = record.get("certificate_path") or att.certificate_path

        s.commit()
        return att.test_code


def _generate_unique_code(session) -> str:
    """In-session version of generate_test_code that reuses an open session."""
    date_part = datetime.utcnow().strftime("%Y%m%d")
    for _ in range(8):
        rand = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        code = f"AOC-{date_part}-{rand}"
        if session.scalar(select(Attempt).where(Attempt.test_code == code)) is None:
            return code
    raise RuntimeError("Could not generate a unique test code after 8 tries")


def attempts_for(email: str) -> List[Dict]:
    email = email.strip().lower()
    with get_session() as s:
        rows = s.scalars(
            select(Attempt).where(Attempt.user_email == email)
                           .order_by(Attempt.submitted_at.desc())
        ).all()
        return [_attempt_to_dict(a) for a in rows]


def last_attempt(email: str) -> Optional[Dict]:
    a = attempts_for(email)
    return a[0] if a else None


def cooldown_remaining_days(email: str) -> int:
    last = last_attempt(email)
    if not last or last["passed"]:
        return 0
    try:
        ts = datetime.fromisoformat(last["submitted_at"].replace("Z", ""))
    except (ValueError, KeyError):
        return 0
    elapsed = (datetime.utcnow() - ts).days
    return max(0, config.COOLDOWN_DAYS - elapsed)


def has_passed(email: str) -> bool:
    email = email.strip().lower()
    with get_session() as s:
        row = s.scalar(
            select(Attempt).where(Attempt.user_email == email, Attempt.passed.is_(True)).limit(1)
        )
        return row is not None


def all_attempts() -> List[Dict]:
    with get_session() as s:
        rows = s.scalars(select(Attempt).order_by(Attempt.submitted_at.desc())).all()
        return [_attempt_to_dict(a) for a in rows]


def attempt_by_cert_id(cert_id: str) -> Optional[Dict]:
    with get_session() as s:
        a = s.scalar(select(Attempt).where(Attempt.cert_id == cert_id))
        return _attempt_to_dict(a) if a else None


# ---------- helpers ----------

def _attempt_to_dict(a: Attempt) -> Dict:
    """Render an Attempt row in the shape main.py + templates expect."""
    payload = a.payload or {}
    return {
        "test_code": a.test_code,
        "cert_id": a.cert_id,
        "quiz_id": a.quiz_id,
        "user": {"email": a.user_email, "name": a.user.name if a.user else None},
        "difficulty": a.difficulty,
        "score": a.score,
        "correct": a.correct,
        "total": a.total,
        "passed": a.passed,
        "started_at": a.started_at.isoformat() + "Z",
        "submitted_at": a.submitted_at.isoformat() + "Z",
        "certificate_path": a.certificate_path,
        "questions": payload.get("questions", []),
        "user_answers": payload.get("user_answers", {}),
        "grading": payload.get("grading", {}),
    }


def _parse_iso(s: str) -> datetime:
    """Tolerant ISO-8601 → datetime."""
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(str(s).replace("Z", ""))
