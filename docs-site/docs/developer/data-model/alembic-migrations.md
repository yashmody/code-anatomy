---
id: alembic-migrations
title: Alembic migrations
sidebar_position: 3
---

# Alembic migrations

## Scan box

- **Alembic is the only schema-change mechanism.** It replaced the
  hand-rolled `db.py:_migrate()` patcher and the drifted `deploy_schema.sql`.
  The chain runs `0001`→`0008`, head is `0008_directus_app_role`.
- **The baseline is stamped, not run.** `0001_baseline` has empty
  `upgrade()`/`downgrade()`. `alembic stamp 0001` records the live schema as
  revision 1 without touching a single table — the keystone of the
  no-data-loss adoption.
- **Additions before drops.** New tables, columns, and seed data land first
  (`0002`–`0007`); the only structural-ownership change is the additive
  `directus_app` role grant in `0008`. No destructive drop runs against
  existing data in the shipped chain.
- **Every migration is idempotent and dialect-aware.** Each guards on an
  inspector lookup or `IF NOT EXISTS`, skips Postgres-only steps on SQLite,
  and excludes `directus_*` tables from autogenerate.

The Alembic project lives in `backend/migrations/`. The models in
`backend/app/core/models.py` are the source; `env.py` points
`target_metadata` at `Base.metadata` so `--autogenerate` diffs against them.

## The chain

```mermaid
graph LR
    A["0001_baseline<br/>(stamped, empty)"] --> B["0002_reconcile<br/>indexes + score fix"]
    B --> C["0003_new_tables<br/>6 new tables"]
    C --> D["0004_new_columns<br/>persona, environment,<br/>signing_key_id"]
    D --> E["0005_seed_data<br/>roles + legacy-prod key<br/>+ attempts backfill"]
    E --> F["0006_lo_cleanup<br/>lo_unlink trigger"]
    F --> G["0007_seed_nonprod_<br/>signing_keys<br/>dev + staging"]
    G --> H["0008_directus_app_role<br/>GRANT / REVOKE"]
```

### 0001 — baseline (stamped)

`0001_baseline.py` is intentionally empty. Alembic was adopted on a database
that already held the legacy seven-table schema, created by the old
`init_db()` + `_migrate()` path. Running `alembic stamp 0001_baseline`
writes the `alembic_version` row and **touches no tables** — the live schema
is declared "this is revision 1" exactly as it stands. Nothing is dropped,
nothing is recreated.

:::note[Why This Matters]

`alembic stamp` is what makes adoption safe on a production database with
real certificates in it. A naive `alembic upgrade` from an empty baseline
would try to *create* tables that already exist and fail — or worse, on a
fresh autogenerate, propose dropping columns it did not know about. Stamping
declares the truth instead of asserting it, then every later revision is a
pure forward step. This is the no-data-loss keystone.

:::

### 0002 — reconcile

`0002_reconcile.py` fixes the drift between the ORM and the old
`deploy_schema.sql`. The legacy `create_all()` boot path never created the
lookup indexes that lived only in the DDL file, so a system booted that way
had none of them. This migration installs them, all `CREATE INDEX IF NOT
EXISTS` so re-runs and fresh installs both converge:

- `idx_questions_lookup` on `(status, difficulty, topic)`
- `idx_attempts_user` on `(user_email, submitted_at)`
- `idx_feed_items_ordering` on `(status, created_at)`
- Postgres-only GIN indexes: `idx_feed_items_topics` on `topics`, and
  `idx_feed_items_search` on the `search` tsvector column when it is present.

It also carries the conditional `score`-type fix described below.

### 0003 — new tables

`0003_new_tables.py` creates the six Phase 2a tables: `signing_keys`,
`roles`, `user_roles`, `quiz_sessions`, `app_config`, and `auth_audit`.
Each `create_table` is guarded by an inspector lookup so the migration stays
idempotent even when `init_db()`'s first-boot `create_all()` has already
made some of them. `auth_audit` is created here, ahead of any authorisation
backfill, so that the later authz split can write `role.grant` rows for its
own backfill.

### 0004 — new columns

`0004_new_columns.py` adds the non-breaking columns: `users.persona`,
`attempts.environment` (with `server_default='production'`), and
`attempts.signing_key_id`. The column additions and the data backfill are
deliberately split across `0004` and `0005` so the schema change and the
data change can be reverted independently. SQLite cannot
`ALTER TABLE ADD CONSTRAINT`, so the FK on `signing_key_id` is added through
Alembic batch mode for local-suite portability.

### 0005 — seed data

`0005_seed_data.py` does three things, all idempotent:

1. Seeds the six capability roles into `roles`.
2. Inserts the `legacy-prod` row into `signing_keys`, with
   `env_var_name = 'CERT_HMAC_LEGACY'`.
3. Backfills `attempts.signing_key_id` so every existing attempt points at
   `legacy-prod`.

Step 3 is the certificate-survival keystone — see the section below.

### 0006 — large-object cleanup

`0006_lo_cleanup.py` installs the `BEFORE DELETE` trigger on `media_assets`
that calls `lo_unlink(OLD.large_object_oid)`. It is Postgres-only and a
no-op on SQLite. Full detail in
[Media large objects](./media-large-objects.md).

### 0007 — non-production signing keys

`0007_seed_nonprod_signing_keys.py` seeds two more `signing_keys` rows —
`dev-default` (env var `CERT_HMAC_DEV`) and `stg-default`
(`CERT_HMAC_STG`) — so development and staging sign and verify certificates
with their *own* material instead of borrowing the production key. Both
guard on the unique `name`, and each claims the active slot for its
environment only when no active signer already exists, so it never violates
the one-active-key-per-environment rule. The `legacy-prod` production row is
untouched.

### 0008 — Directus role

`0008_directus_app_role.py` creates the scoped Directus Postgres login role and
pins its reach with a GRANT/REVOKE matrix. The role **name is parameterised**
via `DIRECTUS_DB_ROLE` (`directus_app` for prod, `directus_app_dev` for dev) so
that on the shared remote instance the dev role is GRANTed only on
`codecoder_dev` and can never reach prod. It is additive, reversible, and moves
no content. The full matrix — and why a distinct role name per env is what gives
credential isolation on one cluster — is in [Role isolation](./role-isolation.md).

## The score type — load-bearing

The single most important correctness decision in the chain is that
`attempts.score` stays `DOUBLE PRECISION` and is never converted to
`NUMERIC(5,2)`.

The certificate seal is an HMAC-SHA256 over
`cert_id|email|score|submitted_at`, and the `score` part is formatted as
`f"{score:.6f}"`. `score` is a 0–1 fraction (`correct / total`), so a value
like `0.866667` is hashed exactly. If the column were `NUMERIC(5,2)`, that
value would round to `0.87` on read, the recomputed HMAC would not match,
and **every already-issued certificate would fail verification**.

The legacy schema had a real drift here: a database created from
`deploy_schema.sql` had a `NUMERIC(5,2)` column, while one created by the
ORM's `create_all()` had `double precision`. `0002_reconcile` resolves it in
the safe direction — and only conditionally:

```sql
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='attempts' AND column_name='score'
             AND data_type='numeric') THEN
    ALTER TABLE attempts ALTER COLUMN score TYPE double precision
      USING score::double precision;
  END IF;
END $$;
```

The `downgrade()` deliberately does **not** reverse this — going back to
`NUMERIC(5,2)` would break verification, so the rollback leaves the column as
`double precision`.

:::caution[Common Pitfall]

Letting `alembic revision --autogenerate` propose a `score` type change and
applying it without review. Autogenerate compares the ORM `Float` against
the live column and may suggest an `ALTER`. On a database that is already
`double precision` this is a harmless no-op, but if anyone ever sets the ORM
type to `Numeric`, autogenerate would happily round the column and silently
break certificates. Always hand-review the diff; the model comment in
`models.py` exists precisely to warn against this.

:::

## No data loss — how certificates survive

The adoption was designed so a database full of real, already-issued
certificates comes through unchanged. Four facts combine to guarantee it:

1. **The HMAC input is unchanged.** `cert_id|email|score|submitted_at` is
   the same string before and after the migration.
2. **`score` keeps its exact value** — `DOUBLE PRECISION`, never rounded
   (see above).
3. **`attempts.environment` defaults to `production`**, so every existing
   row is treated as a real certificate, not a development one.
4. **`attempts.signing_key_id` is backfilled to `legacy-prod`**, whose
   `env_var_name` is `CERT_HMAC_LEGACY`. The verifier will pick the key by
   `signing_key_id`, so rotating the session secret never invalidates an old
   cert.

The shipped chain was verified against a real certificate
(`CCA-F-20260605-E79E74AB`): it verifies after every migration in the chain
has run. That canary is the proof the no-data-loss claim is not theoretical.

:::tip[Agency Tip]

Before the verify endpoint is cut over to read the HMAC secret by
`signing_keys.env_var_name`, the operator must set
`CERT_HMAC_LEGACY=<current value of SECRET_KEY>` in the production `.env`
and reload. Until that lands, `SECRET_KEY` and `CERT_HMAC_LEGACY` hold the
same bytes and verification works either way. The cutover self-check fails
fast if `CERT_HMAC_LEGACY` is missing — so set it during the same
maintenance window as the migration, not after.

:::

## Day-to-day operation

From the `backend/` directory:

```bash
.venv/bin/alembic current          # show the applied revision
.venv/bin/alembic upgrade head      # apply pending migrations
.venv/bin/alembic downgrade -1      # roll back one step
.venv/bin/alembic history --verbose # full revision history
```

`env.py` resolves `DATABASE_URL` from the environment first, then from
`app.core.config`, so a one-off `DATABASE_URL=... alembic upgrade head`
points the tool at a different database for a single command. Against the
**remote shared instance** this is how you target the right env and supply the
right credential: migrations run with a **privileged** credential (DDL on the
target database) — the runtime app role (`app_prod` / `app_dev`) is DML-only and
cannot run DDL, create extensions, or create the Directus role. Set
`DIRECTUS_DB_ROLE` alongside it so `0008` creates the env-correct Directus role,
and keep `?sslmode=require` in the URL:

```bash
DATABASE_URL="postgresql://migrator:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require" \
DIRECTUS_DB_ROLE=directus_app \
  .venv/bin/alembic upgrade head        # prod; for dev use codecoder_dev + directus_app_dev
```

For a first-time cutover on a database that already holds the legacy
seven-table baseline, the helper `backend/scripts/init_alembic.sh` stamps
`0001` if `alembic_version` is empty, runs `upgrade head`, and prints the
`CERT_HMAC_LEGACY` follow-up checklist. Re-running it is safe — every step
is guarded.

## Directus tables are off-limits to autogenerate

Directus creates and owns its own `directus_*` tables in the same database.
`env.py` registers an `include_object` hook that returns `False` for any
table whose name starts with `directus_`, so `--autogenerate` never proposes
dropping or altering them:

```python
def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name and name.startswith("directus_"):
        return False
    return True
```

This is what lets the two systems share one database safely: Alembic manages
the application tables, Directus manages its own, and neither tool's
autogenerate ever touches the other's. See
[Postgres-only features](./postgres-only-features.md) for how the two table
namespaces coexist.
