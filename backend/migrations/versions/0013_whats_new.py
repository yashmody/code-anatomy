"""0013_whats_new — What's New items (Adobe content-refresh sync)

Stores Adobe release-note updates ingested weekly by
`scripts/sync_adobe_updates.py` and served by `GET /api/whatsnew`. Additive —
no changes to existing tables. Idempotent (guarded create) so it is a no-op on a
DB where the create_all safety net already made the table.

Revision ID: 0013_whats_new
Revises: 0012
Create Date: 2026-06-07

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_whats_new"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "whats_new_items" not in existing:
        op.create_table(
            "whats_new_items",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("source_url", sa.String(1024), nullable=False),
            sa.Column("product", sa.String(128), nullable=False),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("related_chapter", sa.String(128), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="new"),
        )
        op.create_unique_constraint(
            "uq_whats_new_source_url", "whats_new_items", ["source_url"]
        )
        op.create_index("idx_whats_new_source", "whats_new_items", ["source"])
        op.create_index("idx_whats_new_fetched_at", "whats_new_items", ["fetched_at"])

    # App-owned content (populated by the sync script, not the Directus CMS), so
    # no GRANT to the scoped directus_app role — same posture as techflix_episodes.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    # Dropping the table removes its indexes/constraints with it (robust whether
    # created by this migration or by the create_all safety net).
    if "whats_new_items" in existing:
        op.drop_table("whats_new_items")
