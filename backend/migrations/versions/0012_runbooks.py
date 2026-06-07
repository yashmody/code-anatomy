"""Add runbooks table.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-07

Each runbook stores role + domain metadata and a JSONB `phases` tree
(phases → sections → tasks) so the reader page can render it in one
query. Seeded from Excel uploads via POST /api/runbooks/upload.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011_techflix_episodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runbooks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False, server_default="generic"),
        sa.Column("type", sa.String(32), nullable=False, server_default="greenfield"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column(
            "phases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_runbooks_slug", "runbooks", ["slug"], unique=True)
    op.create_index("idx_runbooks_role_domain", "runbooks", ["role", "domain"])
    op.create_index("idx_runbooks_status", "runbooks", ["status"])


def downgrade() -> None:
    op.drop_index("idx_runbooks_status", table_name="runbooks")
    op.drop_index("idx_runbooks_role_domain", table_name="runbooks")
    op.drop_index("uq_runbooks_slug", table_name="runbooks")
    op.drop_table("runbooks")
