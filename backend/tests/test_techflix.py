"""Tests for the Techflix library endpoint (GET /api/media/techflix).

Covers:
  - auth gate: unauthenticated /api request → 401 (not a redirect),
  - shape: authenticated request → 200 with a {"topics": [...]} envelope,
  - grouping: an inserted episode comes back under its topic with the right
    video_url / poster_url / duration.

Runs against the real configured database (Postgres in dev — large objects and
the techflix_episodes table only exist there). Every row/large-object it
creates is torn down, so repeat runs don't leak.
"""
import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.core.db import engine, get_session
from app.core.deps import require_authenticated
from app.core.models import MediaAsset, TechflixEpisode
from app.modules.media import service as media_service

client = TestClient(app)


@pytest.fixture
def as_signed_in_user():
    """Override the auth dependency so the route sees a signed-in learner.

    `require_authenticated` is a plain dependency function, so it can be
    overridden directly — no session cookie / dev-login round trip needed."""
    app.dependency_overrides[require_authenticated] = lambda: {
        "email": "techflix-test@deptagency.com"
    }
    yield
    app.dependency_overrides.pop(require_authenticated, None)


@pytest.fixture
def episode_factory():
    """Create a full Techflix episode (video asset + poster asset + row) and
    tear it all down afterwards. Yields a callable (topic, title, **kw) -> dict."""
    created_assets = []   # (asset_id, oid)
    created_episodes = []  # episode id

    def _png_bytes() -> bytes:
        img = Image.new("RGB", (8, 8), (255, 73, 0))  # DEPT ochre, why not
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _store(blob: bytes, filename: str, mime: str) -> str:
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
            asset_id, oid = media_service.store_media_asset(path, filename, mime, "")
            created_assets.append((asset_id, oid))
            return asset_id
        finally:
            if os.path.exists(path):
                os.remove(path)

    def _factory(topic: str, title: str, *, duration_sec=420, with_poster=True,
                 sort_order=0, description=None) -> dict:
        video_id = _store(bytes(range(256)) * 8, f"{title}.mp4", "video/mp4")
        poster_id = _store(_png_bytes(), f"{title}-poster.png", "image/png") if with_poster else None
        ep_id = f"test-ep-{video_id}"
        with get_session() as s:
            s.add(TechflixEpisode(
                id=ep_id, video_asset_id=video_id, poster_asset_id=poster_id,
                topic=topic, title=title, description=description,
                sort_order=sort_order, duration_sec=duration_sec,
            ))
            s.commit()
        created_episodes.append(ep_id)
        return {"id": ep_id, "video_id": video_id, "poster_id": poster_id,
                "topic": topic, "title": title}

    yield _factory

    # Teardown: episodes first (FK), then asset rows, then unlink large objects.
    with get_session() as s:
        for ep_id in created_episodes:
            row = s.get(TechflixEpisode, ep_id)
            if row:
                s.delete(row)
        for asset_id, _ in created_assets:
            row = s.get(MediaAsset, asset_id)
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
    """An unauthenticated /api/ request is rejected with 401 (JSON), not a redirect."""
    res = client.get("/api/media/techflix")
    assert res.status_code == 401


def test_techflix_returns_topics_envelope(as_signed_in_user):
    """Authenticated request returns 200 with a {topics: [...]} shape."""
    res = client.get("/api/media/techflix")
    assert res.status_code == 200
    body = res.json()
    assert "topics" in body and isinstance(body["topics"], list)


def test_techflix_groups_episode_under_topic(as_signed_in_user, episode_factory):
    """An inserted episode appears under its topic with the right URLs + duration."""
    ep = episode_factory("Caching", "Cache Invalidation", duration_sec=420,
                          description="The second hardest problem.")

    res = client.get("/api/media/techflix")
    assert res.status_code == 200
    topics = {t["topic"]: t for t in res.json()["topics"]}

    assert "Caching" in topics, "topic group missing"
    episode = next((e for e in topics["Caching"]["episodes"] if e["id"] == ep["id"]), None)
    assert episode is not None, "inserted episode not listed"
    assert episode["title"] == "Cache Invalidation"
    assert episode["duration_sec"] == 420
    assert episode["video_url"] == f"/media/video/{ep['video_id']}"
    assert episode["poster_url"] == f"/media/image/{ep['poster_id']}"
    assert episode["description"] == "The second hardest problem."
