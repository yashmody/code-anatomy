# v2 — URL + Security Audit (remote-Postgres cutover)

> Scope note. This pass audits the externally- and internally-reachable URL
> surface of the v2 deployment, recaps the Phase 5b security verdict, and adds
> the security analysis for the 2026-06 change that moves the database to a
> **remote shared Postgres instance** (one server, a separate database per
> environment). It is a read-only audit over the codebase; the only file it
> writes is this one. Every claim cites the source file and line.

The companion fixes for the gaps called out here land in the same change set —
the deploy.sh remote-DB rewrite, the `init_db()` privilege softening in
`backend/app/core/db.py`, and the parameterised Directus role in
`backend/migrations/versions/0008_directus_app_role.py`. Where a finding is
addressed by one of those slices, the row says so. At the time of writing the
env templates and `config.py` validator have already landed (working tree);
the three code files above are still in their pre-cutover state and are tracked
as findings.

---

## 1 · URL / topology map

### Scan box

- The box is a single VM. **Apache** terminates TLS on 80/443 and is the only
  public listener; everything else binds to loopback. Two upstreams sit behind
  it — **uvicorn** (FastAPI) on `127.0.0.1:8000` and **Directus** on
  `127.0.0.1:8055`.
- Two static path prefixes are served by Apache directly off disk — `/app/`
  (the buildless SPA, `frontend/`) and `/anatomy/` (the frozen content
  monolith, `content/frozen/`). Everything else falls through to FastAPI.
- The route table has **one deliberate ordering rule**: `/cms/` must be
  proxied *before* the catch-all `ProxyPass /`, or the Directus admin would be
  shadowed by the FastAPI app. The vhost gets this right
  (`deploy.sh:1506`).
- After the cutover the topology gains **one remote hop**: uvicorn and Directus
  no longer reach Postgres over a local Unix socket but over **TLS to a remote
  shared instance**. The HTTP topology above is unchanged — only the DB leg
  moves off-box.
- Two OAuth redirect URIs exist on the same origin but **different subpaths**:
  learner sign-in at `/auth/google/callback` (FastAPI) and staff sign-in at
  `/cms/auth/login/google/callback` (Directus). They are distinct OAuth
  clients.

### 1.1 Public route table (what a browser can reach)

All public routes share the single HTTPS origin `https://${DOMAIN}` (default
`internal.in.deptagency.com`, `deploy.sh:47`). The vhost is generated in
`deploy.sh` STEP 9 (`deploy.sh:1210`–`1511`).

| Public path | Served by | Upstream / disk | Source |
|---|---|---|---|
| `/` (catch-all) | FastAPI | `http://127.0.0.1:8000/` | `deploy.sh:1506-1507` |
| `/app/` | Apache static | `${APP_HOME}/frontend` (Alias, `FallbackResource /app/index.html`) | `deploy.sh:1430-1436` |
| `/anatomy/` | Apache static | `${APP_HOME}/content/frozen` (index `anatomy-of-code-course.html`) | `deploy.sh:1423-1428` |
| `/static/` | FastAPI | mounted in-app (NO Apache alias by design, Q-13) | `deploy.sh:1438-1439`, `backend/app/main.py:140` |
| `/login`, `/login/dev` | FastAPI auth | uvicorn | `backend/app/modules/auth/routes.py:56,63` |
| `/auth/google`, `/auth/google/callback` | FastAPI auth | uvicorn (learner OAuth) | `backend/app/modules/auth/routes.py:99,124` |
| `/auth/session-key`, `/auth/me`, `/logout` | FastAPI auth | uvicorn | `backend/app/modules/auth/routes.py:43,207,174` |
| `/onboarding/role`, `/profile/role` | FastAPI quiz | uvicorn | `backend/app/modules/quiz/routes.py:92-137` |
| `/quiz/start`, `/quiz/submit`, `/quiz/take` | FastAPI quiz | uvicorn | `backend/app/modules/quiz/routes.py:144,184,280` |
| `/certificate/{cert_id}` | FastAPI quiz | uvicorn (private cache, `Vary: Cookie`) | `backend/app/modules/quiz/routes.py:298`, `deploy.sh:1482-1485` |
| `/history`, `/verify`, `/verify/{cert_id}` | FastAPI quiz | uvicorn | `backend/app/modules/quiz/routes.py:312,321,340` |
| `/admin/attempts` | FastAPI quiz (HTML) | uvicorn | `backend/app/modules/quiz/routes.py:347` |
| `/api/course/framework`, `/chapters`, `/chapters/{filename}`, `/framework-explainer` | FastAPI content | uvicorn (prefix `/api/course`) | `backend/app/main.py:154`, `content/routes.py:23-53` |
| `/api/feed`, `/api/feed/flag`, `/api/feed` (POST) | FastAPI feed | uvicorn (prefix `/api`) | `backend/app/main.py:155`, `feed/routes.py:31-66` |
| `/api/moderate/queue`, `/api/moderate/action` | FastAPI feed | uvicorn | `backend/app/modules/feed/routes.py:103,109` |
| `/media/video/{asset_id}`, `/media/image/{asset_id}` | FastAPI media | uvicorn (Range-stream from pg large objects) | `backend/app/modules/media/routes.py:87,124` |
| `/api/media/upload` | FastAPI media | uvicorn (bandwidth-throttled at Apache) | `media/routes.py:23`, `deploy.sh:1488-1491` |
| `/api/cms/webhook` | FastAPI cms | uvicorn — **loopback-only** (`Require ip 127.0.0.1 ::1`) | `cms/routes.py:40`, `deploy.sh:1497-1499` |
| `/api/admin/questions` | FastAPI quiz | uvicorn | `backend/app/modules/quiz/routes.py:352` |
| `/api/admin/roles` (GET/POST/DELETE) | FastAPI admin | uvicorn (prefix `/api/admin`) | `backend/app/main.py:160`, `admin/routes.py:49-95` |
| `/healthz`, `/readyz` | FastAPI health | uvicorn | `backend/app/main.py:79,89` |
| `/cms/` (+ `/cms/auth/login/google/callback`) | Directus | `http://127.0.0.1:8055/` — **only when `DEPLOY_DIRECTUS=true`** | `deploy.sh:1380-1382` |

Notes:

- `/csp/report` is referenced by the CSP `report-to` directive
  (`deploy.sh:1320`,`1351`) but **no route serves it** — see Finding U-2 / the
  Phase 5b item V2-F-02.
- The `MEDIA.explainer` front-end constant resolves to `/media/video/explainer`
  (`frontend/core/config.js:32-34`); the literal `explainer` is a server-side
  slug alias, not a UUID, and lands on the `/media/video/{asset_id}` route.

### 1.2 Internal / loopback targets (not browser-reachable)

| Internal target | Caller → callee | Source |
|---|---|---|
| `127.0.0.1:8000` (uvicorn) | Apache `ProxyPass /` → FastAPI | `deploy.sh:1506`, systemd `--host 127.0.0.1 --port 8000` `deploy.sh:881-882` |
| `127.0.0.1:8055` (Directus) | Apache `ProxyPass /cms/` → Directus | `deploy.sh:1381`, `cms/.env` `HOST=127.0.0.1 PORT=8055` `deploy.sh:1032-1033` |
| `http://127.0.0.1:8000/api/cms/webhook` | Directus → FastAPI (cache-invalidation loopback) | `cms/register-collections.mjs:54`, `cms/.env:54` |
| Postgres `:5432` | FastAPI (`DATABASE_URL`) + Directus (`DB_HOST/DB_PORT`) | pre-cutover: `localhost` `deploy.sh:646`; post-cutover: `REMOTE_DB_HOST` over TLS, `backend/.env.production.example:53-54` |

### 1.3 OAuth redirect URIs

| Flow | Redirect URI | Set where |
|---|---|---|
| Learner (FastAPI) | `https://${DOMAIN}/auth/google/callback` | `deploy.sh:653`; derived in `config.py:174-183` |
| Staff (Directus) | `https://${DOMAIN}/cms/auth/login/google/callback` | `deploy.sh:1075`; `PUBLIC_URL=https://${DOMAIN}/cms` `deploy.sh:1034` |

The two are distinct OAuth clients (`deploy.sh:1043-1047` reuses the FastAPI
client only if no dedicated CMS client is supplied). Both ride the same
single-origin vhost; isolation is by subpath, not host.

### 1.4 Front-end constants (`frontend/core/config.js`)

| Constant | Value | Line |
|---|---|---|
| `API_BASE` | `''` (same origin; `window.__API_BASE` override) | `frontend/core/config.js:14-15` |
| `QUIZ_URL` | `${location.origin}/` in http(s); `http://localhost:8000/` on `file://` only | `frontend/core/config.js:21-25` |
| `MEDIA.explainer` | `/media/video/explainer` | `frontend/core/config.js:32-34` |
| `ALLOWED_DOMAIN` | `deptagency.com` | `frontend/core/config.js:57` |
| `GOOGLE_CLIENT_ID` | `''` unless `window.__GOOGLE_CLIENT_ID` set | `frontend/core/config.js:62-63` |
| `DEV_MOCK` | `true` | `frontend/core/config.js:67` |

`API_BASE=''` and the origin-derived `QUIZ_URL` are correct for the
same-origin reverse-proxy topology — no stale host is baked in. The two
front-end items to watch are not URLs: `DEV_MOCK = true`
(`frontend/core/config.js:67`) and `ALLOWED_DOMAIN` as a hard literal — both
are noted as future Phase-2d DB-config reads in the file's own comments and are
out of scope for this cutover. They are flagged at LOW (Finding U-3) so they
are not lost.

### 1.5 ASCII topology

```
                              Internet
                                 │  TLS 1.2 / 1.3 (HSTS, CSP)
                                 ▼
                    ┌─────────────────────────────┐
                    │   Apache  :80 → :443        │   deploy.sh:1394
                    │   (only public listener)    │
                    └──────────────┬──────────────┘
        ┌──────────────────┬───────┴────────┬───────────────────────┐
        │ /app/            │ /anatomy/      │ /cms/   (if enabled)   │ everything else
        ▼ (Alias)          ▼ (Alias)        ▼ ProxyPass (BEFORE /)   ▼ ProxyPass /
  ┌───────────┐     ┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐
  │ frontend/ │     │content/frozen│   │ Directus         │   │ uvicorn          │
  │  (disk)   │     │   (disk)     │   │ 127.0.0.1:8055   │   │ 127.0.0.1:8000   │
  └───────────┘     └──────────────┘   └────────┬─────────┘   └─────────┬────────┘
                                                 │  loopback webhook      │
                                                 │  127.0.0.1:8000/api/   │
                                                 │      cms/webhook ───────┘
                                                 │  (Require ip 127.0.0.1)
                                                 ▼                        ▼
                                       ╔════════════════════════════════════════╗
                                       ║   REMOTE shared Postgres  :5432         ║
                                       ║   TLS required (sslmode=require / ─full)║
                                       ║   ┌──────────┐ ┌────────────────┐       ║
                                       ║   │ codecoder│ │ codecoder_dev  │  …    ║
                                       ║   │  (prod)  │ │ codecoder_stg  │       ║
                                       ║   └──────────┘ └────────────────┘       ║
                                       ║   roles: app_prod / app_dev / …         ║
                                       ║          directus_app / directus_app_dev║
                                       ╚════════════════════════════════════════╝
```

Pre-cutover the box on the right was a **local** Postgres over the
`/var/run/postgresql` Unix socket (`deploy.sh:235`,`646`); post-cutover it is a
remote instance reached over TCP+TLS, shared across environments by database.

### 1.6 URL ordering / shadowing check

- **`/cms/` vs catch-all `/`** — correct. `ProxyPass /cms/` is emitted from
  `CMS_PROXY_BLOCK` (`deploy.sh:1380-1383`) and interpolated *above*
  `ProxyPass /` (`deploy.sh:1506`). The comment at `deploy.sh:1357-1358`,`1380`
  states the ordering requirement explicitly. No shadowing.
- **`/app` and `/anatomy` vs `/`** — correct. Both carry `ProxyPass … !`
  exclusions (`deploy.sh:1504-1505`) so the Alias serves them off disk before
  the catch-all proxy sees them.
- **`/api/cms/webhook` `Require ip`** — the `<Location>` sits *after*
  `ProxyPass /` deliberately (`deploy.sh:1493-1499`); `mod_authz_core`'s
  `Require` is still evaluated for the proxied request, so the loopback
  restriction holds. This is defence-in-depth on top of the app's own
  non-loopback rejection.
- **No `host all all 0.0.0.0/0`** wildcard is generated anywhere in the vhost.
- One latent inconsistency: the `/api/cms/webhook` `Require ip 127.0.0.1 ::1`
  protects the public edge, but the webhook's *caller* (Directus) reaches
  FastAPI via the loopback URL directly, not through Apache — so the real guard
  is the app-side loopback check plus `--forwarded-allow-ips='*'` exposure
  (V2-F-07). Called out in §2.

---

## 2 · Security posture

### Scan box

- Phase 5b certified **0 CRITICAL, 0 HIGH** open. All four original CRITICALs
  are closed in code (`phase-5-report.md:162-168`). What remains is **6 MEDIUM,
  4 LOW, 3 INFO** — none forge a certificate or open a path to prod data.
- Two of those MEDIUMs are the documented **must-fix-before-cutover** pair:
  **V2-F-02** (`/csp/report` has no handler) and **V2-F-03** (`fastapi` /
  `uvicorn[standard]` unpinned). Both are still open in the working tree.
- The cutover adds one new security axis: **TLS-in-transit to the DB**. The old
  model leaned on `localhost` trust over a Unix socket; the new model sends DB
  traffic across the network and so **must** encrypt it. The app-side enforcement
  has landed (`config.py` `validate_db_tls`); the deploy.sh and migration slices
  are what make it real on the box.
- **Dev/prod isolation on one instance** is achieved by *separate databases +
  separate login roles per env* — a dev credential physically cannot reach the
  prod database. Roles are cluster-global in Postgres but GRANTs are per-DB, so
  distinct role *names* per env are the boundary.
- The webhook / loopback assumptions are **unchanged and still valid**: FastAPI
  and Directus remain co-resident on the VM; only the DB moves off-box.

### 2.1 Phase 5b verdict (recap)

The Phase 5b security sweep certified **CRITICAL 0 · HIGH 0 · MEDIUM 6 · LOW 4
· INFO 3** (`phase-5-report.md:168`). The four original CRITICAL findings are
closed in code (`phase-5-report.md:162-168`). The edge posture — TLS 1.2/1.3,
HSTS, CSP, the eight security headers split between Apache and the app's
`SecurityHeadersMiddleware`, and the dual-guarded loopback webhook — is sound
(`phase-5-report.md:181`, `deploy.sh:1405-1417`,`1493-1499`).

The MEDIUM/LOW list (`phase-5-report.md:192-201`):

| ID | Sev | Area | Summary |
|---|---|---|---|
| V2-F-01 | MED | CSP | Ships **Report-Only by default**; not enforced until `CSP_ENFORCE=1` after soak (`deploy.sh:1342-1348`). |
| **V2-F-02** | MED | CSP | `Report-To` points at `/csp/report` which **has no handler** — reports 404 and are lost. **Must-fix.** |
| **V2-F-03** | MED | supply-chain | `fastapi` and `uvicorn[standard]` **completely unpinned** in `requirements.txt:1-2`. **Must-fix.** |
| V2-F-04 | MED | supply-chain | No SRI on CDN scripts; mermaid pinned only to floating `@11`. |
| V2-F-05 | MED | audit | Moderator approve/flag/remove write no `auth_audit` row. |
| V2-F-06 | MED | upload/DoS | Bandwidth throttle but no per-user rate limit; MIME sniff is offset-0 only. |
| V2-F-07 | LOW | config | `--forwarded-allow-ips='*'` makes `request.client.host` attacker-controllable; only Apache's `Require ip` saves the webhook (`deploy.sh:885`,`1497-1499`). |
| V2-F-08 | LOW | upload | Large-object stream read-error path uses a bare `print`, yields a truncated body. |
| V2-F-09 | LOW | moderation | Auto-flag at `flag_count >= 1` — one user can flag-hide any post. |
| V2-F-10 | LOW | secrets | Dev `.env` templates carry literal dev markers (harmless; `validate_for_env` rejects them outside dev — `config.py:187-229`). |

The two must-fix items (V2-F-02, V2-F-03) remain open in the working tree:
there is no `/csp/report` route under `backend/app/`, and `requirements.txt:1-2`
still reads bare `fastapi` / `uvicorn[standard]`. They are release-gate tasks
for the cutover window (`phase-5-report.md:208-211`,`259-260`); fixing them is
out of this audit slice's file area but is recorded here so the gate is explicit.

### 2.2 New: remote-DB security analysis

**(a) TLS in transit — now mandatory, was localhost-trust.**
Before the cutover, FastAPI reached Postgres over a Unix socket
(`deploy.sh:235` injects `-h /var/run/postgresql`) and the connection string was
`postgresql://…@localhost:5432/…` (`deploy.sh:646`) — cleartext, but never on
the wire. A remote instance puts DB traffic on the network, so the connection
**must** be encrypted. psycopg2/SQLAlchemy honour `?sslmode=` in the URL query,
so TLS is achievable purely via the connection string — but nothing *required*
it until now. The app side now enforces it: `config.py` defines
`_TLS_SSLMODES = {require, verify-ca, verify-full}` (`config.py:40`),
`_db_is_remote()` (`config.py:62-74`), and a `validate_db_tls` model-validator
that **refuses to boot** when a remote `DATABASE_URL` lacks a TLS sslmode
outside development. `prefer` is deliberately *not* treated as TLS (it silently
downgrades). The templates carry the right shape:
`sslmode=require` minimum, `verify-full` with `sslrootcert` preferred for prod
(`backend/.env.production.example:53-54`, `backend/.env.development.example:62`,
`backend/.env.staging.example:52`). Directus must match: its `cms/.env`
template still shows `DB_HOST=localhost` and a commented `# DB_SSL=false`
(`cms/.env.example:17`,`28`) — the deploy.sh CMS block must point Directus at
`REMOTE_DB_HOST` with `DB_SSL=true` so the editorial plane is not the one
cleartext leg. **(Finding S-1.)**

**(b) Dev/prod isolation on one instance.**
The instance hosts `codecoder` (prod), `codecoder_dev`, and `codecoder_staging`
(`backend/.env.development.example:8-15`). Isolation is two-layer: a *separate
database per env* and a *separate login role per env* — `app_prod` /
`app_dev` / `app_staging` for FastAPI, and `directus_app` / `directus_app_dev`
/ `directus_app_stg` for Directus
(`backend/.env.production.example:11,57`, `.env.development.example:62,66`,
`.env.staging.example:11,55`). Each role is GRANTed only on its own database, so
a dev credential cannot read prod and vice-versa. This is the correct model:
Postgres ROLEs are cluster-global, but object GRANTs are per-database, so the
isolation comes from distinct role *names* each granted on exactly one DB. The
single largest risk in the old migration is precisely here — see (d).

**(c) Credential handling.**
DB credentials live in `backend/.env` and `cms/.env`, both gitignored
(`.gitignore:14`,`36`); templates carry placeholders only
(`DATABASE_URL=` empty in prod, `CHANGE_ME@REMOTE_DB_HOST` in dev). The deploy
step writes `.env` 0600 and chowns to the app user (`deploy.sh:690`,`1086`).
The cutover does not change this; it raises the stakes, because a leaked
`DATABASE_URL` now reaches a network-addressable host rather than a localhost
socket. The per-env role split (b) is the blast-radius limiter: a leaked
`app_dev` URL exposes only `codecoder_dev`.

**(d) `init_db()` privilege issue.**
`backend/app/core/db.py:47-53` runs, on **every** boot against any postgresql
URL, `CREATE EXTENSION IF NOT EXISTS hstore` / `pgcrypto` and then
`Base.metadata.create_all()`. On a managed/remote instance the runtime app role
(`app_prod`) is DML-only — it will not hold superuser or DDL/`CREATE EXTENSION`
privilege — so these statements **error and crash the boot**. The DBA
pre-creates the extensions; Alembic owns the schema. This must become
non-fatal: the extension/DDL block should be guarded so a privilege error is
logged and swallowed rather than fatal. **This is still unfixed in the working
tree** (`db.py:47-53` runs unconditionally) and is the `db.py` slice's job.
**(Finding S-2.)**

**(e) Migration 0008 hardcoded role → isolation leak.**
`0008_directus_app_role.py` hardcodes the literal `directus_app` in the
`CREATE ROLE`, every `GRANT`, and the `REVOKE`
(`0008_directus_app_role.py:51-52`,`68`,`75`,`82`,`88`,`93`,`97`,`102`,`107`,`118`).
A Postgres ROLE is cluster-global. If Alembic runs `0008` against *both* the
dev DB and the prod DB, the **same** `directus_app` role is granted on both —
one Directus credential then reaches both databases, collapsing the dev/prod
boundary. The role name must be parameterised (the env templates already carry
`DIRECTUS_DB_ROLE=directus_app` / `directus_app_dev` / `directus_app_stg` —
`.env.production.example:57`, `.env.development.example:66`,
`.env.staging.example:55`) so dev grants `directus_app_dev` on `codecoder_dev`
only. **Still unfixed in the working tree.** **(Finding S-3.)**

**(f) pg_hba on the remote (DBA-owned).**
The old deploy.sh edited the local `pg_hba.conf` to add `md5` host rules and
toggled `listen_addresses` (`deploy.sh:736-748`,`797-811`). None of that is
possible — or appropriate — against a managed remote instance: the app box does
not own the DB host's filesystem. pg_hba on the remote becomes a **DBA
responsibility**: it must allow the per-env roles from the app VM's egress IP,
require TLS (`hostssl`), and must **not** carry a `0.0.0.0/0` / `::/0` wildcard.
The Phase 5b assertion to verify-no-wildcard
(`07-security-baseline.md:197`) still applies, but on the remote, by the DBA.

**(g) Firewall / egress to the remote DB port.**
The deploy firewall step opens inbound 80/443 only (`deploy.sh:1543-1562`) —
correct and unchanged. The new requirement is **outbound**: the app VM must be
able to reach `REMOTE_DB_HOST:5432`. On Azure that is an NSG outbound rule /
private-endpoint reachability, not something deploy.sh manages
(`deploy.sh:1561` already flags the NSG to the operator for inbound). The remote
DB should accept 5432 **only** from the app VM's address, not the world.

**(h) Webhook / loopback assumptions still hold.**
FastAPI and Directus remain co-resident on the VM and talk over loopback
(`cms/.env:54-59` documents the co-residency by design; the webhook target is
`http://127.0.0.1:8000/api/cms/webhook`). Only the DB leg moves remote, so the
`Require ip 127.0.0.1 ::1` guard (`deploy.sh:1497-1499`) and the app-side
loopback check are unaffected. No change needed here.

---

## 3 · Remote-DB readiness checklist

What the **DBA** provisions on the remote instance, by hand, *before* cutover:

1. **Databases** — `codecoder` (prod), `codecoder_dev`, `codecoder_staging`
   (`.env.development.example:8-15`).
2. **Extensions** per database — `pgcrypto` and `hstore` in *each* DB
   (the app no longer creates them; see S-2). Requires superuser.
3. **Login roles, per env** — `app_prod`/`app_dev`/`app_staging` (FastAPI,
   DML-only) and `directus_app`/`directus_app_dev`/`directus_app_stg`
   (Directus). Each granted **only** on its own database.
4. **TLS** — server certificate in place; instance configured to accept (or
   require) TLS. Provision a CA bundle so prod can use `verify-full`
   (`.env.production.example:53`).
5. **pg_hba** — `hostssl` rules allowing each env role from the app VM's
   egress IP; **no** `0.0.0.0/0` / `::/0` wildcard (S-f).
6. **Firewall** — DB instance accepts 5432 from the app VM only; app VM allowed
   outbound to `REMOTE_DB_HOST:5432` (S-g).

What **deploy.sh** automates after the cutover rewrite:

- Writes the per-env `DATABASE_URL` (with `?sslmode=…`) into `backend/.env`
  and the matching `DB_HOST=REMOTE_DB_HOST` / `DB_SSL=true` into `cms/.env`,
  from operator-supplied values — replacing the hardcoded `localhost:5432`
  string (`deploy.sh:646`,`775`).
- Runs `alembic upgrade head` with a privileged migration credential, which
  owns the schema and the parameterised Directus role GRANTs (per `DIRECTUS_DB_ROLE`).
- **Optionally** pre-creates databases/extensions/roles *only* when a remote
  superuser password is supplied — otherwise it assumes the DBA did steps 1–3.

What deploy.sh **must stop doing** (was local-only, breaks against remote):

- Provisioning a local Postgres via the `/var/run/postgresql` socket as
  superuser (`deploy.sh:229-247`).
- Editing `pg_hba.conf` and `listen_addresses`
  (`deploy.sh:736-748`,`791-811`) — the remote host's files are DBA-owned.

**Backward-compat preserved:** the local path (sqlite smoke / `DB_MODE=local`)
must keep working unchanged. The offline smoke harness forces sqlite and never
touches the network (`.env.development.example:69-72`); it must stay 15/15.
With no new env vars set, default behaviour must equal today's.

---

## 4 · Prioritised findings

### URL findings

| ID | Sev | Finding | Fix / status |
|---|---|---|---|
| U-1 | MED | `/csp/report` is referenced by `report-to` (`deploy.sh:1320,1351`) but no FastAPI route serves it — CSP reports 404. (= V2-F-02.) | Add a `/csp/report` 204 handler or drop the directive. Release-gate task; not in this audit's file area. |
| U-2 | LOW | `/cms/` ordering vs catch-all `/` is correct **today** but is the one place a careless vhost edit would shadow Directus. | No fix; documented (`deploy.sh:1357-1358,1506`). Keep the ordering invariant in review. |
| U-3 | LOW | Front-end `DEV_MOCK=true` (`frontend/core/config.js:67`) and literal `ALLOWED_DOMAIN` ship in source; both are flagged in-file as future Phase-2d DB reads. | Out of cutover scope; recorded so it is not lost. `DEV_MOCK` must be off in any prod build. |

### Security findings (remote-DB)

| ID | Sev | Finding | Addressed in this change set |
|---|---|---|---|
| S-1 | HIGH (new) | No TLS enforcement on the DB leg once it is remote; Directus `cms/.env` still defaults `DB_HOST=localhost` / `DB_SSL=false` (`cms/.env.example:17,28`). | App side **done** — `config.py` `validate_db_tls` (`config.py:40,62-74` + validator). deploy.sh CMS slice must set `REMOTE_DB_HOST` + `DB_SSL=true`. Templates updated. |
| S-2 | HIGH (new) | `init_db()` runs `CREATE EXTENSION` + `create_all()` on every boot (`db.py:47-53`); the DML-only remote app role cannot, so boot crashes. | **Open** — the `backend/app/core/db.py` slice makes the DDL block non-fatal (DBA pre-creates extensions; Alembic owns schema). |
| S-3 | HIGH (new) | Migration `0008` hardcodes `directus_app` (`0008_directus_app_role.py:51-118`); granting it on both dev and prod DBs collapses isolation. | **Open** — the migration slice parameterises the role from `DIRECTUS_DB_ROLE` (templates already set `directus_app` / `_dev` / `_stg`). |
| S-4 | MED | deploy.sh hardcodes `postgresql://…@localhost:5432/…` and provisions a local Postgres (`deploy.sh:646,229-247,736-811`) — none of it works against a remote instance. | **Open** — the deploy.sh slice rewrites the DB section for remote + TLS, keeping the `DB_MODE=local` path. |
| S-5 | MED | V2-F-03 — `fastapi` / `uvicorn[standard]` unpinned (`requirements.txt:1-2`). | Release-gate task (not this slice's file area); recorded so the cutover gate is explicit. |
| S-6 | LOW | V2-F-07 — `--forwarded-allow-ips='*'` (`deploy.sh:885`) trusts any proxy header; the loopback webhook leans on Apache `Require ip` (`deploy.sh:1497-1499`). Unchanged by the cutover but worth narrowing. | Deferred hardening per `phase-5-report.md:278`. |

**Net:** URL surface is consistent and correctly ordered; the one real URL gap
(U-1 / V2-F-02) is a known release-gate item. The new remote-DB axis introduces
three HIGH-severity cutover requirements (S-1 TLS, S-2 boot privilege, S-3 role
isolation) — all three are being addressed by the sibling code slices in this
same change, with the app-side TLS enforcement and the env templates already
landed in the working tree.
