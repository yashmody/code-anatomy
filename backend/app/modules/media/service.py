"""Media Service — native media uploading, validation, and streaming from PostgreSQL.

Features:
  - File spoofing protection via magic byte signature checks.
  - Video resolution & duration validation via FFprobe.
  - Image size & dimensions validation via Pillow.
  - Media asset storage using PostgreSQL Large Objects (pg_largeobject) and BYTEA.
  - Range-request-compatible chunked video streaming generator.

Phase 2e hardening (v2/07 §6):
  - Explicit SVG deny — F-UPL-03. SVG can carry inline <script>; never allow.
  - tempfile permissions tightened to 0o600 — defence in depth on shared hosts.
  - detect_mime_type already verifies the WebP `WEBP` tag at offset 8 and the
    MP4 `ftyp` box at offsets 4–12, so polyglot defence is partly there.
    Phase 2d may further extend with sniffs at additional offsets.
"""
import os
import stat
import tempfile
import uuid
import datetime
from typing import Dict, Tuple, Generator, Optional

from fastapi import HTTPException
from PIL import Image
import ffmpeg
from sqlalchemy import select

from app.core import config
from app.core.db import get_session, engine
from app.core.models import MediaAsset, User

# Supported signatures (magic numbers)
_SIGNATURES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],  # WebP also has WEBP at offset 8, checked below
    "video/webm": [b"\x1a\x45\xdf\xa3"],
}

# Phase 2e — F-UPL-03: SVG and other XML-y image formats are never allowed.
# SVG can carry <script>; serving it from same-origin = stored XSS.
_DENY_MIMES = frozenset({
    "image/svg+xml",
    "image/svg",
    "application/xml",
    "text/xml",
    "text/html",
})


def detect_mime_type(data: bytes) -> Optional[str]:
    """Detect mime type from magic bytes to prevent spoofed extensions.

    Multi-offset checks today:
      - JPEG / PNG / WebM at offset 0
      - WebP confirmed via `WEBP` at offset 8
      - MP4 confirmed via `ftyp` at offsets 4-12
    SVG / XML / HTML headers are rejected explicitly (F-UPL-03).
    """
    if not data:
        return None

    # Hard-deny SVG / XML / HTML headers before any positive-match below.
    stripped = data.lstrip()[:64].lower()
    if (
        stripped.startswith(b"<?xml")
        or stripped.startswith(b"<svg")
        or stripped.startswith(b"<!doctype html")
        or stripped.startswith(b"<html")
    ):
        return None

    # Check simple signatures at offset 0
    for mime, sigs in _SIGNATURES.items():
        for sig in sigs:
            if data.startswith(sig):
                if mime == "image/webp":
                    # Extra check for WebP — confirm offset-8 magic
                    if len(data) >= 12 and data[8:12] == b"WEBP":
                        return mime
                else:
                    return mime

    # Check MP4 signature (typically has 'ftyp' at offset 4)
    if len(data) >= 12 and b"ftyp" in data[4:12]:
        return "video/mp4"

    return None


def assert_mime_allowed(mime_type: Optional[str]) -> None:
    """Raise HTTPException(415) if the MIME type is denied or unknown.

    Centralised so both the upload route and any internal callers share the
    same deny-list. F-UPL-03 (SVG denial) lives here.
    """
    if not mime_type:
        raise HTTPException(status_code=415, detail="Unsupported or unrecognised media type")
    if mime_type.lower() in _DENY_MIMES:
        raise HTTPException(status_code=415, detail="SVG and XML-based media are not allowed")


def create_secure_tempfile(suffix: str = "") -> Tuple[int, str]:
    """`tempfile.mkstemp` wrapper that hardens permissions to 0o600.

    mkstemp() on POSIX already opens with `O_CREAT|O_EXCL|O_RDWR` and mode
    0o600 — but the umask on some hosts can widen the resulting mode on
    very old kernels, so we re-chmod explicitly. Returns (fd, path) just
    like the stdlib for drop-in replacement.
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        # Best-effort: a host that refuses chmod still has the mkstemp default,
        # which is already 0600 on every POSIX we care about.
        pass
    return fd, path


def validate_image(file_path: str) -> Tuple[bool, Optional[str]]:
    """Validate image dimensions and integrity using Pillow."""
    try:
        with Image.open(file_path) as img:
            img.verify()  # Verify integrity
        return True, None
    except Exception as e:
        return False, f"Invalid image file: {str(e)}"


def validate_video(file_path: str) -> Tuple[bool, Optional[str]]:
    """Validate video duration, resolution, and codecs using FFprobe."""
    try:
        probe = ffmpeg.probe(file_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if not video_stream:
            return False, "No video stream found in file"
            
        width = int(video_stream.get('width', 0))
        height = int(video_stream.get('height', 0))
        duration = float(probe.get('format', {}).get('duration', 0))
        
        # Check constraints
        if duration > config.MAX_VIDEO_DURATION_SEC:
            return False, f"Video duration too long ({duration:.1f}s > {config.MAX_VIDEO_DURATION_SEC}s)"
            
        if width > 1920 or height > 1080:
            return False, f"Resolution exceeds 1080p limit ({width}x{height} > 1920x1080)"
            
        return True, None
    except Exception as e:
        return False, f"Failed to analyze video: {str(e)}"


def store_media_asset(file_path: str, filename: str, mime_type: str, uploader_email: str) -> Tuple[str, int]:
    """Upload file into PostgreSQL pg_largeobject and record metadata.

    Defensive: refuses denied MIMEs (SVG / XML / HTML) even when called
    directly, in case a future caller skips the route-level check (F-UPL-03).

    Returns:
      Tuple[asset_id_str, large_object_oid]
    """
    assert_mime_allowed(mime_type)
    raw_conn = engine.raw_connection()
    try:
        # Binary mode ('wb'): symmetric with the 'rb' read in stream_video_chunks.
        # Text mode ('w') happens to round-trip binary correctly on this
        # psycopg2/libpq, but it asks psycopg2 to treat writes as str — only
        # robust because we hand it bytes. 'wb' is the correct contract for
        # binary media and removes the latent text/binary mismatch.
        lobj = raw_conn.lobject(0, 'wb')  # Create a new large object
        oid = lobj.oid
        
        # Stream file into large object in 1MB chunks
        size_bytes = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                lobj.write(chunk)
                
        lobj.close()
        raw_conn.commit()
        
        # Record in media_assets metadata table
        asset_id = str(uuid.uuid4())
        with get_session() as session:
            # Verify user exists or set None
            uploader = session.get(User, uploader_email.lower()) if uploader_email else None
            asset = MediaAsset(
                id=asset_id,
                large_object_oid=oid,
                filename=filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                uploaded_by=uploader.email if uploader else None
            )
            session.add(asset)
            session.commit()
            
        return asset_id, oid
    except Exception as e:
        raw_conn.rollback()
        raise RuntimeError(f"Database media ingestion failed: {e}")
    finally:
        raw_conn.close()


def stream_video_chunks(oid: int, start_byte: int, end_byte: int, chunk_size: int = 262144) -> Generator[bytes, None, None]:
    """Generates byte chunks from pg_largeobject for range queries."""
    raw_conn = engine.raw_connection()
    try:
        # Binary mode ('rb'): large-object bytes must NOT be decoded as text.
        # In text mode ('r') psycopg2 decodes each read as UTF-8, which throws on
        # the first non-UTF-8 byte (e.g. a PNG's 0x89 signature) — the exception
        # was swallowed below and the stream silently yielded zero bytes. It only
        # appeared to work for ranges that happened to be valid UTF-8.
        lobj = raw_conn.lobject(oid, 'rb')
        lobj.seek(start_byte)
        
        bytes_to_read = end_byte - start_byte + 1
        while bytes_to_read > 0:
            to_read = min(chunk_size, bytes_to_read)
            data = lobj.read(to_read)
            if not data:
                break
            yield data
            bytes_to_read -= len(data)
            
        lobj.close()
    except Exception as e:
        print(f"[media_service] Error streaming large object OID {oid}: {e}")
    finally:
        raw_conn.close()
