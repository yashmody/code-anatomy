---
id: operations
title: Day-two operations
sidebar_position: 7
---

# Day-two operations

## Scan box

- The nightly **backup must include large objects** — `pg_dump --large-objects`,
  run **against the remote database over TLS** (the DB is no longer on the app
  VM). A plain dump silently drops every video and image, because all media lives
  in `pg_largeobject`. The `directus_*` tables ride the same dump. Run one job
  per database — `codecoder` (prod) and `codecoder_dev` (dev).
- Two mechanisms keep large objects from leaking: a **delete trigger**
  (authoritative) and the **nightly `vacuumlo` sweep** (the safety net for
  failed uploads). `deploy.sh` installs the sweep as a systemd timer.
- **Certificate signing keys** rotate in a single transaction, with the old key
  kept `can_verify` until its five-year window closes. The key *material* lives
  in an env var, never in the database or a dump.
- The cache backend is **in-process by default** (no Redis at launch). Pointing
  `REDIS_URL` at a shared Redis swaps the backend behind the same interface, with
  no data migration and no downtime beyond a restart.
- The restore drill's go/no-go gate is the **cert canary**: a known
  already-issued certificate must still verify against the restored data.

## Connecting to the remote database

Postgres is a **remote shared instance** (`REMOTE_DB_HOST:5432`), so the old
`sudo -u postgres` peer-auth path on the app VM no longer reaches it. Every
command below connects with a URL instead — set two placeholders once per ops
session, and include `sslmode=require` so the connection is encrypted (with a
provisioned CA, prefer `verify-full` plus `sslrootcert=`):

```bash
# Runtime role — DML only. For dev, use the codecoder_dev URL with app_dev.
export PGURL="postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require"
# Privileged role — DDL / role / restore work (the DBA's migration credential).
export PGURL_ADMIN="postgresql://migrator:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require"
```

`psql "$PGURL" -c "\conninfo"` must report an `SSL connection` line; if it does
not, the link is cleartext and must be fixed before any data work.

## Backup — both halves

The nightly backup is a custom-format `pg_dump` of the **remote** database, taken
over TLS, that **must** carry large objects:

```bash
pg_dump \
    --format=custom \
    --large-objects \
    --dbname="$PGURL" \
    --file=/var/backups/cca-$(date +%F).dump
# $PGURL = postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require
# run a separate job per database: codecoder (prod) and codecoder_dev (dev).
```

```mermaid
flowchart LR
    PG[("remote codecoder<br/>(REMOTE_DB_HOST)")]
    PG -- "pg_dump --large-objects<br/>over TLS (sslmode=require)" --> D["nightly .dump<br/>schema + content + media bytes<br/>+ directus_* tables"]
    D -- "age -r OPERATOR_PUBKEY" --> E["weekly encrypted .age<br/>→ offsite (BACKUP_TARGET_URL)"]
    UP["cms/uploads/<br/>(avatars only — on app VM disk)"] -- "tar -czf" --> T["cms-uploads-*.tgz"]
```

Retention is 90 days. The weekly offsite copy is encrypted with `age` before it
leaves the box — never ship an unencrypted dump off the VM. Two things to know:

- **The `directus_*` tables are already inside this dump.** Directus shares the
  `codecoder` database, so the one custom-format dump captures schema, content,
  media bytes, *and* the Directus system tables. No separate Directus DB dump is
  needed.
- **`cms/uploads/` is not in the dump.** It is on the filesystem (avatars and
  incidental Directus-internal files only — no app media), so back it up
  alongside if you want those: `sudo tar -C /opt/dept-anatomy/cms -czf
  /var/backups/cms-uploads-$(date +%F).tgz uploads`.

:::caution[Common Pitfall]
A plain `pg_dump codecoder` **silently drops every large object** — so the dump
looks complete, restores cleanly, and serves zero videos and images. Media bytes
live only in `pg_largeobject`; `--large-objects` is mandatory, not optional. This
is the single most important fact on this page.
:::

## The restore drill

Restore into a **scratch** database **on the remote instance** — never over
`codecoder` — and gate it on the cert canary. Creating and restoring need a
privileged credential (the DBA / remote superuser), not the DML-only runtime
role:

```bash
createdb -h REMOTE_DB_HOST -U postgres codecoder_restore_drill
pg_restore \
    --dbname="postgresql://postgres:****@REMOTE_DB_HOST:5432/codecoder_restore_drill?sslmode=require" \
    --no-owner /var/backups/cca-$(date +%F).dump
psql "postgresql://postgres:****@REMOTE_DB_HOST:5432/codecoder_restore_drill?sslmode=require" \
    -c "SELECT count(*) AS media FROM media_assets;"
```

The acceptance check is the **cert canary**: a known load-bearing certificate must
still verify against the restored database. Point the verifier at the scratch DB
with the legacy HMAC env var present:

```bash
cd /opt/dept-anatomy/backend
DATABASE_URL="postgresql://postgres:****@REMOTE_DB_HOST:5432/codecoder_restore_drill?sslmode=require" \
  CERT_HMAC_LEGACY="$CERT_HMAC_LEGACY" \
  .venv/bin/python -c "..."   # asserts storage.verify_signature(attempt) is True
```

A `VERIFIES` result means the signing-key metadata and legacy HMAC material
round-tripped intact. If it prints `FAILED`, the most common cause is a missing
`CERT_HMAC_LEGACY` — **the key material lives in the env, not the dump**, which is
exactly why a database restore alone is not enough to verify a certificate. Drop
the scratch DB once the drill passes.

A real disaster restore is the same steps against a fresh `codecoder` on the
remote instance (stop `cca-quiz` first, create the database, `pg_restore` over
TLS, restart), with the same canary check as the go/no-go gate before taking
traffic. The app VM never holds the data — it only points its `DATABASE_URL` at
the restored remote database. Run the drill quarterly.

## Large-object cleanup

Media bytes are large objects referenced by `media_assets.large_object_oid`. Two
mechanisms keep `pg_largeobject` from leaking:

1. **Delete trigger (authoritative).** Migration `0006_lo_cleanup` adds a
   `BEFORE DELETE` trigger on `media_assets` that calls `lo_unlink` on the OID,
   reclaiming the happy-path delete transactionally.
2. **Nightly sweep (safety net).** `vacuumlo` over the **remote** `codecoder`
   unlinks any large object not referenced anywhere. This catches orphans from
   **failed uploads**, where the large object is created and committed before the
   metadata row is inserted — if that insert fails, only a sweep can reclaim the
   bytes.

`deploy.sh` installs the sweep as a nightly systemd timer (`dept-vacuumlo.timer`,
03:30) on the app VM, connecting out to the remote database over TLS. Run one
timer per database (`codecoder`, `codecoder_dev`). To run it by hand during an
incident:

```bash
vacuumlo -v "$PGURL"
# $PGURL = postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require
```

It is idempotent and empty-cost when there are no orphans, so it is safe to run
any number of times.

## Signing-key rotation

Certificates are signed with an HMAC keyed on material held in an environment
variable. The `signing_keys` table holds only metadata — which env var holds the
material, which environment it belongs to, whether it is the active signer, and
how long it stays valid on verify. Three columns drive the lifecycle:

- **`is_active`** — the current signer for that environment. A partial unique
  index on `(environment) WHERE is_active` guarantees exactly one active key per
  environment.
- **`can_verify`** — whether the key is still accepted when verifying an old cert.
- **`verify_until`** — a hard deadline. Past it, the verifier treats the key as
  un-verifiable regardless of `can_verify`, enforcing the five-year verify window.

Rotate in a **single transaction** so there is never a window with zero or two
active signers. The new material must already be in its env var and the service
restarted *before* you flip `is_active`:

```sql
BEGIN;
-- 1. Insert the new signer; verify_until is five years out.
INSERT INTO signing_keys
    (name, environment, env_var_name, is_active, can_verify, verify_until, notes)
VALUES
    ('prod-2026-Q3', 'production', 'CERT_HMAC_PROD_2026Q3',
     true, true, now() + interval '5 years', 'Rotated 2026-Q3.');
-- 2. Demote the old signer; it KEEPS its verify_until, so certs it already
--    signed keep verifying until that deadline.
UPDATE signing_keys SET is_active = false
 WHERE environment = 'production' AND name = 'legacy-prod';
COMMIT;
```

:::note[Why This Matters]
**Keep the old env var in place after rotation.** Removing `CERT_HMAC_LEGACY`
breaks verification of every certificate it signed. It is retired only after the
old key's `verify_until` passes and the explicit sweep
(`UPDATE signing_keys SET can_verify = false WHERE verify_until < now()`) has run.
A certificate is a five-year promise; the deploy honours it by keeping the legacy
material reachable for the full window.
:::

## The cache backend switch

The app caches the framework payload, the feed, and app-config in process by
default. **There is no Redis on the box at launch** — the in-process `AppCache`
is the default and is correct for a single VM with a small worker count. The
backend is selected by environment configuration:

```mermaid
flowchart LR
    A["REDIS_URL unset (default)"] --> B["in-process AppCache<br/>per-worker · webhook-invalidated<br/>TTLs from CACHE_TTL_*"]
    C["REDIS_URL set"] --> D["shared Redis<br/>one webhook-invalidated cache<br/>bound to 127.0.0.1 only"]
    D -. "Redis unreachable at boot" .-> B
```

- **In-process (default).** Leave `REDIS_URL` unset. Each worker keeps its own
  cache, invalidated by the Directus webhooks and the `CACHE_TTL_*` lifetimes
  (`CACHE_TTL_FRAMEWORK`, `CACHE_TTL_FEED`, `CACHE_TTL_APP_CONFIG` in `.env`).
- **Shared Redis (multi-worker / multi-host).** Point `REDIS_URL` at a Redis
  instance and restart `cca-quiz`. If `REDIS_URL` is set but Redis is unreachable
  at boot, the app **logs a warning and falls back to the in-process cache**
  rather than failing to start — confirm the fallback in the journal after any
  Redis change, and confirm Redis is bound to `127.0.0.1` only.

The switch is cache-only and stateless: no data migration, no downtime beyond the
restart. The TTLs and webhook-invalidation contract are identical across both
backends.

## Reading the slow-query log

`log_min_duration_statement = 500ms` makes Postgres log every statement taking
half a second or more, with its duration — the first place to look after a deploy
when latency rises. On the **remote** instance this parameter is owned by the DBA
/ managed-service parameter group, not by a local `infra/postgres/cca-tuning.conf`
on the app VM; confirm it with `psql "$PGURL" -c "SHOW log_min_duration_statement;"`.

The slow-query log lives **on the DB host or the managed-service log stream**, not
on the app VM. For a managed instance, read it from the provider's log export
(Azure Database for PostgreSQL → Logs). Where you have shell on a self-managed DB
host the files are `/var/lib/pgsql/*/data/log/postgresql-*.log` (RHEL) or
`/var/log/postgresql/postgresql-<ver>-main.log` (Debian). A `duration: NNNN ms`
line names the exact statement; run it under `EXPLAIN (ANALYZE, BUFFERS)` against
the remote DB (`psql "$PGURL_ADMIN" -c "EXPLAIN ..."`) and diff against the
hot-query baselines under `tests/baseline/explain/`. The same config logs
checkpoints, lock waits, and large temp files — a flood of temp-file lines for one
query means `work_mem` is too low for that workload; raise it for the session.

## directus_app password rotation

The Directus DB-role password lives in two places that must stay in sync — the
Postgres role on the **remote** instance and `cms/.env` on the app VM. Rotate in
this order (no app-plane downtime; the FastAPI app uses a different role). Use the
env-correct role name — `directus_app` against `codecoder` for prod,
`directus_app_dev` against `codecoder_dev` for dev:

```bash
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
psql "$PGURL_ADMIN" -c "ALTER ROLE directus_app WITH PASSWORD '$NEW';"
sudo sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$NEW|" /opt/dept-anatomy/cms/.env
sudo systemctl restart cms-directus
```

Or simply re-run `sudo CMS_DB_PASS="$NEW" ./deploy.sh --update`, which does the
same three steps idempotently. Confirm reconnection with
`journalctl -u cms-directus -n 20`.

## Routine commands

```bash
# App
journalctl -u cca-quiz -f
systemctl restart cca-quiz

# Apache
sudo tail -f /var/log/httpd/cca-quiz_error.log
sudo httpd -t && sudo systemctl reload httpd

# Directus
systemctl status cms-directus
journalctl -u cms-directus -f

# Database (remote, over TLS)
psql "$PGURL" -c "SELECT count(*) FROM questions;"
psql "$PGURL" -c "\conninfo"   # confirm an SSL connection line
```

## Known accepted risks

- **Frozen monolith CDN tags.** The frozen course HTML under `content/frozen/`
  keeps its original un-pinned mermaid `<script>` tag as accepted historical risk
  — that file is bit-frozen for parity and is not edited in v2. The **live**
  front-end is hardened instead: mermaid is pinned to an exact version with a
  Subresource Integrity hash, and the CSP `script-src` allow-list is the
  supply-chain gate for the dynamic Ajv imports.
- **No Redis at launch.** The in-process cache is the v2 default; Redis is an
  opt-in scale lever, not a dependency.
