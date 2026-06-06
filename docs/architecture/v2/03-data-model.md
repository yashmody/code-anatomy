# v2/03 · Data model — target Postgres schema, Alembic plan, Directus compatibility

> Status: **Phase 0 — DESIGN ONLY.** No code changes, no migrations run. This is
> the contract Phase 2a (DB + migrations) implements directly.
> Owner agent: Data model. Covers plan item **6** (Postgres schema + DB
> integration). Coordinates with `04-authz-model.md` (item 8), `05-config-cms.md`
> (items 2/11/3), `06-caching-performance.md` (item 5, pooling), and
> `07-security-baseline.md` (item 7, cert dev-mode + LO lifecycle).

All file:line citations are against branch `v2` at the time of writing.

---

## 0 · Scan box

- The "quiz" backend already owns **7 tables** for quiz, feed, course, media and
  framework — it is the whole backend, not a quiz module. The schema is defined
  in **two places that have drifted** (`app/models.py` vs `deploy_schema.sql`)
  with no migration tool reconciling them.
- Hard problems to fix in 2a: **score type drift** (`NUMERIC(5,2)` vs `Float`),
  a hand-rolled `_migrate()` that ALTERs by inspection, **dual sqlite/postgres**
  type shims that hide Postgres-only features (`tsvector`, `ARRAY`, `hstore`,
  large objects), **orphaned `pg_largeobject` OIDs** on media delete, an
  **in-memory `_active_quizzes` dict** that breaks multi-worker, and an
  **overloaded `users.role`** carrying two unrelated concepts.
- Target: **Postgres-only** for any DB feature; **Alembic** baseline-stamped
  from the live schema then one reconcile migration; `deploy_schema.sql` and
  `_migrate()` retired. New tables: `quiz_sessions`, `roles` + `user_roles`,
  `signing_keys`, `app_config`. New columns: `users.persona`,
  `attempts.environment` + `attempts.signing_key_id`.
- **Source of truth = Postgres** (editable), git-JSON becomes export/seed — a
  deliberate shift from ADR 0001. Directus owns the staff-edited content
  collections and introspects the existing app tables; FastAPI owns runtime
  writes (attempts, sessions, media bytes, flags).
- **No data loss**: certs already issued keep verifying because the HMAC input
  (`cert_id|email|score|submitted_at`, `storage.py:21-28`) is unchanged and dev
  markers default to the production environment for existing rows.

---

## 1 · Current schema (as built)

Seven tables. ORM in `quiz-certification/app/models.py`; raw DDL in
`quiz-certification/deploy_schema.sql`. The two are **not** generated from one
source and have drifted (see §1.9).

### 1.1 `users` — identity + overloaded role
`models.py:53-68`, `deploy_schema.sql:6-15`

| Column | ORM type | DDL type | Notes |
|---|---|---|---|
| `email` | `String(255)` PK | `VARCHAR(255)` PK | natural key; lower-cased in app (`storage.py:68`) |
| `name` | `String(255)` | `VARCHAR(255)` | |
| `picture` | `String(1024)` | `VARCHAR(1024)` | |
| `role` | `String(32)` | `VARCHAR(32)` | **OVERLOADED** — see §1.10 |
| `provider` | `String(32)` | `VARCHAR(32)` | `'google'` / `'dev'` |
| `preferences` | `HSTORE` (sqlite: TEXT JSON) | `hstore DEFAULT ''::hstore` | flat KV |
| `created_at` | `DateTime` (naive utcnow) | `TIMESTAMPTZ DEFAULT now()` | **tz drift** — ORM naive, DDL aware |
| `updated_at` | `DateTime` onupdate | `TIMESTAMPTZ DEFAULT now()` | DDL has **no** `ON UPDATE`; the ORM sets it |

Relationships (`models.py:65-68`): `attempts`, `questions`, `feed_items`,
`media_assets`, all `lazy="dynamic"`.

### 1.2 `attempts` — graded quiz submissions + cert seal
`models.py:71-94`, `deploy_schema.sql:36-54`

| Column | ORM type | DDL type | Notes |
|---|---|---|---|
| `id` | `Integer` PK autoinc | `SERIAL PK` | |
| `test_code` | `String(32)` unique, not null, idx | `VARCHAR(32) UNIQUE NOT NULL` | `AOC-YYYYMMDD-XXXXXX` (`storage.py:54-63`) |
| `cert_id` | `String(64)` unique, nullable, idx | `VARCHAR(64) UNIQUE` | `CCA-F-YYYYMMDD-XXXXXXXX` (`main.py:378-383`) |
| `quiz_id` | `String(64)` not null | `VARCHAR(64) NOT NULL` | the ephemeral session id |
| `user_email` | FK→`users.email`, not null, idx | FK **ON DELETE CASCADE** | ORM declares **no** ondelete |
| `difficulty` | `String(16)` not null | `VARCHAR(16) NOT NULL` | |
| `score` | **`Float`** | **`NUMERIC(5,2)`** | **DRIFT — see §1.9.1.** ORM stores a 0–1 fraction (`quiz_generator.py:188`) |
| `correct` | `Integer` not null | `INT NOT NULL` | |
| `total` | `Integer` not null | `INT NOT NULL` | |
| `passed` | `Boolean` not null, idx | `BOOLEAN NOT NULL` | |
| `started_at` | `DateTime` not null | `TIMESTAMPTZ NOT NULL` | tz drift |
| `submitted_at` | `DateTime` not null, default, idx | `TIMESTAMPTZ DEFAULT now()` | tz drift |
| `certificate_path` | `Text` | `TEXT` | server filesystem path |
| `signature` | `String(64)` | `VARCHAR(64)` | HMAC-SHA256, added by `_migrate()` |
| `payload` | `JSONB`/`JSON` not null | `JSONB NOT NULL` | `{questions, user_answers, grading}` |
| `attempt_metadata` → col **`metadata`** | `HSTORE` | `hstore DEFAULT ''::hstore` | attr renamed to dodge SQLAlchemy reserved `metadata` (`models.py:94`) |

Index: `idx_attempts_user (user_email, submitted_at DESC)` (`deploy_schema.sql:54`)
— **DDL only**, not in the ORM.

> **Note on `score`:** the signature is computed over `f"{score:.6f}"`
> (`storage.py:23`). If `score` is ever stored as `NUMERIC(5,2)` and re-read as a
> rounded value, the recomputed HMAC will not match. Today the ORM `Float`
> happens to preserve the fraction, so verification works — but this is
> load-bearing and must be preserved through the type resolution (§2.1).

### 1.3 `questions` — quiz bank with versioning + UGC
`models.py:97-115`, `deploy_schema.sql:18-33`

| Column | ORM type | DDL type | Notes |
|---|---|---|---|
| `id` | `String(64)` PK | `VARCHAR(64) PK` | e.g. `q.ugc.<feedid>` (`main.py:662`) |
| `topic` | `String(128)` not null | `VARCHAR(128) NOT NULL` | |
| `difficulty` | `String(16)` not null | `VARCHAR(16) NOT NULL` | |
| `question` | `Text` not null | `TEXT NOT NULL` | |
| `options` | `JSONB`/`JSON` not null | `JSONB NOT NULL` | array of strings |
| `correct_index` | `Integer` not null | `INT NOT NULL` | |
| `explanation` | `Text` | `TEXT` | |
| `status` | `String(32)` default `'draft'` | `VARCHAR(32) DEFAULT 'draft'` | draft/pending_review/published/archived |
| `version` | `Integer` default 1 | `INT DEFAULT 1` | |
| `author_id` | FK→`users.email`, nullable | FK **ON DELETE SET NULL** | ORM declares no ondelete |
| `is_user_submitted` | `Boolean` default False | `BOOLEAN DEFAULT FALSE` | |
| `created_at` / `updated_at` | `DateTime` | `TIMESTAMPTZ` | tz drift |

Index: `idx_questions_lookup (status, difficulty, topic)` (`deploy_schema.sql:33`)
— **DDL only**. Note the live query in `quiz_generator.py:70-78` filters
`difficulty, status` then `id NOT IN (...)`.

### 1.4 `feed_items` — UGC stream
`models.py:118-133`, `deploy_schema.sql:57-73`

| Column | ORM type | DDL type | Notes |
|---|---|---|---|
| `id` | `String(64)` PK | `VARCHAR(64) PK` | `post.<hex>` |
| `type` | `String(32)` not null | `VARCHAR(32) NOT NULL` | post/video/list/card/vocab/scenario |
| `status` | `String(32)` not null default `'published'` | same | draft/pending_review/published/flagged/removed |
| `author_id` | FK→`users.email`, nullable | FK **ON DELETE SET NULL** | ORM declares no ondelete |
| `framework_ref` | `String(64)` | `VARCHAR(64)` | the optional bridge |
| `topics` | `ARRAY(Text)` (sqlite: TEXT JSON) | `TEXT[] NOT NULL DEFAULT '{}'` | ORM default `[]` is mutable-default risk |
| `created_at` / `updated_at` | `DateTime` not null | `TIMESTAMPTZ NOT NULL` | tz drift |
| `data` | `JSONB`/`JSON` not null | `JSONB NOT NULL` | full envelope: payload, media, engagement, moderation |
| `search` | **absent in ORM** | `tsvector GENERATED ALWAYS AS (...) STORED` | **DRIFT — see §1.9.2** |

Indexes (`deploy_schema.sql:71-73`, **DDL only**):
`idx_feed_items_ordering (status, created_at DESC)`,
`idx_feed_items_topics USING gin (topics)`,
`idx_feed_items_search USING gin (search)`.

### 1.5 `media_assets` — large-object metadata
`models.py:136-148`, `deploy_schema.sql:76-84`

| Column | ORM type | DDL type | Notes |
|---|---|---|---|
| `id` | `String(64)` PK | `UUID PK DEFAULT gen_random_uuid()` | **DRIFT** — ORM passes a Python `uuid4()` string (`media_service.py:110`); DDL generates server-side. Type mismatch `VARCHAR` vs `UUID`. |
| `large_object_oid` | `OID` (sqlite: Integer) not null | `OID NOT NULL` | points into `pg_largeobject`; **no FK possible** |
| `filename` | `String(255)` not null | `VARCHAR(255) NOT NULL` | |
| `mime_type` | `String(64)` not null | `VARCHAR(64) NOT NULL` | |
| `size_bytes` | `BigInteger` not null | `BIGINT NOT NULL` | |
| `uploaded_by` | FK→`users.email`, nullable | FK **ON DELETE SET NULL** | |
| `uploaded_at` | `DateTime` | `TIMESTAMPTZ` | tz drift |

> **Orphan risk (§7):** deleting a `media_assets` row does not call
> `lo_unlink(oid)`. The bytes in `pg_largeobject` leak. There is **no** delete
> path in code today, but the cleanup strategy must exist before any delete is
> added.

### 1.6 `course_chapters` — authored prose, one row per section file
`models.py:151-159`, `deploy_schema.sql:87-94`

| Column | ORM type | DDL type | Notes |
|---|---|---|---|
| `filename` | `String(128)` PK | `VARCHAR(128) PK` | e.g. `coder-d.json` — natural key |
| `ring` | `String(32)` not null | `VARCHAR(32) NOT NULL` | code/coder/anatomy/adobe/ai (derived from prefix, `migrate_to_postgres.py:288-298`) |
| `title` | `String(255)` not null | `VARCHAR(255) NOT NULL` | |
| `content` | `JSONB`/`JSON` not null | `JSONB NOT NULL` | the full block tree (SCHEMA.md §Domain 1) |
| `created_at` / `updated_at` | `DateTime` | `TIMESTAMPTZ` | tz drift |

### 1.7 `frameworks` — framework spine + explainer, both in one table
`models.py:162-167`, `deploy_schema.sql:97-101`

| Column | ORM type | DDL type | Notes |
|---|---|---|---|
| `id` | `String(32)` PK default `'framework'` | `VARCHAR(32) PK DEFAULT 'framework'` | two live rows: `'framework'` and `'explainer'` (`storage.py:450-487`) |
| `data` | `JSONB`/`JSON` not null | `JSONB NOT NULL` | |
| `updated_at` | `DateTime` onupdate | `TIMESTAMPTZ DEFAULT now()` | |

This is a deliberate single-table-two-rows pattern (commit 5b63ef8); keep it.

### 1.8 sqlite/postgres type shims
`models.py:20-50`. At import time the module branches on
`"postgresql" in config.DATABASE_URL`:

- Postgres: real `JSONB`, `HSTORE`, `ARRAY`, `OID`.
- sqlite: `JSON`; `HSTORE`→`SQLiteHStore(TypeDecorator over TEXT)` json-dumps;
  `ARRAY`→`SQLiteArray` json-dumps; `OID`→`Integer`.

Consequences: on sqlite the `tsvector` generated column, the GIN indexes, the
`hstore` operators, and large objects **do not exist**. Local sqlite silently
runs a *different* schema from production. `migrate_media()` explicitly skips on
sqlite (`migrate_to_postgres.py:200-202`).

### 1.9 Schema drift — precise list

**1.9.1 Score type.** `models.py:83` `score = Column(Float)` vs
`deploy_schema.sql:43` `score NUMERIC(5,2) NOT NULL`. On a DB created by
`deploy_schema.sql`, SQLAlchemy reads a `Decimal`; `create_all` (the live path,
`db.py:32`) instead makes a `double precision` column. **Two databases stood up
two different ways have different column types.** Resolution in §2.1.

**1.9.2 `feed_items.search` + all GIN/lookup indexes.** Present only in
`deploy_schema.sql` (`:33,:54,:67-73`). `create_all` from the ORM (`db.py:32`)
does **not** create them. A live system bootstrapped by `init_db()` (the actual
startup path, `main.py:74`) has **no** generated `search` column and **none** of
the performance indexes. So `deploy_schema.sql` and the running schema diverge
depending on which one created the DB.

**1.9.3 Timestamp tz.** Every `DateTime` in the ORM is naive
(`datetime.utcnow`); every DDL column is `TIMESTAMPTZ`. ISO strings are
re-suffixed with `"Z"` on read (`storage.py:249-250`).

**1.9.4 FK ondelete.** All `ON DELETE` rules (`CASCADE`, `SET NULL`) live only
in the DDL; the ORM `ForeignKey`s declare none, so `create_all` makes plain FKs
with default `NO ACTION`.

**1.9.5 `media_assets.id` type + default.** `VARCHAR(64)` + app-side uuid string
(ORM) vs `UUID` + `gen_random_uuid()` server default (DDL).

**1.9.6 No FK on `large_object_oid`.** Postgres exposes no catalog table you can
FK to for large objects; integrity is purely procedural. This is the root of the
orphan problem.

**1.9.7 `_migrate()` hand-rolled drift-patcher.** `db.py:36-83` inspects columns
at startup and ALTERs in `signature`, `metadata`, `preferences` if missing. This
is an ad-hoc migration runner with three hard-coded steps, no ordering, no
down-path, no history table. It silently no-ops once columns exist. Retire in
§3.

### 1.10 Two role systems on one column
The single `users.role VARCHAR(32)` carries **two unrelated concepts**:

1. **Persona / job family** picked at onboarding — `pm, ba, qa, sales, design,
   devops, coder, architect, other` (`roles.py:9-19`). Drives only the
   *recommended quiz difficulty* (`recommended_level`, `roles.py:28-32`). **Not**
   a permission.
2. **RBAC capability** — `'User', 'FeedCreator', 'Moderator', 'QuizManager'`
   (`models.py:59`, `deploy_schema.sql:10`, enforced in `auth.require_role`,
   `auth.py:107-136`).

These are mutually exclusive *values in the same column*. A user is either a
persona **or** a capability role, never both — `set_user_role` (`storage.py:91`)
overwrites whichever was there. `upsert_user` even hard-codes `QuizManager` in
dev (`storage.py:74,84`). This is the core defect item 8 fixes; the schema split
is designed in §2.2 and the policy in `04-authz-model.md`.

---

## 2 · Target schema (DDL intent)

Principles for the target:

- **Postgres-only** (§4). One schema, no dialect branching.
- **`TIMESTAMPTZ` everywhere**; ORM uses `DateTime(timezone=True)` +
  `server_default=func.now()` so the DB clock is authoritative.
- **All constraints + indexes live in the ORM/migrations**, never DDL-only.
  `deploy_schema.sql` is retired (§3).
- snake_case, plural table names (§5).
- New surfaces for later phases are introduced here as **columns/tables only** —
  policy and behaviour are owned by their respective docs.

DDL below is *intent* expressed as the migration target, not a file to run
directly — Alembic authors the real `op.*` calls (§3).

### 2.1 `attempts` — resolve score drift + add cert dev-mode (item 9)

```sql
CREATE TABLE attempts (
    id              BIGSERIAL PRIMARY KEY,
    test_code       VARCHAR(32)  NOT NULL UNIQUE,
    cert_id         VARCHAR(64)  UNIQUE,
    quiz_id         VARCHAR(64)  NOT NULL,
    user_email      VARCHAR(255) NOT NULL
                       REFERENCES users(email) ON DELETE CASCADE,
    difficulty      VARCHAR(16)  NOT NULL
                       CHECK (difficulty IN ('beginner','intermediate','advanced')),
    score           DOUBLE PRECISION NOT NULL CHECK (score >= 0 AND score <= 1),
    correct         INTEGER NOT NULL CHECK (correct >= 0),
    total           INTEGER NOT NULL CHECK (total > 0),
    passed          BOOLEAN NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    certificate_path TEXT,
    signature       VARCHAR(64),
    payload         JSONB NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- migrated off hstore, see §2.6
    -- cert dev-mode (item 9), designed with 07-security-baseline.md:
    environment     VARCHAR(16) NOT NULL DEFAULT 'production'
                       CHECK (environment IN ('production','staging','development')),
    signing_key_id  VARCHAR(32) REFERENCES signing_keys(key_id) ON DELETE RESTRICT
);
CREATE INDEX idx_attempts_user      ON attempts (user_email, submitted_at DESC);
CREATE INDEX idx_attempts_cert      ON attempts (cert_id);
CREATE INDEX idx_attempts_passed    ON attempts (passed);
CREATE INDEX idx_attempts_env       ON attempts (environment);
```

**Score type resolution — keep `DOUBLE PRECISION` (ORM `Float`), NOT
`NUMERIC(5,2)`.** Rationale:

- `score` is a **0–1 fraction** (`quiz_generator.py:188`,
  `score = correct / total`), not a 0–100 percentage. `NUMERIC(5,2)` was written
  for a percentage that never materialised.
- The HMAC seal hashes `f"{score:.6f}"` (`storage.py:23`). `DOUBLE PRECISION`
  round-trips the exact value the signature was computed over; switching live
  rows to `NUMERIC(5,2)` would round e.g. `0.866667 → 0.87` and **break
  verification of already-issued certs** — a hard constraint
  (`v2-plan.md:119`). The reconcile migration (§3) therefore **standardises on
  the type `create_all` already produced** (`double precision`) and only fixes
  DBs that were stood up from `deploy_schema.sql`.
- The `CHECK (score BETWEEN 0 AND 1)` documents the contract.

**Cert dev-mode columns (item 9) — design only, behaviour in
`07-security-baseline.md` + `04-authz-model.md`:**

- `environment` marks where a cert was issued. **Existing rows default to
  `'production'`** so every already-issued cert is treated as real and keeps
  verifying.
- `signing_key_id` references a row in `signing_keys` (§2.5) — *which* key signed
  this attempt. Existing rows backfill to the current production key id (§3 step
  4). The verifier picks the key by `signing_key_id`, so rotating or adding a dev
  key never invalidates old certs.
- The verify UI (`main.py:488-509`) gains the ability to show a "development
  certificate — not valid for certification" banner when
  `environment <> 'production'`, without changing the HMAC scheme.

> **`metadata` rename note:** the SQLAlchemy attribute stays
> `attempt_metadata` mapped to column `metadata` (`models.py:94`). Keep that
> mapping; only the column *type* moves hstore→jsonb (§2.6).

### 2.2 `users` + `roles` + `user_roles` — split the overloaded column (item 8)

The split: **persona becomes a column on `users`; capability roles become a
many-to-many mapping.** This lets a user be both a `Learner` and a
`Feed Moderator`, which the single column cannot express today.

> **Canonical role storage = `user_roles` join table.** Application code reads
> roles via a `users_service.roles_for(email) -> set[str]` helper (owned by
> `04-authz-model.md`); there is **no** `users.roles text[]` column and the
> ORM has no `users.roles` array attribute. Any cross-doc snippet that appears
> to read `db["roles"]` or a `users.roles` array is repointed to the helper —
> see `04-authz-model.md` for the helper signature and call sites.

```sql
CREATE TABLE users (
    email        VARCHAR(255) PRIMARY KEY,
    name         VARCHAR(255),
    picture      VARCHAR(1024),
    provider     VARCHAR(32),                         -- 'google' | 'dev'
    persona      VARCHAR(32),                         -- profile attribute, NOT authz
                   -- CHECK in (pm,ba,qa,sales,design,devops,coder,architect,other) | NULL
                   -- width aligned with 04-authz-model.md (VARCHAR(32))
    preferences  JSONB NOT NULL DEFAULT '{}'::jsonb,  -- migrated off hstore (§2.6)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    -- NOTE: legacy `role VARCHAR(32)` is DROPPED only after backfill (§3 step 5)
);

-- Capability roles — the staff/learner-plane taxonomy (open decision 1).
CREATE TABLE roles (
    role_key     VARCHAR(32) PRIMARY KEY,   -- 'learner','feed_contributor',
                                            -- 'content_author','quiz_admin',
                                            -- 'feed_moderator','platform_admin'
    label        VARCHAR(64) NOT NULL,
    plane        VARCHAR(16) NOT NULL CHECK (plane IN ('learner','staff')),
    description  TEXT
);

CREATE TABLE user_roles (
    user_email   VARCHAR(255) NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    role_key     VARCHAR(32)  NOT NULL REFERENCES roles(role_key) ON DELETE RESTRICT,
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by   VARCHAR(255) REFERENCES users(email) ON DELETE SET NULL,
    PRIMARY KEY (user_email, role_key)
);
CREATE INDEX idx_user_roles_role ON user_roles (role_key);
```

- `persona` is **nullable** and carries the old onboarding personas verbatim
  (`roles.py`), now demoted to a recommendation input only. `recommended_level`
  reads `users.persona` instead of `users.role`.
- `roles` is a **seeded reference table** (so Directus / Platform Admin can read
  and label them); the six rows match open decision 1 in `v2-plan.md:112`. The
  exact permission semantics per role are owned by `04-authz-model.md`; this doc
  only fixes the *storage*.
- Whether roles are **DB-owned or Directus-owned**: `roles` is reference data
  Directus may surface read-only; `user_roles` grants are written by the staff
  plane (Directus admin or a FastAPI admin endpoint) — see §5 ownership table.
- **Alternative + tradeoff (so the gate can flip it):** a single
  `users.capability_role` enum instead of `user_roles`. Simpler, one column, no
  join — but it **re-creates the single-value limitation** (can't be both author
  and moderator) and forfeits `granted_by`/`granted_at` audit. Recommended:
  keep the mapping table; the M:N flexibility is the whole point of the split.

### 2.3 `quiz_sessions` — persist the in-memory `_active_quizzes` (item 6)

Replaces `main.py:69` `_active_quizzes: Dict[str, Dict]`. That dict is populated
at `/quiz/start` (`main.py:327-333`), read + deleted at `/quiz/submit`
(`main.py:367-415`). It is per-process: with >1 uvicorn worker a submit can hit
a worker that never saw the start → `404 quiz_not_found`. It is also lost on
restart and grows unbounded (no expiry sweep). Persist it:

```sql
CREATE TABLE quiz_sessions (
    quiz_id        VARCHAR(64) PRIMARY KEY,           -- main.py:157 uuid4 (stored as text)
    user_email     VARCHAR(255) NOT NULL
                      REFERENCES users(email) ON DELETE CASCADE,
    difficulty     VARCHAR(16) NOT NULL
                      CHECK (difficulty IN ('beginner','intermediate','advanced')),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,              -- started_at + QUIZ_DURATION_MIN (+ grace)
    server_answers JSONB NOT NULL,                    -- {qid: correct_index}  (quiz_generator.py:143)
    full_questions JSONB NOT NULL,                    -- the graded copy (quiz_generator.py:144-155)
    submitted_at   TIMESTAMPTZ,                       -- NULL until graded; non-null = consumed
    CHECK (expires_at > started_at)
);
CREATE INDEX idx_quiz_sessions_user    ON quiz_sessions (user_email);
CREATE INDEX idx_quiz_sessions_expires ON quiz_sessions (expires_at);
```

- **`quiz_id` type alignment + no-FK rule.** Both `quiz_sessions.quiz_id` and
  `attempts.quiz_id` (§2.1) are `VARCHAR(64)` — the smallest-migration choice
  that lets `/quiz/submit` look up the in-flight session by the same text id
  the dict used (`main.py:367-371`). **There is intentionally no foreign key
  between `attempts.quiz_id` and `quiz_sessions.quiz_id`:** `quiz_sessions` is
  a short-lived dict-replacement table whose rows are swept after expiry
  (§2.3 cleanup), while `attempts.quiz_id` is historical — it records *which*
  ephemeral session produced the attempt and must survive the session row's
  deletion. Treating these as two independent text columns with the same
  shape is the deliberate choice.
- The dict's four payload keys map 1:1:
  `user_email, started_at, difficulty, server_answers, full_questions`
  (`main.py:328-332`).
- `/quiz/submit` becomes: `SELECT ... WHERE quiz_id = :id FOR UPDATE`; reject if
  row missing, `user_email` mismatches (`main.py:371`), `submitted_at IS NOT
  NULL` (replay), or `now() > expires_at` (expiry — a behaviour the dict never
  enforced; introduce it). On success set `submitted_at` instead of `del`
  (`main.py:415`) — keeps an audit row and makes double-submit idempotent.
- **Cleanup:** a periodic `DELETE FROM quiz_sessions WHERE expires_at < now() -
  interval '1 day'` (cron or app sweep). Pairs with the LO job in §7.
- **DB vs Redis — recommendation: Postgres table now.** A `quiz_sessions` table
  needs zero new infrastructure, is transactional with the `attempts` insert,
  and the volume is trivial (one row per in-flight quiz). Redis is the right home
  for the response-cache and rate-limit counters (`06-caching-performance.md`),
  **not** for a record that must be consistent with a committed attempt. If
  Redis lands later, sessions *may* move there with a TTL, but that is an
  optimisation, not a requirement. Tradeoff: a DB write per quiz start — fine at
  this scale.

### 2.4 `app_config` — config-as-content (item 11)

Non-secret, runtime-tunable values Directus can edit. **Secrets stay in env**
(`config.py`) and are explicitly out of this table — see `05-config-cms.md`.

```sql
CREATE TABLE app_config (
    key          VARCHAR(64) PRIMARY KEY,    -- e.g. 'quiz.pass_mark_correct'
    value        JSONB NOT NULL,             -- typed: 25 | true | "v2" | {...}
    value_type   VARCHAR(16) NOT NULL        -- metadata for Directus rendering only
                   CHECK (value_type IN ('int','float','bool','string','json')),
    description  TEXT NOT NULL,              -- shown in Directus
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by   VARCHAR(255) REFERENCES users(email) ON DELETE SET NULL
);
```

- **No `is_secret` column / no self-defeating CHECK.** Whether a value belongs
  in env-secret, env-config, or `app_config` is determined entirely by the
  typed registry in **`05-config-cms.md`** (the source of truth for the
  secret/config/content tiering). `value_type` is kept **only** so Directus
  can render the right form widget (number vs toggle vs JSON editor); it
  carries no security semantics.
- Candidate keys (non-secret tunables from `config.py`): `quiz.cooldown_days`
  (`config.py:50`), `quiz.duration_min` (`:51`), `quiz.questions_per_quiz`
  (`:52`), `quiz.pass_mark_correct` (`:56`), `feed.flag_threshold`
  (SCHEMA.md default 1), `media.max_video_size_mb` (`:62`),
  `media.max_image_size_mb` (`:63`), `media.max_video_duration_sec` (`:64`).
- **Explicitly NOT here:** `SECRET_KEY`, `GOOGLE_CLIENT_SECRET`, `SMTP_PASS`,
  `APP_PAYLOAD_SECRET`, `DATABASE_URL`, signing-key *material*. The guard is
  the registry in `05-config-cms.md`, not a DB column — operator/CI
  discipline (and the Directus role's narrow GRANT, §5) keep secrets out.
- The backend reads `app_config` with a short cache (`06-caching-performance.md`)
  and falls back to the `config.py` default if a key is absent — so an empty
  table behaves exactly like today.
- The full collection map (which keys, defaults, Directus field types) is owned
  by `05-config-cms.md`; this is the storage shape only.

### 2.5 `signing_keys` — per-environment cert key reference (item 9)

Stores **key identity and metadata, never the key material.** The material stays
in env/secret store (`07-security-baseline.md`). This table answers "which key,
for which environment, is current, and is it still allowed to verify".

```sql
CREATE TABLE signing_keys (
    key_id       VARCHAR(32) PRIMARY KEY,     -- opaque id, e.g. 'prod-2026-01'
    environment  VARCHAR(16) NOT NULL
                   CHECK (environment IN ('production','staging','development')),
    algorithm    VARCHAR(32) NOT NULL DEFAULT 'HMAC-SHA256',
    env_var_name VARCHAR(64) NOT NULL,        -- name of the env var holding the secret
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,   -- current signer for its environment
    can_verify   BOOLEAN NOT NULL DEFAULT TRUE,   -- still accepted on verify (rotation)
    verify_until TIMESTAMPTZ,                 -- hard deadline after which verify rejects (NULL = open-ended)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at   TIMESTAMPTZ
);
CREATE UNIQUE INDEX idx_signing_keys_active
    ON signing_keys (environment) WHERE is_active;   -- one active key per environment
```

- `attempts.signing_key_id` (§2.1) FKs here. **Backfill:** insert one row
  `('legacy-prod', 'production', 'HMAC-SHA256', 'CERT_HMAC_LEGACY', true,
  true)` and point every existing attempt at it (§3 step 4). The current code
  signs with `config.SECRET_KEY` (`storage.py:24`), so the operator **seeds
  `CERT_HMAC_LEGACY` with the existing `SECRET_KEY` byte-value at migration
  time** — a one-line `.env` step documented in the runbook. From that point
  forward, cert HMAC is decoupled from session-secret rotation: rotating
  `SECRET_KEY` only invalidates active sessions, while every issued cert
  continues to verify because `CERT_HMAC_LEGACY` is unchanged. No cert
  changes; verification is byte-identical.
  > **Operator instruction (Phase 2c runbook):** before `0005_cert_devmode`
  > runs, set `CERT_HMAC_LEGACY=<current value of SECRET_KEY>` in the
  > production `.env` and reload the service. The migration assumes this var
  > exists; a startup self-check fails fast if it doesn't.
- A separate `'development'` key lets dev/staging issue clearly-marked,
  independently-verifiable certs without touching the production key.
- **`verify_until` (rotation deadline).** When a key is rotated out, the
  operator sets `verify_until = now() + interval '5 years'` (or the
  policy-defined window). The verifier (owned by `07-security-baseline.md`)
  rejects a cert whose `signing_key_id` row has `verify_until < now()` —
  giving the 5-year `can_verify` window an *enforced* deadline rather than a
  runbook hope. `NULL` means open-ended (the current legacy-prod row stays
  `NULL` at backfill); 07 §8.4 references this column for the verifier rule.
- **Where the bytes live:** `env_var_name` tells the app which env var to read
  for the HMAC secret; the table never holds the secret. This keeps item 9 and
  item 7 (secrets in env) aligned.

### 2.6 Migrate `hstore` → `jsonb` (users.preferences, attempts.metadata)

Both `hstore` columns become `jsonb`:

- `hstore` is flat-string-only and a niche extension; `jsonb` is already the
  workhorse type in this schema (questions/options, feed/data, course/content)
  and Directus models it natively as a JSON field (§5). The sqlite shim already
  json-encodes these (`models.py:31-45`), so the app code treats them as dicts
  regardless.
- Migration is lossless: `hstore` → `jsonb` via
  `preferences::jsonb` won't cast directly, so the migration does
  `hstore_to_jsonb(preferences)` (Postgres built-in) — see §3 step 3.
  > **Phase 2a verification note (C-47, deferred):** `hstore_to_jsonb` lives
  > in the `hstore` extension. On the live Postgres version, a direct
  > `preferences::jsonb` cast may work in-place and is cleaner — verify
  > during Phase 2a authoring of `0007_hstore_to_jsonb`. If the direct cast
  > works, prefer it; the DDL stays the same either way (this note only
  > flags the `USING` clause choice for the migration author).
- Lets us **drop the `hstore` extension dependency** entirely (the only other
  user was these two columns). `pgcrypto` is still needed for
  `gen_random_uuid()` on `media_assets` (§2.7).

### 2.7 `media_assets` — fix id type, add a delete path hook (item 6 + §7)

```sql
CREATE TABLE media_assets (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    large_object_oid  OID NOT NULL,
    filename          VARCHAR(255) NOT NULL,
    mime_type         VARCHAR(64)  NOT NULL,
    size_bytes        BIGINT NOT NULL CHECK (size_bytes >= 0),
    uploaded_by       VARCHAR(255) REFERENCES users(email) ON DELETE SET NULL,
    uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_media_assets_oid ON media_assets (large_object_oid);
```

- **Resolve the id drift (§1.9.5):** standardise on `UUID` +
  `gen_random_uuid()`. The ORM column becomes the Postgres `UUID` type; the app
  still generates `uuid4()` (`media_service.py:110`) which casts cleanly to
  `UUID`. Existing string ids are valid UUID text → cast in place (§3 step 6).
- `large_object_oid` keeps **no FK** (impossible, §1.9.6); integrity is enforced
  by the cleanup job + a delete trigger (§7).

### 2.8 Tables kept structurally as-is (with tz + constraint hardening)

`questions`, `feed_items`, `course_chapters`, `frameworks` keep their shapes.
Changes applied uniformly:

- All timestamps → `TIMESTAMPTZ NOT NULL DEFAULT now()` with ORM
  `DateTime(timezone=True)`.
- All FK `ON DELETE` rules promoted into the ORM (matching the DDL intent in
  §1: `SET NULL` for author refs, `CASCADE` for `attempts.user_email`).
- `questions.status` and `feed_items.status` gain
  `CHECK (status IN (...))` enumerations matching SCHEMA.md.
- **`feed_items.search` (tsvector) + the three GIN/lookup indexes
  (`idx_feed_items_ordering/topics/search`, `idx_questions_lookup`) are made
  authoritative in the ORM/migration** (they exist only in DDL today, §1.9.2).
  The `search` generated column is declared once in the model so `create_all`
  and migrations agree.
- `course_chapters.ring` gains `CHECK (ring IN ('code','coder','anatomy',
  'adobe','ai','other'))` (values from `migrate_to_postgres.py:288-298`).

### 2.10 `auth_audit` — append-only authn/authz event log

Required by `04-authz-model.md` (role grant/revoke) and
`07-security-baseline.md` (login/logout, session cutover) and consumed by
`02-parity-method.md` for the AuthZ-split smoke. Append-only, never updated;
truncation is operational policy, not application behaviour.

```sql
CREATE TABLE auth_audit (
    id            BIGSERIAL PRIMARY KEY,
    actor_email   VARCHAR(255) NOT NULL,                 -- who performed the action
    action        VARCHAR(64)  NOT NULL,                 -- e.g. 'role.grant', 'role.revoke',
                                                          --      'login.success', 'login.fail',
                                                          --      'logout', 'session.rotate'
    target_email  VARCHAR(255),                          -- the subject (NULL for self-actions)
    target_role   VARCHAR(32),                           -- role_key when action ∈ role.{grant,revoke}
    before        JSONB,                                  -- prior state snapshot (NULL if N/A)
    after         JSONB,                                  -- new state snapshot (NULL if N/A)
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_auth_audit_actor    ON auth_audit (actor_email, occurred_at DESC);
CREATE INDEX idx_auth_audit_action   ON auth_audit (action, occurred_at DESC);
```

- `target_role` FKs are intentionally **omitted** — role taxonomies evolve and
  an audit row must survive a `roles` row being archived. Validation is
  application-side.
- The table is **write-only from the FastAPI runtime**; Directus and the
  Platform Admin UI read but never edit (see §5 GRANT table).
- Detailed action vocabulary and per-action `before`/`after` shapes are owned
  by `04-authz-model.md` §7.4 — this doc fixes the storage shape only.

### 2.9 ER summary (target)

```
users ──< user_roles >── roles
  │  └──< attempts >── signing_keys
  │  └──< questions
  │  └──< feed_items
  │  └──< media_assets
  │  └──< quiz_sessions
  └ (persona column; preferences jsonb)

course_chapters   (standalone, Directus-owned content)
frameworks        (standalone, Directus-owned content; 2 rows)
app_config        (standalone, Directus-owned config)
signing_keys      (standalone, Platform-Admin/infra-owned)
auth_audit        (standalone, append-only; FastAPI writes, Directus read-only)
pg_largeobject    (system; referenced by media_assets.large_object_oid, no FK)
```

---

## 3 · Alembic adoption — no data loss

Alembic replaces both `db.py:_migrate()` (the hand-rolled patcher) and
`deploy_schema.sql` (the parallel DDL). Directory placement matches the v2 tree
(`v2-plan.md:42`): **`backend/migrations/`**.

```
backend/
  migrations/
    env.py                 # online/offline; reads DATABASE_URL from core.config; target_metadata = Base.metadata
    script.py.mako
    versions/
      0001_baseline.py     # empty upgrade/downgrade — matches the live schema as-is
      0002_reconcile.py    # fix drift + new constraints/indexes (non-destructive)
      0003_authz_split.py  # roles, user_roles, users.persona; backfill; drop users.role
      0004_quiz_sessions.py
      0005_cert_devmode.py # signing_keys, attempts.environment/signing_key_id; backfill
      0006_app_config.py
      0007_hstore_to_jsonb.py
      0008_auth_audit.py   # auth_audit table + indexes; empty downgrade preserves audit history
  alembic.ini              # script_location = migrations
```

**Step 0 — generate the baseline FROM the live DB, not the models.** This is the
no-data-loss keystone. On the running Postgres:

```
alembic init backend/migrations           # wire env.py to core.config.DATABASE_URL
alembic revision -m "baseline"             # author 0001 with EMPTY up/down
alembic stamp 0001                         # records 0001 as applied WITHOUT running it
```

`alembic stamp` writes the `alembic_version` row and **touches no tables** — the
live schema is declared "this is revision 0001" exactly as it stands. Nothing is
dropped or recreated.

**Step 1 — autogenerate the diff to spot drift.** With `target_metadata =
Base.metadata` and the hardened models from §2 loaded, `alembic revision
--autogenerate -m reconcile` produces a candidate `0002`. **Hand-review it** —
autogenerate will propose creating the missing indexes/`search` column (§1.9.2)
and may propose a `score` type change; **delete any `score` ALTER** unless the
live column is actually `numeric` (§2.1), and keep it non-destructive.

**Step 2 — `0002_reconcile` (non-destructive).** ADD-only:

- `CREATE INDEX IF NOT EXISTS` the four missing indexes
  (`idx_feed_items_ordering/topics/search`, `idx_questions_lookup`) and the new
  attempt indexes.
- ADD `feed_items.search` generated column **if absent** (it is, on init_db DBs).
- ADD the `CHECK` constraints (`NOT VALID` first, then `VALIDATE CONSTRAINT` so
  existing rows aren't locked-scanned in one shot).
- Promote FK `ON DELETE` rules (drop+recreate FK with the rule).
- Conditionally fix `score` type **only** if `information_schema` reports
  `numeric` — `ALTER ... TYPE double precision USING score::double precision`.

**Step 3 — `0007_hstore_to_jsonb`** (can be ordered earlier; numbered last only
for readability): `ALTER TABLE users ALTER preferences TYPE jsonb USING
hstore_to_jsonb(preferences)`; same for `attempts.metadata`. Then `DROP
EXTENSION IF EXISTS hstore` once no column uses it.

**Step 4 — `0005_cert_devmode`:**
`INSERT INTO signing_keys ('legacy-prod','production',...,'CERT_HMAC_LEGACY',
true,true)` (operator pre-seeds `CERT_HMAC_LEGACY` from today's `SECRET_KEY`
value — see §2.5 operator instruction);
ADD `attempts.environment DEFAULT 'production'` and `attempts.signing_key_id`;
`UPDATE attempts SET signing_key_id='legacy-prod'` (backfill all existing rows);
then `ALTER ... SET NOT NULL` on `signing_key_id`. Every existing cert now points
at the real production key and verifies unchanged.

**Step 5 — `0003_authz_split`:** create `roles` (seed 6 rows), `user_roles`,
`users.persona`. **Backfill from the overloaded `users.role`** (aligned with
`04-authz-model.md`'s stricter rule — admin is never auto-granted by migration):

- where `role IN ('pm','ba','qa','sales','design','devops','coder','architect',
  'other')` → copy to `users.persona`, grant `user_roles('learner')`.
- where `role = 'User'` → grant `learner`.
- where `role = 'FeedCreator'` → grant `learner` + `feed_contributor`.
- where `role = 'Moderator'` → grant `feed_moderator`.
- where `role = 'QuizManager'` → grant **`learner` only** (never auto-grant
  `quiz_admin` or `platform_admin`). The historical `QuizManager` value
  conflated capability with the dev-default upsert (`storage.py:74,84`); a real
  admin grant must be issued explicitly by an operator after the cutover via
  the Platform Admin endpoint, recorded in `auth_audit` (§2.10). The migration
  **emits a report** of every row reclassified (e.g. `"reclassified N
  QuizManager rows to {learner}; admin grants require explicit operator
  action"`) — written to migration stdout and the Alembic log so the operator
  can immediately follow up.
- only **after** backfill is verified: `ALTER TABLE users DROP COLUMN role`.
  (Mapping table here is storage; `04-authz-model.md` owns the exact role→grant
  policy — this rule is the reconciled version.)

**Step 6 — `media_assets.id`:** `ALTER ... TYPE uuid USING id::uuid` (existing
ids are uuid4 strings, cast cleanly); set `DEFAULT gen_random_uuid()`.

**Step 7 — `0008_auth_audit`** (§2.10): create `auth_audit` with the two
indexes; no backfill (the table starts empty — login/grant events accrue from
the cutover forward). `downgrade()` is intentionally `pass` so an audit
history is never destroyed by a rollback; manual `DROP TABLE` only if the
operator explicitly chooses to discard.

**Ongoing workflow.** Models in `backend/.../models.py` are the source; every
schema change = `alembic revision --autogenerate -m "..."` → review → commit →
`alembic upgrade head` on deploy. `init_db()` (`db.py:23-33`) **stops calling
`create_all` + `_migrate()` in production**; startup instead asserts
`alembic_version == head` (fail-fast) and runs migrations via the deploy step,
not on import. `deploy_schema.sql` is **deleted** — its content is now §2 + the
migrations. `_migrate()` (`db.py:36-83`) is **deleted**.

> **Safety:** every destructive step (DROP COLUMN role, DROP EXTENSION, type
> ALTERs) runs only after a verified backup snapshot (`02-parity-method.md` DB
> snapshot) and a successful dry-run on a restored copy. Each migration has a
> real `downgrade()`.

---

## 4 · sqlite vs postgres stance

**Recommendation: Postgres-only. Remove the sqlite path.**

Justification:

- The production feature set is Postgres-specific and has **no sqlite
  equivalent**: large objects (`media_service.py`), `tsvector` generated column +
  GIN search (`deploy_schema.sql:67-73`), `hstore`/`jsonb` operators, `ARRAY`
  with GIN, `gen_random_uuid()`. The sqlite shims (`models.py:20-50`) make local
  dev run a *materially different schema* — tests that pass on sqlite prove
  nothing about production (e.g. media is skipped entirely,
  `migrate_to_postgres.py:200-202`).
- Alembic migrations will increasingly use Postgres-only DDL (generated columns,
  partial unique indexes, `USING` casts, `NOT VALID` constraints) that sqlite
  cannot execute — so the migration path is Postgres-only regardless.
- The drift class of bugs in §1.9 is *caused* by maintaining two dialects.

**Impact on `db.py`:**

- Delete the `sqlite` branch in `_engine_kwargs` (`db.py:14-16`).
- Delete the entire dialect shim in `models.py:20-50`; import `JSONB`, `ARRAY`,
  `OID` from `sqlalchemy.dialects.postgresql` unconditionally (no more `HSTORE` —
  §2.6).
- `init_db()` keeps `CREATE EXTENSION pgcrypto` (still needed for UUID); drops
  `CREATE EXTENSION hstore` after `0007`; loses `create_all`+`_migrate` (§3).
- **Local dev** runs Postgres via Docker/`infra/start_local.sh` (the v2 tree has
  `infra/`, `v2-plan.md:54`). A throwaway containerised Postgres is the dev DB —
  same engine as prod, zero shim.
- **Tradeoff / alternative:** keep sqlite for unit tests only, behind a feature
  flag. Rejected — it perpetuates the two-schema problem and gives false
  confidence. If a fast in-memory test DB is wanted, use a Postgres testcontainer
  or a transactional-rollback fixture against the dev Postgres. State this in the
  test plan (`02-parity-method.md`).

---

## 5 · Directus compatibility

Directus runs as a **separate Node service over the same Postgres**
(`v2-plan.md:26`). Coexistence rules:

**Naming conventions.** Directus introspects table/column names directly into its
admin UI, so the schema must be Directus-friendly:

- **snake_case** columns and tables (already true).
- **plural** table names (already true: `users`, `attempts`, `questions`, …) —
  keep plural for the new tables (`roles`, `user_roles`, `quiz_sessions`,
  `app_config`, `signing_keys`).
- Every content table needs a **stable single-column primary key** Directus can
  use as the item key — all current tables satisfy this (`email`, `id`,
  `filename`). `user_roles` has a **composite PK**, which Directus handles poorly
  as an editable collection; expose it to Directus read-only, or add a surrogate
  `id BIGSERIAL` if Directus must edit grants (decide in `05-config-cms.md`).
- Avoid SQL reserved words as bare column names — `attempts.metadata` is already
  aliased in the ORM; in Directus it appears as the column `metadata`, which is
  fine at the DB layer (the reservation is a SQLAlchemy attribute concern).

**System tables.** Directus creates and **owns its own `directus_*` tables**
(`directus_users`, `directus_roles`, `directus_permissions`, `directus_files`,
`directus_activity`, `directus_revisions`, …) in the same database. These are
**disjoint** from the app tables — no name collision (app uses `users`, Directus
uses `directus_users`). Migrations (§3) **must never touch `directus_*`**; the
Alembic `env.py` `include_object` hook should **exclude any table prefixed
`directus_`** from autogenerate so Alembic never proposes dropping Directus's
tables.

**Introspect vs own.** Directus does **both**, per table:

- **Introspects existing app tables** it will edit as content:
  `course_chapters`, `frameworks`, `questions` (the official-author surface),
  `feed_items` (moderation surface), `app_config`, `roles`. These already exist;
  Directus registers them as collections and renders editors over the existing
  columns (its `directus_fields`/`directus_collections` metadata describes them
  without altering the data columns).
- **Owns separate collections** for its own concerns: editor accounts/roles live
  in `directus_users`/`directus_roles` (the *staff* identity plane), distinct
  from the app's `users`/`roles` (the *learner* + capability plane). The two
  identity systems are bridged by `04-authz-model.md`, not merged.

**Permissions / ownership.** Directus's own RBAC governs *editor* access inside
the admin UI; it does not govern the FastAPI runtime. The DB role Directus
connects as should be **scoped** (see `07-security-baseline.md`): it needs DDL on
`directus_*` and DML on the content tables it edits, but should **not** be the
same superuser role the migrations run as.

**Who owns writes to each table** (the authority map):

| Table | FastAPI writes | Directus writes | Notes |
|---|---|---|---|
| `users` | yes (SSO upsert, `storage.py:68`) | no (read-only view) | learner identity |
| `roles` | seed via migration | read-only (label/admin) | reference data |
| `user_roles` | admin endpoint | optional (grant UI) | decide in 05; if Directus edits, add surrogate PK |
| `attempts` | **yes, exclusively** | **no** | runtime, signed; never editor-mutable |
| `quiz_sessions` | **yes, exclusively** | no | ephemeral runtime state |
| `signing_keys` | infra/migration | no | key metadata; Platform Admin only |
| `questions` | yes (UGC + admin, `main.py:740`) | **yes (official authoring)** | shared; status field is the seam |
| `feed_items` | yes (post/flag, `main.py:649,621`) | **yes (moderation)** | shared; moderation via status |
| `media_assets` | **yes (bytes + metadata)** | metadata read ONLY (no bytes) | media = Postgres LO, FastAPI-streamed (see below) |
| `course_chapters` | read-only at runtime | **yes (authoring)** | Postgres-as-source (§6) |
| `frameworks` | read-only at runtime | **yes (authoring)** | 2 rows |
| `app_config` | read (cached) | **yes (config UI)** | item 11 |

The detailed Directus collection map (field types, interfaces, which collections
are exposed) is owned by **`05-config-cms.md`**; this section fixes only the
DB-level coexistence and write-authority.

**Media decision — FINAL (2026-06-06, owner-confirmed):** **ALL media lives in
Postgres large objects and is streamed from there. No S3, no object store, no
filesystem media store — Postgres is the only database.** The
Postgres-large-object pipeline (`media_service.py` — `/media/{video,image}`
Range support) is the permanent and only media path: bytes in
`media_assets.large_object_oid` + `pg_largeobject`, uploaded via FastAPI
`/api/media/upload`, streamed via FastAPI `/media/*`. **Directus does NOT store
app media** — it binds `media_assets` as read-only metadata so editors can
reference assets by id; app-media uploads into `directus_files` are disabled by
permission. `directus_files` is used only for incidental Directus-internal files
(e.g. avatars). There is no media migration; the earlier storage-adapter/S3 idea
is cancelled.

**Directus DB-role GRANT table.** Directus connects as a dedicated Postgres
role (`directus_app`, created in Phase 2a infra). The role must reach exactly
the tables it edits/reads as collections and be **denied** the runtime-only
and audit tables. This is the bare minimum; tighten further if a column-level
grant is needed.

| Table | SELECT | INSERT | UPDATE | DELETE | Notes |
|---|---|---|---|---|---|
| `users` | ✅ | — | — | — | learner identity (read-only view in Directus) |
| `roles` | ✅ | — | — | — | reference data; labels editable via migration only |
| `user_roles` | ✅ | (✅) | (✅) | (✅) | optional grant UI — gate behind a decision in `05-config-cms.md`; if disabled, SELECT only |
| `questions` | ✅ | ✅ | ✅ | ✅ | official authoring + moderation |
| `feed_items` | ✅ | — | ✅ | — | moderation only (status field); never insert/delete posts |
| `course_chapters` | ✅ | ✅ | ✅ | ✅ | Content Author surface |
| `frameworks` | ✅ | ✅ | ✅ | — | 2-row table; never DROP rows |
| `app_config` | ✅ | ✅ | ✅ | — | Platform Admin config UI; deletion via migration |
| `media_assets` | ✅ | — | — | — | metadata read for the asset browser; bytes via FastAPI only |
| **`attempts`** | ❌ | ❌ | ❌ | ❌ | runtime + HMAC-sealed; never editor-mutable |
| **`quiz_sessions`** | ❌ | ❌ | ❌ | ❌ | ephemeral runtime state |
| **`signing_keys`** | ❌ | ❌ | ❌ | ❌ | key metadata; Platform-Admin infra path only |
| **`auth_audit`** | ❌ | ❌ | ❌ | ❌ | append-only audit; not even SELECT for Directus |

The denied set (`attempts`, `quiz_sessions`, `signing_keys`, `auth_audit`)
must be enforced with explicit `REVOKE ALL ... FROM directus_app` after the
default `GRANT` block, since a future migration creating a table won't
auto-include the role. The Phase 2a migration that creates `directus_app`
emits both the GRANTs and the REVOKEs as a single transaction.

---

## 6 · Source-of-truth resolution

**Default (this doc implements): Postgres is the editable source of truth;
git-JSON becomes an export/seed.** This is a deliberate **shift from ADR 0001**
(`content-architecture/docs/adr/0001-storage.md:17-23`), which kept course
content as canonical files. The trigger ADR 0001 itself named — *"Move to a
database only if non-technical editors need a CMS"* (`adr/0001-storage.md:19`) —
**has now fired**: Directus is that CMS (`v2-plan.md:26`). Record this as a
superseding ADR (e.g. `adr/0002-postgres-as-source.md`) in Phase 1.

| Content type | Canonical store (target) | Seeded by | Exported to git as | Owner |
|---|---|---|---|---|
| **Course chapters** | `course_chapters` (Postgres) | `migrate_to_postgres.py:255-305` from `content-architecture/course/sections/*.json` | periodic dump → `content/source/course/sections/*.json` (export script) | Directus (Content Author) |
| **Framework spine** | `frameworks` row `id='framework'` | ETL `:258-263` from `course/framework.json` | dump → `content/source/course/framework.json` | Directus |
| **Framework-explainer** | `frameworks` row `id='explainer'` | ETL `:269-274` from `framework-explainer.json` (commit 5b63ef8) | dump → `content/source/course/framework-explainer.json` | Directus |
| **Feed items (UGC)** | `feed_items` (Postgres) | live at runtime (`main.py:649`); ETL `:143-196` seeds legacy `feed.json` | optional periodic backup dump (UGC isn't authored, so export is for backup, not canon) | FastAPI runtime + Directus moderation |
| **Questions — official** | `questions` (Postgres) | ETL `:35-69` from `data/question_bank.json` | dump → `content/source/quiz/question_bank.json` | Directus (Quiz Admin) |
| **Questions — UGC** | `questions` (Postgres, `is_user_submitted=true`) | live at runtime (`main.py:660-672`) | not exported (user data) | FastAPI runtime + moderation |
| **Media** | `media_assets` + `pg_largeobject` | ETL `:198-253` from `media/*.mp4` | not git (binary); backed up via `pg_dump` of large objects | FastAPI runtime |
| **Config** | `app_config` (Postgres) | migration seed from `config.py` defaults | dump → `content/source/config/app_config.json` | Directus (Platform Admin) |

**Direction of truth.** Postgres → git (export), not git → Postgres (except the
**one-time seed** and disaster recovery re-seed). The git-JSON is a **versioned
snapshot** for diff/review/backup, not the live read path. The current
on-disk **fallback** in `main.py:592-606` (framework-explainer reads the file if
the DB is empty) is kept only as a deploy-bootstrap safety net and should log a
warning — it is not a second source of truth.

**Export mechanism.** A `scripts/export_content.py` (Phase 2a/4) reads the
canonical tables and writes the JSON files; run on a schedule or a Directus
publish webhook (`05-config-cms.md`). This keeps the "content in git" property
ADR 0001 valued while making the **DB authoritative for editing**.

**Note for the AuthZ doc:** UGC questions and feed items are *runtime-written,
moderation-gated* (status field), whereas official questions/chapters are
*Directus-authored*. The same physical table serves both; the `is_user_submitted`
/ `status` columns are the provenance seam.

---

## 7 · Connection pooling + large-object lifecycle

### 7.1 Pooling
Today `create_engine` (`db.py:18`) uses SQLAlchemy defaults (`QueuePool`,
`pool_size=5`, `max_overflow=10`) — never tuned, and on sqlite pooling is moot.
For Postgres-only:

- **Sizing rule:** `pool_size × worker_count` must stay well under Postgres
  `max_connections` (default 100), leaving headroom for Directus + psql + the LO
  streaming connections (which use **separate raw connections**,
  `media_service.py:92,135` — these are *not* from the SQLAlchemy pool and must
  be counted).
- Recommended start: **`pool_size=5, max_overflow=5, pool_pre_ping=True,
  pool_recycle=1800`** per worker. With 4 uvicorn workers that's ≤40 pooled +
  overflow, plus a margin for raw LO connections and Directus's own pool.
- `pool_pre_ping=True` is important behind a connection that may be cut by a
  proxy/Apache (`06-caching-performance.md`); `pool_recycle` guards against
  server-side idle timeouts.
- The **raw large-object connections** (`engine.raw_connection()` in
  `media_service.py`) bypass the pool and are closed in `finally` — verify they
  are always closed even on streaming-generator GC (a long range-stream holds a
  connection for the whole transfer). Consider a small dedicated pool or a cap on
  concurrent streams. Detailed tuning (`shared_buffers`, `work_mem`, Apache
  side) is owned by `06-caching-performance.md`; this doc fixes the **count
  contract** between `pool_size` and workers.

### 7.2 Large-object lifecycle — orphan cleanup
The defect (§1.5): no `lo_unlink` when a `media_assets` row goes away; bytes
leak in `pg_largeobject`. Two complementary mechanisms:

1. **Delete trigger (authoritative).** A row-level `BEFORE DELETE` /
   `AFTER DELETE` trigger on `media_assets` that calls `lo_unlink(OLD.
   large_object_oid)`. This guarantees no orphan is created by an application
   delete, transactionally with the row removal. Authored in a migration.

   ```sql
   CREATE OR REPLACE FUNCTION media_assets_unlink_lo() RETURNS trigger AS $$
   BEGIN
     PERFORM lo_unlink(OLD.large_object_oid);
     RETURN OLD;
   EXCEPTION WHEN undefined_object THEN
     RETURN OLD;  -- already unlinked; don't block the delete
   END; $$ LANGUAGE plpgsql;

   CREATE TRIGGER trg_media_assets_unlink
     BEFORE DELETE ON media_assets
     FOR EACH ROW EXECUTE FUNCTION media_assets_unlink_lo();
   ```

2. **Sweep job (safety net) — `vacuumlo`.** The standard Postgres contrib tool
   `vacuumlo` scans every OID-typed column in the database and unlinks any large
   object not referenced anywhere. Run it as a periodic infra cron
   (`infra/`), e.g. nightly: `vacuumlo -n` (dry-run report) then `vacuumlo` (the
   `media_assets.large_object_oid` column is exactly what it scans). This catches
   orphans created by **failed uploads** — `store_media_asset`
   (`media_service.py:92-128`) creates the LO and commits **before** inserting
   the metadata row; if the metadata insert fails the LO is already orphaned, and
   only a sweep (not the trigger) reclaims it.

> Recommendation: **both** — the trigger for the happy-path delete (correctness),
> `vacuumlo` nightly for the crash/partial-failure path (resilience). Also
> reorder `store_media_asset` so the LO and the metadata row commit in **one**
> transaction (move the LO creation inside the metadata session) to shrink the
> orphan window — a Phase 2a code fix, noted for the implementer.

The `quiz_sessions` expiry sweep (§2.3) and this LO sweep can share one
scheduled-maintenance entry.

---

## 8 · What Phase 2a implements (ordered, data-preserving checklist)

Each step is reversible and gated on a verified backup + the parity harness
(`02-parity-method.md`). **Run on a restored copy first.**

1. **Snapshot.** `pg_dump` (schema + data + large objects) of the live DB;
   verify restore. This is the rollback point for every destructive step.
2. **Refactor `db.py` + `models.py` to Postgres-only** (§4): remove the sqlite
   branch (`db.py:14-16`) and the dialect shim (`models.py:20-50`); add the §2
   hardening (tz, constraints, FK ondelete, `search` column + indexes declared in
   the ORM). Stop importing `HSTORE`.
3. **Alembic init + baseline-stamp** (§3 step 0): `alembic init
   backend/migrations`; author empty `0001_baseline`; `alembic stamp 0001`
   against the live DB (no table changes).
4. **`0002_reconcile`** (§3 step 2): add the four missing indexes + new attempt
   indexes; add `feed_items.search` if absent; add CHECK constraints
   (`NOT VALID`→`VALIDATE`); promote FK `ON DELETE` rules; conditional `score`
   type fix.
5. **`0007_hstore_to_jsonb`** (§2.6, §3 step 3): convert `users.preferences` and
   `attempts.metadata` to `jsonb`; `DROP EXTENSION hstore`.
6. **`0005_cert_devmode`** (§2.5, §3 step 4): create `signing_keys`; seed
   `legacy-prod`; add `attempts.environment` (default `'production'`) +
   `signing_key_id`; backfill all rows to `legacy-prod`; set NOT NULL. **Verify
   every existing cert still verifies** via the parity smoke (the HMAC input is
   unchanged).
7a. **`0008_auth_audit`** (§2.10, §3 step 7): create `auth_audit` + the two
    indexes **before** the authz split so the split itself can emit
    `role.grant` rows for the backfill (each row reclassified per §3 step 5
    appends one `auth_audit` entry with `actor_email='migration'`).
7. **`0003_authz_split`** (§2.2, §3 step 5): create `roles` (seed 6), `user_roles`,
   `users.persona`; backfill from `users.role` per the mapping. **`QuizManager`
   maps to `{learner}` only** — admin capability is never auto-granted by the
   migration; the operator issues `quiz_admin`/`platform_admin` explicitly
   post-cutover via the Platform Admin endpoint (each grant recorded in
   `auth_audit`, §2.10). The migration **emits a reclassification report**
   ("X rows reclassified: Y QuizManager → {learner}, Z Moderator →
   {feed_moderator}, …") to stdout and the Alembic log so the operator can
   review and issue follow-up grants. **Verify** `auth.require_role` still
   resolves for every existing user *before* dropping; then `DROP COLUMN
   users.role`. (Coordinate the exact mapping with `04-authz-model.md` before
   this step runs — this step matches that doc's stricter rule.)
8. **`0006_app_config`** (§2.4): create `app_config`; seed non-secret defaults
   from `config.py`; wire the backend to read-with-fallback (empty table behaves
   as today).
9. **`media_assets.id` → UUID** (§2.7, §3 step 6): cast in place; set default.
10. **Large-object cleanup** (§7.2): add the `AFTER DELETE` trigger via
    migration; install the `vacuumlo` nightly cron in `infra/`; reorder
    `store_media_asset` to single-transaction commit.
11. **`quiz_sessions`** (§2.3): create the table; refactor `/quiz/start` +
    `/quiz/submit` (`main.py:306-444`) to persist/read/consume rows with
    `FOR UPDATE`, expiry, and replay protection; **delete** the `_active_quizzes`
    dict (`main.py:69`). Add the expiry sweep alongside the LO sweep.
12. **Retire the old paths:** delete `deploy_schema.sql`; delete `db.py:_migrate()`;
    change `init_db()` to assert `alembic_version == head` instead of
    `create_all` (run migrations in the deploy step, not on import).
13. **Parity gate:** run `tests/baseline/` — every route, content checksum, cert
    verification, feed/quiz flow must match the pre-2a baseline.

Order rationale: schema-safe reconcile and additive features (cert, config)
before any DROP; the only drops (`users.role`, `hstore` extension,
`_active_quizzes`, `deploy_schema.sql`) come after their replacements are proven.

---

## Cross-references

- `04-authz-model.md` — owns role→permission policy, the persona→difficulty rule,
  SSO+PKCE, and the Directus/app identity bridge. This doc fixes only the
  *storage* of roles/persona (§2.2) and must be reconciled with its taxonomy
  before §3 step 5 / 2a step 7 runs.
- `05-config-cms.md` — owns the Directus collection map, the secret-vs-config
  registry behind `app_config` (§2.4), and the media-vs-`directus_files`
  decision (§5).
- `06-caching-performance.md` — owns Postgres server tuning and Apache caching;
  consumes the pool/worker count contract (§7.1) and may move `quiz_sessions`
  to Redis later (§2.3).
- `07-security-baseline.md` — owns the cert dev-mode behaviour and key material
  handling behind `signing_keys` (§2.5), and the scoped DB role for Directus
  (§5).
- `02-parity-method.md` — provides the DB snapshot + smoke that gates every step
  in §8.
