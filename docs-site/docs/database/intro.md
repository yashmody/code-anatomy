---
id: intro
title: Database
sidebar_position: 1
---

# Database

> **Phase 0 stub.** Phase 5a expands this into the page set listed below.

## Scan box

- The platform is **Postgres-only** in v2. The dual SQLite/Postgres shims
  in the current `models.py` are retired — Postgres-only features
  (`tsvector`, `hstore`, `ARRAY`, large objects) become first-class.
- **Alembic** owns schema change. The hand-rolled `_migrate()` in
  `app/db.py` and the drifted `deploy_schema.sql` are retired; a baseline
  is stamped from the live schema, then one reconcile migration brings ORM
  and DDL into agreement.
- Seven existing tables (`users`, `attempts`, `questions`, `feed_items`,
  `media_assets`, `course_chapters`, `frameworks`) plus new ones in v2:
  `quiz_sessions`, `roles` + `user_roles`, `signing_keys`, `app_config`.
- **No data loss**: certificates already issued continue to verify because
  the HMAC input (`cert_id|email|score|submitted_at`) is unchanged and
  `attempts.environment` defaults to `production` for existing rows.
- Media bytes stay in `pg_largeobject` for streaming. Directus reads the
  metadata tables; FastAPI owns runtime writes (attempts, media bytes,
  flags, sessions).

## What lives here

This section is the database reference: every table, every index, the
migration story, how the score type drift was resolved, how large objects
are cleaned up on delete, and how to take/restore a logical backup.

Source contract: `docs/architecture/v2/03-data-model.md` is the design.
Everything in this section maps back to it.

## Planned pages (Phase 5a)

1. **Schema overview** — the eleven-ish v2 tables in one map.
2. **ER diagram** — auto-generated from Alembic metadata (see Sourcing in
   `v2/08-docs-plan.md`).
3. **Alembic and migrations** — baseline stamp, reconcile migration, the
   per-phase migration cadence.
4. **Postgres-only features** — `tsvector`, `hstore`, `ARRAY`, large
   objects; why the SQLite shims are gone.
5. **Media large objects** — `MediaAsset`, `pg_largeobject`, the cleanup
   trigger that prevents orphan OIDs.
6. **Backup and restore** — `pg_dump --format=custom` recipe, restore
   walk-through, retention policy.

:::warning Common Pitfall

Storing `attempts.score` as `NUMERIC(5,2)`. The HMAC signature is
computed over `f"{score:.6f}"` — rounding the column breaks every
already-issued certificate. v2 keeps `score` as `DOUBLE PRECISION` and
the data-model doc calls this out as load-bearing.

:::

## Cross-references

- `docs/architecture/v2/03-data-model.md` — full schema and migration
  plan.
- `docs/architecture/v2/06-caching-performance.md` — connection pooling
  and Postgres tuning.
- `docs/architecture/v2/07-security-baseline.md` — encryption at rest,
  role grants, audit trail.
