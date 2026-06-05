"""Database — SQLAlchemy engine + session.

Local dev: SQLite at q0.db (DATABASE_URL default; kept for parity with the
sqlite shim still present in models.py — Phase 2a does not remove it).
Production: set DATABASE_URL=postgresql://user:pass@host/db.

Same SQL works on both. Schema lives in models.py. Phase 2a retired the
hand-rolled `_migrate()` in favour of Alembic — see backend/migrations/.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import NullPool

from app.core import config

# Engine config differs by dialect:
#   - sqlite: needs check_same_thread=False for FastAPI's thread pool; pooling
#     is largely moot, so we use NullPool to avoid stale-connection surprises.
#   - postgresql: pool_size/max_overflow tuned per 03-data-model.md §7.1.
#     pool_pre_ping survives idle-killed connections behind a proxy.
_engine_kwargs = {}
if config.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = NullPool
elif "postgresql" in config.DATABASE_URL:
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 5
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 1800

engine = create_engine(config.DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    """Create tables if missing. Called on app startup.

    Phase 2a note: the hand-rolled `_migrate()` patcher has been retired.
    Schema evolution is now driven by Alembic — run
    `alembic upgrade head` from backend/ as part of the deploy step. The
    create_all() call below is kept only as a safety net for first-time local
    boots that haven't run migrations yet; on a DB with Alembic history it is
    a no-op because every table already exists.
    """
    from app.core import models  # noqa: F401 — register models with Base
    if "postgresql" in str(engine.url):
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS hstore"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            conn.commit()
    Base.metadata.create_all(bind=engine)
    print("[db] init_db complete — schema evolution is owned by Alembic "
          "(see backend/migrations/). Run `alembic upgrade head` to apply.")


def get_session() -> Session:
    """Return a fresh session. Caller closes it."""
    return SessionLocal()
