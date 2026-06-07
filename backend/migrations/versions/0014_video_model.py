"""0014_video_model — unified video model (asset / variant / placement / usage maps)

Introduces a normalised video model layered over the existing `media_assets`
byte store (Postgres large objects), per the agreed design:

    media_assets        physical files (KEPT — one row = one large object)
    video_asset         one logical video
    video_variant       renditions of an asset, each → a media_assets file
                        (kind: original | poster | thumbnail | hls | mp4_720 …)
    video_placement     which surfaces an asset may appear on (content|techflix|feed)
    techflix_video_map  Techflix section metadata (supersedes techflix_episodes)
    content_video_map   which chapter/block embeds a video
    social_feed_video   feed UGC metadata, links a feed_item

Additive + idempotent. Backfills the new model from existing `media_assets`
(videos → asset+original variant) and `techflix_episodes` (→ techflix_video_map
+ poster variant + placement) so current prod data carries over. The legacy
`techflix_episodes` table is left in place (read no more after code switch) and
dropped in a later migration once verified.

Revision ID: 0014_video_model
Revises: 0013_whats_new
Create Date: 2026-06-07
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_video_model"
down_revision: Union[str, Sequence[str], None] = "0013_whats_new"
branch_labels = None
depends_on = None


def _has(insp, name) -> bool:
    return name in set(insp.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # ── video_asset ──────────────────────────────────────────────────────────
    if not _has(insp, "video_asset"):
        op.create_table(
            "video_asset",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("slug", sa.String(128), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("duration_sec", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="ready"),
            sa.Column("uploaded_by", sa.String(255),
                      sa.ForeignKey("users.email", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_unique_constraint("uq_video_asset_slug", "video_asset", ["slug"])

    # ── video_variant ────────────────────────────────────────────────────────
    if not _has(insp, "video_variant"):
        op.create_table(
            "video_variant",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("video_asset_id", sa.String(64),
                      sa.ForeignKey("video_asset.id", ondelete="CASCADE"), nullable=False),
            sa.Column("media_asset_id", sa.String(64),
                      sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),  # original|poster|thumbnail|hls|mp4_720…
            sa.Column("mime_type", sa.String(64), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_unique_constraint("uq_video_variant_asset_kind", "video_variant",
                                    ["video_asset_id", "kind"])
        op.create_index("idx_video_variant_asset", "video_variant", ["video_asset_id"])

    # ── video_placement ──────────────────────────────────────────────────────
    if not _has(insp, "video_placement"):
        op.create_table(
            "video_placement",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("video_asset_id", sa.String(64),
                      sa.ForeignKey("video_asset.id", ondelete="CASCADE"), nullable=False),
            sa.Column("surface", sa.String(16), nullable=False),  # content|techflix|feed
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_unique_constraint("uq_video_placement", "video_placement",
                                    ["video_asset_id", "surface"])

    # ── content_video_map ────────────────────────────────────────────────────
    if not _has(insp, "content_video_map"):
        op.create_table(
            "content_video_map",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("video_asset_id", sa.String(64),
                      sa.ForeignKey("video_asset.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chapter", sa.String(128), nullable=True),    # e.g. code-c.json
            sa.Column("block_ref", sa.String(128), nullable=True),  # block id within chapter
            sa.Column("caption", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_content_video_map_asset", "content_video_map", ["video_asset_id"])

    # ── techflix_video_map ───────────────────────────────────────────────────
    if not _has(insp, "techflix_video_map"):
        op.create_table(
            "techflix_video_map",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("video_asset_id", sa.String(64),
                      sa.ForeignKey("video_asset.id", ondelete="CASCADE"), nullable=False),
            sa.Column("topic", sa.String(128), nullable=False),
            sa.Column("title", sa.String(255), nullable=True),       # override; else video_asset.title
            sa.Column("description", sa.Text(), nullable=True),      # override
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_unique_constraint("uq_techflix_map_asset", "techflix_video_map", ["video_asset_id"])
        op.create_index("idx_techflix_map_topic", "techflix_video_map", ["topic"])

    # ── social_feed_video ────────────────────────────────────────────────────
    if not _has(insp, "social_feed_video"):
        op.create_table(
            "social_feed_video",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("feed_item_id", sa.String(64),
                      sa.ForeignKey("feed_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("video_asset_id", sa.String(64),
                      sa.ForeignKey("video_asset.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_unique_constraint("uq_social_feed_video_item", "social_feed_video", ["feed_item_id"])

    _backfill(bind)


def _backfill(bind) -> None:
    """Populate the new model from media_assets + techflix_episodes. Idempotent:
    runs only when video_asset is empty (a fresh model)."""
    existing = bind.execute(sa.text("SELECT count(*) FROM video_asset")).scalar()
    if existing:
        return

    insp = sa.inspect(bind)
    media_to_asset: dict[str, str] = {}

    # 1. Every video media_asset → a video_asset + an 'original' variant.
    vids = bind.execute(sa.text(
        "SELECT id, filename, mime_type, uploaded_by, uploaded_at "
        "FROM media_assets WHERE mime_type LIKE 'video/%'"
    )).mappings().all()
    for m in vids:
        va = str(uuid.uuid4())
        bind.execute(sa.text(
            "INSERT INTO video_asset (id, title, status, uploaded_by, created_at, updated_at) "
            "VALUES (:id, :title, 'ready', :ub, COALESCE(:ts, now()), now())"
        ), {"id": va, "title": (m["filename"] or "Untitled"), "ub": m["uploaded_by"], "ts": m["uploaded_at"]})
        bind.execute(sa.text(
            "INSERT INTO video_variant (id, video_asset_id, media_asset_id, kind, mime_type, is_primary, created_at) "
            "VALUES (:id, :va, :ma, 'original', :mime, true, now())"
        ), {"id": str(uuid.uuid4()), "va": va, "ma": m["id"], "mime": m["mime_type"]})
        media_to_asset[m["id"]] = va

    # 2. techflix_episodes → techflix_video_map (+ poster variant + placement).
    if _has(insp, "techflix_episodes"):
        eps = bind.execute(sa.text(
            "SELECT video_asset_id, poster_asset_id, topic, title, description, sort_order, duration_sec "
            "FROM techflix_episodes"
        )).mappings().all()
        for e in eps:
            va = media_to_asset.get(e["video_asset_id"])
            if not va:
                continue  # video file row missing — skip defensively
            bind.execute(sa.text(
                "UPDATE video_asset SET title=:t, description=:d, duration_sec=:dur WHERE id=:va"
            ), {"t": e["title"], "d": e["description"], "dur": e["duration_sec"], "va": va})
            if e["poster_asset_id"]:
                bind.execute(sa.text(
                    "INSERT INTO video_variant (id, video_asset_id, media_asset_id, kind, mime_type, is_primary, created_at) "
                    "VALUES (:id, :va, :ma, 'poster', 'image/jpeg', false, now()) "
                    "ON CONFLICT ON CONSTRAINT uq_video_variant_asset_kind DO NOTHING"
                ), {"id": str(uuid.uuid4()), "va": va, "ma": e["poster_asset_id"]})
            bind.execute(sa.text(
                "INSERT INTO techflix_video_map (video_asset_id, topic, sort_order, created_at, updated_at) "
                "VALUES (:va, :topic, :so, now(), now())"
            ), {"va": va, "topic": e["topic"], "so": e["sort_order"] or 0})
            bind.execute(sa.text(
                "INSERT INTO video_placement (video_asset_id, surface, created_at) "
                "VALUES (:va, 'techflix', now())"
            ), {"va": va})

    # 3. Any video asset not placed in techflix → default 'content' placement.
    bind.execute(sa.text(
        "INSERT INTO video_placement (video_asset_id, surface, created_at) "
        "SELECT va.id, 'content', now() FROM video_asset va "
        "WHERE NOT EXISTS (SELECT 1 FROM video_placement p WHERE p.video_asset_id = va.id)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for t in ("social_feed_video", "techflix_video_map", "content_video_map",
              "video_placement", "video_variant", "video_asset"):
        if _has(insp, t):
            op.drop_table(t)
