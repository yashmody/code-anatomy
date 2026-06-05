# ADR 0001 · Content storage — JSON files now, Postgres later (split by domain)

**Status:** Accepted · 2026-06
**Context owner:** Yash Mody

## Context

The CODE-CODER learning system has two content domains with opposite storage profiles:

- **Course** — the authored field manual. Framework-navigated, version-controlled, read-mostly, written by a small editorial team.
- **Feed** — a user-generated stream. High-write, concurrent, unbounded growth, atomic engagement counters, a moderation state machine, and sorting by recency × engagement × topic.

The eventual target is Postgres with an indexable, semi-structured (JSONB) schema and search plugins. The question is whether to adopt Postgres now, during the HTML-componentization and course-extraction work.

## Decision

**Stay on JSON files for this phase. Apply Postgres per domain, when each domain warrants it:**

- **Course → files, long-term.** Authored content belongs in version control. The UI reads the JSON directly. Move to a database only if non-technical editors need a CMS, or full-text/semantic search across chapters becomes a requirement. Neither is true today.
- **Feed → Postgres, at the multi-user composer build.** UGC is a database workload, but it is not live yet — there are no real users posting, so there is nothing to store. The feed stays JSON for defining item shapes during this restructuring, and migrates to Postgres as part of the separate feed-backend effort (composer + API + moderation queue).

Do **not** stand up Postgres during the current restructuring.

## Rationale

- The current task — componentizing the HTML into block renderers and extracting course prose — needs neither a backend nor a database. Adding Postgres now introduces a service, migrations, an ORM, hosting, and connection management: real scope that delivers nothing for the work in front of us.
- Course-as-files is not a compromise; it is the correct end state for authored, versioned content.
- Deferring the feed DB costs nothing because the feed has no data until the composer ships.

## Postgres-readiness (so the later migration is mechanical)

Every content item is already a clean JSON object with a stable envelope, so it maps to one row: promoted columns for indexing + a JSONB column for the rest.

```sql
CREATE TABLE feed_item (
  id            text PRIMARY KEY,
  type          text NOT NULL,
  status        text NOT NULL,
  author_id     text NOT NULL,
  framework_ref text,
  topics        text[] NOT NULL DEFAULT '{}',
  created_at    timestamptz NOT NULL,
  updated_at    timestamptz NOT NULL,
  data          jsonb NOT NULL,            -- payload + media + engagement + moderation
  search        tsvector GENERATED ALWAYS AS
                  (to_tsvector('english', coalesce(data->>'title','') || ' ' || coalesce(data->>'body',''))) STORED,
  embedding     vector(1536)               -- pgvector, added when semantic search is needed
);
CREATE INDEX ON feed_item (status, created_at DESC);        -- feed ordering
CREATE INDEX ON feed_item USING gin (topics);               -- topic filter
CREATE INDEX ON feed_item USING gin (data jsonb_path_ops);  -- containment queries
CREATE INDEX ON feed_item USING gin (search);               -- full-text
-- CREATE INDEX ON feed_item USING hnsw (embedding vector_cosine_ops);  -- when pgvector added
```

Plugins, when the time comes: **pgvector** (embeddings → semantic search, "related posts"), **pg_trgm** (fuzzy match), built-in **tsvector** full-text. The JSON Schemas in `schemas/` are the contract that keeps the JSON mappable to this row shape; if a field can't map cleanly, the schema review catches it.

## Triggers to revisit

- **Feed → Postgres:** when the multi-user composer is built (next major effort).
- **Course → Postgres:** only if a CMS for non-technical editors or cross-chapter search is required.

Until those triggers fire, the envelope-stable JSON *is* the migration plan.

## Consequences

- **Positive:** restructuring ships without backend scope; course content stays in git; the feed schema is validated and Postgres-ready; migration becomes a mechanical load, not a redesign.
- **Negative / accepted:** the feed prototype can't demonstrate real multi-user posting (no concurrent writes, no live counters) until the backend exists — acceptable, because that is a deliberately separate build.
