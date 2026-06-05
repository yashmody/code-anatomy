# Migrations

Alembic root for the backend. Phase 2a wired this directory in and replaced
the hand-rolled `db.py:_migrate()` + `deploy_schema.sql` patcher.

## Layout

```
backend/
  alembic.ini                 # script_location = migrations, sqlalchemy.url from env.py
  migrations/
    env.py                    # target_metadata = Base.metadata; reads DATABASE_URL
    script.py.mako            # Alembic revision template
    versions/
      0001_baseline.py        # empty — stamps the live schema as revision 0001
      0002_reconcile.py       # adds missing indexes, conditional score-type fix
      0003_new_tables.py      # signing_keys, roles, user_roles, quiz_sessions, app_config, auth_audit
      0004_new_columns.py     # users.persona, attempts.environment, attempts.signing_key_id
      0005_seed_data.py       # seeds 6 roles + legacy-prod signing key; backfills attempts
      0006_lo_cleanup.py      # Postgres-only: BEFORE DELETE trigger calling lo_unlink
    legacy/
      reference.sql           # frozen deploy_schema.sql (delete in Phase 2b once 0002 is verified)
```

## Day-to-day usage

From the `backend/` directory:

```bash
.venv/bin/alembic current             # show the applied revision
.venv/bin/alembic upgrade head        # apply pending migrations
.venv/bin/alembic downgrade -1        # roll back one step
.venv/bin/alembic revision --autogenerate -m "describe change"   # author a new one
.venv/bin/alembic history --verbose   # full revision history
```

`DATABASE_URL` is resolved by `env.py` in this order:

1. `os.environ["DATABASE_URL"]`
2. `app.core.config.DATABASE_URL` (which itself reads `.env`)

So setting the env var on the command line is enough to point Alembic at a
different database for one-off operations.

## First-time operator path (cutover)

When adopting Alembic on a database that already has the legacy 7-table
baseline (everything created by the old `init_db()`/`deploy_schema.sql`):

```bash
cd backend
DATABASE_URL=postgresql://... bash scripts/init_alembic.sh
```

The helper:

1. Stamps `0001_baseline` if `alembic_version` is empty.
2. Runs `alembic upgrade head` (adds indexes + new tables + new columns +
   seed data + LO trigger).
3. Prints the Phase 2c follow-up checklist (set `CERT_HMAC_LEGACY`).

Re-running is safe; every step is guarded.

## Cert backward-compatibility — critical

`0005_seed_data` inserts a `signing_keys` row named `legacy-prod` with
`env_var_name = 'CERT_HMAC_LEGACY'` and backfills every existing
`attempts.signing_key_id` to point at it. The HMAC input
(`cert_id|email|score|submitted_at`) is unchanged, so every cert that
verified before Phase 2a continues to verify after.

In Phase 2c the verify endpoint will start reading the HMAC secret from the
env var named in `signing_keys.env_var_name` rather than `SECRET_KEY`
directly. **Before that cutover lands, the operator must set**:

```
CERT_HMAC_LEGACY=<current value of SECRET_KEY>
```

in the production `.env` and reload the service. Until that happens, the
two env vars hold the same byte sequence and verification continues to work
either way. The startup self-check in Phase 2c will fail fast if
`CERT_HMAC_LEGACY` is missing.

## Large-object lifecycle

`0006_lo_cleanup` installs a `BEFORE DELETE` trigger on `media_assets` that
calls `lo_unlink(OLD.large_object_oid)`. This catches the happy-path
delete. The crash/partial-upload path (where a large object is allocated
but the metadata row never lands) is caught by the **nightly `vacuumlo`
cron**, which scans every OID-typed column and unlinks unreferenced large
objects.

Recommended infra cron (place in `infra/` once the directory lands):

```
# /etc/cron.d/codecoder-vacuumlo
PATH=/usr/bin:/usr/local/bin
SHELL=/bin/bash
# Run at 03:17 daily — late enough to be off-peak, offset off the hour.
17 3 * * *  postgres  vacuumlo -v -n codecoder >> /var/log/codecoder/vacuumlo.log 2>&1
```

Drop the `-n` (dry-run) flag once the report column is reviewed and
confirmed to only contain genuine orphans.

## Phase 2a status

Done:
- [x] Alembic project initialised in `backend/migrations/` and pinned in `requirements.txt`.
- [x] `env.py` wired to read `DATABASE_URL` from env / `app.core.config`.
- [x] `0001_baseline` matches the live schema; stamp-only.
- [x] `0002_reconcile` adds the missing `idx_questions_lookup`,
      `idx_attempts_user`, `idx_feed_items_ordering` indexes that lived only
      in `deploy_schema.sql`. Postgres-only: also adds the GIN indexes on
      `topics`/`search`. The score-type fix is conditional — no-op when the
      live column is already `double precision`.
- [x] `0003_new_tables` adds `signing_keys`, `roles`, `user_roles`,
      `quiz_sessions`, `app_config`, `auth_audit`.
- [x] `0004_new_columns` adds `users.persona`, `attempts.environment`
      (default `'production'`), `attempts.signing_key_id`.
- [x] `0005_seed_data` seeds the 6 capability roles and the `legacy-prod`
      signing key; backfills every existing attempt to it.
- [x] `0006_lo_cleanup` installs the Postgres LO unlink trigger.
- [x] `db.py:_migrate()` retired; `db.py` now configures the SQLAlchemy
      pool per `03-data-model.md §7.1` (Postgres: `pool_size=5`,
      `max_overflow=5`, `pool_pre_ping=True`, `pool_recycle=1800`).
- [x] Existing real cert (`CCA-F-20260605-E79E74AB`) verifies after
      migration — confirmed by the strict smoke canary.

Deferred to later phases:
- [ ] Drop `legacy/reference.sql` once Phase 2b confirms no caller reads it.
- [ ] Phase 2b: backfill `users.role` into `user_roles`, drop `users.role`,
      wire `/verify` to read `signing_keys.env_var_name`.
- [ ] Phase 2b: persist `_active_quizzes` into `quiz_sessions` and add the
      expiry sweep.
- [ ] Phase 2d: read `app_config` with a short cache, fall back to
      `config.py` defaults.
- [ ] `infra/` cron entries for `vacuumlo` and the `quiz_sessions` expiry sweep.

See `docs/architecture/v2/03-data-model.md` §8 for the full ordering and the
parity-gate checklist each step must clear.
