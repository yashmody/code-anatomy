"""0010_faq_tables — Create tables for Directus-managed FAQs

Revision ID: 0010_faq_tables
Revises: 0009_superadmin
Create Date: 2026-06-06

"""
from __future__ import annotations

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_faq_tables"
down_revision: Union[str, Sequence[str], None] = "0009_superadmin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. faq_categories
    if "faq_categories" not in existing_tables:
        op.create_table(
            "faq_categories",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("audience", sa.String(255), nullable=True),
            sa.Column("source", sa.String(255), nullable=True),
            sa.Column("reviewed_at", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_faq_categories_status", "faq_categories", ["status"])

    # 2. faq_items
    if "faq_items" not in existing_tables:
        # SQLite Array fallback compatibility
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import ARRAY
            tags_col_type = ARRAY(sa.Text())
        else:
            tags_col_type = sa.Text()

        op.create_table(
            "faq_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("category_id", sa.String(64), sa.ForeignKey("faq_categories.id", ondelete="CASCADE"), nullable=False),
            sa.Column("q_num", sa.String(10), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("tags", tags_col_type, nullable=False, server_default="[]" if dialect != "postgresql" else None),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_faq_items_category_id", "faq_items", ["category_id"])

    # 3. Directus DB Role grants (Postgres-only)
    if dialect == "postgresql":
        role = os.getenv("DIRECTUS_DB_ROLE", "directus_app")
        role_exists = bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": role},
        ).scalar()
        if role_exists:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON faq_categories, faq_items TO {role};")
            op.execute(f"GRANT USAGE, SELECT ON SEQUENCE faq_items_id_seq TO {role};")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "faq_items" in existing_tables:
        op.drop_index("idx_faq_items_category_id", table_name="faq_items")
        op.drop_table("faq_items")

    if "faq_categories" in existing_tables:
        op.drop_index("idx_faq_categories_status", table_name="faq_categories")
        op.drop_table("faq_categories")
