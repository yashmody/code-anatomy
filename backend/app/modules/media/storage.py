"""Media storage — resolvers over the unified video model + raw file lookups.

Layering (migration 0014):
  media_assets   physical files (large objects)
  video_asset    one logical video  ── video_variant ─→ media_assets (original/poster/…)
  techflix_video_map / content_video_map / social_feed_video   usage

The serve routes call `resolve_playable` / `resolve_image`, which accept either a
video_asset **id or slug** (preferred) or a legacy **media_asset id** (back-compat
for any old `/media/video/{media_asset_id}` links). Everything returns plain
dicts with the session already closed.
"""
from typing import List, Optional

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import (
    MediaAsset, VideoAsset, VideoVariant, TechflixVideoMap,
)


def _file_dict(ma: MediaAsset) -> dict:
    return {"oid": ma.large_object_oid, "mime": ma.mime_type, "size": ma.size_bytes}


def _primary_variant(s, video_asset_id: str) -> Optional[VideoVariant]:
    """The primary (or, failing that, the 'original') variant of an asset."""
    return (
        s.scalar(select(VideoVariant).where(
            VideoVariant.video_asset_id == video_asset_id, VideoVariant.is_primary.is_(True)))
        or s.scalar(select(VideoVariant).where(
            VideoVariant.video_asset_id == video_asset_id, VideoVariant.kind == "original"))
    )


def _video_asset_by_ref(s, ref: str) -> Optional[VideoAsset]:
    """Resolve a ref to a VideoAsset by primary-key id, else by slug."""
    return s.get(VideoAsset, ref) or s.scalar(select(VideoAsset).where(VideoAsset.slug == ref))


def resolve_playable(ref: str) -> Optional[dict]:
    """Resolve a video ref to its playable file {oid, mime, size}.

    ref = video_asset id | video_asset slug | (legacy) media_asset id.
    Returns None if nothing resolves.
    """
    with get_session() as s:
        va = _video_asset_by_ref(s, ref)
        if va:
            v = _primary_variant(s, va.id)
            if v:
                ma = s.get(MediaAsset, v.media_asset_id)
                if ma:
                    return _file_dict(ma)
        ma = s.get(MediaAsset, ref)  # legacy direct-file fallback
        if ma:
            return _file_dict(ma)
    return None


def resolve_image(ref: str) -> Optional[dict]:
    """Resolve an image ref to a file {oid, mime, size}.

    ref = media_asset id (a poster/image file) | video_asset id/slug (→ its poster).
    """
    with get_session() as s:
        ma = s.get(MediaAsset, ref)
        if ma:
            return _file_dict(ma)
        va = _video_asset_by_ref(s, ref)
        if va:
            v = s.scalar(select(VideoVariant).where(
                VideoVariant.video_asset_id == va.id, VideoVariant.kind == "poster"))
            if v:
                ma = s.get(MediaAsset, v.media_asset_id)
                if ma:
                    return _file_dict(ma)
    return None


def list_techflix_episodes() -> List[dict]:
    """Techflix episodes (techflix_video_map ⋈ video_asset ⋈ poster variant).

    Ordered (topic, sort_order, title). `video_url` prefers the asset slug so the
    URL is stable across environments; `poster_url` points at the poster file.
    """
    with get_session() as s:
        maps = s.execute(
            select(TechflixVideoMap).order_by(
                TechflixVideoMap.topic, TechflixVideoMap.sort_order)
        ).scalars().all()
        out: List[dict] = []
        for m in maps:
            va = s.get(VideoAsset, m.video_asset_id)
            if not va:
                continue
            poster = s.scalar(select(VideoVariant).where(
                VideoVariant.video_asset_id == va.id, VideoVariant.kind == "poster"))
            out.append({
                "id": va.id,
                "topic": m.topic,
                "title": m.title or va.title,
                "description": m.description or va.description,
                "sort_order": m.sort_order,
                "duration_sec": va.duration_sec,
                "video_url": f"/media/video/{va.slug or va.id}",
                "poster_url": (f"/media/image/{poster.media_asset_id}" if poster else None),
            })
        # maps already ordered by topic, sort_order; keep stable title tiebreak
        out.sort(key=lambda e: (e["topic"], e["sort_order"], e["title"] or ""))
        return out
