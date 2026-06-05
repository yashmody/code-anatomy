"""List all media in PostgreSQL and print their streaming URLs.

Usage:
    python -m scripts.list_media                              # default base: http://localhost:8000
    python -m scripts.list_media --base https://example.com   # use a different host
    python -m scripts.list_media --json                       # machine-readable output

URL routing (matches quiz-certification/app/main.py):
    video/*   →  {base}/media/video/{asset_id}    (HTTP Range — scrubbing works)
    image/*   →  {base}/media/image/{asset_id}
    other     →  {base}/media/video/{asset_id}    (falls through to the stream endpoint)
"""
import argparse
import json
import os
import sys

# Path setup so this runs as `python -m scripts.list_media`
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.core import config
from app.core.db import get_session, init_db
from app.core.models import MediaAsset


def url_for(base: str, asset) -> str:
    mime = (asset.mime_type or "").lower()
    if mime.startswith("video/"):
        return f"{base}/media/video/{asset.id}"
    if mime.startswith("image/"):
        return f"{base}/media/image/{asset.id}"
    # Fallback — the stream endpoint serves any MIME via StreamingResponse
    return f"{base}/media/video/{asset.id}"


def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description="List all media in PostgreSQL with their streaming URLs.")
    parser.add_argument(
        "--base",
        default="http://localhost:8000",
        help="Base URL prefix for the streaming endpoints (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a table",
    )
    args = parser.parse_args()

    init_db()
    with get_session() as session:
        assets = session.scalars(
            select(MediaAsset).order_by(MediaAsset.uploaded_at.desc())
        ).all()

    if not assets:
        print("[list-media] No media assets in the database.")
        print("[list-media] Upload some with: python -m scripts.upload_media [folder]")
        return

    if args.json:
        out = [
            {
                "id": a.id,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "large_object_oid": a.large_object_oid,
                "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
                "url": url_for(args.base, a),
            }
            for a in assets
        ]
        print(json.dumps(out, indent=2))
        return

    # ── Pretty table output ─────────────────────────────────────────────────
    print(f"\n[list-media] {len(assets)} asset(s) in PostgreSQL\n")
    print(f"  Base URL: {args.base}\n")
    print(f"  {'Filename':<40} {'Type':<16} {'Size':>10}  URL")
    print(f"  {'-'*40} {'-'*16} {'-'*10}  {'-'*60}")
    for a in assets:
        url = url_for(args.base, a)
        size = fmt_size(a.size_bytes)
        fn = (a.filename[:37] + "...") if len(a.filename) > 40 else a.filename
        mime = (a.mime_type or "")[:16]
        print(f"  {fn:<40} {mime:<16} {size:>10}  {url}")
    print()

    print("  HTML snippets:")
    for a in assets:
        url = url_for(args.base, a)
        if (a.mime_type or "").startswith("video/"):
            print(f'    <video controls src="{url}"></video>          <!-- {a.filename} -->')
        elif (a.mime_type or "").startswith("image/"):
            print(f'    <img src="{url}" alt="{a.filename}">          <!-- {a.filename} -->')
    print()


if __name__ == "__main__":
    main()
