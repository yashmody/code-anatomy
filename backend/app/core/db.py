"""Database — SQLAlchemy engine + session.

Local dev: SQLite at q0.db (DATABASE_URL default; kept for parity with the
sqlite shim still present in models.py — Phase 2a does not remove it).
Production: set DATABASE_URL=postgresql://user:pass@host/db.

Same SQL works on both. Schema lives in models.py. Phase 2a retired the
hand-rolled `_migrate()` in favour of Alembic — see backend/migrations/.
"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import NullPool

from app.core import config

logger = logging.getLogger(__name__)

# Engine config differs by dialect:
#   - sqlite: needs check_same_thread=False for FastAPI's thread pool; pooling
#     is largely moot, so we use NullPool to avoid stale-connection surprises.
#   - postgresql: pool_size/max_overflow come from settings (db_pool_size /
#     db_max_overflow, defaults 5/5 per 03-data-model.md §7.1) so a remote
#     shared instance can be tuned without a code change. pool_pre_ping
#     survives idle-killed connections behind a proxy; pool_recycle bounds
#     connection age against a managed instance's idle timeout.
#   - TLS for a remote Postgres is carried entirely by the URL query
#     (?sslmode=require|verify-full); psycopg2 honours it, so NO connect_args
#     change is needed here. config.settings.validate_db_tls() refuses to
#     construct settings if a remote URL in a non-dev env lacks it.
_engine_kwargs = {}
if config.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = NullPool
elif "postgresql" in config.DATABASE_URL:
    _engine_kwargs["pool_size"] = config.settings.db_pool_size
    _engine_kwargs["max_overflow"] = config.settings.db_max_overflow
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

    Remote-safe posture: on a REMOTE managed Postgres the runtime app role has
    DML only — it holds no CREATE EXTENSION nor DDL (CREATE TABLE) privilege.
    The DBA pre-creates the extensions and Alembic (run by a privileged
    migration credential at deploy) owns the real schema. So both the extension
    creation and create_all() below are made best-effort: on insufficient
    privilege we log a WARNING and continue rather than crash app startup. On a
    fully-migrated remote DB both are no-ops anyway. The LOCAL sqlite/dev path
    is behaviourally unchanged (the superuser local Postgres still runs them
    successfully; sqlite skips the extension block entirely).
    """
    from app.core import models  # noqa: F401 — register models with Base
    if "postgresql" in str(engine.url):
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS hstore"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
                conn.commit()
        except Exception as exc:  # e.g. insufficient_privilege on a managed DB
            logger.warning(
                "[db] skipping CREATE EXTENSION (hstore/pgcrypto): %s. "
                "On a remote managed Postgres the DBA pre-creates extensions "
                "and the runtime role lacks CREATE — continuing.",
                exc,
            )
    try:
        # Alembic (run by a privileged credential at deploy) owns the real
        # schema; this is only a first-boot safety net. A minimal-privilege
        # remote runtime role cannot run DDL, so a failure here must not crash
        # the app — it is a no-op against an already-migrated DB.
        Base.metadata.create_all(bind=engine)
    except Exception as exc:  # e.g. insufficient_privilege / no DDL on remote
        logger.warning(
            "[db] skipping create_all(): %s. Schema is owned by Alembic "
            "(run `alembic upgrade head`); the runtime role need not hold DDL "
            "— continuing.",
            exc,
        )
    print("[db] init_db complete — schema evolution is owned by Alembic "
          "(see backend/migrations/). Run `alembic upgrade head` to apply.")


def get_session() -> Session:
    """Return a fresh session. Caller closes it."""
    return SessionLocal()
