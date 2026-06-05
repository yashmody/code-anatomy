"""Media storage — MediaAsset metadata lookups.

Asset bytes live in pg_largeobject (handled in `service.py`); the rows in
`media_assets` are just the (asset_id, oid, mime, size) tuple plus an
uploader FK. This module owns the small relational surface; service.py
owns the large-object I/O.
"""
from typing import Optional

from app.core.db import get_session
from app.core.models import MediaAsset


def get_asset(asset_id: str) -> Optional[MediaAsset]:
    """Return the MediaAsset row, or None.

    Returns the ORM object because callers (media/routes.py) want to read
    `large_object_oid`, `size_bytes`, and `mime_type` together before
    spinning up a raw connection for the stream. The session is closed
    before return — these fields are loaded eagerly by primary-key get.
    """
    with get_session() as s:
        return s.get(MediaAsset, asset_id)
