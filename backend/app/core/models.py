"""SQLAlchemy models for Q0, upgraded to support PostgreSQL-specific types with SQLite fallbacks.

Tables:
  - User: One per email, stores role, preferences.
  - Attempt: One per submitted quiz, stores test_code, score, payload, metadata.
  - Question: Quiz question bank with versioning, UGC flags, options.
  - FeedItem: Social stream posts, scenarios, videos, indexing.
  - MediaAsset: Stores binary file metadata referencing PostgreSQL Large Object OIDs.
  - Runbook: Role- and domain-specific runbooks seeded from Excel uploads or direct API.
"""
import json
from datetime import datetime
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer,
    PrimaryKeyConstraint, String, Text, BigInteger, TypeDecorator, TEXT, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.core import config
from app.core.db import Base

# Dynamic type fallback for SQLite vs PostgreSQL compatibility
if "postgresql" in config.DATABASE_URL:
    from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, HSTORE as PG_HSTORE, ARRAY as PG_ARRAY, OID as PG_OID
    JSONB_TYPE = PG_JSONB
    HSTORE_TYPE = PG_HSTORE
    ARRAY_TYPE = PG_ARRAY
    OID_TYPE = PG_OID
else:
    from sqlalchemy import JSON as SQLite_JSON
    JSONB_TYPE = SQLite_JSON
    
    class SQLiteHStore(TypeDecorator):
        impl = TEXT
        cache_ok = True
        def process_bind_param(self, value, dialect):
            return json.dumps(value) if value is not None else None
        def process_result_value(self, value, dialect):
            return json.loads(value) if value is not None else {}
            
    class SQLiteArray(TypeDecorator):
        impl = TEXT
        cache_ok = True
        def process_bind_param(self, value, dialect):
            return json.dumps(value) if value is not None else None
        def process_result_value(self, value, dialect):
            return json.loads(value) if value is not None else []

    JSONB_TYPE = SQLite_JSON
    HSTORE_TYPE = SQLiteHStore
    ARRAY_TYPE = lambda t: SQLiteArray
    OID_TYPE = Integer


class User(Base):
    __tablename__ = "users"

    email = Column(String(255), primary_key=True)
    name = Column(String(255))
    picture = Column(String(1024))
    role = Column(String(32))  # DEPRECATED in v2 — kept for backward-compat; 2b backfills into user_roles.
    persona = Column(String(32), nullable=True)  # demoted job-family attribute (pm/ba/qa/...); drives quiz difficulty only.
    provider = Column(String(32))
    preferences = Column(HSTORE_TYPE, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    attempts = relationship("Attempt", back_populates="user", lazy="dynamic")
    questions = relationship("Question", back_populates="author", lazy="dynamic")
    feed_items = relationship("FeedItem", back_populates="author", lazy="dynamic")
    media_assets = relationship("MediaAsset", back_populates="uploader", lazy="dynamic")
    roles = relationship("UserRole", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_code = Column(String(32), unique=True, nullable=False, index=True)
    cert_id = Column(String(64), unique=True, nullable=True, index=True)
    quiz_id = Column(String(64), nullable=False)

    user_email = Column(String(255), ForeignKey("users.email"), nullable=False, index=True)
    user = relationship("User", back_populates="attempts")

    difficulty = Column(String(16), nullable=False)
    # NOTE: score stays Float (DOUBLE PRECISION on PG; REAL on sqlite). The cert
    # HMAC reads `f"{score:.6f}"` (modules/quiz/storage.py:26); a NUMERIC(5,2)
    # round trip would break verification of every already-issued cert.
    score = Column(Float, nullable=False)
    correct = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    passed = Column(Boolean, nullable=False, index=True)

    started_at = Column(DateTime, nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    certificate_path = Column(Text, nullable=True)
    signature = Column(String(64), nullable=True) # HMAC-SHA256 of cert_id|email|score|submitted_at
    payload = Column(JSONB_TYPE, nullable=False)
    attempt_metadata = Column("metadata", HSTORE_TYPE, default={})

    # Cert dev-mode (Phase 2a §2.1). Existing rows default to 'production' so
    # every already-issued cert continues to verify unchanged.
    environment = Column(String(32), nullable=False, server_default="production", default="production")
    signing_key_id = Column(Integer, ForeignKey("signing_keys.id"), nullable=True)
    signing_key = relationship("SigningKey")

    __table_args__ = (
        # Mirrors deploy_schema.sql:54 — was DDL-only previously.
        Index("idx_attempts_user", "user_email", "submitted_at"),
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(String(64), primary_key=True)
    topic = Column(String(128), nullable=False)
    difficulty = Column(String(16), nullable=False)
    question = Column(Text, nullable=False)
    options = Column(JSONB_TYPE, nullable=False) # Array of strings
    correct_index = Column(Integer, nullable=False)
    explanation = Column(Text)
    status = Column(String(32), default="draft") # 'draft', 'pending_review', 'published', 'archived'
    version = Column(Integer, default=1)
    
    author_id = Column(String(255), ForeignKey("users.email"), nullable=True)
    author = relationship("User", back_populates="questions")
    
    is_user_submitted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Mirrors deploy_schema.sql:33 — was DDL-only previously.
        Index("idx_questions_lookup", "status", "difficulty", "topic"),
    )


class FeedItem(Base):
    __tablename__ = "feed_items"

    id = Column(String(64), primary_key=True)
    type = Column(String(32), nullable=False) # 'post', 'video', 'list', 'card', 'vocab', 'scenario'
    status = Column(String(32), nullable=False, default="published") # 'draft', 'pending_review', 'published', 'flagged', 'removed'
    
    author_id = Column(String(255), ForeignKey("users.email"), nullable=True)
    author = relationship("User", back_populates="feed_items")
    
    framework_ref = Column(String(64), nullable=True)
    topics = Column(ARRAY_TYPE(Text), nullable=False, default=[])
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    data = Column(JSONB_TYPE, nullable=False) # payload metadata, comments, engagement counters

    __table_args__ = (
        # Mirrors deploy_schema.sql:71 — was DDL-only previously. (The GIN
        # topics/search indexes are Postgres-only and authored in the
        # 0002_reconcile migration; declared in the ORM only for parity.)
        Index("idx_feed_items_ordering", "status", "created_at"),
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(String(64), primary_key=True) # UUID string
    large_object_oid = Column(OID_TYPE, nullable=False) # Postgres Large Object OID
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    
    uploaded_by = Column(String(255), ForeignKey("users.email"), nullable=True)
    uploader = relationship("User", back_populates="media_assets")
    
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class TechflixEpisode(Base):
    """Techflix — curated video episodes grouped by topic.

    A thin editorial layer over `media_assets`: each row pairs one video asset
    with display metadata (topic, title, description, ordering) plus an optional
    poster image (itself a `media_assets` row) and a probed duration. Populated
    by `scripts/upload_media.py` from a `techflix.json` manifest; read by
    `GET /api/media/techflix`. The bytes still stream from `/media/video/{id}`.

    Two FKs point at `media_assets` (video + poster), so the relationships must
    name their `foreign_keys` explicitly. The bare-asset rows stay generic;
    only the editorial metadata lives here.
    """
    __tablename__ = "techflix_episodes"

    id = Column(String(64), primary_key=True)  # UUID string
    video_asset_id = Column(
        String(64), ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    poster_asset_id = Column(
        String(64), ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    topic = Column(String(128), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    duration_sec = Column(Integer, nullable=True)  # None when FFprobe unavailable
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    video_asset = relationship("MediaAsset", foreign_keys=[video_asset_id])
    poster_asset = relationship("MediaAsset", foreign_keys=[poster_asset_id])


class WhatsNewItem(Base):
    """What's New — a single Adobe update ingested by the content-refresh sync.

    Populated weekly by `scripts/sync_adobe_updates.py` (the Content Refresh
    Agent's pipeline): fetch Adobe release-notes pages, extract + summarise
    entries with Claude, store here. Read by `GET /api/whatsnew`. `source_url`
    is unique and is the dedup key — for page-derived entries with no per-item
    link it is a synthesised stable key (page URL + title slug).
    """
    __tablename__ = "whats_new_items"

    id = Column(String(64), primary_key=True)  # UUID string
    source = Column(String(32), nullable=False, index=True)  # commerce|aem|ajo|cja|target|campaign
    source_url = Column(String(1024), nullable=False, unique=True)  # dedup key
    product = Column(String(128), nullable=False)
    title = Column(String(512), nullable=False)
    summary = Column(Text, nullable=True)        # Claude, DEPT voice; null on LLM error
    related_chapter = Column(String(128), nullable=True)  # e.g. 'adobe-cm.json' | null
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(32), nullable=False, default="new")  # new|published|archived|held


class CourseChapter(Base):
    __tablename__ = "course_chapters"

    filename = Column(String(128), primary_key=True)  # e.g., 'code-c.json'
    ring = Column(String(32), nullable=False)          # e.g., 'code', 'coder'
    title = Column(String(255), nullable=False)
    content = Column(JSONB_TYPE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Framework(Base):
    __tablename__ = "frameworks"

    id = Column(String(32), primary_key=True, default="framework")
    data = Column(JSONB_TYPE, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2a new tables — see docs/architecture/v2/03-data-model.md §2.2–§2.10.
# ─────────────────────────────────────────────────────────────────────────────


class QuizSession(Base):
    """Persisted replacement for the in-process _active_quizzes dict.

    Owned by Phase 2b for read/write wiring; storage shape defined in 2a.
    Replaces app.main._active_quizzes (the dict that broke QUIZ_WORKERS > 1).
    """
    __tablename__ = "quiz_sessions"

    quiz_id = Column(String(64), primary_key=True)
    user_email = Column(String(255), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    difficulty = Column(String(32), nullable=False)
    server_answers = Column(JSONB_TYPE, nullable=False)
    full_questions = Column(JSONB_TYPE, nullable=False)
    submitted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_quiz_sessions_user_expires", "user_email", "expires_at"),
    )


class SigningKey(Base):
    """Per-environment cert HMAC key metadata. Key material lives in env vars.

    The `legacy-prod` row (seeded by 0005_cert_devmode) points at
    CERT_HMAC_LEGACY, which the operator seeds with the existing SECRET_KEY
    value at cutover. Every already-issued attempt is backfilled to this row,
    so cert verification is byte-identical (Phase 2c owns the verify wiring).
    """
    __tablename__ = "signing_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    environment = Column(String(32), nullable=False)
    env_var_name = Column(String(128), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    can_verify = Column(Boolean, nullable=False, default=True, server_default="1")
    verify_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "environment IN ('production','staging','development')",
            name="ck_signing_keys_environment",
        ),
    )


class Role(Base):
    """Capability-role reference table. Seeded in 0003_authz_split."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(32), unique=True, nullable=False)
    plane = Column(String(16), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("plane IN ('learner','staff')", name="ck_roles_plane"),
    )

    user_roles = relationship("UserRole", back_populates="role", lazy="dynamic")


class UserRole(Base):
    """Many-to-many grant of capability roles to users. Owned by 04-authz-model."""
    __tablename__ = "user_roles"

    user_email = Column(String(255), ForeignKey("users.email"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow)
    granted_by = Column(String(255), nullable=True)

    user = relationship("User", back_populates="roles")
    role = relationship("Role", back_populates="user_roles")

    __table_args__ = (
        PrimaryKeyConstraint("user_email", "role_id", name="pk_user_roles"),
        Index("idx_user_roles_user", "user_email"),
    )


class AppConfig(Base):
    """Runtime-tunable, non-secret config Directus can edit. See 05-config-cms.

    No `is_secret` column per C-20 — the secret-vs-config tiering is enforced
    by the typed registry in 05, not by a DB flag.
    """
    __tablename__ = "app_config"

    key = Column(String(128), primary_key=True)
    value = Column(JSONB_TYPE, nullable=False)
    value_type = Column(String(16), nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "value_type IN ('string','int','float','bool','json')",
            name="ck_app_config_value_type",
        ),
    )


class SuperAdmin(Base):
    """Break-glass superadmin account — local username/password + TOTP 2FA.

    Completely separate from the learner-plane `users` table and Google OAuth.
    One account maximum. Credentials never come from git — seeded via
    scripts/create_superadmin.py. Not visible to Directus (REVOKE in 0009).

    Auth state machine:
      totp_enabled=False → password verified → redirect to first-time TOTP setup
      totp_enabled=True  → password + TOTP both required to create a session
    """
    __tablename__ = "superadmin"

    email          = Column(String(255), primary_key=True)
    password_hash  = Column(String(255), nullable=False)   # bcrypt hash
    totp_secret    = Column(String(64),  nullable=True)    # base32; NULL until setup
    totp_enabled   = Column(Boolean,     nullable=False, default=False)
    created_at     = Column(DateTime,    default=datetime.utcnow)
    last_login_at  = Column(DateTime,    nullable=True)


class AuthAudit(Base):
    """Append-only authn/authz event log. FastAPI writes; Directus has no SELECT."""
    __tablename__ = "auth_audit"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_email = Column(String(255), nullable=True)
    action = Column(String(64), nullable=False)
    target_email = Column(String(255), nullable=True)
    target_role = Column(String(32), nullable=True)
    before = Column(JSONB_TYPE, nullable=True)
    after = Column(JSONB_TYPE, nullable=True)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_auth_audit_actor", "actor_email", "occurred_at"),
        Index("idx_auth_audit_action", "action", "occurred_at"),
    )


class FAQCategory(Base):
    """FAQ Category / Topic representation."""
    __tablename__ = "faq_categories"

    id = Column(String(64), primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    audience = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)
    reviewed_at = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("FAQItem", back_populates="category", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_faq_categories_status", "status"),
    )


class FAQItem(Base):
    """Individual FAQ Item (Question & Answer)."""
    __tablename__ = "faq_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(String(64), ForeignKey("faq_categories.id", ondelete="CASCADE"), nullable=False)
    q_num = Column(String(10), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    tags = Column(ARRAY_TYPE(Text), nullable=False, default=[])
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("FAQCategory", back_populates="items")

    __table_args__ = (
        Index("idx_faq_items_category_id", "category_id"),
    )


class Runbook(Base):
    """Role- and domain-specific runbooks.

    Each row is a complete runbook — greenfield or brownfield — for a
    given practitioner role (architect, devops, developer, qa, pm, ba)
    and optional domain (banking, ecommerce, manufacturing, generic).

    `sections` holds the full phases → sections → tasks tree as JSONB so
    the reader page can render it without additional queries. The schema
    mirrors the Excel upload template: see backend/scripts/generate_runbook_template.py.

    Idempotent on `slug` — uploading the same Excel twice overwrites the
    existing row rather than creating a duplicate.
    """
    __tablename__ = "runbooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(512), nullable=False)
    role = Column(String(32), nullable=False)    # architect | devops | developer | qa | pm | ba
    domain = Column(String(64), nullable=False, default="generic")  # banking | ecommerce | manufacturing | generic
    runbook_type = Column("type", String(32), nullable=False, default="greenfield")  # greenfield | brownfield
    description = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="draft")    # draft | published
    phases = Column(JSONB_TYPE, nullable=False, default=[])
    meta = Column(JSONB_TYPE, nullable=False, default={})
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_runbooks_role_domain", "role", "domain"),
        Index("idx_runbooks_status", "status"),
    )


