# Baseline DB snapshot — v2 parity safety net

> Source DB: `quiz-certification/q0.db` (sqlite, used by local dev when
> `DATABASE_URL` is unset — `quiz-certification/app/config.py:46`).
> Snapshot taken at Phase 0 freeze using the project's own venv:
>
> ```
> cd quiz-certification && .venv/bin/python -c "
>   import sqlite3; cur = sqlite3.connect('q0.db').cursor()
>   ..."
> ```
>
> Cross-references:
> - Target schema + Alembic adoption plan: [`docs/architecture/v2/03-data-model.md` §2-3](../../docs/architecture/v2/03-data-model.md)
> - Role overload analysis (`users.role` column): [`docs/architecture/v2/04-authz-model.md` §5](../../docs/architecture/v2/04-authz-model.md)
> - ORM definitions: `quiz-certification/app/models.py:53-168`

## What this file proves

This is the **data baseline**. After Phase 2a's Alembic migration runs, the row
counts here must reconcile against the new schema (allowing for *additive*
deltas — new columns, new tables — but **never lost rows** in the seven tables
below). Production parity uses `pg_dump --schema-only` + per-table `SELECT
COUNT(*)`; the local snapshot uses sqlite as a proxy.

## 1. Database identity

| Property              | Value                                                                       |
|-----------------------|-----------------------------------------------------------------------------|
| Engine (local)        | SQLite 3 (file mode)                                                        |
| Engine (production)   | PostgreSQL (DSN provided via `DATABASE_URL` env)                            |
| File path (local)     | `quiz-certification/q0.db`                                                  |
| File size (bytes)     | 446 464                                                                     |
| Tables                | 7 — `attempts`, `course_chapters`, `feed_items`, `frameworks`, `media_assets`, `questions`, `users` |
| Indexes               | 5 named (all on `attempts`) + 6 auto (sqlite primary-key indexes)           |
| Total user rows       | **525** (4 attempts + 8 feed_items + 0 media_assets + 500 questions + 13 users + 0 course_chapters + 0 frameworks) |

The local `q0.db` is **not seeded** with course content (`course_chapters=0`,
`frameworks=0`). Production Postgres has these populated by the ETL
(`scripts/migrate_to_postgres.py` per `01-blueprint.md` §0.7). The smoke test
treats both as valid baselines; the parity criterion is "production row count
≥ baseline", not "local matches prod".

## 2. Per-table inventory

### 2.1 `users`  (rows = 13)

```sql
CREATE TABLE users (
        email VARCHAR(255) NOT NULL,
        name VARCHAR(255),
        picture VARCHAR(1024),
        role VARCHAR(32),
        provider VARCHAR(32),
        created_at DATETIME,
        updated_at DATETIME,
        preferences TEXT,
        PRIMARY KEY (email)
)
```

Role distribution (the overloaded column — capability strings **and** persona
keys live here side by side, see `04-authz-model.md` §1.3):

| role         | rows | classification                                  |
|--------------|------|-------------------------------------------------|
| FeedCreator  |   5  | capability (legacy single-string RBAC)          |
| architect    |   3  | persona (from `roles.py`)                        |
| coder        |   1  | persona                                          |
| devops       |   1  | persona                                          |
| pm           |   3  | persona                                          |

Phase 2b uses this exact split to drive the migration in
`04-authz-model.md` §5.2.

### 2.2 `attempts`  (rows = 4)

```sql
CREATE TABLE attempts (
        id INTEGER NOT NULL,
        test_code VARCHAR(32) NOT NULL,
        cert_id VARCHAR(64),
        quiz_id VARCHAR(64) NOT NULL,
        user_email VARCHAR(255) NOT NULL,
        difficulty VARCHAR(16) NOT NULL,
        score FLOAT NOT NULL,
        correct INTEGER NOT NULL,
        total INTEGER NOT NULL,
        passed BOOLEAN NOT NULL,
        started_at DATETIME NOT NULL,
        submitted_at DATETIME NOT NULL,
        certificate_path TEXT,
        payload JSON NOT NULL,
        signature VARCHAR(64),
        metadata TEXT,
        PRIMARY KEY (id),
        FOREIGN KEY(user_email) REFERENCES users (email)
)
-- indexes:
--   ix_attempts_cert_id        UNIQUE
--   ix_attempts_test_code      UNIQUE
--   ix_attempts_user_email
--   ix_attempts_passed
--   ix_attempts_submitted_at
```

| split                                  | rows |
|----------------------------------------|------|
| `passed = 0`                           |   3  |
| `passed = 1`                           |   1  |
| `cert_id IS NOT NULL`                  |   1  |
| `signature IS NOT NULL`                |   1  |
| **Legacy (cert without HMAC)**         |   0  |

One real signed certificate exists locally — `cert_id=CCA-F-20260605-E79E74AB`,
`test_code=AOC-20260605-D6YRNU`, owner `yash@deptagency.com`. This is the
**load-bearing parity artefact**: the public `/verify` endpoint must keep
returning `valid=true` for it after every migration. The smoke test includes a
direct request against this cert id.

### 2.3 `questions`  (rows = 500)

```sql
CREATE TABLE questions (
        id VARCHAR(64) NOT NULL,
        topic VARCHAR(128) NOT NULL,
        difficulty VARCHAR(16) NOT NULL,
        question TEXT NOT NULL,
        options JSON NOT NULL,
        correct_index INTEGER NOT NULL,
        explanation TEXT,
        status VARCHAR(32),
        version INTEGER,
        author_id VARCHAR(255),
        is_user_submitted BOOLEAN,
        created_at DATETIME,
        updated_at DATETIME,
        PRIMARY KEY (id),
        FOREIGN KEY(author_id) REFERENCES users (email)
)
```

| status      | rows |
|-------------|------|
| published   | 500  |

Difficulty distribution: `beginner=168`, `intermediate=168`, `advanced=164` —
matching the three-bucket model used by `quiz_generator.py`. 102 distinct
topics; the four "core" topics each carry 50 questions (`ai-governance`,
`app-builder-api-mesh`, `bmad`, `content-supply-chain`) plus
`code-coder-framework=87`.

The Phase 2a migration adds `status='archived'` semantics for the moderator
"remove" action (`main.py:721`) — verify no production rows currently use that
status before adopting the new constraint.

### 2.4 `feed_items`  (rows = 8)

```sql
CREATE TABLE feed_items (
        id VARCHAR(64) NOT NULL,
        type VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL,
        author_id VARCHAR(255),
        framework_ref VARCHAR(64),
        topics TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        data JSON NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(author_id) REFERENCES users (email)
)
```

| status         | type      | rows |
|----------------|-----------|------|
| published      | card      |   1  |
| published      | list      |   1  |
| published      | post      |   2  |
| published      | scenario  |   1  |
| published      | video     |   1  |
| published      | vocab     |   1  |
| pending-review | post      |   1  |

The seven feed-block types observed here pin the parity contract for the
front-end renderer registry (`app/js/registry.js`) — Phase ≥1 must not lose
any of these block types.

### 2.5 `media_assets`  (rows = 0)

```sql
CREATE TABLE media_assets (
        id VARCHAR(64) NOT NULL,
        large_object_oid INTEGER NOT NULL,
        filename VARCHAR(255) NOT NULL,
        mime_type VARCHAR(64) NOT NULL,
        size_bytes BIGINT NOT NULL,
        uploaded_by VARCHAR(255),
        uploaded_at DATETIME,
        PRIMARY KEY (id),
        FOREIGN KEY(uploaded_by) REFERENCES users (email)
)
```

Empty locally — large-object streaming is Postgres-only
(`03-data-model.md` §2.7). The `MediaAsset` table exists in the sqlite schema
purely so the ORM doesn't error on import. Production parity is asserted on
Postgres only.

### 2.6 `course_chapters`  (rows = 0)

```sql
CREATE TABLE course_chapters (
        filename VARCHAR(128) NOT NULL,
        ring VARCHAR(32) NOT NULL,
        title VARCHAR(255) NOT NULL,
        content JSON NOT NULL,
        created_at DATETIME,
        updated_at DATETIME,
        PRIMARY KEY (filename)
)
```

Empty locally → `/api/course/chapters` returns `{"chapters": []}`
(verified, see `fixtures/api-course-chapters.json`). In production the ETL
seeds **41 rows** (one per `content-architecture/course/sections/*.json` —
count from `tests/baseline/content-manifest.txt`). Production parity check:
`COUNT(*) FROM course_chapters >= 41`.

### 2.7 `frameworks`  (rows = 0)

```sql
CREATE TABLE frameworks (
        id VARCHAR(32) NOT NULL,
        data JSON NOT NULL,
        updated_at DATETIME,
        PRIMARY KEY (id)
)
```

Two logical rows in production: `id='spine'` (the framework hierarchy) and
`id='explainer'` (the framing JSON for the renderer). Both empty locally; the
filesystem fallback at `main.py:592-606` saves us — the smoke test asserts the
framework-explainer JSON is served either way.

## 3. Production snapshot procedure (Postgres)

When taking a real baseline against the production DB before any v2 migration:

```bash
# 1. Schema dump (no data, no owner, no privileges — pure structure).
pg_dump \
  --host="$PGHOST" --user="$PGUSER" --dbname="$PGDATABASE" \
  --schema-only --no-owner --no-privileges \
  --file=tests/baseline/prod-schema-$(date +%Y%m%d).sql

# 2. Per-table row counts.
psql --host="$PGHOST" --user="$PGUSER" --dbname="$PGDATABASE" --no-align --tuples-only \
  --command="
    SELECT relname, n_live_tup
    FROM pg_stat_user_tables
    WHERE schemaname = 'public'
    ORDER BY relname;" \
  > tests/baseline/prod-rowcounts-$(date +%Y%m%d).txt

# 3. Sentinel: the load-bearing real certificate must still verify.
psql --no-align --tuples-only --command="
    SELECT cert_id, test_code, user_email, passed,
           signature IS NOT NULL AS signed
    FROM attempts
    WHERE passed = true AND cert_id IS NOT NULL
    ORDER BY submitted_at;"
```

The output files are **uncommitted** (real PII / real cert ids); keep them
under `tests/baseline/.local/` or on an admin-only host. The *counts* and the
*sentinel cert id list* are what each phase gate compares.

## 4. Parity criteria for the data plane

Each phase gate runs the three commands above and asserts:

1. **Schema diff is additive only.** `diff prod-schema-pre.sql prod-schema-post.sql`
   must show only `+` lines (new tables, new columns with defaults). Any `-`
   line — dropped column, narrowed type, removed index — blocks the gate.
2. **Row counts never decrease** for `users`, `attempts`, `questions`,
   `feed_items`, `course_chapters`, `media_assets`, `frameworks`. Increases
   are fine.
3. **Every `cert_id` from the pre-snapshot still verifies via `GET /verify`.**
   Phase 2a's `signing_keys` table (`03-data-model.md` §2.5) must remap
   correctly — the old HMAC over `SECRET_KEY` cannot be silently revoked.
4. **`users.role` distribution is preserved at the persona+capability level.**
   The Phase 2b cutover (`04-authz-model.md` §5.2) must keep every existing
   user reachable by at least one capability in the new RBAC.

## 5. Reproducibility

To re-take this snapshot at any later gate (idempotent, read-only):

```bash
cd quiz-certification
.venv/bin/python <<'PY'
import sqlite3, json
conn = sqlite3.connect('q0.db')
cur = conn.cursor()

print("# tables / row counts")
for t, in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
):
    n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:20s} rows={n}")

print("\n# attempts with certs")
for r in cur.execute(
    "SELECT cert_id, test_code, user_email, passed, "
    "       signature IS NOT NULL "
    "FROM attempts WHERE cert_id IS NOT NULL ORDER BY submitted_at"
):
    print(" ", r)
PY
```
