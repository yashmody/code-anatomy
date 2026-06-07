# DEPT® Anatomy of Code — Operator Runbook

This runbook covers the day-two operations an on-call engineer needs for the
v2 deployment: database backup and restore, reading the slow-query log, rotating
a certificate signing key, switching the cache backend, and the large-object
cleanup cron. The topology from `deploy.sh` is one Azure VM running Apache, the
FastAPI app under systemd (`cca-quiz`), and Directus (`cms-directus`) — and a
**remote shared PostgreSQL instance** the app VM connects out to over TLS. That
single instance hosts the prod database (`codecoder`) and the dev database
(`codecoder_dev`) side by side, isolated by separate login roles per environment
(see §8). The database no longer lives on the app VM.

Paths below use the RHEL layout (`/var/lib/pgsql/...`, `/etc/httpd/...`) that
`deploy.sh` targets; the Debian equivalents are noted where they differ. The
production application database is `codecoder` (dev: `codecoder_dev`); the remote
host is referred to as `REMOTE_DB_HOST`.

> **Convention.** Because Postgres is remote, the old `sudo -u postgres` peer-auth
> path on the app VM no longer reaches it. Commands run against a connection
> string instead: a **privileged** credential (the migration / superuser role the
> DBA issues) for DDL, role, and restore work, and the **runtime** role
> (`app_prod` / `app_dev`, DML-only) for the app itself. Always include
> `sslmode=require` in the URL so the connection is encrypted; with a provisioned
> CA, `verify-full` plus `sslrootcert=` is preferred. The examples below use a
> placeholder `PSQL`/`PGURL` you set once:
>
> ```bash
> export PGURL="postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require"
> # privileged work uses a DDL/superuser credential instead of app_prod:
> export PGURL_ADMIN="postgresql://migrator:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require"
> ```

---

## 1 · PostgreSQL backup and restore drill

### 1.1 Nightly backup

The backup is a custom-format `pg_dump` of the **remote** database, taken over
TLS, that includes large objects (the media bytes live in `pg_largeobject`, so
`--large-objects` is mandatory — a plain dump silently drops them). It runs from
the app VM (or any host that can reach the instance), pointed at the remote
`codecoder` with `sslmode=require`:

```bash
pg_dump \
    --format=custom \
    --large-objects \
    --dbname="$PGURL" \
    --file=/var/backups/cca-$(date +%F).dump
# $PGURL = postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require
```

On the shared instance, run the backup **per database**: the prod schedule dumps
`codecoder`, the dev schedule dumps `codecoder_dev` (point `--dbname` at the dev
URL). Never one job for both — that would couple the two environments' backup
windows and retention.

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

Restore into a **scratch** database **on the remote instance** — never over
`codecoder` — and use the cert canary as the acceptance check. Creating a
database and restoring need a privileged credential (the DBA or the remote
superuser), not the DML-only runtime role. The drill passes only when the
already-issued real certificate still verifies against the restored data.

```bash
# 1. Create an empty scratch database on the remote instance.
createdb -h REMOTE_DB_HOST -U postgres codecoder_restore_drill   # or CREATE DATABASE

# 2. Restore the most recent dump into it, over TLS (custom format -> pg_restore).
pg_restore \
    --dbname="postgresql://postgres:****@REMOTE_DB_HOST:5432/codecoder_restore_drill?sslmode=require" \
    --no-owner \
    /var/backups/cca-$(date +%F).dump

# 3. Sanity-check the row counts roughly match production.
psql "postgresql://postgres:****@REMOTE_DB_HOST:5432/codecoder_restore_drill?sslmode=require" \
    -c "SELECT count(*) AS attempts FROM attempts;" \
    -c "SELECT count(*) AS signing_keys FROM signing_keys;" \
    -c "SELECT count(*) AS media FROM media_assets;"
```

**Acceptance check — the cert canary.** The load-bearing certificate
`CCA-F-20260605-E79E74AB` must still verify against the restored database. Point
the verifier at the scratch DB and confirm `verify_signature` returns `True`:

```bash
cd /opt/dept-anatomy/backend   # the deployed backend
DATABASE_URL="postgresql://postgres:****@REMOTE_DB_HOST:5432/codecoder_restore_drill?sslmode=require" \
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
var (the key material lives in the env, not the dump). Drop the scratch DB on the
remote instance once the drill passes:

```bash
dropdb -h REMOTE_DB_HOST -U postgres codecoder_restore_drill
```

A real disaster restore is the same steps against a fresh `codecoder` on the
remote instance: stop `cca-quiz` first, create the database (`createdb -h
REMOTE_DB_HOST -U postgres codecoder` or have the DBA do it), `pg_restore` over
TLS, then restart the service — with the same canary check as the go/no-go gate
before taking traffic. The app VM never holds the data; it only points its
`DATABASE_URL` at the restored remote database.

---

## 2 · Reading the slow-query log

`log_min_duration_statement = 500ms` makes PostgreSQL log every statement that
takes half a second or longer, with its duration. This is the first place to look
after a deploy when latency rises. On the **remote** instance this setting is
owned by the DBA / managed-service parameter group, not by
`infra/postgres/cca-tuning.conf` on the app VM (that file applied when Postgres
was co-resident; on a managed instance the equivalent parameters are set on the
instance itself). Confirm it is on before relying on it:

```bash
psql "$PGURL" -c "SHOW log_min_duration_statement;"   # expect 500ms (or lower)
```

The slow-query log lives **on the DB host or the managed-service log stream**,
not on the app VM. Where you have shell access to a self-managed DB host the
files are still:

- **RHEL:** `/var/lib/pgsql/<ver>/data/log/postgresql-*.log`
- **Debian:** `/var/log/postgresql/postgresql-<ver>-main.log`

For a managed instance, pull the slow lines from the provider's log export
(Azure Database for PostgreSQL → Logs / Log Analytics) instead. Where you do have
the file, tail it live or pull the slow lines out of a rotated file:

```bash
# Live, slow statements only:
sudo tail -f /var/lib/pgsql/*/data/log/postgresql-*.log | grep -E 'duration: [0-9]{4,}'

# The ten slowest statements in the current log, longest first:
sudo grep -hoE 'duration: [0-9.]+ ms[^,]*statement: .*' \
    /var/lib/pgsql/*/data/log/postgresql-*.log \
  | sort -t' ' -k2 -n -r | head
```

A `duration: NNNN ms` line names the exact statement. To understand *why* it is
slow, run it under `EXPLAIN (ANALYZE, BUFFERS)` against the remote DB
(`psql "$PGURL_ADMIN" -c "EXPLAIN (ANALYZE, BUFFERS) <stmt>"`) and check for
sequential scans on indexed columns or unexpected row estimates. The hot-query
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
-- Run against the remote DB with a privileged credential
-- (psql "$PGURL_ADMIN"), in ONE transaction. Target the right database per
-- environment: codecoder for prod, codecoder_dev for dev — the signing_keys
-- rows are per-database, so a prod rotation never touches dev and vice versa.
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
   over the **remote** `codecoder` to unlink any large object not referenced
   anywhere. This catches orphans from **failed uploads**, where the LO is
   created and committed before the metadata row is inserted — if that insert
   fails, only a sweep can reclaim the bytes.

`deploy.sh` installs the sweep as a nightly systemd timer on the app VM (with the
cron-friendly script as the fallback form); the timer connects out to the remote
database over TLS, using the runtime app role's connection string (`vacuumlo`
only needs to own / be able to unlink the orphaned objects). Run the sweep **per
database** — a prod timer against `codecoder`, a dev timer against
`codecoder_dev`. To run it by hand during an incident or a drill:

```bash
vacuumlo -v "$PGURL"
# $PGURL = postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require
```

It is idempotent and empty-cost when there are no orphans — safe to run any
number of times. Output is logged to `/var/log/dept-anatomy/vacuumlo.log` on the
app VM. The `quiz_sessions` expiry sweep can share the same nightly maintenance
window.

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

---

## 7 · Directus CMS (editorial write plane)

Directus is the **content + config write plane** (media *metadata* only) — a
separate Node service that runs **on the app VM** alongside FastAPI and connects
out to the *same* remote `codecoder` Postgres the FastAPI app uses (over TLS, as
the env's scoped role), and is reverse-proxied under `/cms/` on the existing
HTTPS vhost. The FastAPI↔Directus loopback webhook is unaffected — both services
are still co-resident on the app VM; only the database is remote. It is
the editorial console only: the SPA and quiz still read all content through
FastAPI `/api/*` (cache-backed), **never** through Directus. This section is the
day-two runbook for it. The design contract is `05-config-cms.md` (§5.5
coexistence, §8.2 4a checklist); the as-code lives in `cms/`.

> **Phase 4a is additive and reversible.** Directus introspects the existing
> tables — it does not move content and does not decompose `course_chapters`
> (a later *gated* slice). **Media is final: all media lives in Postgres large
> objects and is streamed by FastAPI `/media/*` — no S3, no object store, no
> filesystem media store, ever. Directus never stores app media.** To run a box
> with no CMS at all, set `DEPLOY_DIRECTUS=false`
> in `deploy.env`; nothing else changes.

### 7.1 Stand-up — systemd + npm (default) vs Docker Compose

`deploy.sh` runs Directus as a **systemd Node service** (`cms-directus.service`)
to match the one operational shape the box already uses for `cca-quiz` (one
hardened unit, one `journalctl` stream). The unit is written automatically when
`DEPLOY_DIRECTUS=true` (the default):

- **Type:** `exec`, **User/Group:** `directus`, **WorkingDirectory:**
  `${APP_HOME}/cms`, **EnvironmentFile:** `${APP_HOME}/cms/.env`,
  **ExecStart:** `${APP_HOME}/cms/node_modules/.bin/directus start`,
  **Restart:** `on-failure`. It carries the **same** hardening keys as
  `cca-quiz` (`NoNewPrivileges`, `ProtectSystem=full`, `ProtectKernelTunables`,
  `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, …) and the **same**
  deliberate omission of `MemoryDenyWriteExecute` (the V8 JIT needs W^X off,
  same rationale as the Pillow/ffprobe carve-out, C-64). `ReadWritePaths` is
  scoped to `cms/uploads` (local storage) and `cms/.directus` (cache).

On a **fresh install** `deploy.sh` does, in order:

1. create the `directus` system user,
2. set the `directus_app` DB-role password (the role itself comes from Alembic
   0008 — see §7.4 bootstrap order),
3. seed `cms/.env` (KEY/SECRET/admin/DB/PUBLIC_URL/Google),
4. `npm ci --omit=dev` in `cms/`,
5. `npx directus bootstrap` (creates the `directus_*` tables + the admin),
6. `cms/bootstrap.sh` (roles, permissions, webhooks),
7. `npx directus schema apply ./snapshot.yaml` (the introspected collections),
8. write + enable + start the unit.

On `./deploy.sh --update` it **restarts** the service and **re-applies** the
schema snapshot + `bootstrap.sh` (both idempotent) — it does not re-bootstrap.

Manual control:

```bash
sudo systemctl status  cms-directus
sudo systemctl restart cms-directus
sudo journalctl -u cms-directus -f
```

**Docker Compose alternative.** `cms/docker-compose.yml` (slice 4a-2) runs the
official `directus/directus` image against the host Postgres
(`DB_HOST=host.docker.internal` or the host's bridge IP) with `cms/.env` as the
`env_file` and `cms/uploads` bind-mounted. Use it only if the box already runs
Docker; the Apache `/cms/` proxy and the `8055` port are identical, so nothing
downstream changes. Do **not** run both the systemd unit and the container at
once — they would contend for port 8055 and the same DB tables. On this VM the
Docker daemon is not the deployment path; systemd is canonical.

### 7.2 Node version constraint

Directus officially supports **Node 18 / 20 / 22 LTS**. `deploy.sh` detects the
Node major and **warns** (does not fail) on anything outside that set, because
the as-code install should still land. If `cms-directus` refuses to boot with a
Node-version error in the journal, pin an LTS:

```bash
# Option A — nodesource (system-wide):
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -   # Debian
#   then: sudo apt-get install -y nodejs

# Option B — nvm for the directus user, then point ExecStart at it:
#   sudo -u directus bash -lc 'nvm install 20'
#   override ExecStart in /etc/systemd/system/cms-directus.service.d/node.conf:
#     [Service]
#     ExecStart=
#     ExecStart=/home/directus/.nvm/versions/node/v20.x.x/bin/node \
#       /opt/dept-anatomy/cms/node_modules/.bin/directus start
```

(Local-dev note: the dev box currently has Node 25, which is newer than the
supported set. `start_local.sh --with-cms` will attempt to boot Directus anyway;
if it crash-loops, switch the local shell to a Node 20 LTS before retrying.)

### 7.3 Google SSO console setup + redirect URI

Staff sign in to Directus with Google SSO restricted to `deptagency.com`, using
a **separate OAuth client** from the FastAPI app's (one client per plane,
per `05 §4.1`). There is always one **break-glass local Directus admin**
(generated on first deploy, printed once in the deploy summary, stored in
`cms/.env`) so a misconfigured SSO can never lock everyone out.

In the Google Cloud Console (same project as the app is fine):

1. **APIs & Services → Credentials → Create OAuth client ID → Web application.**
2. **Authorised redirect URI** — this must match Directus's callback exactly:
   ```
   https://<DOMAIN>/cms/auth/login/google/callback
   ```
   (e.g. `https://internal.in.deptagency.com/cms/auth/login/google/callback`).
   The path routes through the Apache `/cms/` proxy to Directus on `:8055`;
   `PUBLIC_URL=https://<DOMAIN>/cms` in `cms/.env` is what makes Directus build
   that callback.
3. Put the client id/secret into the deploy via
   `AUTH_GOOGLE_CLIENT_ID` / `AUTH_GOOGLE_CLIENT_SECRET` (deploy.sh writes the
   `AUTH_GOOGLE_*` block into `cms/.env`). If you do not supply CMS-specific
   creds, deploy.sh falls back to the FastAPI `GOOGLE_CLIENT_ID/SECRET` — fine
   for a quick stand-up, but a dedicated client is the documented end state.
4. Restrict to the workspace domain (`deptagency.com`); first-login role mapping
   is governed by `bootstrap.sh` and the six roles in `04-authz-model.md`.

After changing any Google value, restart: `sudo systemctl restart cms-directus`.

### 7.4 Bootstrap order (get this right or the stand-up fails)

The dependency order is strict:

1. **Alembic `0008` first** — creates the scoped Directus DB role (DDL on
   `directus_*`, DML on the content tables only; no access to `attempts` /
   `quiz_sessions` / `signing_keys`). The role **name is per environment** via
   `DIRECTUS_DB_ROLE` — `directus_app` for prod, `directus_app_dev` for dev — so
   the dev Directus credential is GRANTed only on `codecoder_dev` and can never
   reach prod. `deploy.sh` only sets that role's password; it does **not** create
   the role. Run the migration against the **remote** DB with a privileged
   (DDL) credential — the runtime app role is DML-only:
   ```bash
   cd /opt/dept-anatomy/backend
   DATABASE_URL="$PGURL_ADMIN" DIRECTUS_DB_ROLE=directus_app \
     .venv/bin/alembic upgrade head
   ```
2. **`npx directus bootstrap`** — creates the `directus_*` system tables and the
   break-glass admin account from `ADMIN_EMAIL`/`ADMIN_PASSWORD` in `cms/.env`.
3. **`cms/bootstrap.sh`** — wires the six roles, the per-collection permissions
   (the C/R/U/D matrices in `05 §3`), and the loopback webhooks (each content
   table → `http://127.0.0.1:<FASTAPI_PORT>/api/cms/webhook`, no HMAC — network
   reachability is the auth, C-52).
4. **`npx directus schema apply ./snapshot.yaml`** — applies the introspected
   collection schema (interfaces, validations, field groups) over the existing
   tables. The snapshot is the source of truth for the editor UI; regenerate it
   after an intentional collection change with
   `npx directus schema snapshot ./snapshot.yaml`.

`deploy.sh` runs steps 2–4 for you; step 1 is part of the backend migration
chain. Re-running any of 2–4 is idempotent.

### 7.5 Media storage — Postgres large objects only (no S3, no disk)

**There is no storage-adapter flip. By owner decision (2026-06-06) all media
lives in Postgres large objects and is streamed from there — there is no S3, no
object store, and no filesystem media store, ever.** Postgres is the only
database and the only place media bytes live.

- Bytes: `media_assets.large_object_oid` + `pg_largeobject`.
- Upload: FastAPI `POST /api/media/upload` (validate + ingest into a large object).
- Stream: FastAPI `GET /media/{video,image}/{asset_id}` with HTTP Range (206).
- Cleanup: the `lo_unlink` `BEFORE DELETE` trigger + nightly `vacuumlo` (see §below).

Directus does **not** store app media. `media_assets` is bound read-only metadata
so editors can reference assets by id; **app-media uploads into Directus Files are
disabled by permission**, and `cms/uploads/` holds only incidental Directus-
internal files (e.g. avatars). Do not configure `STORAGE_S3_*`.

### 7.6 Backup — BOTH halves

A Directus backup is two artefacts, and a restore needs both:

1. **The `directus_*` tables** — these are *already inside* the `codecoder`
   `pg_dump` from §1.1 (Directus shares the database). No separate dump is
   needed; the nightly custom-format dump captures schema + content + Directus
   system tables in one file.
2. **The local upload store** — `cms/uploads/` is on the filesystem, **not** in
   Postgres, so the DB dump does not cover it. Back it up alongside:
   ```bash
   sudo tar -C /opt/dept-anatomy/cms -czf \
       /var/backups/cms-uploads-$(date +%F).tgz uploads
   ```
   If you have flipped to S3 (§7.5), the bucket *is* the durable store — enable
   bucket versioning / lifecycle there and you can drop the tar.

Restore order: restore the `codecoder` dump (§1.2) **then** untar `cms/uploads/`
(or rely on the S3 bucket). The cert canary in §1.2 is unaffected by Directus —
it reads `signing_keys` / `attempts`, which `directus_app` cannot touch.

### 7.7 `directus_app` password rotation

The Directus DB-role password lives in two places that must stay in sync: the
Postgres role on the **remote** instance and `cms/.env` on the app VM. Rotate in
this order (no app-plane downtime — the FastAPI app uses a different role).
Rotate **per environment**: `directus_app` on `codecoder` for prod,
`directus_app_dev` on `codecoder_dev` for dev — each rotation is independent and
touches only its own environment's role and `cms/.env`.

```bash
# 1. New password.
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')

# 2. Update the Postgres role on the REMOTE instance (privileged credential).
#    For dev, use directus_app_dev against the codecoder_dev URL.
psql "$PGURL_ADMIN" -c "ALTER ROLE directus_app WITH PASSWORD '$NEW';"

# 3. Write it into cms/.env (same key deploy.sh manages).
sudo sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$NEW|" /opt/dept-anatomy/cms/.env

# 4. Restart Directus to pick it up.
sudo systemctl restart cms-directus
```

Or simply re-run `sudo CMS_DB_PASS="$NEW" ./deploy.sh --update`, which does steps
2–4 (the `ALTER ROLE` is idempotent and `cms/.env` is rewritten with the new
connection block, including `DB_HOST=REMOTE_DB_HOST` and `DB_SSL=require`).
Confirm with `journalctl -u cms-directus -n 20` that Directus reconnected.

### 7.8 Deferred gated slices (NOT part of 4a)

Two pieces are intentionally **out of scope** here and gated behind their own
later slices:

- **Media off large objects.** Media bytes stay in Postgres `pg_largeobject`
  served by the FastAPI `/api/media/...` path. Moving them to object storage is
  a separate, gated migration — the storage-adapter flip in §7.5 affects only
  Directus-side uploads, not the runtime media pipeline.
- **`course_chapters` decomposition.** The chapter `sections` JSONB stays a
  single column that Directus edits via the JSON editor. Decomposing it into
  relational section/block tables is a later gated slice; do not attempt it as
  part of a 4a stand-up.

---

## 8 · The remote shared Postgres

The database is a **single remote PostgreSQL instance** (`REMOTE_DB_HOST:5432`)
that the app VM connects out to over TLS. The local Postgres that earlier v2
documents assumed on the app VM is gone — the instance was moved off-box because
co-resident Postgres ate too much disk. This section is the day-two reference for
the shared-instance layout, the per-env isolation, and the SSL handling.

### 8.1 What lives on the instance

One instance hosts every environment's database side by side, isolated by
separate databases **and** separate login roles:

| Environment | Database | FastAPI role (DML) | Directus role (scoped) | `DATABASE_URL` host |
|---|---|---|---|---|
| Production | `codecoder` | `app_prod` | `directus_app` | `REMOTE_DB_HOST` |
| Development | `codecoder_dev` | `app_dev` | `directus_app_dev` | `REMOTE_DB_HOST` |
| Staging (if live) | `codecoder_staging` | `app_staging` | `directus_app_staging` | `REMOTE_DB_HOST` |

The `pgcrypto` and `hstore` extensions exist in **each** database (the DBA
creates them; the runtime role cannot `CREATE EXTENSION` on a managed instance,
and the app's `init_db()` treats the missing-privilege case as non-fatal — see
the database section's "Postgres-only features" page in the docs site). Alembic
owns the schema; the runtime app role has DML only.

### 8.2 Why separate role *names*, not just separate databases

A PostgreSQL ROLE is **cluster-global**: it exists once for the whole instance,
not per database. A GRANT, by contrast, is per-database-object. So if a single
role name (say `directus_app`) were GRANTed on both `codecoder` and
`codecoder_dev`, that one credential would reach **both** databases — the
separate databases would not isolate it. The isolation comes from giving each
environment a *distinct role name*, each GRANTed only on its own database. That
is why the table above lists `app_dev` / `directus_app_dev` as names, not just
`codecoder_dev` as a database.

Verify the isolation after any role change:

```bash
# A dev role must NOT be able to connect to prod.
psql "$PGURL_ADMIN" -c \
  "SELECT has_database_privilege('app_dev','codecoder','CONNECT');"   # expect f
# The prod role connects to prod.
psql "$PGURL_ADMIN" -c \
  "SELECT has_database_privilege('app_prod','codecoder','CONNECT');"  # expect t
```

:::caution[Common Pitfall]
Reusing one set of credentials across environments "because it is the same
instance". The whole point of separate role names is that a leaked or
misconfigured dev credential cannot reach prod. Never put a prod-GRANTed role in
a dev `.env`, and never GRANT a dev role on the prod database.
:::

### 8.3 TLS and certificate handling

Every connection to the remote instance must be encrypted. The minimum is
`sslmode=require` in the connection URL (psycopg2 / SQLAlchemy honour
`?sslmode=` in the query, so the FastAPI `DATABASE_URL` and the Directus
`DB_SSL=require` both enforce it without extra code). Where a CA is provisioned,
prefer `verify-full`:

```ini
# backend/.env — minimum
DATABASE_URL=postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require

# backend/.env — with a provisioned CA (defends against active MITM, not just
# passive sniffing). The host must match the server certificate's subject.
DATABASE_URL=postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=verify-full&sslrootcert=/etc/dept-anatomy/db-ca.pem
```

Operational notes:

- Confirm SSL is actually in use, not silently downgraded:
  `psql "$PGURL" -c "\conninfo"` must report an `SSL connection` line.
- When the server certificate or CA rotates, update `sslrootcert=` on the app VM
  (and restart `cca-quiz` / `cms-directus`) **before** the old CA is retired on
  the instance, or `verify-full` connections will fail closed.
- The app VM's egress firewall / NSG must allow `REMOTE_DB_HOST:5432`. A new VM
  that cannot reach the instance fails the §1.0 connectivity test in the cutover
  plan before it ever serves traffic.

### 8.4 Password rotation, per environment

Each environment's passwords rotate independently. The runtime app role
(`app_prod` / `app_dev`) and the Directus role (`directus_app` /
`directus_app_dev`) are separate credentials with separate rotation cadences:

```bash
# Runtime app role (prod). Rotate on the remote, then update backend/.env.
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
psql "$PGURL_ADMIN" -c "ALTER ROLE app_prod WITH PASSWORD '$NEW';"
sudo sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://app_prod:$NEW@REMOTE_DB_HOST:5432/codecoder?sslmode=require|" \
  /opt/dept-anatomy/backend/.env
sudo systemctl restart cca-quiz
```

The Directus role rotation is §7.7. Rotate the dev roles against the
`codecoder_dev` URL with the `app_dev` / `directus_app_dev` names — never against
prod. Keep each environment's `.env` files (`backend/.env`, `cms/.env`) carrying
only that environment's connection string and password.

:::tip[Agency Tip]
Set `PGURL` / `PGURL_ADMIN` once at the top of an ops session (see the
Convention note in the intro) and every command in this runbook works against the
remote instance without retyping the host. For a dev-environment task, export the
`codecoder_dev` variants instead — the safest habit is to keep two terminals, one
exported for prod and one for dev, so a prod command can never land on dev by a
stray paste.
:::
