---
id: database-operations
title: Database operations
sidebar_position: 5
---

# Database operations

PostgreSQL is a remote shared instance the app VM connects out to over TLS. This
page covers the day-two database work: backup and restore, the large-object
sweep, key and password rotation, the cache backend, and connection-pool sizing.

## Scan box

- **Back up *with* large objects.** `pg_dump --large-objects` — the single most
  important fact on this page. A plain dump silently drops every video and image.
- **Two cleanup layers for media.** A delete trigger (`0006_lo_cleanup`) is
  authoritative; the nightly `vacuumlo` sweep is the safety net for orphaned
  uploads.
- **The restore go/no-go is the cert canary.** A known issued certificate must
  verify against the restored data, or the restore is not trustworthy.
- **Signing keys rotate in one transaction**, keeping the old key verifiable
  until its 5-year window closes. Key material lives in env vars, never in the
  dump.
- **Cache is in-process by default.** Point `REDIS_URL` at a shared Redis to swap
  the backend — no data migration, no downtime beyond a restart.

## Set your connection once

```bash
export PGURL="postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require"
export PGURL_ADMIN="postgresql://migrator:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require"
psql "$PGURL" -c "\conninfo"     # must report an SSL connection
```

Dev is the `codecoder_dev` database with the `app_dev` role.

## Backup

```bash
pg_dump --format=custom --large-objects \
    --dbname="$PGURL" \
    --file=/var/backups/cca-$(date +%F).dump
```

- One job per database (`codecoder`, `codecoder_dev`); 90-day retention.
- Weekly offsite copy encrypted with `age -r OPERATOR_PUBKEY` — never an
  unencrypted copy off-box.
- The dump contains schema, content, **media bytes** and the `directus_*` system
  tables. It does **not** contain `cms/uploads/` (avatars on app-VM disk) — back
  that up separately if you care about it:
  ```bash
  sudo tar -C /opt/dept-anatomy/cms -czf /var/backups/cms-uploads-$(date +%F).tgz uploads
  ```

```mermaid
flowchart LR
    DB[("codecoder")] -->|"pg_dump --large-objects (TLS)"| F[".dump<br/>schema + content + media + directus_*"]
    F -->|"age -r"| O["encrypted offsite (weekly)"]
```

## Restore drill (quarterly)

Restore into a scratch database on the remote instance — never over production:

```bash
createdb -h REMOTE_DB_HOST -U postgres codecoder_restore_drill
pg_restore --no-owner \
  --dbname="postgresql://postgres:****@REMOTE_DB_HOST:5432/codecoder_restore_drill?sslmode=require" \
  /var/backups/cca-$(date +%F).dump
psql "<restore_drill url>" -c "SELECT count(*) AS media FROM media_assets;"
```

Then the **cert canary** — the acceptance gate. With `CERT_HMAC_LEGACY` set in
the environment, assert that a known issued certificate still verifies against
the restored rows. A failure almost always means a missing `CERT_HMAC_LEGACY`
(it lives in the environment, not the dump). Drop the scratch database once the
drill passes.

## Large-object cleanup

Two layers keep `pg_largeobject` from leaking:

1. **Delete trigger (authoritative)** — `0006_lo_cleanup` installs a
   `BEFORE DELETE` trigger on `media_assets` that `lo_unlink`s the OID in the
   same transaction.
2. **Nightly sweep (safety net)** — `vacuumlo` catches orphans from uploads that
   created a large object but failed before the metadata row committed.
   `deploy.sh` installs `dept-vacuumlo.timer` (03:30 nightly, one per database).
   Manual run during an incident:
   ```bash
   vacuumlo -v "$PGURL"     # idempotent, empty-cost when there are no orphans
   ```

## Rotating certificate signing keys

Keys rotate in a single transaction; the old key keeps verifying until its
`verify_until` deadline passes.

```sql
BEGIN;
INSERT INTO signing_keys (name, environment, env_var_name, is_active, can_verify, verify_until, notes)
VALUES ('prod-2026-Q3', 'production', 'CERT_HMAC_PROD_2026Q3',
        true, true, now() + interval '5 years', 'Rotated 2026-Q3.');
UPDATE signing_keys SET is_active = false
 WHERE environment = 'production' AND name = 'legacy-prod';
COMMIT;
```

The new key's material must already be in its env var and the service restarted
**before** you flip `is_active`. Keep the old env var in place; only retire it
after the window closes:

```sql
UPDATE signing_keys SET can_verify = false WHERE verify_until < now();
```

A partial unique index enforces exactly one `is_active` key per environment. See
[Quiz administration](./quiz-administration) for what these certificates are and
how verification reads these flags.

## Rotating the Directus database password

Two places must stay in sync — the Postgres role and `cms/.env`:

```bash
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
psql "$PGURL_ADMIN" -c "ALTER ROLE directus_app WITH PASSWORD '$NEW';"
sudo sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$NEW|" /opt/dept-anatomy/cms/.env
sudo systemctl restart cms-directus
journalctl -u cms-directus -n 20      # confirm reconnection
```

Or `sudo CMS_DB_PASS="$NEW" ./deploy.sh --update`, which does the same three
steps idempotently.

## The cache backend

| `REDIS_URL` | Backend | Notes |
|---|---|---|
| unset (default) | in-process `AppCache`, per worker | TTLs from `CACHE_TTL_*`; webhook-invalidated |
| set | shared Redis (bound `127.0.0.1`) | same TTLs and webhook; falls back to memory if unreachable at boot |

Switching is stateless — no data migration, no downtime beyond a restart.

## Connection-pool sizing

The engine uses `pool_size=5`, `max_overflow=5`, `pool_pre_ping=True`,
`pool_recycle=1800` **per worker**. `pool_size × worker_count` must stay well
under the remote instance's `max_connections`, leaving headroom for:

- Directus's own pool,
- `psql` sessions, and
- **raw large-object connections** (`engine.raw_connection()` — *not* drawn from
  the SQLAlchemy pool; a long video Range request pins one for the whole
  transfer).

On a shared instance the budget spans every environment that connects (prod and
dev share one `max_connections` ceiling).

## Postgres extensions

The schema needs `pgcrypto` (for `gen_random_uuid()`) and `hstore`. On a managed
remote instance the runtime app role is DML-only and **cannot** `CREATE
EXTENSION` — the DBA pre-creates both in each database before the app boots, as
part of the same pre-flight that creates the databases and per-env roles.
`init_db()` treats its own `CREATE EXTENSION` as non-fatal.

:::caution[Common Pitfall]

A plain `pg_dump codecoder` looks complete, restores cleanly, and serves zero
videos or images. Media bytes live only in `pg_largeobject`; `--large-objects`
is mandatory, not optional. This is the single most important line on the page —
check your backup job for it now.

:::

:::note[Why This Matters]

Keep the old certificate env var after rotation. Removing `CERT_HMAC_LEGACY`
breaks verification of every certificate it signed. A certificate is a five-year
promise; the rotation scheme (a new key plus a kept-verifiable old key, bounded
by `verify_until`) exists so the platform can honour that promise while still
rotating on a normal cadence.

:::

For the data model behind all this — the GRANT/REVOKE matrix, the Postgres-only
features, large-object internals — see
[role isolation](../developer/data-model/role-isolation),
[Postgres-only features](../developer/data-model/postgres-only-features) and
[media large objects](../developer/data-model/media-large-objects).
