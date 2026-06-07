# Techflix · Video episodes from a folder

How to publish videos into the **Techflix** section of the app. Drop your video
files in a folder on the server, describe them in a small `techflix.json` file,
run one script — they appear in Techflix, grouped by topic.

Techflix is a browse-and-watch section: topics (e.g. *Caching*, *Security*),
each with a row of 5–10 minute episodes. The video bytes live in PostgreSQL
(same large-object pipeline as `MEDIA.md`); Techflix just adds the editorial
metadata — topic, title, description, order, poster, duration.

---

## What you need on the server

- The video files (`.mp4`, `.m4v`, `.mov`, `.webm`).
- **FFmpeg installed** (for the poster thumbnail + duration). It's already on the
  app server — it backs upload validation. If it's somehow missing, videos still
  publish; they just won't get an auto thumbnail or duration until you re-run.
- The usual deploy prerequisites (the app's `.env` with the Postgres
  `DATABASE_URL`).

---

## Step 1 · Put the videos + a manifest in a folder

Pick a folder on the server (convention: `/opt/dept-anatomy/media/techflix/`):

```
/opt/dept-anatomy/media/techflix/
├── techflix.json
├── caching-e01.mp4
├── caching-e02.mp4
└── security-e01.mp4
```

Copy files up however you like (e.g. `scp` from your laptop):

```bash
scp caching-e01.mp4 techflix.json user@<vm>:/opt/dept-anatomy/media/techflix/
```

## Step 2 · Write `techflix.json`

One entry per video. `file`, `topic`, and `title` are required; the rest are
optional.

```json
{
  "episodes": [
    {
      "file": "caching-e01.mp4",
      "topic": "Caching",
      "title": "Cache Invalidation",
      "description": "Why naming and invalidation are the hard parts.",
      "order": 1,
      "poster_time": 5
    },
    {
      "file": "caching-e02.mp4",
      "topic": "Caching",
      "title": "TTLs and Stale-While-Revalidate",
      "order": 2
    },
    {
      "file": "security-e01.mp4",
      "topic": "Security",
      "title": "Threat Modelling 101",
      "description": "STRIDE, in ten minutes.",
      "order": 1
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `file` | **yes** | The video's filename in this folder (exact match). |
| `topic` | **yes** | Groups the episode into a row in Techflix. Reuse the same string across episodes to group them. |
| `title` | **yes** | The episode title shown on the card. |
| `description` | no | One or two lines shown under the title. |
| `order` | no | Sort position within the topic (1, 2, 3…). Defaults to 0. |
| `poster_time` | no | Where to grab the thumbnail frame — seconds (e.g. `5`) or `"HH:MM:SS"`. Defaults to 3 seconds in. |

## Step 3 · Run the upload script

Run it as the app's service user so file permissions stay clean:

```bash
cd /opt/dept-anatomy/backend
sudo -u cca .venv/bin/python -m scripts.upload_media /opt/dept-anatomy/media/techflix
```

You'll see one block per video:

```
[manifest] 3 episode(s) declared in techflix.json
[upload-media] Found 3 file(s):
  [up]   caching-e01.mp4  (video/mp4, 42.1 MB)  OK  (OID=16712, id=9e74…)
         ↳ Techflix episode created: [Caching] Cache Invalidation
  [up]   caching-e02.mp4  (video/mp4, 38.7 MB)  OK  (OID=16713, id=3b2c…)
         ↳ Techflix episode created: [Caching] TTLs and Stale-While-Revalidate
  ...
[upload-media] Done. Ingested: 3 · Skipped: 0 · Techflix episodes: 3
```

That's it — Techflix now shows a **Caching** row with two episodes and a
**Security** row with one.

---

## Re-runs are safe (idempotent)

- **Add videos:** drop the new files in, add their entries to `techflix.json`,
  re-run the same command. Existing videos are reused (not re-uploaded); only the
  new ones ingest.
- **Edit metadata:** change a title / topic / order / description in
  `techflix.json` and re-run — the episode row is updated in place. No duplicate
  bytes, no duplicate cards.
- **Posters/duration** are only computed when missing, so re-runs are fast.

### Replace a video's bytes

The script matches by filename and won't overwrite bytes. To swap the actual
video:

```bash
# 1. find it
sudo -u cca .venv/bin/python -m scripts.list_media
# 2. delete its metadata row (large object is reclaimed by vacuumlo later)
sudo -u postgres psql -d codecoder -c \
  "DELETE FROM media_assets WHERE filename = 'caching-e01.mp4'"
# 3. re-upload (gets a fresh asset id; episode row re-links on next run)
sudo -u cca .venv/bin/python -m scripts.upload_media /opt/dept-anatomy/media/techflix
```

---

## Verify

```bash
# list episodes the API will serve (any signed-in user can read this):
curl -s https://<host>/api/media/techflix | python -m json.tool | head -40

# confirm a video streams with Range support (scrubbing):
curl -H "Range: bytes=0-1023" -I https://<host>/media/video/<asset_id>
# expect: 206 Partial Content · Accept-Ranges: bytes
```

In the app, open the **Techflix** tab (visible to signed-in users).

---

## How it fits together

```
techflix.json + *.mp4  ──scripts.upload_media──▶  Postgres
                                                  ├─ media_assets        (video bytes as large objects + poster image)
                                                  └─ techflix_episodes   (topic, title, description, order, duration, poster ref)
                                                          │
Browser ◀── GET /api/media/techflix (grouped by topic) ──┘   ← the Techflix section reads this
Browser ◀── GET /media/video/{id}  (Range / scrubbing)        ← the player streams this
```

- **Access:** the Techflix listing requires a signed-in user; the raw
  `/media/video/{id}` byte stream is unauthenticated (same as all media today).
- **Schema:** episodes live in `techflix_episodes` (migration `0011`). Run
  `alembic upgrade head` once per environment before the first upload.
- **Source of truth:** Postgres. No filesystem media store, no CDN — consistent
  with `MEDIA.md`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `DATABASE_URL is not PostgreSQL` | The `.env` points at SQLite. Large objects are PG-only — fix the URL / re-run deploy. |
| Episode card has no thumbnail / no duration | FFmpeg wasn't available when you ran the script. Install it, then re-run (posters/duration backfill for episodes that lack them). |
| `[manifest] skipping entry … missing topic` | That entry is missing a required field (`file`, `topic`, or `title`). Fix `techflix.json` and re-run. |
| Video in folder but no card | It isn't listed in `techflix.json`, or its `file` name doesn't match exactly. Non-manifest videos ingest as plain media but don't become Techflix episodes. |
| `relation "techflix_episodes" does not exist` | The migration hasn't run in this environment. `cd backend && alembic upgrade head`. |
