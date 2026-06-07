---
id: database-intro
title: Database
sidebar_position: 1
---

# Database

The v2 platform runs on a single Postgres database per environment — `codecoder`
for production — hosted on a **remote shared instance** the app VM connects out
to over TLS. The one instance carries every environment's database side by side
(`codecoder` for prod, `codecoder_dev` for dev), isolated by separate login roles
per environment. Two services share each database: the FastAPI application plane
writes runtime data (attempts, quiz sessions, media bytes, feed flags) and the
Directus editorial plane writes content and configuration through a scoped
database role. There is no object store and no SQLite in production. This section
documents the schema, the migration chain that builds it, and the lifecycle rules
that keep it honest.

## Scan box

- **One Postgres database per env, two writers.** FastAPI owns the runtime
  tables; Directus edits the content and config tables as the scoped
  `directus_app` role. Thirteen application tables, plus Directus's own
  `directus_*` system tables, coexist in the same database without name
  collision. The database lives on a **remote shared instance** (one instance,
  separate `codecoder` / `codecoder_dev` databases, per-env roles, TLS).
- **Alembic owns every schema change.** The chain runs `0001`→`0008`. The
  baseline (`0001`) is stamped — never run — against the live schema, so
  adoption touched no existing rows. The hand-rolled `_migrate()` patcher
  and the drifted `deploy_schema.sql` are retired.
- **Certificates never break.** The HMAC seal hashes
  `cert_id|email|score|submitted_at`. `score` stays `DOUBLE PRECISION` (not
  `NUMERIC(5,2)`), every existing attempt is backfilled to the `legacy-prod`
  signing key, and `attempts.environment` defaults to `production` — so
  every cert issued before v2 verifies byte-for-byte after it.
- **Media is Postgres large objects, full stop.** Bytes live in
  `pg_largeobject`, referenced by `media_assets.large_object_oid`, uploaded
  and streamed (with HTTP Range) by FastAPI. A `BEFORE DELETE` trigger plus
  a nightly `vacuumlo` cron stop orphaned bytes. No S3, no filesystem store.
- **The runtime tables are walled off from editors.** `attempts`,
  `quiz_sessions`, `signing_keys` and `auth_audit` are hard-denied to
  `directus_app` — not even `SELECT`. The deny is an explicit
  `REVOKE ALL`, not an oversight.

## Why a single Postgres

The decision is deliberate and it shapes everything downstream. Postgres
carries the relational data, the full-text search (`tsvector` + GIN), the
JSON document columns (`JSONB`), the role taxonomy, and the media bytes
(large objects). Putting all of that in one engine means one backup
boundary, one transactional guarantee, and one place where the FastAPI
runtime and the Directus editor agree on the truth. The earlier idea of an
S3 or storage-adapter media tier was cancelled on 2026-06-06; large objects
are the permanent media home.

What changed in the same period is *where* that Postgres runs. It moved off the
app VM to a **remote shared instance** — one instance hosting both the prod
(`codecoder`) and dev (`codecoder_dev`) databases — because a co-resident
Postgres, with the media bytes now inside it, consumed too much of the VM's disk.
The "one engine, one backup boundary" property is unchanged *per environment*;
what is new is that the connection is over TLS and that two environments share the
instance, isolated by separate databases and separate per-env login roles (see
[Role isolation](./role-isolation.md)).

The cost of that choice is that the schema is Postgres-specific and cannot
be exercised faithfully on SQLite. The SQLite shims still present in
`backend/app/core/models.py` exist only so the local smoke suite can run
without a Postgres container; they are not a supported production path, and
the Postgres-only features they paper over are documented in
[Postgres-only features](./postgres-only-features.md).

## Section map

| Page | What it covers |
|---|---|
| [Schema overview](./schema-overview.md) | The thirteen application tables, an ER diagram, who writes each one |
| [Alembic migrations](./alembic-migrations.md) | The `0001`–`0008` chain, the stamped baseline, the no-data-loss approach |
| [Role isolation](./role-isolation.md) | The `directus_app` GRANT/REVOKE matrix and the hard-denied runtime tables |
| [Media large objects](./media-large-objects.md) | `pg_largeobject`, the `lo_unlink` trigger, `vacuumlo`, Range streaming |
| [Postgres-only features](./postgres-only-features.md) | `JSONB`, `tsvector`, `ARRAY`, large objects, connection pooling, the SQLite shim |

## Source of truth for this section

Every claim here is grounded in the real code and the design contract.
The primary sources are:

- `docs/architecture/v2/03-data-model.md` — the data-model design contract.
- `backend/app/core/models.py` — the SQLAlchemy models (the schema source).
- `backend/migrations/versions/0001`–`0008` — the migration chain.
- `backend/app/core/db.py` — engine, pooling, `init_db()`.
- `backend/app/modules/media/service.py` — large-object I/O and streaming.

Where the design doc and the shipped code differ, this section follows the
shipped code. The most visible difference: the design sketched
`signing_keys.key_id` and `roles.role_key` as text primary keys, but the
shipped tables use an integer surrogate `id` with a unique `name`/`key`
column. The documentation describes what is in the database.
