"""0015_drop_techflix_episodes — drop the legacy techflix_episodes table

`techflix_episodes` was superseded by the unified video model: 0014 backfilled
its rows into `video_asset` / `video_variant` / `techflix_video_map`. This
migration drops the now-unused table.

Ordering is what makes this safe: 0015 runs strictly after 0014 in the chain, so
`alembic upgrade head` always completes 0014's backfill (which reads
techflix_episodes) before this DROP executes. Idempotent — no-op if the table is
already gone.

Revision ID: 0015_drop_techflix_episodes
Revises: 0014_video_model
Create Date: 2026-06-07
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_drop_techflix_episodes"
down_revision: Union[str, Sequence[str], None] = "0014_video_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "techflix_episodes" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("techflix_episodes")


def downgrade() -> None:
    # Recreate the legacy shape (without data) so a downgrade past 0015 leaves a
    # table for 0014's backfill to read if the chain is replayed. Matches the
    # 0011 definition.
    bind = op.get_bind()
    if "techflix_episodes" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "techflix_episodes",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("video_asset_id", sa.String(64),
                      sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("poster_asset_id", sa.String(64),
                      sa.ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True),
            sa.Column("topic", sa.String(128), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_sec", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_unique_constraint("uq_techflix_video_asset", "techflix_episodes", ["video_asset_id"])
        op.create_index("ix_techflix_episodes_topic", "techflix_episodes", ["topic"])
