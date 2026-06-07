---
id: four-content-types
title: The four content types
sidebar_position: 2
---

# The four content types

## Scan box

- The platform carries four distinct kinds of content: **authored course prose**,
  **feed user-generated content (UGC)**, **media**, and **configuration**. They
  have different write patterns, so they get different homes — but all four live
  in one Postgres database.
- **Course prose** is low-write, read-mostly, authored by editors. **Feed UGC** is
  high-write, concurrent, contributor-authored and moderated. The split is the
  point: neither tool has to understand the other's structure.
- **Media** is bytes — videos and images — and lives in Postgres large objects.
  **Configuration** is non-secret runtime tunables and lives in the `app_config`
  table. Secrets are a fifth thing and never count as content: they stay in env.
- One database, one read path. FastAPI reads every content type from Postgres
  (cached); Directus writes the authored types. There is no second content store.

The first job of a content architecture is to say what content *is*, and to give
each kind exactly one home. The DEPT Anatomy of Code platform names four kinds.
They differ in who writes them, how often, and under what review — and those
differences, not the storage engine, decide the design. What unites them is that
all four resolve to rows in the same `codecoder` Postgres database, read at
runtime through one cached FastAPI read path.

## The four kinds

### 1 · Static course content (authored)

The canonical field manual: the CODE-CODER framework spine and the chapter prose
that hangs off each framework letter. It is **authored**, **versioned**,
**low-write**, and **read-mostly** — written deliberately by editors, not by the
crowd. It is structured as a block tree (covered in
[the course block model](./course-block-model)) so two renderers — Manual mode and
Read mode — can render the same content from one source.

- **Store:** the `course_chapters` table (one row per chapter file) and the
  `frameworks` table (two rows: `framework` and `explainer`).
- **Writer:** the Content Author role, through Directus.
- **Seed and export:** `content/source/course/sections/*.json` (31 chapter files)
  and `content/source/course/framework.json` (the spine).

### 2 · Feed UGC (contributor-authored, moderated)

A social stream. Any signed-in contributor can post one of six types — `post`,
`video`, `list`, `card`, `vocab`, `scenario` — through a composer. It is the
opposite write profile to the course: **high-write**, **concurrent**, **unbounded
growth**, with atomic engagement counters and a moderation state machine. You
cannot run a real feed off a JSON file; this is a database workload.

- **Store:** the `feed_items` table — promoted columns for indexing
  (`type`, `status`, `topics`, `created_at`) plus a JSONB `data` column for the
  type-specific payload.
- **Writers:** the FastAPI runtime writes new posts and flags; the Feed Moderator
  role updates `status` through Directus. Two write surfaces, one provenance seam
  (the `status` column).
- **Seed:** `content/source/feed/feed.json` is illustrative shape only — the feed
  starts empty in production and fills as people post.

### 3 · Media (bytes)

Videos and images attached to feed posts and referenced by course content. Media
is **not** stored inline in any JSON or JSONB column — it is bytes, and bytes
belong in a byte store. In this platform that store is **Postgres large objects**,
streamed by FastAPI with HTTP Range support. This is final; the
[config-and-media page](./config-and-media) covers it in full.

- **Store:** `pg_largeobject` (the bytes) plus the `media_assets` table (the
  metadata: id, OID, filename, MIME type, size, uploader).
- **Writer:** the FastAPI runtime, via `POST /api/media/upload`. Directus holds
  the metadata read-only and never the bytes.

### 4 · Configuration (non-secret runtime tunables)

Values an operator wants to flip without a redeploy: the quiz duration, the pass
mark, media size limits, the feed flag threshold, feature flags. These are
content in the sense that they are edited through the CMS, but they are *settings*,
not prose.

- **Store:** the `app_config` table — one JSONB-valued row per dot-prefixed key.
- **Writer:** the Platform Admin role, through Directus.
- **Seed:** compiled-in defaults in `core/cms_client.py`, so an empty table
  behaves exactly like today's hardcoded values.

## Where each kind lives

```
                         ┌──────────────────────────────────────────────┐
                         │            codecoder  (Postgres)             │
                         │                                              │
  COURSE (authored) ────▶│  course_chapters   frameworks                │
                         │                                              │
  FEED (UGC) ───────────▶│  feed_items        questions  (UGC + bank)   │
                         │                                              │
  MEDIA (bytes) ────────▶│  media_assets  ──▶  pg_largeobject           │
                         │                                              │
  CONFIG (tunables) ────▶│  app_config                                  │
                         └──────────────────────────────────────────────┘
                                  ▲                          ▲
                                  │ writes                   │ reads (cached)
                          ┌───────┴────────┐         ┌───────┴────────┐
                          │  Directus 11   │         │  FastAPI app   │
                          │  (editorial)   │         │  (runtime API) │
                          └────────────────┘         └────────────────┘

  SECRETS are NOT content — they live in env (.env, Pydantic Settings),
  never in Postgres, never in git, never in a Directus collection.
```

## Why the split earns its keep

The course and the feed have opposite storage profiles, so they get opposite
tools. The course editor never has to understand engagement metrics; the feed
composer never has to understand the block model. Keeping the two authoring
surfaces separate keeps each one simpler. The same logic separates configuration
from prose, and separates both from secrets — different risk, different store.

:::tip[Agency Tip]

When you onboard onto a content platform, the first question is not "what database"
but "how many kinds of content, and who writes each". Get that wrong and you end up
with one over-loaded table and one over-loaded editor role doing four unrelated
jobs. The DEPT Anatomy of Code platform spent its design budget on the *split*, not
the storage engine — Postgres is just where all four happen to land.

:::

:::caution[Common Pitfall]

Counting secrets as a content type. `SECRET_KEY`, `GOOGLE_CLIENT_SECRET`, the
database password, the certificate HMAC keys — none of these are content. They
live in env and are read once at process start. The moment a secret reaches a
Directus collection or a git-tracked JSON file, the model is broken. The
[config-and-media page](./config-and-media) draws the secret/config/content line
in full.

:::
