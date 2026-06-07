---
id: postgres-only-features
title: Postgres-only features
sidebar_position: 3
---

# Postgres-only features

## Scan box

- **Production is Postgres-only.** The schema depends on Postgres features
  with no SQLite equivalent: `JSONB`, `tsvector` full-text search with GIN
  indexes, `ARRAY` columns, `hstore`, and large objects.
- **The SQLite shim survives, but only for the local smoke suite.**
  `models.py` branches on the database URL and substitutes JSON-encoded TEXT
  for the Postgres types. That path runs a *materially different* schema and
  is not a production target.
- **The engine is pooled for Postgres** — `pool_size=5`, `max_overflow=5`,
  `pool_pre_ping=True`, `pool_recycle=1800` per worker — and uses `NullPool`
  on SQLite where pooling is moot.
- **Directus's `directus_*` system tables coexist** in the same database,
  disjoint from the application tables by name, and excluded from Alembic
  autogenerate.

The dialect branch is in `backend/app/core/models.py`; the engine config is
in `backend/app/core/db.py`. The stance is argued in
`docs/architecture/v2/03-data-model.md` §4 and §7.

## The Postgres feature set the schema relies on

Five Postgres capabilities are load-bearing. None has a faithful SQLite
equivalent, which is the whole reason the platform is Postgres-only.

| Feature | Where it is used | Why it matters |
|---|---|---|
| `JSONB` | `questions.options`, `feed_items.data`, `course_chapters.content`, `frameworks.data`, `app_config.value`, `quiz_sessions.*`, `auth_audit.before/after` | Document columns for the content tree, quiz state, and audit snapshots — queried and indexed, not just stored |
| `tsvector` + GIN | `feed_items.search` (generated) + `idx_feed_items_search` | Full-text search over the feed |
| `ARRAY` + GIN | `feed_items.topics` + `idx_feed_items_topics` | Multi-valued topic tags, filtered with array operators |
| `hstore` | `users.preferences`, `attempts.metadata` | Flat key-value stores carried from the legacy schema |
| Large objects | `media_assets.large_object_oid` → `pg_largeobject` | Seekable, streamed media bytes (see [Media large objects](./media-large-objects.md)) |

`JSONB` is the workhorse — most of the content in this platform is a JSON
document tree, and putting it in `JSONB` rather than a flattened relational
shape is a deliberate choice that keeps the editorial model close to the
on-screen structure. `tsvector` and the GIN indexes give the feed real search
without an external search engine. `hstore` is the one legacy holdover; the
design notes a path to migrate it to `JSONB`, but the shipped schema still
carries it.

:::note[Why This Matters]

The Postgres-only stance is not dogma — it falls directly out of the feature
list above. Large objects, generated `tsvector` columns, GIN indexes, and
`hstore` operators simply do not exist on SQLite. Any test that passed on
SQLite would prove nothing about whether search works, whether media streams,
or whether a generated column is populated. Choosing one engine for both
development and production is the only way the tests mean something — which is
why the SQLite shim is a local-suite convenience, never a deployment option.

:::

## The SQLite shim — what it is and is not

`models.py` opens with a branch on the database URL:

```python
if "postgresql" in config.DATABASE_URL:
    # real JSONB, HSTORE, ARRAY, OID
else:
    # JSON-encoded TEXT decorators standing in for each
```

On SQLite, `JSONB` becomes `JSON`, `HSTORE` and `ARRAY` become
`TypeDecorator`s that `json.dumps`/`json.loads` over a `TEXT` column, and
`OID` becomes `Integer`. This lets the smoke suite run without a Postgres
container.

What the shim cannot reproduce: the generated `search` column, the GIN
indexes, the `hstore` operators, and — critically — large objects. On
SQLite there are no large objects at all, so the media path is structurally
absent. A migration like `0006_lo_cleanup` and `0008_directus_app_role`
detects the dialect and no-ops on SQLite for exactly this reason.

:::caution[Common Pitfall]

Reading a green SQLite test run as evidence that a Postgres-only feature
works. The shim runs a different schema: no `search` column, no GIN indexes,
no large objects, no roles. A feature that touches any of those is simply not
exercised on SQLite. When you need confidence in search, media, or role
isolation, run against Postgres — a throwaway container is the right local
dev database, same engine as production, zero shim.

:::

## Connection pooling

`db.py` configures the SQLAlchemy engine by dialect. For Postgres it sets a
tuned `QueuePool`:

```python
pool_size = 5
max_overflow = 5
pool_pre_ping = True
pool_recycle = 1800
```

The reasoning, per the data-model contract §7.1:

- **`pool_pre_ping=True`** issues a cheap liveness check before handing out a
  connection, so a connection silently cut by Apache or a proxy is replaced
  rather than handed to a request that then fails.
- **`pool_recycle=1800`** (30 minutes) retires connections before any
  server-side idle timeout can kill them out from under the pool.
- **`pool_size` × `worker_count`** must stay well under the **remote instance's**
  `max_connections`, with headroom for Directus's own pool, `psql` sessions, and
  the **raw large-object connections** the media path opens
  (`engine.raw_connection()`), which are *not* drawn from the SQLAlchemy pool and
  must be counted separately. On the shared instance the budget is across *every*
  environment and app VM that connects — prod and dev share the same
  `max_connections` ceiling, so size each env's pool with the other in mind.

On SQLite, `db.py` uses `NullPool` and `check_same_thread=False` — pooling is
largely moot there and `NullPool` avoids stale-connection surprises with
FastAPI's thread pool.

:::tip[Agency Tip]

When you size workers, count *all* the database connections, not just the
pool. With four uvicorn workers at `pool_size=5, max_overflow=5` that is up
to 40 pooled connections, plus a margin for the raw streaming connections a
long video Range request holds for the whole transfer, plus Directus's pool.
A long scrub through a large video pins one raw connection until the stream
ends — under concurrent video load those are the connections that quietly
eat your `max_connections` headroom. Leave room for them.

:::

## Coexistence with Directus's system tables

Directus runs as a separate Node service against the same Postgres and
creates its own `directus_*` system tables — `directus_users`,
`directus_roles`, `directus_permissions`, `directus_files`,
`directus_activity`, `directus_revisions`, and more. These are **disjoint by
name** from the application tables: the app uses `users` and `roles`, Directus
uses `directus_users` and `directus_roles`. There is no collision and the two
identity systems stay separate — Directus's tables are the *staff* editorial
identity plane, the application's `users`/`roles` are the *learner* plane.

Two rules keep the coexistence clean:

1. **Alembic never touches `directus_*`.** The `include_object` hook in
   `env.py` excludes any table whose name starts with `directus_` from
   autogenerate, so a future `--autogenerate` can never propose dropping or
   altering a Directus table (see
   [Alembic migrations](./alembic-migrations.md)).
2. **Directus never touches the runtime tables.** The `directus_app` role's
   GRANT/REVOKE matrix denies `attempts`, `quiz_sessions`, `signing_keys`,
   and `auth_audit` outright (see [Role isolation](./role-isolation.md)).

```
        one Postgres database "codecoder"
   ┌──────────────────────┬──────────────────────┐
   │  application tables   │  directus_* tables    │
   │  (Alembic-managed)    │  (Directus-managed)   │
   ├──────────────────────┼──────────────────────┤
   │  users, attempts,     │  directus_users,      │
   │  questions, roles,    │  directus_roles,      │
   │  feed_items, ...      │  directus_files, ...  │
   └──────────────────────┴──────────────────────┘
     Alembic skips directus_*     Directus role denied
     in autogenerate              the runtime tables
```

The result is two tools sharing one database, each authoritative over its own
namespace, neither able to corrupt the other's. That is the foundation the
whole [database section](./database-intro.md) rests on: a single Postgres, governed by
two cooperating but isolated planes.

## Extensions

The schema depends on two Postgres extensions:

- **`pgcrypto`** — provides `gen_random_uuid()`, used for media asset ids.
- **`hstore`** — still required by `users.preferences` and
  `attempts.metadata` in the shipped schema.

On a self-managed Postgres `init_db()` issues `CREATE EXTENSION IF NOT EXISTS`
for both, which is idempotent. On the **remote shared instance**, however, the
runtime app role (`app_prod` / `app_dev`) is DML-only and has **no privilege to
`CREATE EXTENSION`** — that is a superuser/owner operation on a managed instance.
So the extensions are **pre-created by the DBA** in each database (`codecoder`,
`codecoder_dev`) before the app boots, and `init_db()` treats its own
`CREATE EXTENSION` attempt as **non-fatal**: if the call fails for lack of
privilege, the app logs and continues rather than refusing to start, because the
extension is already present. The schema is owned by Alembic (run with a
privileged migration credential), not by per-boot DDL.

:::caution[Common Pitfall]

Assuming the app can bootstrap its own extensions on a managed remote, as it did
when Postgres was co-resident and `init_db()` ran as a privileged local role. It
cannot — the runtime role has DML only. If `pgcrypto` or `hstore` is missing,
media asset id generation and the `hstore` columns break, and the fix is for the
DBA to `CREATE EXTENSION` in that database, not to widen the app role's
privileges. Pre-create the extensions as part of the same DBA pre-flight that
creates the databases and the per-env roles.

:::

If a future migration converts the `hstore` columns to `JSONB`, the `hstore`
extension can be dropped — but that is not the shipped state.
