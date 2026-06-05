"""SQLAlchemy models for Q0, upgraded to support PostgreSQL-specific types with SQLite fallbacks.

Tables:
  - User: One per email, stores role, preferences.
  - Attempt: One per submitted quiz, stores test_code, score, payload, metadata.
  - Question: Quiz question bank with versioning, UGC flags, options.
  - FeedItem: Social stream posts, scenarios, videos, indexing.
  - MediaAsset: Stores binary file metadata referencing PostgreSQL Large Object OIDs.
"""
import json
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, BigInteger, TypeDecorator, TEXT
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
    role = Column(String(32))  # e.g., 'FeedCreator', 'Moderator', 'QuizManager', 'User'
    provider = Column(String(32))
    preferences = Column(HSTORE_TYPE, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    attempts = relationship("Attempt", back_populates="user", lazy="dynamic")
    questions = relationship("Question", back_populates="author", lazy="dynamic")
    feed_items = relationship("FeedItem", back_populates="author", lazy="dynamic")
    media_assets = relationship("MediaAsset", back_populates="uploader", lazy="dynamic")


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_code = Column(String(32), unique=True, nullable=False, index=True)
    cert_id = Column(String(64), unique=True, nullable=True, index=True)
    quiz_id = Column(String(64), nullable=False)

    user_email = Column(String(255), ForeignKey("users.email"), nullable=False, index=True)
    user = relationship("User", back_populates="attempts")

    difficulty = Column(String(16), nullable=False)
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

