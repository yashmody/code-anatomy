# cms/ — Directus editorial plane (Phase 4a)

Directus is the **content + config WRITE plane** for DEPT Anatomy of Code (it
manages media *metadata* only — media bytes are Postgres large objects served by
FastAPI; see "Media storage" below). It stands up *additively* over the
**existing** `codecoder` Postgres by introspecting the tables already there. It
does **not** move content or decompose `course_chapters` — that is a later,
separately gated slice. There is **no** media migration: media stays in Postgres
large objects, permanently.

The runtime read path is unchanged: the SPA and quiz read content through
**FastAPI `/api/*`** (cache-backed), never through Directus. Directus only
*writes*; on every write it fires a loopback webhook so FastAPI invalidates the
affected cache key.

- Owner design doc: `docs/architecture/v2/05-config-cms.md` (collection map §3,
  RBAC, webhook §7.3) and §8.2 (the Phase 4a checklist).
- DB role: `directus_app`, created by Alembic migration `0008` (Slice 4a-1).
  It can DDL only `directus_*` tables and DML only the content tables; it
  **cannot** see `attempts`, `quiz_sessions`, `signing_keys`, or `auth_audit`
  (enforced at the Postgres GRANT level — Directus introspection literally
  cannot read those tables).

Pinned Directus version: **11.17.4** (npm `directus` + image
`directus/directus:11.17.4`). Engine requirement: Node >= 22 (LTS).

---

## File map

```
cms/
├── package.json              # pins directus 11.17.4; npm scripts
├── docker-compose.yml        # PROD deploy shape (documented default)
├── .env.example              # committed template — every var documented
├── .env                      # LOCAL ONLY, gitignored — real local values
├── bootstrap.sh              # idempotent operator script (source of truth)
├── register-collections.mjs  # the API work bootstrap.sh drives
├── snapshot.yaml             # captured data-model snapshot (reproducible)
└── README.md                 # this file
```

`node_modules/`, `.env`, `uploads/`, `database/` are gitignored.

---

## What is the source of truth?

Two as-code artifacts, in this order of authority:

1. **`bootstrap.sh` + `register-collections.mjs`** — authoritative for the
   parts a schema snapshot *cannot* capture: collections bound over **existing**
   (introspected) tables, the staff **roles**, the **policies + permissions**
   (Directus 11 RBAC), and the cache-invalidation **Flow**.
2. **`snapshot.yaml`** — the captured data-model (collection + field metadata).
   `directus schema apply ./snapshot.yaml` reproduces the field interfaces on a
   fresh instance. **Run the registrar first**, then snapshot — a freshly
   introspected collection has no Directus metadata and would otherwise be
   absent from the snapshot.

---

## Stand up locally (npm)

Prerequisites: Node 22 LTS (see "Node version" below), the `codecoder`
Postgres running on `localhost:5432`, Alembic at head `0008`.

```bash
cd cms
cp .env.example .env          # then fill KEY/SECRET/ADMIN_* — local dev values
npm install                   # installs pinned directus 11.17.4
bash bootstrap.sh             # bootstrap + register collections/roles/perms/flow
npm start                     # serve on http://localhost:8055
# health:
curl http://localhost:8055/server/health      # -> {"status":"ok"}
```

`bootstrap.sh` is idempotent — re-running it is a no-op (every create is
existence-guarded; field/flow metadata is reconciled).

After the first run it prints the four staff role ids. Paste the
`content_author` id into `AUTH_GOOGLE_DEFAULT_ROLE_ID` in `.env` (so new SSO
staff land in the least-privileged role).

### Local DB auth

Local Postgres `pg_hba.conf` uses `trust` for `127.0.0.1`/`::1`, so
`directus_app`'s password is **ignored** locally — any `DB_PASSWORD` value
works. As a one-off (so the same `.env` shape works on a password-auth VM) we
set a dev password:

```bash
psql postgresql://localhost/codecoder \
  -c "ALTER ROLE directus_app LOGIN PASSWORD 'directus_local_dev';"
```

On the VM, `directus_app` gets a real scoped password and `pg_hba` requires
`scram-sha-256`/`md5`.

### Node version

Directus 11 targets Node LTS (>= 22). One transitive dependency,
`isolated-vm` (the Flow "Run Script" sandbox), is a native addon that **does
not compile against Node 25's V8 headers**, and `node-gyp` additionally needs a
Python with `distutils`/`setuptools` (removed from the Python 3.12+ stdlib).

If you are on Node 25 and `npm install` fails on `isolated-vm`:

```bash
# Use a Node 22 LTS toolchain for the install/build:
#   - nvm:    nvm install 22 && nvm use 22
#   - brew:   brew install node@22   (keg-only; reference its bin directly)
# Provide distutils to node-gyp via a throwaway venv with setuptools:
python3 -m venv /tmp/gypvenv && /tmp/gypvenv/bin/pip install setuptools
export npm_config_python=/tmp/gypvenv/bin/python
# then, with Node 22 on PATH:
npm install
```

Our cache-invalidation Flow uses a **Webhook (Request URL)** operation, not
"Run Script", so `isolated-vm` is never exercised at runtime — but Directus
eagerly `require`s it at boot, so it must be present and compiled. On the
official Docker image (`directus/directus:11.17.4`) this is already compiled
against the image's Node, so the Docker path has none of this friction.

---

## Stand up on the VM

Two supported shapes — pick **one** (mutually exclusive):

### (A) docker-compose — documented PROD default

```bash
cd cms
cp .env.example .env          # fill in real secrets (KEY/SECRET/ADMIN/AUTH/DB)
docker compose up -d
# one-time bootstrap of collections/roles/perms/flow against the live API:
bash bootstrap.sh             # (or run register-collections.mjs against PUBLIC_URL)
```

`docker-compose.yml` reaches the host's Postgres via `host.docker.internal`
(mapped to the gateway on Linux via `extra_hosts`). It pins
`directus/directus:11.17.4` to match `package.json`.

### (B) systemd + npm — the alternative

A `directus.service` unit (owned by infra slice 4a-3) that runs
`directus start` under the `cca` user, mirroring how `deploy.sh` already runs
uvicorn. Same `.env`, same DB role, same bootstrap order.

Either way, **Apache** (4a-3) reverse-proxies Directus under `/cms` (subpath)
or `cms.<domain>` (subdomain), with WS-upgrade headers, and a
`Require ip 127.0.0.1` on `/api/cms/webhook` so only the co-resident Directus
can reach the FastAPI webhook receiver.

---

## Google SSO (staff) — console setup

Staff sign in to Directus with Google, restricted to `deptagency.com`. This is
a **separate** OAuth client from the FastAPI learner one.

1. Google Cloud Console -> Credentials -> Create OAuth client (Web).
2. Authorised redirect URI = `<PUBLIC_URL>/auth/login/google/callback`:
   - local: `http://localhost:8055/auth/login/google/callback`
   - prod subpath: `https://<domain>/cms/auth/login/google/callback`
   - prod subdomain: `https://cms.<domain>/auth/login/google/callback`
3. Put the client id/secret into `.env`
   (`AUTH_GOOGLE_CLIENT_ID` / `AUTH_GOOGLE_CLIENT_SECRET`), set
   `AUTH_PROVIDERS=google`, and set `AUTH_GOOGLE_DEFAULT_ROLE_ID` to the
   `content_author` role id printed by `bootstrap.sh`.
4. `AUTH_GOOGLE_ALLOW_LIST=deptagency.com` restricts which Google accounts may
   register/sign in; `AUTH_GOOGLE_ALLOW_PUBLIC_REGISTRATION=true` lets allowed
   accounts self-provision into the default role.

Keep one **break-glass local admin** (`ADMIN_EMAIL`/`ADMIN_PASSWORD`) as a
fallback if SSO breaks.

---

## Media storage — Postgres large objects, permanently (no S3, no disk)

**FINAL DECISION (2026-06-06): all app media lives in Postgres large objects and
is streamed from there. There is no S3, no object store, and no filesystem media
store.** Postgres is the only database and the only place media bytes live.

- App media bytes: `media_assets.large_object_oid` + `pg_largeobject`.
- Upload: FastAPI `POST /api/media/upload` (validates, ingests into a large object).
- Serve/stream: FastAPI `GET /media/{video,image}/{asset_id}` with HTTP Range (206).
- **Directus does NOT store app media.** `media_assets` is bound read-only
  metadata so editors can reference assets by id. Directus Files is used only for
  incidental Directus-internal assets (e.g. avatars) on the tiny local
  `cms/uploads` dir; **app-media uploads into Directus Files must be disabled by
  permission** so nothing app-facing lands on disk. Do not configure S3.

This is Phase 0 decision C, kept. There is no media migration — the earlier
"move media to a storage adapter / S3" idea is cancelled.

---

## Cache-invalidation webhook (the seam)

A Directus **Flow** ("cache-invalidation", action trigger) fires on
`items.create` / `items.update` / `items.delete` for `course_chapters`,
`frameworks`, `questions`, `feed_items`, and `app_config`. Its single
operation POSTs to the FastAPI loopback receiver:

```
POST http://127.0.0.1:8000/api/cms/webhook
{ "collection": "{{$trigger.collection}}", "keys": "{{$trigger.keys}}" }
```

This is exactly the shape `backend/app/modules/cms/routes.py` accepts
("Directus standard" — `collection` + `keys` array). The receiver maps it to
`cache.invalidate("app_config:<key>")` (config) or `cache.invalidate(
"<collection>:<id>")` (content). No HMAC, no secret — **loopback reachability
is the authentication** (§7.3): uvicorn binds `127.0.0.1`, Apache denies the
location from non-loopback, and the handler rejects non-loopback clients.

### Important: SSRF guard must allow loopback

Directus's request-operation egress guard defaults to
`IMPORT_IP_DENY_LIST=0.0.0.0,169.254.169.254`. The `0.0.0.0` entry expands via
`addLocalNetworkInterfaces()` and **blocks 127.0.0.1**, silently dropping the
webhook. We set `IMPORT_IP_DENY_LIST=169.254.169.254` (keep the cloud-metadata
block, drop `0.0.0.0`) so the loopback POST to the co-resident FastAPI is
allowed. This is required for the seam to work.

---

## Staff-role mirror (Phase 4c — the second loopback seam)

`extensions/directus-extension-roles-sync` is a **hook** that keeps FastAPI's
capability roles in step with the Directus Users UI. On any
`users.create`/`update`/`delete` it re-reads the user's current Directus role
name + status and POSTs `{ email, role }` to the FastAPI loopback receiver:

```
POST http://127.0.0.1:8000/api/cms/roles-sync     # FASTAPI_ROLES_SYNC_URL
{ "email": "person@deptagency.com", "role": "content_author" | null }
```

FastAPI's `core.users.sync_staff_roles` then reconciles `user_roles` — an
**authoritative, staff-roles-only** sync of the four staff keys
(`content_author`, `quiz_admin`, `feed_moderator`, `platform_admin`); it never
touches `learner` or `feed_contributor` (learner-plane, granted via the FastAPI
`/api/admin/roles` API). This closes the cross-plane coupling: **assigning a
staff role in the Directus UI is enough** — no separate FastAPI grant step. See
`docs/architecture/v2/04-authz-model.md §7.2`.

Unlike the cache-invalidation Flow, the hook uses Node's native `fetch`, so the
`IMPORT_IP_DENY_LIST` SSRF guard does **not** apply — loopback works regardless.
Loopback reachability is the authentication (Apache `Require ip 127.0.0.1` on
`/api/cms/roles-sync`; the app also rejects non-loopback). The hook ships a
committed `dist/` like the media-upload module; build it under node@22.

## Deferred (NOT in Phase 4a)

- **Media off large objects — CANCELLED.** Media stays in Postgres large objects
  permanently, streamed by FastAPI. No S3, no object store, no filesystem media
  store. (Phase 0 decision C, kept.)
- **Course relational decomposition.** `course_chapters.content` stays a single
  JSONB column; no decomposition into related collections in 4a.
- **`user_roles` grant UI.** Composite PK → Directus ignores it; grants are
  issued via the FastAPI admin endpoint (05 §3.7). Read-only by design.
- **Webhook *sender* extensions / live authoring acceptance** — Phase 4c.
