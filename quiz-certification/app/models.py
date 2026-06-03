"""SQLAlchemy models for Q0.

Two tables — User (one per email, holds role) and Attempt (one per submitted
quiz, holds test_code, score, full graded payload).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON,
)
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    email = Column(String(255), primary_key=True)
    name = Column(String(255))
    picture = Column(String(1024))
    role = Column(String(32))  # null until onboarding completes
    provider = Column(String(32))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    attempts = relationship("Attempt", back_populates="user", lazy="dynamic")


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
    # HMAC-SHA256 of cert_id|email|score|submitted_at — anti-tamper seal
    signature = Column(String(64), nullable=True)
    # Full graded payload — questions, options, server-side correct indices,
    # user answers, per-question grading, explanations. JSON works on both
    # SQLite (stored as TEXT) and Postgres (native JSON / JSONB).
    payload = Column(JSON, nullable=False)
