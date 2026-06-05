# DEPT® Anatomy of Code — Operator Runbook

This runbook covers the day-two operations an on-call engineer needs for the
v2 single-VM deployment: database backup and restore, reading the slow-query
log, rotating a certificate signing key, switching the cache backend, and the
large-object cleanup cron. It assumes the topology from `deploy.sh` — one Azure
VM running Apache, the FastAPI app under systemd (`cca-quiz`), and PostgreSQL on
the same host.

Paths below use the RHEL layout (`/var/lib/pgsql/...`, `/etc/httpd/...`) that
`deploy.sh` targets; the Debian equivalents are noted where they differ. The
application database is `codecoder` and the OS database superuser is `postgres`.

> **Convention.** Commands prefixed `sudo -u postgres` run as the database
> superuser via peer authentication — no password is needed on the VM itself.

---

## 1 · PostgreSQL backup and restore drill

### 1.1 Nightly backup

The backup is a custom-format `pg_dump` that includes large objects (the media
bytes live in `pg_largeobject`, so `--large-objects` is mandatory — a plain dump
silently drops them):

```bash
sudo -u postgres pg_dump \
    --format=custom \
    --large-objects \
    --file=/var/backups/cca-$(date +%F).dump \
    codecoder
```

Retention is 90 days. A weekly offsite copy is encrypted with `age` before it
leaves the box:

```bash
age -r "$OPERATOR_PUBKEY" \
    -o /var/backups/cca-$(date +%F).dump.age \
    /var/backups/cca-$(date +%F).dump
# then upload the .age file to the configured BACKUP_TARGET_URL
```

`OPERATOR_PUBKEY` and `BACKUP_TARGET_URL` are environment configuration (see
`05-config-cms.md`). Never ship the unencrypted dump off the VM.

### 1.2 Restore drill (quarterly)

Restore into a **scratch** database — never over `codecoder` — and use the
cert canary as the acceptance check. The drill passes only when the
already-issued real certificate still verifies against the restored data.

```bash
# 1. Create an empty scratch database.
sudo -u postgres createdb codecoder_restore_drill

# 2. Restore the most recent dump into it (custom format -> pg_restore).
sudo -u postgres pg_restore \
    --dbname=codecoder_restore_drill \
    --no-owner \
    /var/backups/cca-$(date +%F).dump

# 3. Sanity-check the row counts roughly match production.
sudo -u postgres psql -d codecoder_restore_drill \
    -c "SELECT count(*) AS attempts FROM attempts;" \
    -c "SELECT count(*) AS signing_keys FROM signing_keys;" \
    -c "SELECT count(*) AS media FROM media_assets;"
```

**Acceptance check — the cert canary.** The load-bearing certificate
`CCA-F-20260605-E79E74AB` must still verify against the restored database. Point
the verifier at the scratch DB and confirm `verify_signature` returns `True`:

```bash
cd /opt/dept-anatomy/quiz-certification   # the deployed backend
DATABASE_URL="postgresql://localhost/codecoder_restore_drill" \
  CERT_HMAC_LEGACY="$CERT_HMAC_LEGACY" \
  .venv/bin/python - <<'PY'
from app.modules.quiz import storage
cert = "CCA-F-20260605-E79E74AB"
a = storage.attempt_by_cert_id_public(cert)
ok = bool(a and a.get("passed") and storage.verify_signature(a))
print("CANARY", cert, "->", "VERIFIES" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
PY
```

A `VERIFIES` line (exit 0) means the restore is good: the signing-key metadata
and the legacy HMAC material round-tripped intact. If it prints `FAILED`, the
restore is unusable — the most common cause is a missing `CERT_HMAC_LEGACY` env
var (the key material lives in the env, not the dump). Drop the scratch DB once
the drill passes:

```bash
sudo -u postgres dropdb codecoder_restore_drill
```

A real disaster restore is the same steps against a fresh `codecoder`
(stop `cca-quiz` first, `createdb codecoder`, `pg_restore`, restart the service),
with the same canary check as the go/no-go gate before taking traffic.

---

## 2 · Reading the slow-query log

`infra/postgres/cca-tuning.conf` sets `log_min_duration_statement = 500ms`, so
PostgreSQL logs every statement that takes half a second or longer, with its
duration. This is the first place to look after a deploy when latency rises.

The log lives with the PostgreSQL server logs:

- **RHEL:** `/var/lib/pgsql/<ver>/data/log/postgresql-*.log`
- **Debian:** `/var/log/postgresql/postgresql-<ver>-main.log`

Tail it live, or pull the slow lines out of a rotated file:

```bash
# Live, slow statements only:
sudo tail -f /var/lib/pgsql/*/data/log/postgresql-*.log | grep -E 'duration: [0-9]{4,}'

# The ten slowest statements in the current log, longest first:
sudo grep -hoE 'duration: [0-9.]+ ms[^,]*statement: .*' \
    /var/lib/pgsql/*/data/log/postgresql-*.log \
  | sort -t' ' -k2 -n -r | head
```

A `duration: NNNN ms` line names the exact statement. To understand *why* it is
slow, run it under `EXPLAIN (ANALYZE, BUFFERS)` as the `postgres` user and check
for sequential scans on indexed columns or unexpected row estimates. The hot-query
`EXPLAIN` baselines captured under `tests/baseline/explain/` (per
`06-caching-performance.md` §6.5) are the reference to diff against.

The same config logs checkpoints (`log_checkpoints`), lock waits
(`log_lock_waits`), and large temp files (`log_temp_files = 10MB`). A flood of
temp-file lines for one query means `work_mem` is too low for that workload —
raise it for the session, not globally, before re-tuning the conf.

---

## 3 · Signing-key rotation

Certificates are signed with an HMAC keyed on material held in an environment
variable. The `signing_keys` table holds only the *metadata* — which env var
holds the material, which environment it belongs to, whether it is the active
signer, and how long it stays valid on verify. The material itself never lands
in the database or a dump (this is why the restore drill in §1.2 needs the env
var present). The model follows `07-security-baseline.md` §8.4.

Three columns drive the lifecycle:

- `is_active` — the current signer for that environment. A partial unique index
  on `(environment) WHERE is_active` guarantees exactly one active key per
  environment.
- `can_verify` — whether the key is still accepted when verifying an old cert.
- `verify_until` — a hard wall-clock deadline. Past it, the verifier treats the
  key as un-verifiable regardless of `can_verify`. This enforces the five-year
  verify window (gate decision Q-7).

### 3.1 Rotating the active key (within one environment)

Rotate in a single transaction so there is never a window with zero or two
active signers. The new material must already be present in its env var and the
service restarted to pick it up *before* you flip `is_active`.

```sql
-- Run as the postgres superuser, in ONE transaction.
BEGIN;

-- 1. Insert the new signer. verify_until is five years out (Q-7).
INSERT INTO signing_keys
    (name, environment, env_var_name, is_active, can_verify, verify_until, notes)
VALUES
    ('prod-2026-Q3', 'production', 'CERT_HMAC_PROD_2026Q3',
     true, true, now() + interval '5 years',
     'Rotated 2026-Q3. Material in env var CERT_HMAC_PROD_2026Q3.');

-- 2. Demote the old signer. It KEEPS its original verify_until, so every cert
--    it already signed continues to verify until that deadline.
UPDATE signing_keys
   SET is_active = false
 WHERE environment = 'production'
   AND name = 'legacy-prod';

COMMIT;
```

After the commit:

- New attempts get the new `signing_key_id`. Old attempts keep theirs — they are
  verified against the old (now inactive, still `can_verify=true`) key until its
  `verify_until` passes.
- **Keep the old env var (`CERT_HMAC_LEGACY`) in place.** Removing it breaks
  verification of every cert it signed. It is retired only after the old key's
  `verify_until` has passed and the sweep in §3.2 has run.

### 3.2 Retiring an expired key

Once an inactive key's `verify_until` is in the past, no valid certificate
should still depend on it (the verifier already returns
`{valid:false, reason:"key_expired"}` for anything past the deadline). Flip
`can_verify` off in a sweep so the intent is explicit, then the env var can be
removed at the next deploy:

```sql
UPDATE signing_keys
   SET can_verify = false
 WHERE can_verify = true
   AND verify_until IS NOT NULL
   AND verify_until < now();
```

### 3.3 Non-production signers

Migration `0007_seed_nonprod_signing_keys` seeds `dev-default` (development) and
`stg-default` (staging) so non-prod environments sign with their own material
(env vars `CERT_HMAC_DEV` / `CERT_HMAC_STG`) instead of borrowing production's.
On a fresh deploy these come up active; if a hand-seeded signer already holds the
active slot for that environment, the migration inserts them inactive to respect
the partial unique index — promote one by flipping `is_active` in the same
single-transaction pattern as §3.1. The production `legacy-prod` row is never
touched by that migration.

---

## 4 · Cache backend switch (memory ↔ Redis)

The app caches the framework payload, the feed, and app-config in process by
default. There is **no Redis on the box at v2 launch** — the in-process
`AppCache` is the default and is fully functional on a single VM with a small
number of workers. The cache backend is selected by environment configuration so
the app degrades gracefully when Redis is absent.

- **In-process (default).** Leave `REDIS_URL` unset. Each uvicorn worker keeps
  its own cache, invalidated by the Directus webhooks and the `CACHE_TTL_*`
  lifetimes (`CACHE_TTL_FRAMEWORK`, `CACHE_TTL_FEED`, `CACHE_TTL_APP_CONFIG` in
  the `.env`). This is correct for one or two workers.

- **Shared Redis (multi-worker / multi-host).** When you scale past a couple of
  workers and want one shared, webhook-invalidated cache, point the app at a
  Redis instance:

  ```ini
  # backend/.env
  REDIS_URL=redis://127.0.0.1:6379/0
  ```

  Then restart the service:

  ```bash
  sudo systemctl restart cca-quiz
  ```

  If `REDIS_URL` is set but Redis is unreachable at boot, the app logs a warning
  and falls back to the in-process cache rather than failing to start — verify
  the fallback in the service journal (`journalctl -u cca-quiz`) after any Redis
  change, and confirm Redis is bound to `127.0.0.1` only (never exposed
  externally, per `07-security-baseline.md` §9).

Switching backends is cache-only and stateless: no data migration, no downtime
beyond the service restart. The TTLs and webhook-invalidation contract are
identical across both backends.

---

## 5 · Large-object cleanup cron (`vacuumlo`)

Media bytes are stored as PostgreSQL large objects referenced by
`media_assets.large_object_oid`. Two mechanisms keep `pg_largeobject` from
leaking bytes (`03-data-model.md` §7.2):

1. **Delete trigger (authoritative).** Migration `0006_lo_cleanup` adds a
   `BEFORE DELETE` trigger on `media_assets` that calls `lo_unlink` on the
   referenced OID. This reclaims the happy-path delete transactionally.

2. **Nightly sweep (safety net).** `infra/cron/vacuumlo.sh` runs `vacuumlo`
   over `codecoder` to unlink any large object not referenced anywhere. This
   catches orphans from **failed uploads**, where the LO is created and
   committed before the metadata row is inserted — if that insert fails, only a
   sweep can reclaim the bytes.

`deploy.sh` installs the sweep as a nightly systemd timer (with the cron-friendly
script as the fallback form). To run it by hand during an incident or a drill:

```bash
sudo -u postgres /opt/dept-anatomy/infra/cron/vacuumlo.sh
# or, raw:
sudo -u postgres vacuumlo -v codecoder
```

It is idempotent and empty-cost when there are no orphans — safe to run any
number of times. Output is logged to `/var/log/dept-anatomy/vacuumlo.log`. The
`quiz_sessions` expiry sweep can share the same nightly maintenance window.

---

## 6 · Known accepted risks

- **Frozen monolith CDN tags.** The frozen course HTML under `content/frozen/`
  keeps its original un-pinned CDN `<script>` tags (mermaid) as accepted
  historical risk — that file is bit-frozen for parity and is not edited in v2.
  The **live** frontend (`frontend/`) is hardened instead: mermaid is pinned to
  an exact version with a Subresource Integrity (SRI) hash and
  `crossorigin="anonymous"`, and the Ajv ES-module imports are version-pinned
  (SRI cannot attach to a dynamic `import()`; the CSP `script-src` allow-list is
  the supply-chain gate there). See `07-security-baseline.md` §3.3 and
  `frontend/shared/render/diagram.js` / `frontend/modules/feed/validate.js` for
  the in-code notes and the hash-recompute commands.

- **No Redis at launch.** As above (§4), the in-process cache is the v2 default;
  Redis is an opt-in scale lever, not a dependency.
