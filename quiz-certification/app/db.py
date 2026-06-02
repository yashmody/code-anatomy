"""Database — SQLAlchemy engine + session.

Local dev: SQLite at q0.db (DATABASE_URL default).
Production: set DATABASE_URL=postgresql://user:pass@host/db.

Same SQL works on both. Schema lives in models.py.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from . import config

_engine_kwargs = {}
if config.DATABASE_URL.startswith("sqlite"):
    # SQLite needs check_same_thread=False for multi-threaded FastAPI access
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(config.DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    """Create tables if missing. Called on app startup."""
    from . import models  # noqa: F401 — register models with Base
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    """Return a fresh session. Caller closes it."""
    return SessionLocal()
