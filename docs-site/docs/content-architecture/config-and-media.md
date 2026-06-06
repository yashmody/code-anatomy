---
id: config-and-media
title: Config-as-content and media
sidebar_position: 6
---

# Config-as-content and media

## Scan box

- Configuration follows a **three-tier rule**: secrets live in **env** (Pydantic
  Settings, never in the DB or git); non-secret runtime tunables live in the
  **`app_config`** table (Directus-edited); content lives in **Directus
  collections**. Each value sits in exactly one tier.
- `app_config` is read through `core/cms_client.py` over the shared cache, with a
  **compiled-in default** for every key — so an empty `app_config` table behaves
  byte-identically to the old hardcoded constants.
- **Media is final: all media is Postgres large objects**, streamed by FastAPI
  `/media/{video,image}/{asset_id}` with HTTP Range. No S3, no object store, no
  filesystem media store. Directus holds media metadata only.
- The `media_assets` row is metadata (id, OID, filename, MIME, size, uploader); the
  bytes live in `pg_largeobject`. A delete trigger and a `vacuumlo` sweep keep the
  byte store from leaking orphans.

This page covers the two content types that are not prose: configuration and media.
They share a theme — both are about putting a value in exactly the right store and
never anywhere else — and both have a hard line that the rest of the architecture
depends on.

## Config-as-content: the three tiers

The platform separates configurable values into three tiers, and the whole point is
that the tier decides the store.

```
   TIER 1 · SECRETS                TIER 2 · CONFIG               TIER 3 · CONTENT
 ┌──────────────────────┐      ┌──────────────────────┐     ┌──────────────────────┐
 │  env (.env, 0600)     │      │  app_config table     │     │  Directus collections │
 │  Pydantic Settings    │      │  Directus-edited      │     │  over Postgres        │
 │  read once at startup │      │  cached read in app   │     │  same DB reads as now │
 │  no live reload       │      │  webhook-invalidated  │     │  (course, feed, …)    │
 └──────────────────────┘      └──────────────────────┘     └──────────────────────┘
   SECRET_KEY                     quiz.duration_min            course_chapters
   GOOGLE_CLIENT_SECRET           quiz.pass_mark_correct       frameworks
   DATABASE_URL                   media.max_video_size_mb      feed_items
   CERT_HMAC_PROD                 feed.flag_threshold          questions
   APP_PAYLOAD_SECRET             features.llm.enabled
```

### Tier 1 — secrets, env only

Values that, if leaked, let an attacker forge identity, decrypt traffic, or read the
database. They are **never** in Postgres, **never** in git, **never** in a Directus
collection. They live in `backend/.env` (mode `0600`, owner `cca`), loaded once at
process start by a typed Pydantic `Settings` singleton (`core/config.py`). Reading a
secret is one attribute access; there is no live reload — changing a secret needs a
restart. The full set includes `SECRET_KEY`, `APP_PAYLOAD_SECRET`, `DATABASE_URL`,
`GOOGLE_CLIENT_SECRET`, the SMTP credentials, the LLM key, and the per-environment
certificate HMAC keys (`CERT_HMAC_PROD`, `CERT_HMAC_DEV`, …).

### Tier 2 — configuration, `app_config`

Non-secret runtime tunables an operator wants to flip without a redeploy. They are
JSONB-valued rows in the `app_config` table (one row per dot-prefixed key), edited
through Directus by the Platform Admin role. The reader is `core/cms_client.cfg(key)`
— a thin typed reader over the table that delegates caching and invalidation to the
shared `core/cache.py`. Two properties make this safe:

- **Compiled-in defaults.** `cms_client` carries a `DEFAULTS` dict mirroring today's
  hardcoded constants. A missing row falls back to its default, so an empty
  `app_config` table is byte-identical to the old behaviour — essential for parity.
- **Cached with webhook invalidation.** Reads go through the shared cache (short
  TTL); a Directus edit fires the [loopback webhook](./directus-write-plane) and the
  matching `app_config:<key>` entry is invalidated within seconds, not at TTL.

A representative slice of the registry:

| Key | Type | Default | Note |
|---|---|---|---|
| `quiz.cooldown_days` | int | 7 | |
| `quiz.duration_min` | int | 45 | |
| `quiz.questions_per_quiz` | int | 30 | |
| `quiz.pass_mark_correct` | int | 25 | cert-load-bearing — see below |
| `media.max_video_size_mb` | float | 30 | |
| `media.max_image_size_mb` | float | 2.5 | |
| `media.max_video_duration_sec` | int | 60 | |
| `feed.flag_threshold` | int | 1 | |
| `feed.require_review_on_post` | bool | true | |
| `features.llm.enabled` | bool | false | LLM seam, off by default |

### Tier 3 — content, Directus collections

The authored content types — covered across the rest of this section. They are
edited in Directus over the existing Postgres tables and read by FastAPI through the
same database it already uses.

:::note[Why This Matters]

The `quiz.pass_mark_correct` row is the one Tier 2 value that touches certificate
integrity, and the design pins its behaviour precisely. Certificate verification
recomputes the HMAC over the **signed score only** — it never reads any `app_config`
row. So changing the pass mark affects only *new* attempts; it can never
retroactively invalidate or revalidate a certificate already issued. The grader
freezes the live value into the attempt's payload for display and forensics, but the
verifier does not consult it. An architect must hold this line: a runtime-editable
config value must never be allowed to change the meaning of an already-sealed
artefact.

:::

:::caution[Common Pitfall]

Putting a secret in `app_config` because it is "just a key the app needs". The
`app_config` table is readable by the Platform Admin in Directus and is dumped to
git on export — both fatal for a secret. The tier is decided by the registry in the
config-and-CMS design doc, not by convenience. If a value would let an attacker
forge identity or read the database, it is Tier 1 and lives in env, full stop.

:::

## Media: Postgres large objects, final

Media is bytes — short-form videos and images attached to feed posts and referenced
by content. The decision on where those bytes live is **final and singular**:

> **All media lives in Postgres large objects and is streamed from there. No S3, no
> object store, no filesystem media store. Postgres is the only database.**

The earlier storage-adapter / S3 direction is cancelled. There is no media
migration. Directus stores **no** app media — it binds `media_assets` as read-only
metadata so editors can reference an asset by id, and app-media uploads into
`directus_files` are disabled by permission.

### How a byte gets in and out

```
   UPLOAD                                       SERVE (with Range)
 ┌───────────────────────────┐              ┌────────────────────────────────┐
 │ POST /api/media/upload     │              │ GET /media/video/{asset_id}    │
 │  (permission: media.upload)│              │ GET /media/image/{asset_id}    │
 └────────────┬──────────────┘              └───────────────┬────────────────┘
   validate    │ MIME sniff, size, duration     look up      │ media_assets row
   bytes ──────▶ create large object ──┐        oid+size+mime │ by asset_id
                 (pg_largeobject)      │                      ▼
                 record metadata ──────┘        stream chunks from pg_largeobject
                 in media_assets                 honouring HTTP Range (206)
```

- **Upload** — `POST /api/media/upload` (guarded by the `media.upload` permission)
  sniffs the MIME type, validates size and video duration, refuses SVG/XML/HTML,
  then creates a large object in `pg_largeobject` and records the metadata row in
  `media_assets` (`backend/app/modules/media/service.py`).
- **Serve** — `GET /media/video/{asset_id}` looks up the row, then streams the bytes
  from the large object in chunks, honouring the `Range` header with a `206 Partial
  Content` response (`Content-Range`, `Accept-Ranges`, `Content-Length`). This is
  what lets a learner scrub a video. `GET /media/image/{asset_id}` streams the whole
  object.

### The metadata row vs the bytes

The `media_assets` table holds metadata only: `id` (UUID), `large_object_oid` (the
pointer into `pg_largeobject`, with no foreign key possible), `filename`,
`mime_type`, `size_bytes`, `uploaded_by`, `uploaded_at`. The bytes are the large
object. Because the OID is not a foreign key, integrity is procedural — the design
adds two mechanisms to stop the byte store leaking:

1. A **`BEFORE DELETE` trigger** on `media_assets` that calls `lo_unlink` on the
   OID, so an application delete never orphans bytes.
2. A nightly **`vacuumlo`** sweep that unlinks any large object referenced nowhere —
   catching orphans from a failed upload (where the large object is created before
   the metadata row is inserted).

:::note[Why This Matters]

Keeping media in Postgres rather than an object store is an unusual call, and it is
deliberate. The whole platform is "Postgres is the only database" — one backup
covers content and media together, one access-control surface, no second service to
secure or pay for, no signed-URL dance. The cost is that streaming large objects
holds a raw connection for the length of a transfer, which the connection-pool
sizing has to account for. That is a known, bounded cost the design accepts in
exchange for one fewer moving part. Do not reintroduce S3 — it was considered and
cancelled.

:::

:::caution[Common Pitfall]

Assuming Directus can upload or serve app media. It cannot, and that is by design.
Directus binds `media_assets` read-only and has no path into `pg_largeobject`;
`directus_files` is used only for incidental Directus-internal files like editor
avatars. App media is uploaded and streamed exclusively through FastAPI. If you see
a media asset in the Directus browser, you are looking at metadata — the bytes never
left Postgres, and never went through Directus.

:::
