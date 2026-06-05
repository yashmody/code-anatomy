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
    if "postgresql" in str(engine.url):
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS hstore"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            conn.commit()
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate() -> None:
    """Safe forward migrations — add columns that don't exist yet."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    
    # 1. Add signature column if missing in attempts
    cols_attempts = [c["name"] for c in insp.get_columns("attempts")]
    if "signature" not in cols_attempts:
        with engine.connect() as conn:
            if str(engine.url).startswith("postgresql"):
                conn.execute(text(
                    "ALTER TABLE attempts ADD COLUMN IF NOT EXISTS signature VARCHAR(64)"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE attempts ADD COLUMN signature VARCHAR(64)"
                ))
            conn.commit()
        print("[db] migrated: added signature column to attempts")
        
    # 2. Add metadata column if missing in attempts
    if "metadata" not in cols_attempts:
        with engine.connect() as conn:
            if str(engine.url).startswith("postgresql"):
                conn.execute(text(
                    "ALTER TABLE attempts ADD COLUMN IF NOT EXISTS metadata hstore"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE attempts ADD COLUMN metadata TEXT"
                ))
            conn.commit()
        print("[db] migrated: added metadata column to attempts")

    # 3. Add preferences column if missing in users
    cols_users = [c["name"] for c in insp.get_columns("users")]
    if "preferences" not in cols_users:
        with engine.connect() as conn:
            if str(engine.url).startswith("postgresql"):
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences hstore"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN preferences TEXT"
                ))
            conn.commit()
        print("[db] migrated: added preferences column to users")


def get_session() -> Session:
    """Return a fresh session. Caller closes it."""
    return SessionLocal()
