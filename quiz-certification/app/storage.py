"""Storage layer — SQLAlchemy-backed.

Same surface area as the old JSON-file implementation, with additional
methods for questions, feed items, and media assets in PostgreSQL.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select

from . import config
from .db import get_session, init_db  # noqa: F401 — re-export init_db
from .models import Attempt, User, Question, FeedItem, MediaAsset


# ── Certificate signature (anti-tamper) ───────────────────────────────────────

def _sign_payload(cert_id: str, email: str, score: float, submitted_at: str) -> str:
    """HMAC-SHA256 over pipe-delimited fields using SECRET_KEY."""
    payload = f"{cert_id}|{email.lower()}|{score:.6f}|{submitted_at}"
    return hmac.new(
        config.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sign_attempt(cert_id: str, email: str, score: float, submitted_at: str) -> str:
    return _sign_payload(cert_id, email, score, submitted_at)


def verify_signature(attempt: Dict) -> bool:
    """Return True if the stored signature matches a fresh HMAC over the record."""
    stored = attempt.get("signature")
    if not stored:
        return False  # legacy cert — no signature stored
    expected = _sign_payload(
        attempt["cert_id"],
        attempt["user"]["email"],
        float(attempt["score"]),
        attempt["submitted_at"],
    )
    return hmac.compare_digest(expected, stored)

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
        "preferences": u.preferences or {},
    }


# ---------- attempt save + read ----------

def save_attempt(record: Dict) -> str:
    """Persist a graded attempt."""
    email = record["user"]["email"].lower()
    existing_code = record.get("test_code")

    with get_session() as s:
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
            cert_id = record.get("cert_id")
            submitted_at_str = record["submitted_at"]
            sig = None
            if cert_id:
                sig = sign_attempt(cert_id, email, float(record["score"]), submitted_at_str)

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
                submitted_at=_parse_iso(submitted_at_str),
                cert_id=cert_id,
                certificate_path=record.get("certificate_path"),
                signature=sig,
                payload={
                    "questions": record.get("questions", []),
                    "user_answers": record.get("user_answers", {}),
                    "grading": record.get("grading", {}),
                },
                metadata=record.get("metadata", {})
            )
            s.add(att)
        else:
            att.cert_id = record.get("cert_id") or att.cert_id
            att.certificate_path = record.get("certificate_path") or att.certificate_path
            if not att.signature and att.cert_id:
                att.signature = sign_attempt(
                    att.cert_id, email, att.score, att.submitted_at.isoformat() + "Z"
                )

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


def _attempt_to_dict(a: Attempt) -> Dict:
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
        "signature": a.signature,
        "questions": payload.get("questions", []),
        "user_answers": payload.get("user_answers", {}),
        "grading": payload.get("grading", {}),
        "metadata": a.metadata or {}
    }


def attempt_by_cert_id_public(cert_id: str) -> Optional[Dict]:
    with get_session() as s:
        a = s.scalar(select(Attempt).where(Attempt.cert_id == cert_id))
        return _attempt_to_dict(a) if a else None


# ---------- question bank CRUD ----------

def save_question(q_data: Dict) -> str:
    """Insert or update (version) a question in the bank."""
    qid = q_data["id"]
    with get_session() as s:
        existing = s.get(Question, qid)
        if existing:
            # Check version and increment
            new_version = (existing.version or 1) + 1
            # Archive old question by setting status to 'archived'
            existing.status = "archived"
            
            # Create new question version under a versioned ID to keep attempts working
            # Past attempts link to the specific question ID, so we keep the base ID for attempts,
            # but create a copy of the question with version incremented.
            # Wait, in relational DB, to keep old attempts pointing to the exact same text,
            # we should either copy the question content into attempts.payload (which we already do!)
            # since attempts.payload contains full_questions containing explanation, text, etc.
            # Because full_questions are already copied inline into attempts.payload, we don't need
            # to worry about attempts breaking when editing questions! This is brilliant!
            # Therefore, we can just update the existing question row directly, or increment its version.
            existing.topic = q_data.get("topic", existing.topic)
            existing.difficulty = q_data.get("difficulty", existing.difficulty)
            existing.question = q_data.get("question", existing.question)
            existing.options = q_data.get("options", existing.options)
            existing.correct_index = q_data.get("correct_index", existing.correct_index)
            existing.explanation = q_data.get("explanation", existing.explanation)
            existing.status = q_data.get("status", "published")
            existing.version = new_version
            existing.author_id = q_data.get("author_id", existing.author_id)
        else:
            new_q = Question(
                id=qid,
                topic=q_data["topic"],
                difficulty=q_data["difficulty"],
                question=q_data["question"],
                options=q_data["options"],
                correct_index=q_data["correct_index"],
                explanation=q_data.get("explanation", ""),
                status=q_data.get("status", "published"),
                version=1,
                author_id=q_data.get("author_id"),
                is_user_submitted=q_data.get("is_user_submitted", False)
            )
            s.add(new_q)
        s.commit()
        return qid


def get_questions_queue() -> List[Dict]:
    """Retrieve all user-submitted questions pending moderation."""
    with get_session() as s:
        rows = s.scalars(
            select(Question).where(Question.status.in_(["pending_review", "draft"]))
                           .order_by(Question.created_at.desc())
        ).all()
        return [_question_to_dict(q) for q in rows]


def _question_to_dict(q: Question) -> Dict:
    return {
        "id": q.id,
        "topic": q.topic,
        "difficulty": q.difficulty,
        "question": q.question,
        "options": q.options,
        "correct_index": q.correct_index,
        "explanation": q.explanation,
        "status": q.status,
        "version": q.version,
        "author_id": q.author_id,
        "is_user_submitted": q.is_user_submitted
    }


# ---------- feed CRUD ----------

def save_feed_item(item: Dict) -> str:
    fid = item["id"]
    with get_session() as s:
        existing = s.get(FeedItem, fid)
        author_id = item.get("author", {}).get("userId")
        if author_id and "@" not in author_id:
            author_id = f"{author_id}@deptagency.com"
            
        if existing:
            existing.status = item.get("status", existing.status)
            existing.data = item
        else:
            new_item = FeedItem(
                id=fid,
                type=item["type"],
                status=item.get("status", "published"),
                author_id=author_id.lower() if author_id else None,
                framework_ref=item.get("frameworkRef"),
                topics=item.get("topics", []),
                data=item
            )
            s.add(new_item)
        s.commit()
        return fid


def get_feed_items() -> List[Dict]:
    with get_session() as s:
        rows = s.scalars(
            select(FeedItem).where(FeedItem.status == "published")
                            .order_by(FeedItem.created_at.desc())
        ).all()
        return [r.data for r in rows]


def get_moderation_queue() -> Dict[str, List[Dict]]:
    """Retrieve all flagged or pending moderation items."""
    with get_session() as s:
        # Feed items
        feed_rows = s.scalars(
            select(FeedItem).where(FeedItem.status.in_(["pending_review", "flagged"]))
                            .order_by(FeedItem.created_at.desc())
        ).all()
        # Questions
        question_rows = s.scalars(
            select(Question).where(Question.status.in_(["pending_review", "draft"]))
                           .order_by(Question.created_at.desc())
        ).all()
        
        return {
            "feed_items": [r.data for r in feed_rows],
            "questions": [_question_to_dict(q) for q in question_rows]
        }


# ---------- helpers ----------

def _parse_iso(s: str) -> datetime:
    """Tolerant ISO-8601 → datetime."""
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(str(s).replace("Z", ""))
