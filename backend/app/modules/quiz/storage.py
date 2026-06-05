"""Quiz storage — attempts, certificate signing, test codes, question bank.

Split out of the legacy monolithic app/storage.py during v2 Phase 1. The
question helpers stay alongside the attempt helpers because both belong
to the same domain (an attempt is graded against a question); the feed
moderation queue *reads* questions but does so by importing
`_question_to_dict` from here rather than fragmenting the table.

Phase 2c: certificate signing/verification semantics moved into
`app.modules.quiz.verification`. The functions below stay as thin wrappers
so existing callers (routes.py, certificate.py, smoke.py) keep working
unchanged. The new contract carries `attempt.environment` +
`attempt.signing_key_id` end-to-end.
"""
import secrets
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select

from app.core import config
from app.core.db import get_session
from app.core.models import Attempt, Question, SigningKey, User

from app.modules.quiz import verification


# ── Certificate signature (anti-tamper) ──────────────────────────────────────


def sign_attempt(record: Dict) -> Dict:
    """Sign a record in-place: set `signature`, `signing_key_id`, `environment`.

    Phase 2c shape change: takes the full record (so we can carry environment
    + key id alongside the signature). Returns the same dict for chaining.
    Callers in this module (`save_attempt`) drive it; cross-module callers
    were rewired in the same slice.
    """
    record["environment"] = record.get("environment") or verification.current_environment()
    signature, signing_key_id = verification.sign_record(record, record["environment"])
    record["signature"] = signature
    record["signing_key_id"] = signing_key_id
    return record


def verify_signature(attempt: Dict) -> bool:
    """Return True if the stored signature matches a fresh HMAC over the record.

    Delegates to `verification.verify_attempt`; this wrapper preserves the
    existing boolean contract that routes.py + smoke.py expect. Callers that
    need the structured result (environment badge, retirement reason) should
    call `verification.verify_attempt` directly.
    """
    return bool(verification.verify_attempt(attempt).get("valid"))


# Confusable-free alphabet for human-readable test codes (no 0/O/1/I)
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ── Test code ────────────────────────────────────────────────────────────────

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


def _generate_unique_code(session) -> str:
    """In-session version of generate_test_code that reuses an open session."""
    date_part = datetime.utcnow().strftime("%Y%m%d")
    for _ in range(8):
        rand = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        code = f"AOC-{date_part}-{rand}"
        if session.scalar(select(Attempt).where(Attempt.test_code == code)) is None:
            return code
    raise RuntimeError("Could not generate a unique test code after 8 tries")


# ── Attempts ─────────────────────────────────────────────────────────────────

def save_attempt(record: Dict) -> str:
    """Persist a graded attempt.

    Phase 2c: applies the environment cert-ID prefix (`DEV-`/`STG-`) on the
    first save when the process is running outside production, and stamps
    `environment` + `signing_key_id` onto the row alongside the HMAC. Existing
    production certs (CCA-F-…) are NEVER re-prefixed — the idempotence guards
    in `verification.apply_env_prefix` and the `att.cert_id` reload below keep
    re-saves byte-stable.
    """
    email = record["user"]["email"].lower()
    existing_code = record.get("test_code")

    environment = record.get("environment") or verification.current_environment()
    record["environment"] = environment

    # Stamp the env prefix before we sign — the prefix is part of the cert_id
    # that goes into the HMAC input, so the order matters. Idempotent.
    cert_id_in = record.get("cert_id")
    if cert_id_in:
        record["cert_id"] = verification.apply_env_prefix(cert_id_in, environment)

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
            sig: Optional[str] = None
            signing_key_id: Optional[int] = None
            if cert_id:
                # Build a minimal signing-shape dict so verification doesn't
                # need to know about the larger record payload.
                signing_view = {
                    "cert_id": cert_id,
                    "user": {"email": email},
                    "score": float(record["score"]),
                    "submitted_at": submitted_at_str,
                }
                sig, signing_key_id = verification.sign_record(signing_view, environment)

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
                environment=environment,
                signing_key_id=signing_key_id,
                payload={
                    "questions": record.get("questions", []),
                    "user_answers": record.get("user_answers", {}),
                    "grading": record.get("grading", {}),
                },
                attempt_metadata=record.get("metadata", {}),
            )
            s.add(att)
        else:
            att.cert_id = record.get("cert_id") or att.cert_id
            att.certificate_path = record.get("certificate_path") or att.certificate_path
            if not att.signature and att.cert_id:
                signing_view = {
                    "cert_id": att.cert_id,
                    "user": {"email": email},
                    "score": float(att.score),
                    "submitted_at": att.submitted_at.isoformat() + "Z",
                }
                sig, signing_key_id = verification.sign_record(signing_view, environment)
                att.signature = sig
                att.signing_key_id = signing_key_id
                # Leave att.environment alone if it's already set (existing rows
                # default to 'production' via the column default). Only stamp it
                # if it's somehow missing — i.e. brand-new row whose insert raced
                # past the default, which should never happen on Postgres.
                if not att.environment:
                    att.environment = environment

        s.commit()
        return att.test_code


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


def attempt_by_cert_id_public(cert_id: str) -> Optional[Dict]:
    """Public verifier read path. JOINS `signing_keys` so the verifier can
    reason about key rotation/expiry without a second round-trip.

    Phase 2c adds `environment` + the signing-key snapshot. Existing callers
    that only consume the legacy fields are unaffected.
    """
    with get_session() as s:
        a = s.scalar(select(Attempt).where(Attempt.cert_id == cert_id))
        if not a:
            return None
        result = _attempt_to_dict(a)
        sk: Optional[SigningKey] = a.signing_key  # relationship; None for null FK
        if sk is not None:
            result["signing_key"] = {
                "id": sk.id,
                "name": sk.name,
                "environment": sk.environment,
                "env_var_name": sk.env_var_name,
                "is_active": bool(sk.is_active),
                "can_verify": bool(sk.can_verify),
                "verify_until": sk.verify_until.isoformat() + "Z" if sk.verify_until else None,
            }
        return result


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
        # Phase 2c — every attempt now carries the environment it was issued
        # in, plus the signing-key FK that proves which key signed it.
        "environment": a.environment or "production",
        "signing_key_id": a.signing_key_id,
        "questions": payload.get("questions", []),
        "user_answers": payload.get("user_answers", {}),
        "grading": payload.get("grading", {}),
        # Model column is named "metadata" in SQL but exposed as the
        # Python attribute `attempt_metadata` to avoid clashing with the
        # `metadata` reserved on DeclarativeBase.
        "metadata": a.attempt_metadata or {}
    }


# ── Question bank ────────────────────────────────────────────────────────────

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

            # Create new question version under a versioned ID to keep attempts working.
            # Past attempts link to the specific question ID, so we keep the base ID for
            # attempts but create a copy of the question with version incremented.
            # In relational DB, to keep old attempts pointing to the exact same text,
            # we should either copy the question content into attempts.payload (which
            # we already do!) since attempts.payload contains full_questions containing
            # explanation, text, etc.
            # Because full_questions are already copied inline into attempts.payload, we
            # don't need to worry about attempts breaking when editing questions — we
            # can update the existing question row directly and increment its version.
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
        return [question_to_dict(q) for q in rows]


def question_to_dict(q: Question) -> Dict:
    """Public — feed.moderation imports this to shape the moderation queue."""
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_iso(s: str) -> datetime:
    """Tolerant ISO-8601 → datetime."""
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(str(s).replace("Z", ""))
