# v2 — Unified video model

> Status: **As-built (migrations 0014 + 0015).** One video system, classified by
> usage — not three parallel pipelines. Bytes in Postgres large objects; logical
> videos, renditions, placements, and per-surface usage layered on top.

## 0 · Scan box

- **What:** a normalised model — `media_assets` (files) → `video_asset` (logical
  video) → `video_variant` (renditions) → `video_placement` + three usage maps
  (`techflix_video_map`, `content_video_map`, `social_feed_video`).
- **Why:** general / Techflix / feed videos are the *same* asset reused in
  different places. One asset + usage maps avoids three duplicate systems and
  lets a video appear in more than one surface.
- **So what:** uploads go through one ingest path and one CLI (`scripts.media`);
  serving resolves a video by **id or slug** (env-portable embeds); the variant
  table is the seam for HLS/adaptive streaming with no change above it.

## 1 · Tables

```
media_assets         physical files — one row per large object (bytes, mime, size)
video_asset          one logical video — title, description, duration_sec, status, slug(unique)
video_variant        rendition → media_assets file: kind(original|poster|thumbnail|hls|mp4_720…),
                       is_primary, w/h/bitrate. (uq: video_asset_id+kind)
video_placement      allowed surface per asset: content | techflix | feed  (uq: asset+surface)
techflix_video_map   Techflix metadata: topic, title override, description, sort_order
content_video_map    which chapter/block embeds an asset (impact tracking)
social_feed_video    links a feed_item ↔ video_asset (feed UGC)
```

`media_assets` is unchanged from before — it remains the byte layer (also holds
standalone images/posters). Everything else is new in `0014`. `0015` dropped the
legacy `techflix_episodes` table (backfilled into `techflix_video_map` by `0014`).

## 2 · Serve

- `GET /media/video/{ref}` (HTTP Range) and `GET /media/image/{ref}`.
- `ref` resolves, in order: **video_asset id → video_asset slug → legacy
  media_asset id** (back-compat), then to the asset's **primary variant** → the
  underlying `media_assets` large object.
- Slugs are the stable embed handle (e.g. the course explainer = `explainer` →
  `/media/video/explainer`), so the frontend never holds a per-environment UUID.
- Media responses set `Content-Encoding: identity` so GZip never re-encodes a
  Range/binary stream (which breaks scrubbing).

## 3 · Upload paths (one per surface)

| Surface | How | Writes |
|---|---|---|
| General | `python -m scripts.media upload <folder> [--slug S]` | video_asset + original variant + `content` placement |
| Techflix | `python -m scripts.media techflix <folder>` (reads `techflix.json`) | + poster variant + `techflix_video_map` + `techflix` placement |
| Feed | UI → `POST /api/media/upload` (`surface=feed`) → `video_asset_id` attached to the post | + `social_feed_video` (feed link) |

All three funnel through `media.service.ingest_video` (store file → asset +
original variant → auto poster + duration via FFmpeg → placements). Management:
`scripts.media list | set-slug | rm`.

## 4 · Extensibility (the variant seam)

Adaptive streaming / multi-format was deliberately deferred — there is no
transcoder today (single MP4s, Range-streamed). When it lands, add
`video_variant` rows of `kind='hls'` / `mp4_720` / … pointing at their
`media_assets` files and mark the right one `is_primary`; the serve resolver and
every consumer above are unchanged. No schema migration beyond inserting rows.

## 5 · References

| Need | Source |
|---|---|
| How to add/manage videos | `MEDIA.md`, `TECHFLIX.md` |
| Migrations | `backend/migrations/versions/0014_video_model.py`, `0015_drop_techflix_episodes.py` |
| Models | `backend/app/core/models.py` (VideoAsset/VideoVariant/VideoPlacement/…) |
| Ingest + resolve | `backend/app/modules/media/{service,storage,routes}.py` |
| CLI | `backend/scripts/media.py` |
