"""media — the single CLI for managing videos in the unified model.

One tool for all three placements (general / techflix / feed-is-via-UI):

    python -m scripts.media upload  <folder> [--slug S] [--surface content] [-r]
    python -m scripts.media techflix <folder>            # reads <folder>/techflix.json
    python -m scripts.media list [--surface content|techflix|feed]
    python -m scripts.media set-slug <video_asset_id> <slug>
    python -m scripts.media rm <video_asset_id>

Model (migration 0014):
    media_assets   physical files (large objects)
    video_asset → video_variant → media_assets ; video_placement ; *_video_map

Ingest goes through `media.service.ingest_video` (stores the file, builds the
asset + original variant + auto poster + duration + placements). Idempotent by
filename: a file already in media_assets is skipped/reused.
"""
import argparse
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.core import config
from app.core.db import get_session, engine, init_db
from app.core.models import (
    MediaAsset, VideoAsset, VideoVariant, VideoPlacement, TechflixVideoMap,
)
from app.modules.media import service as media_service

VIDEO_EXTS = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
MANIFEST = "techflix.json"


def _guess_mime(p: Path) -> Optional[str]:
    return VIDEO_EXTS.get(p.suffix.lower()) or (mimetypes.guess_type(str(p))[0])


def _find_videos(folder: Path, recursive: bool):
    if not folder.is_dir():
        sys.exit(f"[media] not a directory: {folder}")
    pat = "**/*" if recursive else "*"
    return sorted(p for p in folder.glob(pat) if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def _existing_asset_id_for_file(filename: str) -> Optional[str]:
    """If this filename is already stored, return the VideoAsset that owns it
    (dedup, so re-running is safe)."""
    with get_session() as s:
        ma = s.scalar(select(MediaAsset).where(MediaAsset.filename == filename))
        if not ma:
            return None
        v = s.scalar(select(VideoVariant).where(VideoVariant.media_asset_id == ma.id))
        return v.video_asset_id if v else None


def _require_pg():
    if "postgresql" not in config.DATABASE_URL:
        sys.exit("[media] DATABASE_URL is not PostgreSQL — large objects are PG-only.")


# ── upload (general) ─────────────────────────────────────────────────────────

def cmd_upload(args):
    _require_pg(); init_db()
    folder = Path(args.folder).resolve()
    vids = _find_videos(folder, args.recursive)
    if not vids:
        print(f"[media] no video files in {folder}"); return
    if args.slug and len(vids) > 1:
        sys.exit("[media] --slug is only valid for a single file")
    print(f"[media] uploading {len(vids)} video(s) from {folder} (surface={args.surface})")
    for p in vids:
        if _existing_asset_id_for_file(p.name):
            print(f"  [skip] {p.name} (already ingested)"); continue
        va = media_service.ingest_video(
            str(p), title=p.stem, mime_type=_guess_mime(p), uploaded_by="",
            slug=args.slug, surfaces=(args.surface,),
        )
        print(f"  [up]   {p.name}  → video_asset={va}  url=/media/video/{args.slug or va}")
    print("[media] done.")


# ── techflix (manifest) ──────────────────────────────────────────────────────

def cmd_techflix(args):
    _require_pg(); init_db()
    folder = Path(args.folder).resolve()
    mpath = folder / MANIFEST
    if not mpath.exists():
        sys.exit(f"[media] no {MANIFEST} in {folder}")
    data = json.loads(mpath.read_text(encoding="utf-8"))
    episodes = data.get("episodes", data) if isinstance(data, dict) else data
    print(f"[media] techflix: {len(episodes)} entry(ies) in {MANIFEST}")
    created = 0
    for e in episodes or []:
        fn = e.get("file") or e.get("filename")
        miss = [k for k in ("topic", "title") if not e.get(k)]
        if not fn or miss:
            print(f"  [skip] entry {e!r} missing {'file' if not fn else ', '.join(miss)}"); continue
        p = folder / fn
        if not p.exists():
            print(f"  [skip] {fn} not found in folder"); continue
        va = _existing_asset_id_for_file(p.name)
        if not va:
            va = media_service.ingest_video(
                str(p), title=e["title"], mime_type=_guess_mime(p), uploaded_by="",
                poster_time=e.get("poster_time", 3), surfaces=("techflix",),
            )
        _upsert_techflix_map(va, e)
        print(f"  [ok]   {fn}  [{e['topic']}] {e['title']}  → {va}")
        created += 1
    print(f"[media] techflix done. {created} episode(s).")


def _upsert_techflix_map(video_asset_id: str, entry: dict):
    with get_session() as s:
        row = s.scalar(select(TechflixVideoMap).where(TechflixVideoMap.video_asset_id == video_asset_id))
        if row:
            row.topic = entry["topic"]; row.title = entry["title"]
            row.description = entry.get("description"); row.sort_order = int(entry.get("order", 0) or 0)
        else:
            s.add(TechflixVideoMap(
                video_asset_id=video_asset_id, topic=entry["topic"], title=entry["title"],
                description=entry.get("description"), sort_order=int(entry.get("order", 0) or 0),
            ))
        # ensure techflix placement exists
        if not s.scalar(select(VideoPlacement).where(
                VideoPlacement.video_asset_id == video_asset_id, VideoPlacement.surface == "techflix")):
            s.add(VideoPlacement(video_asset_id=video_asset_id, surface="techflix"))
        s.commit()


# ── list ─────────────────────────────────────────────────────────────────────

def cmd_list(args):
    _require_pg()
    with get_session() as s:
        q = select(VideoAsset).order_by(VideoAsset.created_at.desc())
        assets = s.execute(q).scalars().all()
        rows = []
        for va in assets:
            placements = {p.surface for p in s.execute(
                select(VideoPlacement).where(VideoPlacement.video_asset_id == va.id)).scalars()}
            if args.surface and args.surface not in placements:
                continue
            orig = s.scalar(select(VideoVariant).where(
                VideoVariant.video_asset_id == va.id, VideoVariant.kind == "original"))
            ma = s.get(MediaAsset, orig.media_asset_id) if orig else None
            rows.append((va, placements, ma))
    if not rows:
        print("[media] no video assets" + (f" with surface={args.surface}" if args.surface else "")); return
    print(f"\n{'video_asset_id':38} {'slug':16} {'surfaces':22} {'dur':>5}  title")
    print("-" * 110)
    for va, pl, ma in rows:
        print(f"{va.id:38} {(va.slug or '—'):16} {','.join(sorted(pl)):22} "
              f"{(str(va.duration_sec)+'s' if va.duration_sec else '—'):>5}  {va.title}")
        print(f"    url=/media/video/{va.slug or va.id}"
              + (f"   file={ma.filename} ({ma.size_bytes} B)" if ma else "  (no original file!)"))
    print()


# ── set-slug ─────────────────────────────────────────────────────────────────

def cmd_set_slug(args):
    _require_pg()
    with get_session() as s:
        va = s.get(VideoAsset, args.video_asset_id)
        if not va:
            sys.exit(f"[media] no video_asset {args.video_asset_id}")
        clash = s.scalar(select(VideoAsset).where(VideoAsset.slug == args.slug, VideoAsset.id != va.id))
        if clash:
            sys.exit(f"[media] slug '{args.slug}' already used by {clash.id}")
        va.slug = args.slug; s.commit()
    print(f"[media] {args.video_asset_id} → slug '{args.slug}'  (embed: /media/video/{args.slug})")


# ── rm ───────────────────────────────────────────────────────────────────────

def cmd_rm(args):
    _require_pg()
    oids, media_ids = [], []
    with get_session() as s:
        va = s.get(VideoAsset, args.video_asset_id)
        if not va:
            sys.exit(f"[media] no video_asset {args.video_asset_id}")
        for v in s.execute(select(VideoVariant).where(VideoVariant.video_asset_id == va.id)).scalars():
            ma = s.get(MediaAsset, v.media_asset_id)
            if ma:
                media_ids.append(ma.id); oids.append(ma.large_object_oid)
        s.delete(va)  # cascades variants / placements / maps / social_feed_video
        s.commit()
        for mid in set(media_ids):
            row = s.get(MediaAsset, mid)
            if row:
                s.delete(row)
        s.commit()
    raw = engine.raw_connection()
    try:
        for oid in set(oids):
            try:
                raw.lobject(oid, "n").unlink()
            except Exception:
                pass
        raw.commit()
    finally:
        raw.close()
    print(f"[media] removed {args.video_asset_id} + {len(set(oids))} file(s)/large object(s).")


def main():
    ap = argparse.ArgumentParser(prog="media", description="Manage videos in the unified model.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("upload", help="ingest general videos from a folder")
    u.add_argument("folder"); u.add_argument("--slug"); u.add_argument("--surface", default="content")
    u.add_argument("--recursive", "-r", action="store_true"); u.set_defaults(fn=cmd_upload)

    t = sub.add_parser("techflix", help="ingest videos from a folder's techflix.json")
    t.add_argument("folder"); t.set_defaults(fn=cmd_techflix)

    l = sub.add_parser("list", help="list video assets")
    l.add_argument("--surface", choices=["content", "techflix", "feed"]); l.set_defaults(fn=cmd_list)

    ss = sub.add_parser("set-slug", help="assign a stable embed slug")
    ss.add_argument("video_asset_id"); ss.add_argument("slug"); ss.set_defaults(fn=cmd_set_slug)

    rm = sub.add_parser("rm", help="delete a video asset + its files")
    rm.add_argument("video_asset_id"); rm.set_defaults(fn=cmd_rm)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
