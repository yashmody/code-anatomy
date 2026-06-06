"""Regression tests for the media serve path (modules/media).

Why this file exists
--------------------
`stream_video_chunks` used to open the Postgres large object in TEXT mode
(`lobject(oid, 'r')`). psycopg2 then tried to UTF-8-decode every read, which
throws on the first non-UTF-8 byte — e.g. a PNG's 0x89 signature. The
exception was swallowed inside the generator, so `GET /media/image/{id}`
silently returned a 200 with a ZERO-byte body for any binary image. No test
covered binary serving, so it went undetected.

The fix opened the read in binary mode (`'rb'`); the write side was hardened
to match (`'wb'`). These tests lock both in: they store real binary media
(bytes that are NOT valid UTF-8) and assert the serve endpoints return the
content byte-for-byte, not an empty stream.

These tests talk to the real configured database (Postgres in dev — large
objects don't exist on sqlite). Each stored asset is torn down (metadata row
deleted + large object unlinked) so repeated runs don't leak rows or OIDs.
"""
import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.core.db import engine, get_session
from app.core.models import MediaAsset
from app.modules.media import service as media_service

client = TestClient(app)


def _make_png_bytes() -> bytes:
    """A small but real PNG. Starts with 0x89 — the exact byte that broke the
    text-mode read — and contains a spread of non-UTF-8 bytes in the body."""
    img = Image.new("RGB", (16, 16))
    for x in range(16):
        for y in range(16):
            img.putpixel((x, y), ((x * 16) % 256, (y * 16) % 256, (x * y) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"  # guard: real PNG signature
    return data


def _store_blob(blob: bytes, filename: str, mime_type: str):
    """Persist `blob` via the production write path and return its asset id."""
    fd, path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        # uploader_email="" -> uploaded_by NULL; avoids needing a real user row.
        asset_id, oid = media_service.store_media_asset(path, filename, mime_type, "")
        return asset_id, oid
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture
def stored_media():
    """Factory that stores a blob and guarantees teardown.

    Yields a callable (blob, filename, mime_type) -> asset_id. Every asset it
    creates has its metadata row deleted and its large object unlinked when the
    test finishes, pass or fail."""
    created = []  # list[(asset_id, oid)]

    def _factory(blob: bytes, filename: str, mime_type: str) -> str:
        asset_id, oid = _store_blob(blob, filename, mime_type)
        created.append((asset_id, oid))
        return asset_id

    yield _factory

    # Teardown — drop metadata rows, then unlink the large objects.
    for asset_id, _ in created:
        with get_session() as s:
            row = s.get(MediaAsset, asset_id)
            if row:
                s.delete(row)
                s.commit()
    raw = engine.raw_connection()
    try:
        for _, oid in created:
            try:
                raw.lobject(oid, "n").unlink()
            except Exception:
                pass  # already gone / never created
        raw.commit()
    finally:
        raw.close()


def test_image_serve_is_byte_identical(stored_media):
    """GET /media/image/{id} must return the stored bytes exactly — not empty.

    This is the direct regression for the text-mode read bug: under the old
    code this body was 0 bytes."""
    png = _make_png_bytes()
    asset_id = stored_media(png, "regression.png", "image/png")

    res = client.get(f"/media/image/{asset_id}")

    assert res.status_code == 200
    assert len(res.content) > 0, "serve path returned an empty body (the bug)"
    assert res.content == png, "served bytes are not byte-for-byte identical"
    assert res.headers["content-type"].startswith("image/png")


def test_video_range_serve_returns_206_partial(stored_media):
    """GET /media/video/{id} with a Range header must return 206 + the correct
    Content-Range, and the partial bytes must match the stored slice exactly."""
    # A binary blob with deliberately non-UTF-8 bytes throughout, so a text-mode
    # read would throw on it. Content isn't probed on the serve path, so it need
    # not be a real container — we're testing range streaming, not validation.
    blob = bytes((i * 7 + 0x80) % 256 for i in range(2048))
    asset_id = stored_media(blob, "regression.mp4", "video/mp4")

    start, end = 100, 599  # a 500-byte window, not aligned to the 256 KiB chunk
    res = client.get(
        f"/media/video/{asset_id}",
        headers={"Range": f"bytes={start}-{end}"},
    )

    assert res.status_code == 206
    assert res.headers["content-range"] == f"bytes {start}-{end}/{len(blob)}"
    assert res.headers["accept-ranges"] == "bytes"
    assert res.headers["content-length"] == str(end - start + 1)
    assert res.content == blob[start : end + 1], "partial bytes do not match"


def test_video_full_serve_is_byte_identical(stored_media):
    """No Range header -> full 200 stream, byte-identical. Guards the other
    branch of stream_video that also goes through stream_video_chunks."""
    blob = bytes((i * 13 + 0x90) % 256 for i in range(4096))
    asset_id = stored_media(blob, "regression-full.mp4", "video/mp4")

    res = client.get(f"/media/video/{asset_id}")

    assert res.status_code == 200
    assert res.content == blob
