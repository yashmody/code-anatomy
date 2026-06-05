"""phase-2a baseline — stamp the live schema as revision 0001

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-05

This migration is intentionally empty. Phase 2a adopts Alembic on a database
that already has the legacy 7-table schema (users, questions, attempts,
feed_items, media_assets, course_chapters, frameworks) created by
`init_db()` + `_migrate()`. Running `alembic stamp 0001_baseline` against
that live DB records the schema as revision 0001 without touching any
tables. Subsequent revisions (0002+) apply reconciles and additions.

For a fresh DB (no tables yet), `alembic upgrade head` first runs this
no-op then 0002_reconcile etc. — but the first call to `init_db()` in the
app would create the base tables via Base.metadata.create_all anyway, so
either ordering is safe.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: the live DB already has the baseline schema.
    pass


def downgrade() -> None:
    # No-op: never tear down the baseline via Alembic.
    pass
