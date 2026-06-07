"""Media storage — MediaAsset metadata lookups.

Asset bytes live in pg_largeobject (handled in `service.py`); the rows in
`media_assets` are just the (asset_id, oid, mime, size) tuple plus an
uploader FK. This module owns the small relational surface; service.py
owns the large-object I/O.
"""
from typing import Optional

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import MediaAsset, TechflixEpisode


def get_asset(asset_id: str) -> Optional[MediaAsset]:
    """Return the MediaAsset row, or None.

    Returns the ORM object because callers (media/routes.py) want to read
    `large_object_oid`, `size_bytes`, and `mime_type` together before
    spinning up a raw connection for the stream. The session is closed
    before return — these fields are loaded eagerly by primary-key get.
    """
    with get_session() as s:
        return s.get(MediaAsset, asset_id)


def list_techflix_episodes() -> list[dict]:
    """Return all Techflix episodes as plain dicts, ordered for grouped display.

    Returns dicts (not ORM objects) so the session can close before
    serialisation — the route groups these by topic. Ordering is
    (topic, sort_order, title) so each topic's episodes come back in author
    order. `video_url`/`poster_url` are the stable stream endpoints the SPA
    renders; the bytes are Range-streamed from `/media/video/{id}`.
    """
    with get_session() as s:
        rows = s.execute(
            select(TechflixEpisode).order_by(
                TechflixEpisode.topic,
                TechflixEpisode.sort_order,
                TechflixEpisode.title,
            )
        ).scalars().all()
        return [
            {
                "id": e.id,
                "topic": e.topic,
                "title": e.title,
                "description": e.description,
                "sort_order": e.sort_order,
                "duration_sec": e.duration_sec,
                "video_url": f"/media/video/{e.video_asset_id}",
                "poster_url": (
                    f"/media/image/{e.poster_asset_id}" if e.poster_asset_id else None
                ),
            }
            for e in rows
        ]
