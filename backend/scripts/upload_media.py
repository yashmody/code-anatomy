"""Upload media files from a folder into PostgreSQL large objects.

Two modes, both idempotent (re-running only does new work):

1. Plain bulk ingest (no manifest) — scans a directory and ingests each media
   file not already in `media_assets` (matched by filename). This is the
   original behaviour.

2. Techflix mode (a `techflix.json` manifest in the folder) — in addition to
   ingesting each listed video, it builds the curated **Techflix** library:
   extracts a poster frame, probes the duration, and writes/updates a
   `techflix_episodes` row (topic, title, description, order). The SPA's
   Techflix section reads these via `GET /api/media/techflix`.

Manifest format (`techflix.json` in the scanned folder):

    {
      "episodes": [
        {
          "file": "caching-e01.mp4",          // required — filename in this folder
          "topic": "Caching",                  // required — groups the row in the UI
          "title": "Cache Invalidation",       // required — episode title
          "description": "Why it's hard…",     // optional
          "order": 1,                           // optional — sort within the topic
          "poster_time": 3                      // optional — seconds (or "HH:MM:SS")
                                                //            for the poster frame
        }
      ]
    }

Usage:
    python -m scripts.upload_media                       # default: ../media/
    python -m scripts.upload_media /path/to/folder
    python -m scripts.upload_media /path/to/folder --recursive

Notes:
- Existing media (same filename) is reused, not re-ingested. Episode rows are
  upserted by video asset, so editing the manifest and re-running refreshes
  titles/topics/order without duplicating bytes.
- Requires DATABASE_URL pointing at PostgreSQL (large objects are PG-only).
- Duration + poster need FFmpeg/FFprobe on PATH. If absent, the video still
  ingests and the episode is created with duration/poster left empty — the run
  does not fail. (FFmpeg is present on the app server; it backs validate_video.)
- Reads/writes in 1 MB chunks (via media.service.store_media_asset) so large
  files don't blow up RAM, and the large object is opened in binary mode.
"""
import argparse
import json
import mimetypes
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

# Path setup so this runs as `python -m scripts.upload_media`
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.core import config
from app.core.db import get_session, init_db
from app.core.models import MediaAsset, TechflixEpisode
from app.modules.media import service as media_service


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

MANIFEST_NAME = "techflix.json"


def guess_mime(path: Path) -> str:
    """Pick the best MIME type for a file — extension first, then mimetypes module."""
    ext = path.suffix.lower()
    if ext in MEDIA_EXTS:
        return MEDIA_EXTS[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def is_media(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTS


def is_video(mime: str) -> bool:
    return mime.startswith("video/")


def find_media(folder: Path, recursive: bool) -> list[Path]:
    """Return media files in the folder (sorted, deterministic)."""
    if not folder.exists():
        sys.exit(f"[err] Folder not found: {folder}")
    if not folder.is_dir():
        sys.exit(f"[err] Not a directory: {folder}")
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in folder.glob(pattern) if p.is_file() and is_media(p))


# ── Manifest ─────────────────────────────────────────────────────────────────

def load_manifest(folder: Path) -> dict[str, dict]:
    """Return {filename: entry} from techflix.json, or {} if absent/invalid.

    Accepts either {"episodes": [...]} or a bare [...] list. Each entry must
    carry `file`, `topic`, and `title`; entries missing any of these are warned
    about and skipped (so one typo doesn't sink the whole run).
    """
    mpath = folder / MANIFEST_NAME
    if not mpath.exists():
        return {}
    try:
        data = json.loads(mpath.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[manifest] {MANIFEST_NAME} present but unreadable: {e} — ignoring.")
        return {}

    entries = data.get("episodes", []) if isinstance(data, dict) else data
    out: dict[str, dict] = {}
    for entry in entries or []:
        fn = entry.get("file") or entry.get("filename")
        missing = [k for k in ("topic", "title") if not entry.get(k)]
        if not fn or missing:
            print(f"[manifest] skipping entry {entry!r} — missing "
                  f"{'file' if not fn else ', '.join(missing)}")
            continue
        out[fn] = entry
    print(f"[manifest] {len(out)} episode(s) declared in {MANIFEST_NAME}")
    return out


# ── FFmpeg helpers (best-effort — None on any failure / FFmpeg absent) ────────

def probe_duration(video_path: Path) -> Optional[int]:
    """Whole-second duration via FFprobe, or None if it can't be determined."""
    try:
        import ffmpeg
        probe = ffmpeg.probe(str(video_path))
        return int(round(float(probe["format"]["duration"])))
    except Exception as e:
        print(f"    [duration] unavailable ({e.__class__.__name__}) — leaving empty")
        return None


def extract_poster(video_path: Path, poster_time) -> Optional[str]:
    """Extract one frame to a temp JPEG and return its path, or None on failure.

    `poster_time` may be seconds (int/float) or an FFmpeg timestamp string
    ("HH:MM:SS"). Caller owns deleting the returned temp file.
    """
    try:
        import ffmpeg
    except Exception:
        print("    [poster] FFmpeg not available — leaving empty")
        return None

    fd, out = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        (
            ffmpeg
            .input(str(video_path), ss=poster_time)
            .output(out, vframes=1, format="image2", vcodec="mjpeg")
            .overwrite_output()
            .run(quiet=True)
        )
        if os.path.getsize(out) > 0:
            return out
    except Exception as e:
        print(f"    [poster] extraction failed ({e.__class__.__name__}) — leaving empty")
    if os.path.exists(out):
        os.remove(out)
    return None


# ── Ingest ───────────────────────────────────────────────────────────────────

def ingest_asset(session, path: Path, mime: str) -> tuple[str, int, bool]:
    """Ensure `path` is in media_assets. Return (asset_id, oid, was_new).

    Reuses an existing row matched by filename (idempotent); otherwise stores
    the bytes via media.service.store_media_asset (1 MB chunks, binary mode).
    """
    existing = session.scalar(select(MediaAsset).where(MediaAsset.filename == path.name))
    if existing:
        return existing.id, existing.large_object_oid, False
    asset_id, oid = media_service.store_media_asset(str(path), path.name, mime, "")
    return asset_id, oid, True


def upsert_episode(session, entry: dict, video_asset_id: str, folder: Path,
                   video_path: Path) -> str:
    """Create or update the techflix_episodes row for a video. Return action word.

    Poster + duration are only computed when missing (no episode yet, or an
    existing episode lacks a poster), so re-runs don't spawn duplicate poster
    assets or re-probe needlessly.
    """
    existing = session.scalar(
        select(TechflixEpisode).where(TechflixEpisode.video_asset_id == video_asset_id)
    )

    # Decide whether we need to compute a poster / duration this run.
    need_poster = (existing is None) or (existing.poster_asset_id is None)
    need_duration = (existing is None) or (existing.duration_sec is None)

    poster_asset_id = existing.poster_asset_id if existing else None
    if need_poster:
        poster_path = extract_poster(video_path, entry.get("poster_time", 3))
        if poster_path:
            try:
                pid, _ = media_service.store_media_asset(
                    poster_path, f"{video_path.stem}-poster.jpg", "image/jpeg", ""
                )
                poster_asset_id = pid
            finally:
                if os.path.exists(poster_path):
                    os.remove(poster_path)

    duration_sec = existing.duration_sec if existing else None
    if need_duration:
        probed = probe_duration(video_path)
        if probed is not None:
            duration_sec = probed

    if existing:
        existing.topic = entry["topic"]
        existing.title = entry["title"]
        existing.description = entry.get("description")
        existing.sort_order = int(entry.get("order", existing.sort_order) or 0)
        existing.poster_asset_id = poster_asset_id
        existing.duration_sec = duration_sec
        session.commit()
        return "updated"

    session.add(TechflixEpisode(
        id=str(uuid.uuid4()),
        video_asset_id=video_asset_id,
        poster_asset_id=poster_asset_id,
        topic=entry["topic"],
        title=entry["title"],
        description=entry.get("description"),
        sort_order=int(entry.get("order", 0) or 0),
        duration_sec=duration_sec,
    ))
    session.commit()
    return "created"


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload media files from a folder into PostgreSQL.")
    parser.add_argument(
        "folder",
        nargs="?",
        default=str(config.BASE_DIR.parent / "media"),
        help="Folder to scan (default: ../media relative to backend/)",
    )
    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Recurse into subdirectories",
    )
    args = parser.parse_args()

    folder = Path(args.folder).resolve()
    db_disp = config.DATABASE_URL.split("@")[-1] if "@" in config.DATABASE_URL else config.DATABASE_URL
    print(f"[upload-media] DB     : {db_disp}")
    print(f"[upload-media] Folder : {folder}  (recursive={args.recursive})")

    if "postgresql" not in config.DATABASE_URL:
        sys.exit("[err] DATABASE_URL is not PostgreSQL — large objects are PG-only.")

    init_db()
    manifest = load_manifest(folder)
    files = find_media(folder, args.recursive)
    if not files:
        print(f"[upload-media] No media files found in {folder} "
              f"(extensions: {', '.join(sorted(MEDIA_EXTS))})")
        return

    print(f"[upload-media] Found {len(files)} file(s):")

    ingested = skipped = episodes = 0
    with get_session() as session:
        for path in files:
            mime = guess_mime(path)
            asset_id, oid, was_new = ingest_asset(session, path, mime)
            if was_new:
                size_mb = path.stat().st_size / (1024 * 1024)
                print(f"  [up]   {path.name}  ({mime}, {size_mb:.1f} MB)  OK  (OID={oid}, id={asset_id})")
                ingested += 1
            else:
                print(f"  [skip] {path.name}  (already in DB, id={asset_id})")
                skipped += 1

            entry = manifest.get(path.name)
            if entry and is_video(mime):
                action = upsert_episode(session, entry, asset_id, folder, path)
                print(f"         ↳ Techflix episode {action}: "
                      f"[{entry['topic']}] {entry['title']}")
                episodes += 1
            elif entry and not is_video(mime):
                print(f"         ↳ skipping Techflix entry for {path.name} — not a video")

    print(f"\n[upload-media] Done. Ingested: {ingested}  ·  Skipped: {skipped}  "
          f"·  Techflix episodes: {episodes}")
    if manifest and episodes:
        print("[upload-media] Techflix library updated — visible at /api/media/techflix")


if __name__ == "__main__":
    main()
