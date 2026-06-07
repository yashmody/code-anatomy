"""Tests for the Techflix endpoint (GET /api/media/techflix) on the unified model.

A Techflix episode now = a VideoAsset (with an 'original' + 'poster' variant over
media_assets) plus a TechflixVideoMap row. Covers the auth gate, the envelope
shape, and that an inserted episode comes back grouped under its topic with the
right URLs. Runs against the real DB; everything created is torn down.
"""
import io
import os
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.core.db import engine, get_session
from app.core.deps import require_authenticated
from app.core.models import (
    MediaAsset, VideoAsset, VideoVariant, VideoPlacement, TechflixVideoMap,
)
from app.modules.media import service as media_service

client = TestClient(app)


@pytest.fixture
def as_signed_in_user():
    app.dependency_overrides[require_authenticated] = lambda: {"email": "tfx-test@deptagency.com"}
    yield
    app.dependency_overrides.pop(require_authenticated, None)


@pytest.fixture
def techflix_episode():
    """Create a full Techflix episode (asset + original + poster variants + map),
    return its facts, and tear it all down (rows + large objects)."""
    created_assets = []   # (media_asset_id, oid)
    created_videos = []   # video_asset_id

    def _store(blob: bytes, filename: str, mime: str) -> str:
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
            aid, oid = media_service.store_media_asset(path, filename, mime, "")
            created_assets.append((aid, oid))
            return aid
        finally:
            if os.path.exists(path):
                os.remove(path)

    def _png() -> bytes:
        buf = io.BytesIO(); Image.new("RGB", (8, 8), (255, 73, 0)).save(buf, format="PNG")
        return buf.getvalue()

    def _factory(topic, title, *, duration_sec=420, sort_order=0, description=None):
        vid_media = _store(bytes(range(256)) * 8, f"{title}.mp4", "video/mp4")
        poster_media = _store(_png(), f"{title}-poster.png", "image/png")
        va_id = str(uuid.uuid4())
        with get_session() as s:
            s.add(VideoAsset(id=va_id, title=title, description=description, duration_sec=duration_sec))
            s.add(VideoVariant(id=str(uuid.uuid4()), video_asset_id=va_id, media_asset_id=vid_media,
                               kind="original", mime_type="video/mp4", is_primary=True))
            s.add(VideoVariant(id=str(uuid.uuid4()), video_asset_id=va_id, media_asset_id=poster_media,
                               kind="poster", mime_type="image/png"))
            s.add(VideoPlacement(video_asset_id=va_id, surface="techflix"))
            s.add(TechflixVideoMap(video_asset_id=va_id, topic=topic, title=title,
                                   description=description, sort_order=sort_order))
            s.commit()
        created_videos.append(va_id)
        return {"video_asset_id": va_id, "poster_media_id": poster_media, "topic": topic, "title": title}

    yield _factory

    with get_session() as s:
        for va_id in created_videos:
            va = s.get(VideoAsset, va_id)
            if va:
                s.delete(va)  # cascades variants/placements/map
        s.commit()
        for mid, _ in created_assets:
            row = s.get(MediaAsset, mid)
            if row:
                s.delete(row)
        s.commit()
    raw = engine.raw_connection()
    try:
        for _, oid in created_assets:
            try:
                raw.lobject(oid, "n").unlink()
            except Exception:
                pass
        raw.commit()
    finally:
        raw.close()


def test_techflix_requires_authentication():
    assert client.get("/api/media/techflix").status_code == 401


def test_techflix_returns_topics_envelope(as_signed_in_user):
    res = client.get("/api/media/techflix")
    assert res.status_code == 200
    assert isinstance(res.json().get("topics"), list)


def test_techflix_groups_episode_under_topic(as_signed_in_user, techflix_episode):
    ep = techflix_episode("Caching", "Cache Invalidation", duration_sec=420,
                          description="The second hardest problem.")
    res = client.get("/api/media/techflix")
    assert res.status_code == 200
    topics = {t["topic"]: t for t in res.json()["topics"]}
    assert "Caching" in topics
    episode = next((e for e in topics["Caching"]["episodes"] if e["id"] == ep["video_asset_id"]), None)
    assert episode is not None, "inserted episode not listed"
    assert episode["title"] == "Cache Invalidation"
    assert episode["duration_sec"] == 420
    assert episode["video_url"] == f"/media/video/{ep['video_asset_id']}"
    assert episode["poster_url"] == f"/media/image/{ep['poster_media_id']}"
    assert episode["description"] == "The second hardest problem."
