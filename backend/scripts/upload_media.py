"""Upload media files from a folder into PostgreSQL large objects.

Scans a directory for media files and ingests each one that isn't already
in the `media_assets` table (matched by filename). Idempotent — re-running
only ingests new files.

Usage:
    python -m scripts.upload_media                       # default: ../media/
    python -m scripts.upload_media /path/to/folder
    python -m scripts.upload_media /path/to/folder --recursive

Notes:
- Existing files (same filename) are skipped — delete them via list_media + a DB call if you want to re-ingest.
- Requires DATABASE_URL pointing at PostgreSQL (large objects are PG-only).
- Reads/writes in 1 MB chunks so large files don't blow up RAM.
"""
import argparse
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

# Path setup so this runs as `python -m scripts.upload_media`
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.core import config
from app.core.db import get_session, init_db
from app.core.models import MediaAsset


# Extensions we recognise as media. Anything else in the folder is skipped silently.
MEDIA_EXTS = {
    ".mp4":  "video/mp4",
    ".m4v":  "video/mp4",
    ".mov":  "video/quicktime",
    ".webm": "video/webm",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".svg":  "image/svg+xml",
}


def guess_mime(path: Path) -> str:
    """Pick the best MIME type for a file — extension first, then mimetypes module."""
    ext = path.suffix.lower()
    if ext in MEDIA_EXTS:
        return MEDIA_EXTS[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def is_media(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTS


def find_media(folder: Path, recursive: bool) -> list[Path]:
    """Return media files in the folder (sorted, deterministic)."""
    if not folder.exists():
        sys.exit(f"[err] Folder not found: {folder}")
    if not folder.is_dir():
        sys.exit(f"[err] Not a directory: {folder}")
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in folder.glob(pattern) if p.is_file() and is_media(p))


def ingest_file(session, path: Path) -> Optional[str]:
    """Upload one file into pg_largeobject + media_assets. Returns the asset_id, or None if skipped."""
    # Skip if filename already in the table
    existing = session.scalar(select(MediaAsset).where(MediaAsset.filename == path.name))
    if existing:
        print(f"  [skip] {path.name}  (already in DB, OID={existing.large_object_oid}, id={existing.id})")
        return None

    mime = guess_mime(path)
    size = path.stat().st_size
    size_mb = size / (1024 * 1024)
    print(f"  [up]   {path.name}  ({mime}, {size_mb:.1f} MB) … ", end="", flush=True)

    # Write to pg_largeobject via psycopg2's lobject() interface
    engine = session.bind
    raw_conn = engine.raw_connection()
    try:
        lobj = raw_conn.lobject(0, "w")
        oid = lobj.oid
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                lobj.write(chunk)
        lobj.close()
        raw_conn.commit()
    except Exception as e:
        raw_conn.rollback()
        print(f"FAIL\n  [err]  {e}")
        return None
    finally:
        raw_conn.close()

    asset_id = str(uuid.uuid4())
    asset = MediaAsset(
        id=asset_id,
        large_object_oid=oid,
        filename=path.name,
        mime_type=mime,
        size_bytes=size,
        uploaded_by=None,
    )
    session.add(asset)
    session.commit()
    print(f"OK  (OID={oid}, id={asset_id})")
    return asset_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload media files from a folder into PostgreSQL.")
    parser.add_argument(
        "folder",
        nargs="?",
        default=str(config.BASE_DIR.parent / "media"),
        help="Folder to scan (default: ../media relative to quiz-certification)",
    )
    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Recurse into subdirectories",
    )
    args = parser.parse_args()

    folder = Path(args.folder).resolve()
    print(f"[upload-media] DB     : {config.DATABASE_URL.split('@')[-1] if '@' in config.DATABASE_URL else config.DATABASE_URL}")
    print(f"[upload-media] Folder : {folder}  (recursive={args.recursive})")

    if "postgresql" not in config.DATABASE_URL:
        sys.exit("[err] DATABASE_URL is not PostgreSQL — large objects are PG-only.")

    init_db()
    files = find_media(folder, args.recursive)
    if not files:
        print(f"[upload-media] No media files found in {folder} (extensions: {', '.join(sorted(MEDIA_EXTS))})")
        return

    print(f"[upload-media] Found {len(files)} file(s):")

    ingested = 0
    skipped = 0
    with get_session() as session:
        for path in files:
            result = ingest_file(session, path)
            if result is None:
                skipped += 1
            else:
                ingested += 1

    print(f"\n[upload-media] Done. Ingested: {ingested}  ·  Skipped (already present): {skipped}")


if __name__ == "__main__":
    main()
