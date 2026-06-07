"""0011_techflix_episodes — Curated video episodes (Techflix) over media_assets

Adds a thin editorial table that pairs a video `media_assets` row with display
metadata (topic, title, description, ordering), an optional poster image (also a
`media_assets` row), and a probed duration. Populated by
`scripts/upload_media.py` from a `techflix.json` manifest; read by
`GET /api/media/techflix`. Additive — no changes to existing tables.

Revision ID: 0011_techflix_episodes
Revises: 0010_faq_tables
Create Date: 2026-06-07

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_techflix_episodes"
down_revision: Union[str, Sequence[str], None] = "0010_faq_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "techflix_episodes" not in existing_tables:
        # FK columns must match media_assets.id's actual DB type.
        # deploy_schema.sql creates media_assets.id as UUID on Postgres;
        # create_all() creates it as VARCHAR(64). Detect and match so the FK
        # constraint can be enforced. The ORM model uses String(64) for both
        # paths — psycopg2 coerces Python str ↔ UUID transparently at DML time.
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID
            _asset_fk_type = PG_UUID(as_uuid=False)
        else:
            _asset_fk_type = sa.String(64)

        op.create_table(
            "techflix_episodes",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column(
                "video_asset_id", _asset_fk_type,
                sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "poster_asset_id", _asset_fk_type,
                sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("topic", sa.String(128), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_sec", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        # One episode per video asset; topic index drives the grouped listing.
        op.create_unique_constraint(
            "uq_techflix_video_asset", "techflix_episodes", ["video_asset_id"]
        )
        op.create_index("idx_techflix_topic", "techflix_episodes", ["topic"])
        op.create_index(
            "idx_techflix_topic_order", "techflix_episodes", ["topic", "sort_order"]
        )

    # NOTE: no GRANT to the Directus role here. Techflix is app-owned content —
    # it is populated by the upload script, not edited in the Directus CMS — so
    # the scoped `directus_app` role deliberately gets no access to this table,
    # the same posture as the runtime/audit tables.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Dropping the table removes its indexes and constraints with it, so we do
    # not name them explicitly. This keeps downgrade robust whether the table
    # was created by this migration (custom index names) or by the create_all
    # safety net (model-convention names) — the two paths name indexes
    # differently, and a name-specific drop_index would fail on the other path.
    if "techflix_episodes" in existing_tables:
        op.drop_table("techflix_episodes")
