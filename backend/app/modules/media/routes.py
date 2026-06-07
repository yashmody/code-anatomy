"""Media routes — upload (permission: media.upload), range-streaming for video, image.

The upload handler enforces a per-stream byte cap and runs FFprobe / Pillow
validation before the bytes hit pg_largeobject. Most of that lives in
`service.py`; the route is thin — it owns the multipart parsing and the
size-cap guard, then delegates ingest.
"""
import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core import config
from app.core.deps import require_authenticated, require_permission
from app.modules.media import service as media_service
from app.modules.media import storage as media_storage


router = APIRouter()


@router.get("/api/media/techflix")
async def list_techflix(user=Depends(require_authenticated)):
    """Techflix library — video episodes grouped by topic, for any signed-in user.

    Read-only editorial view over `media_assets`: returns topics in author
    order, each with its episodes (title, description, duration, poster, and the
    stable `/media/video/{id}` stream URL). The bytes themselves are served —
    with HTTP Range support — by `stream_video` below. Populated by
    `scripts/upload_media.py` from a `techflix.json` manifest.
    """
    episodes = media_storage.list_techflix_episodes()
    topics: dict[str, list] = {}
    for ep in episodes:
        topics.setdefault(ep["topic"], []).append(ep)
    # `episodes` is already ordered by (topic, sort_order, title), so dict
    # insertion order reflects the intended topic order without a second sort.
    return {"topics": [{"topic": t, "episodes": eps} for t, eps in topics.items()]}


@router.post("/api/media/upload")
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    surface: str = Form("feed"),
    title: str = Form(None),
    user=Depends(require_permission("media.upload")),
):
    """Upload a file with strict type/size/FFmpeg validation.

    Video → ingested into the unified model (video_asset + 'original' variant +
    auto poster + duration) on the given `surface` (default 'feed' — the UI path).
    Returns `video_asset_id` so the caller (e.g. the feed composer) can attach it.
    Image → stored as a plain media_asset (e.g. a feed image). The response keeps
    `asset_id` for back-compat.
    """
    # 1. Read headers for type spoofing protection
    head_bytes = await file.read(2048)  # Read signature block
    await file.seek(0)  # Reset pointer

    mime_type = media_service.detect_mime_type(head_bytes)
    if not mime_type:
        raise HTTPException(status_code=400, detail="Unsupported file format or header mismatch")

    # Check limit boundaries
    is_video = mime_type.startswith("video/")
    max_size = (
        config.MAX_VIDEO_SIZE_MB * 1024 * 1024
        if is_video
        else config.MAX_IMAGE_SIZE_MB * 1024 * 1024
    )

    # 2. Enforce stream-level size caps
    temp_fd, temp_path = tempfile.mkstemp()
    bytes_written = 0
    try:
        with os.fdopen(temp_fd, "wb") as tmp:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds size boundary (Max: {max_size / (1024*1024):.1f}MB)",
                    )
                tmp.write(chunk)

        # 3. Perform specific quality and metadata checks locally
        if is_video:
            valid, err = media_service.validate_video(temp_path)
            if not valid:
                raise HTTPException(status_code=400, detail=err)
        else:
            valid, err = media_service.validate_image(temp_path)
            if not valid:
                raise HTTPException(status_code=400, detail=err)

        # 4. Ingest
        if is_video:
            video_asset_id = media_service.ingest_video(
                temp_path, title=(title or file.filename), mime_type=mime_type,
                uploaded_by=user["email"], surfaces=(surface or "feed",),
            )
            return {
                "status": "success",
                "video_asset_id": video_asset_id,
                "asset_id": video_asset_id,          # back-compat alias
                "url": f"/media/video/{video_asset_id}",
            }
        # Images stay plain media_assets (e.g. feed images).
        asset_id, _ = media_service.store_media_asset(
            temp_path, file.filename, mime_type, user["email"]
        )
        return {"status": "success", "asset_id": asset_id, "url": f"/media/image/{asset_id}"}

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/media/video/{ref}")
async def stream_video(request: Request, ref: str):
    """Stream a video with HTTP Range support. `ref` = video_asset id or slug
    (preferred), or a legacy media_asset id. Resolves to the primary variant."""
    info = media_storage.resolve_playable(ref)
    if not info:
        raise HTTPException(status_code=404, detail="Asset not found")
    oid, size, mime = info["oid"], info["size"], info["mime"]

    range_header = request.headers.get("Range")
    if not range_header:
        # Request full file. `Content-Encoding: identity` opts this response out
        # of GZipMiddleware — video is already compressed, and gzip on a stream
        # strips Content-Length and breaks Range/scrubbing. Advertise Range too.
        generator = media_service.stream_video_chunks(oid, 0, size - 1)
        return StreamingResponse(
            generator, media_type=mime,
            headers={"Content-Encoding": "identity", "Accept-Ranges": "bytes"},
        )

    try:
        range_str = range_header.replace("bytes=", "")
        start_str, end_str = range_str.split("-")
        start = int(start_str)
        end = int(end_str) if end_str else size - 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Range header")

    if start >= size or end >= size or start > end:
        raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")

    headers = {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        # Opt out of GZipMiddleware: it would drop Content-Length and re-encode
        # the partial body, breaking Range semantics (and gzipping already-
        # compressed video wastes CPU). identity = no transformation.
        "Content-Encoding": "identity",
    }

    generator = media_service.stream_video_chunks(oid, start, end)
    return StreamingResponse(generator, status_code=206, headers=headers, media_type=mime)


@router.get("/media/image/{ref}")
async def serve_image(ref: str):
    """Serve an image. `ref` = media_asset id (a poster/image file), or a
    video_asset id/slug (→ its poster variant)."""
    info = media_storage.resolve_image(ref)
    if not info:
        raise HTTPException(status_code=404, detail="Asset not found")
    oid, size, mime = info["oid"], info["size"], info["mime"]

    # `Content-Encoding: identity` keeps GZipMiddleware off already-compressed
    # image bytes (gzip would only waste CPU and drop Content-Length).
    generator = media_service.stream_video_chunks(oid, 0, size - 1)
    return StreamingResponse(
        generator, media_type=mime, headers={"Content-Encoding": "identity"}
    )
