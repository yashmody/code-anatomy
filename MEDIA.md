# Media Pipeline · Postgres Large Objects

How to get video, image, and other media files into PostgreSQL so the
FastAPI app can stream them.

The app already has streaming endpoints with HTTP Range support (so
scrubbing works in `<video controls>`). What's missing is the bytes —
this doc walks through getting them in.

## Architecture in one paragraph

Media files live as PostgreSQL **large objects** (the `pg_largeobject`
system catalogue), referenced by row in the `media_assets` table
(`id UUID`, `large_object_oid OID`, `filename`, `mime_type`, `size_bytes`).
The FastAPI app streams them via:

| Endpoint | Returns |
|---|---|
| `GET /media/video/{asset_id}` | Video stream with `Accept-Ranges: bytes` — scrubbing works |
| `GET /media/image/{asset_id}` | Image bytes with correct `Content-Type` |

No filesystem path, no CDN. Postgres is the source of truth.

---

## On a fresh VM — first-time setup

### Step 1 · Put files on the VM

Pick any folder on the VM. The convention is:

```
/opt/dept-anatomy/media/
```

Get your files in there however you prefer:

```bash
# From your laptop, with scp:
scp "Anatomy of Code.mp4" hero-banner.jpg user@<vm>:/tmp/

# On the VM, move them into place:
sudo mkdir -p /opt/dept-anatomy/media
sudo mv /tmp/Anatomy\ of\ Code.mp4 /tmp/hero-banner.jpg /opt/dept-anatomy/media/
sudo chown -R cca:cca /opt/dept-anatomy/media
```

You can use any folder — the upload script takes the path as an argument.

### Step 2 · Run the upload script

The script is in the quiz-certification venv. Always run it as the `cca`
service user so file permissions stay clean:

```bash
cd /opt/dept-anatomy/quiz-certification
sudo -u cca .venv/bin/python -m scripts.upload_media /opt/dept-anatomy/media
```

You'll see one line per file:

```
[upload-media] DB     : localhost:5432/codecoder
[upload-media] Folder : /opt/dept-anatomy/media  (recursive=False)
[upload-media] Found 2 file(s):
  [up]   Anatomy of Code.mp4  (video/mp4, 28.4 MB) … OK  (OID=16678, id=9e74f3a2-…)
  [up]   hero-banner.jpg      (image/jpeg, 1.2 MB) … OK  (OID=16679, id=3b2c81d4-…)

[upload-media] Done. Ingested: 2  ·  Skipped (already present): 0
```

### Step 3 · Verify and get the URLs

```bash
cd /opt/dept-anatomy/quiz-certification
sudo -u cca .venv/bin/python -m scripts.list_media \
  --base https://internal.in.deptagency.com
```

Output:

```
[list-media] 2 asset(s) in PostgreSQL

  Base URL: https://internal.in.deptagency.com

  Filename                                 Type             Size  URL
  ---------------------------------------- ---------------- ----------  -----------------
  Anatomy of Code.mp4                      video/mp4       28.4 MB  https://…/media/video/9e74f3a2-…
  hero-banner.jpg                          image/jpeg       1.2 MB  https://…/media/image/3b2c81d4-…

  HTML snippets:
    <video controls src="https://…/media/video/9e74f3a2-…"></video>
    <img src="https://…/media/image/3b2c81d4-…" alt="hero-banner.jpg">
```

The URL is what you paste into your HTML or front-end code.

### Step 4 · Test it in a browser

```bash
# Quick smoke test from any machine that can reach the VM:
curl -I https://internal.in.deptagency.com/media/video/<asset_id>
# Expect: 200 OK · Accept-Ranges: bytes · Content-Type: video/mp4
```

Or just open the URL in a browser tab. For videos, the browser shows
native controls and lets you scrub.

---

## Re-runs and updates

### Adding new files later

Drop new files into the folder and re-run the same command:

```bash
sudo -u cca .venv/bin/python -m scripts.upload_media /opt/dept-anatomy/media
```

Files that are already in the database (matched by filename) are skipped:

```
  [skip] Anatomy of Code.mp4  (already in DB, OID=16678, id=9e74f3a2-…)
  [up]   new-explainer.mp4     (video/mp4, 14.1 MB) … OK  (OID=16690, id=…)
```

### Replacing an existing file

The upload script **matches by filename**, so it won't replace anything.
To replace a file:

```bash
# 1. Get the asset_id from list_media
sudo -u cca .venv/bin/python -m scripts.list_media

# 2. Delete the row from media_assets (the large object will become orphaned,
#    which is fine — pg vacuum will eventually clean it)
sudo -u postgres psql -d codecoder -c \
  "DELETE FROM media_assets WHERE filename = 'Anatomy of Code.mp4'"

# 3. Re-upload
sudo -u cca .venv/bin/python -m scripts.upload_media /opt/dept-anatomy/media
```

The asset gets a **new** `asset_id` — update any front-end code that
references the old URL.

### Recursive folder scan

For folders with subdirectories (`/opt/dept-anatomy/media/videos/`,
`/opt/dept-anatomy/media/images/`, etc.):

```bash
sudo -u cca .venv/bin/python -m scripts.upload_media \
  /opt/dept-anatomy/media --recursive
```

Filename uniqueness is still enforced — don't have two `hero.jpg` files in
different subdirectories, or the second one will be skipped.

---

## Supported file types

| Extension | MIME type | Endpoint |
|---|---|---|
| `.mp4`, `.m4v` | `video/mp4` | `/media/video/{id}` |
| `.mov` | `video/quicktime` | `/media/video/{id}` |
| `.webm` | `video/webm` | `/media/video/{id}` |
| `.jpg`, `.jpeg` | `image/jpeg` | `/media/image/{id}` |
| `.png` | `image/png` | `/media/image/{id}` |
| `.gif` | `image/gif` | `/media/image/{id}` |
| `.webp` | `image/webp` | `/media/image/{id}` |
| `.svg` | `image/svg+xml` | `/media/image/{id}` |

Any other file in the folder is silently ignored — safe to put `README.md`,
`.DS_Store`, etc. alongside the media.

---

## Wiring an asset URL into the SPA

Once you have a stable `asset_id`, point the front-end at the streaming
URL. Example — the manual explainer video lives in
`app/js/modes/scroll.js`:

```js
// Before
const MANUAL_VIDEO_SRC = '../media/Anatomy%20of%20Code.mp4';

// After
const MANUAL_VIDEO_SRC = '/media/video/9e74f3a2-…-real-asset-id…';
```

Commit the change, redeploy with `sudo ./deploy.sh --update`, and the SPA
will stream from Postgres.

Tip: if you re-upload the file later, the `asset_id` changes. To avoid
front-end churn, consider asking for a filename-based endpoint (e.g.
`/media/by-name/Anatomy of Code.mp4`) — open a separate ticket if you
need this.

---

## Troubleshooting

### `[err] DATABASE_URL is not PostgreSQL`

The script saw a SQLite URL in the env. Confirm your `.env`:

```bash
grep DATABASE_URL /opt/dept-anatomy/quiz-certification/.env
# Expect: DATABASE_URL=postgresql://codecoder:…@localhost:5432/codecoder
```

If it shows SQLite, re-run `sudo ./deploy.sh` — that step rewrites the URL.

### `[err] Folder not found`

The path you passed doesn't exist. Check:

```bash
ls -la /opt/dept-anatomy/media
```

If empty, scp/move your files in first.

### `psql: FATAL: password authentication failed for user "codecoder"`

The `.env` password doesn't match what's stored in the role. Re-run the
deploy script — it now resyncs the role password on every run:

```bash
sudo ./deploy.sh
```

### Video plays but won't scrub

Confirm the Range header is being served end-to-end. From a machine that
can reach the VM:

```bash
curl -H "Range: bytes=0-1023" -I https://your-vm/media/video/<id>
# Expect: HTTP/1.1 206 Partial Content
```

If you get `200` instead of `206`, something between the browser and
uvicorn is stripping the Range header — usually Apache. Check the vhost
config has `ProxyPreserveHost On` (the deploy script sets this).

### How big can a file be?

The schema doesn't cap it, but `MAX_VIDEO_SIZE_MB=30` in `config.py`
applies to user uploads via the upload endpoint, not to the bulk
ingest scripts. The scripts read in 1 MB chunks and stream into pg, so
GB-scale files work — but check your VM disk has 2× the file size free
during the ingest (Postgres journals it before committing).

---

## Useful one-liners

```bash
# How many assets are in Postgres right now?
sudo -u postgres psql -d codecoder -tAc "SELECT COUNT(*) FROM media_assets"

# Total bytes stored in pg_largeobject (assigned to media_assets)
sudo -u postgres psql -d codecoder -tAc \
  "SELECT pg_size_pretty(SUM(size_bytes)::bigint) FROM media_assets"

# List by upload date (newest first)
sudo -u postgres psql -d codecoder -c \
  "SELECT filename, mime_type, pg_size_pretty(size_bytes::bigint), uploaded_at
   FROM media_assets ORDER BY uploaded_at DESC"

# Clean up orphaned large objects (Postgres 9.0+, run during maintenance)
sudo -u postgres vacuumlo codecoder
```

---

## Files in this pipeline

```
quiz-certification/
├── deploy_schema.sql                 ← creates media_assets table
├── app/
│   ├── media_service.py              ← chunked Range streaming (1 MB chunks)
│   ├── main.py                       ← /media/video/{id}, /media/image/{id}
│   └── models.py                     ← MediaAsset SQLAlchemy model
└── scripts/
    ├── upload_media.py               ← THIS DOC — bulk-ingest a folder
    ├── list_media.py                 ← THIS DOC — print URLs
    └── migrate_to_postgres.py        ← one-shot first-deploy seeder
```
