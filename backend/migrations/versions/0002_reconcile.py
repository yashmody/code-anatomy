"""phase-2a reconcile — add missing indexes that lived only in deploy_schema.sql

Revision ID: 0002_reconcile
Revises: 0001_baseline
Create Date: 2026-06-05

The legacy create_all() path (db.py:init_db) never created the lookup indexes
declared in deploy_schema.sql — so a live system bootstrapped via init_db()
has zero of them. This migration installs the ones the ORM can express on
both sqlite and Postgres (the Postgres-only GIN indexes on
`feed_items.topics` / `feed_items.search` are authored here too but guarded
behind a dialect check).

All steps are CREATE INDEX IF NOT EXISTS / dialect-guarded — idempotent.
The score-type conditional fix is also dialect-guarded; on sqlite it is a
no-op because the live column is already REAL (float).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_reconcile"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Missing indexes (declared in models.py __table_args__ as of 2a, but
    #    not yet on disk for DBs bootstrapped via create_all). IF NOT EXISTS
    #    keeps this idempotent across re-runs and fresh installs.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_questions_lookup "
        "ON questions (status, difficulty, topic)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_user "
        "ON attempts (user_email, submitted_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_items_ordering "
        "ON feed_items (status, created_at)"
    )

    # 2. Postgres-only: GIN indexes on the array + tsvector columns.
    if dialect == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_items_topics "
            "ON feed_items USING gin (topics)"
        )
        # `search` is a generated tsvector column declared in deploy_schema.sql.
        # If a live system already has the column (deploy_schema-created DB),
        # add the GIN index. If not (init_db-created DB), the index creation
        # is deferred to a later migration that also adds the column.
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='feed_items' AND column_name='search') THEN "
            "EXECUTE 'CREATE INDEX IF NOT EXISTS idx_feed_items_search "
            "ON feed_items USING gin (search)'; "
            "END IF; END $$;"
        )

        # 3. Score-type drift: deploy_schema.sql created NUMERIC(5,2); create_all
        #    created DOUBLE PRECISION. Standardise on DOUBLE PRECISION because
        #    the cert HMAC reads `f"{score:.6f}"` and rounding would break
        #    verification. Conditional — only ALTER if the live column is numeric.
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='attempts' AND column_name='score' "
            "AND data_type='numeric') THEN "
            "ALTER TABLE attempts ALTER COLUMN score TYPE double precision "
            "USING score::double precision; "
            "END IF; END $$;"
        )


def downgrade() -> None:
    # Drop the indexes we created. Score-type ALTER is intentionally not
    # reversed — going back to numeric(5,2) would break cert verification.
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_feed_items_search")
        op.execute("DROP INDEX IF EXISTS idx_feed_items_topics")
    op.execute("DROP INDEX IF EXISTS idx_feed_items_ordering")
    op.execute("DROP INDEX IF EXISTS idx_attempts_user")
    op.execute("DROP INDEX IF EXISTS idx_questions_lookup")
