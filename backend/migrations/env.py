"""Alembic environment — wires the migration tool to the app's models + DATABASE_URL.

Designed for Phase 2a:
  - target_metadata = app.core.models.Base.metadata so `--autogenerate` diffs
    against the live ORM definitions.
  - DATABASE_URL is read from os.environ first, then falls back to
    app.core.config.DATABASE_URL. This keeps `alembic` and the running app on
    the same DB without duplicating the env-loading logic.
  - Directus-owned tables (any name beginning with `directus_`) are excluded
    from autogenerate so future migrations never propose dropping them.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure backend/ is on sys.path so `app.core.*` imports resolve regardless of
# where alembic is invoked from.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core import config as app_config  # noqa: E402
from app.core.db import Base  # noqa: E402
from app.core import models  # noqa: F401,E402 — register tables with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve the DB URL: env var wins, then app config.
_db_url = os.getenv("DATABASE_URL", app_config.DATABASE_URL)
# configparser (alembic's online engine config) treats `%` as interpolation
# syntax, so a URL-encoded password (e.g. %40 for `@`, %23 for `#`) raises
# "invalid interpolation syntax". Escape `%` -> `%%` for the config string only;
# offline mode (run_migrations_offline) uses the raw `_db_url` directly.
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Skip Directus-owned tables during autogenerate.

    Directus creates and manages `directus_*` tables in the same database. We
    must never drop them or alter their shape via Alembic.
    """
    if type_ == "table" and name and name.startswith("directus_"):
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without a live DB."""
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        render_as_batch=_db_url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
