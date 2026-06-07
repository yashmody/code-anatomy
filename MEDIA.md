# Media & Video — the unified model

How videos are stored, uploaded, and served. There is **one** video system; videos
are classified by **where they're used** (general / Techflix / feed), not three
separate pipelines.

## The model (migration 0014)

```
media_assets          physical files — one row per stored file in pg_largeobject
   ▲
video_variant         renditions of a video → each points at a media_assets file
   │                  (kind: original | poster | thumbnail | hls | mp4_720 …; one is_primary)
video_asset           one logical video (title, duration, status, slug)
   ├─ video_placement    which surfaces it may appear on: content | techflix | feed
   ├─ techflix_video_map Techflix section metadata (topic, order, title override)
   ├─ content_video_map  which chapter/block embeds it
   └─ social_feed_video  feed UGC metadata (links a feed_item)
```

- **Bytes** live in Postgres large objects (`media_assets`) — no filesystem store, no CDN.
- **Streaming**: `GET /media/video/{ref}` (HTTP Range / scrubbing) and `GET /media/image/{ref}`.
  `ref` resolves as a **video_asset id, a slug, or a legacy media_asset id** → the primary variant.
- **Slugs** give a stable, env-portable embed handle (e.g. the course explainer is
  `/media/video/explainer`) so the frontend never holds a per-environment UUID.

## The one tool: `scripts.media`

```bash
cd backend
python -m scripts.media upload   <folder> [--slug S] [--surface content] [-r]
python -m scripts.media techflix <folder>                 # reads <folder>/techflix.json
python -m scripts.media list      [--surface content|techflix|feed]
python -m scripts.media set-slug  <video_asset_id> <slug>
python -m scripts.media rm        <video_asset_id>
```
On the VM, run with the venv: `/opt/dept-anatomy/backend/.venv/bin/python -m scripts.media …`.
Idempotent by filename — a file already stored is reused, not duplicated.

## Adding videos — by category

### 1. General videos (added anywhere, e.g. course-embedded)
```bash
python -m scripts.media upload /opt/dept-anatomy/media          # ingest folder (surface=content)
python -m scripts.media list                                    # find the new asset id
python -m scripts.media set-slug <asset_id> explainer           # give it a stable handle
```
Embed it anywhere with `/media/video/<slug>` (e.g. the manual explainer uses
`/media/video/explainer`).

### 2. Techflix videos (via manifest)
Put the `.mp4`s + a `techflix.json` (see `TECHFLIX.md`) in a folder, then:
```bash
python -m scripts.media techflix /opt/dept-anatomy/media/techflix
```
Each entry becomes a `video_asset` + a `techflix_video_map` row (topic/title/order)
+ an auto poster + duration (if ffmpeg is present). It appears in the Techflix tab.

### 3. Feed videos (uploaded from the UI)
No script — the feed composer uploads the file via `POST /api/media/upload`
(`surface=feed`), gets back a `video_asset_id`, and attaches it to the post; the
backend links `social_feed_video`. The post then streams from `/media/video/{id}`.

## Verify / manage
```bash
python -m scripts.media list                       # all assets, surfaces, slugs, URLs
curl -is -H 'Range: bytes=0-1023' https://<host>/media/video/<slug-or-id> | head
#   expect 206 + Content-Range + Content-Length, no Content-Encoding: gzip
```

## Notes
- **ffmpeg** (server-side) gives auto posters + duration. Without it, videos still
  upload; posters/duration are just empty.
- Media responses set `Content-Encoding: identity` so Apache/GZip never compress a
  Range/binary stream (which would break scrubbing).
- The variant table is the seam for adaptive streaming (HLS/multi-rendition) — add
  `kind='hls'`/`mp4_720` variants later with no change above.
- Legacy: the old `techflix_episodes` table was superseded by `techflix_video_map`
  — migration `0014` backfilled it into the unified model, and `0015` dropped it.
