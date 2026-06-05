"""Media routes — upload (permission: media.upload), range-streaming for video, image.

The upload handler enforces a per-stream byte cap and runs FFprobe / Pillow
validation before the bytes hit pg_largeobject. Most of that lives in
`service.py`; the route is thin — it owns the multipart parsing and the
size-cap guard, then delegates ingest.
"""
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core import config
from app.core.deps import require_permission
from app.modules.media import service as media_service
from app.modules.media import storage as media_storage


router = APIRouter()


@router.post("/api/media/upload")
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_permission("media.upload")),
):
    """Upload a file to PostgreSQL Large Objects with strict type/size/FFmpeg resolution validation."""
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

        # 4. Ingest into PostgreSQL Large Objects
        asset_id, oid = media_service.store_media_asset(
            temp_path, file.filename, mime_type, user["email"]
        )

        # Generate the access endpoints
        endpoint = f"/media/video/{asset_id}" if is_video else f"/media/image/{asset_id}"
        return {"status": "success", "asset_id": asset_id, "url": endpoint}

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/media/video/{asset_id}")
async def stream_video(request: Request, asset_id: str):
    """Stream videos from PostgreSQL large objects supporting HTTP Range requests (scrubbing)."""
    asset = media_storage.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    oid = asset.large_object_oid
    size = asset.size_bytes
    mime = asset.mime_type

    range_header = request.headers.get("Range")
    if not range_header:
        # Request full file
        generator = media_service.stream_video_chunks(oid, 0, size - 1)
        return StreamingResponse(generator, media_type=mime)

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
    }

    generator = media_service.stream_video_chunks(oid, start, end)
    return StreamingResponse(generator, status_code=206, headers=headers, media_type=mime)


@router.get("/media/image/{asset_id}")
async def serve_image(asset_id: str):
    """Serve images stored inside PostgreSQL Large Objects."""
    asset = media_storage.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    oid = asset.large_object_oid
    size = asset.size_bytes
    mime = asset.mime_type

    generator = media_service.stream_video_chunks(oid, 0, size - 1)
    return StreamingResponse(generator, media_type=mime)
