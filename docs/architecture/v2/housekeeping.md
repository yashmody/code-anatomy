# Housekeeping Reference — Scripts, Env Vars, URLs

> Single reference for operators and new team members.
> All paths are relative to the repo root unless stated otherwise.
> Secret values are **never** committed — they live only in gitignored `.env` files.

---

## Scan box

- **Two `.env` files**: `backend/.env` (FastAPI) and `cms/.env` (Directus). Both are gitignored. Copy the `.example` files and fill in secrets.
- **One script to start everything locally**: `./start_local.sh`. Individual processes can also be started manually — see §1.
- **Break-glass account** is provisioned once with `backend/scripts/create_superadmin.py` — never do it twice (the script refuses if a row exists).
- **All key URLs for local dev** are on ports `:8000` (FastAPI), `:8080` (static frontend), `:8055` (Directus). Production replaces ports with Apache path prefixes.

---

## 1 · Scripts

### 1.1 Start / stop

| Script | Path | What it does |
|--------|------|-------------|
| `start_local.sh` | `./start_local.sh` | Starts FastAPI (:8000), static frontend (:8080), and Directus (:8055) in the background. Prints URLs on boot. |
| Stop all | `pkill -f "uvicorn app.main"; pkill -f "http.server 8080"; pkill -f "directus start"` | Kills all three processes. |
| Start FastAPI only | `cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` | Preferred over `.venv/bin/uvicorn` — the wrapper script has a Python version shebang bug locally. |
| Start static server only | `python3 -m http.server 8080 --directory .` | Run from repo root. |
| Start Directus only | `cd cms && node@22 npx directus start` (or `npm run start`) | Requires Node 22 (`node@22`). Node 25 is broken locally. |

### 1.2 Database / migrations

| Script | Path | Usage |
|--------|------|-------|
| Alembic upgrade | `cd backend && .venv/bin/python -m alembic upgrade head` | Runs all pending migrations against `DATABASE_URL`. Safe to re-run (idempotent checks inside each migration). |
| Alembic current | `cd backend && .venv/bin/python -m alembic current` | Shows which revision the DB is on. |
| Alembic history | `cd backend && .venv/bin/python -m alembic history` | Lists all migrations in order. |
| Stamp baseline | `cd backend && .venv/bin/python -m alembic stamp 0001_baseline` | Use only when bootstrapping an empty DB that was created via `init_db()` / `create_all`. Never run against a DB that already has migration history. |
| Init DB (Python) | `cd backend && .venv/bin/python -c "from app.core.db import init_db; init_db()"` | Creates all tables via SQLAlchemy `create_all`. Run before `alembic stamp` on a fresh DB. |
| Seed roles | `cd backend && .venv/bin/python -m scripts.seed_roles` | Inserts the canonical role rows if they are missing. Idempotent. |
| Seed app config | `cd backend && .venv/bin/python -m scripts.seed_app_config` | Seeds `app_config` table with defaults. Idempotent. |
| Seed FAQs | `cd backend && .venv/bin/python -m scripts.seed_faqs` | Loads FAQ content into the DB. |
| Migrate to Postgres | `cd backend && .venv/bin/python -m scripts.migrate_to_postgres` | One-time migration of data from SQLite to Postgres. |
| Backfill user roles | `cd backend && .venv/bin/python -m scripts.backfill_user_roles` | Backfills `user_roles` for existing users missing a `learner` row. |
| List media | `cd backend && .venv/bin/python -m scripts.list_media` | Lists all `media_assets` rows and their large-object OIDs. |
| Upload media | `cd backend && .venv/bin/python -m scripts.upload_media <file>` | Uploads a file to Postgres large objects. |

### 1.3 Superadmin (break-glass)

| Script | Path | Usage |
|--------|------|-------|
| Provision account | `cd backend && .venv/bin/python -m scripts.create_superadmin` | Interactive. Prompts for email + password (min 12 chars, not echoed). Generates TOTP secret. Prints provisioning URI for Google Authenticator. Refuses if an account already exists. |
| Reset account | `psql <DATABASE_URL> -c "DELETE FROM superadmin;"` then re-run `create_superadmin` | Use only in an emergency. |

### 1.4 Infrastructure

| Script | Path | What it does |
|--------|------|-------------|
| `deploy.sh` | `./deploy.sh` | Full production deploy: rsync backend + frontend + content, run Alembic, restart systemd units, reload Apache, smoke `/healthz`. |
| `init_env.sh` | `backend/scripts/init_env.sh` | Bootstrap helper: creates `.venv`, installs pip deps. Run once on a fresh checkout. |
| `init_alembic.sh` | `backend/scripts/init_alembic.sh` | One-time Alembic initialisation. Already done — do not re-run on the live DB. |

---

## 2 · Environment variables

### 2.1 `backend/.env` — FastAPI

File location: `backend/.env` (gitignored). Copy from the inline defaults below or from `backend/.env.example` if it exists.

#### Run mode

| Variable | Default | Required in prod | Description |
|----------|---------|-----------------|-------------|
| `APP_ENV` | `development` | ✅ | One of `development`, `staging`, `production`. Controls cert watermarks, HMAC key selection, TLS enforcement. |
| `QUIZ_DEV_MODE` | `true` | — | Legacy alias. Prefer `APP_ENV`. When `true`: dev email login enabled, emails written to `backend/outbox/`. |
| `APP_BASE_URL` | `http://localhost:8000` | ✅ | Public base URL of the FastAPI app. Drives the Google OAuth redirect URI derivation. |
| `LOG_LEVEL` | `INFO` | — | Uvicorn + app logging level. `DEBUG` is verbose; use `WARNING` in production. |
| `CSP_REPORT_ONLY` | `true` | — | When `true`, CSP violations are reported but not enforced. Flip to `false` once CSP is stable. |

#### Secrets

| Variable | Default | Required in prod | Description |
|----------|---------|-----------------|-------------|
| `SECRET_KEY` | `dev-secret-CHANGE-IN-PROD-…` | ✅ | Signs session cookies. Rotating this logs out all users. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `APP_PAYLOAD_SECRET` | `dev-payload-secret-32bytes-long!` | ✅ | Signs AES-GCM payload encryption keys. Must be ≥32 bytes. |
| `ADMIN_EMAILS` | _(empty)_ | ✅ | Comma-separated emails seeded as `platform_admin` on every boot. E.g. `yash.mody@deptagency.com`. |

#### Google OAuth (learner SSO)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `GOOGLE_CLIENT_ID` | _(empty)_ | ✅ for SSO | OAuth 2.0 client ID from Google Cloud Console. Authorised redirect URI must include `APP_BASE_URL/auth/google/callback`. |
| `GOOGLE_CLIENT_SECRET` | _(empty)_ | ✅ for SSO | OAuth client secret. |
| `GOOGLE_REDIRECT_URI` | _(derived from APP_BASE_URL)_ | — | Override only if the derived value doesn't match what's registered in Google Console. |
| `ALLOWED_DOMAIN` | `deptagency.com` | ✅ | Only Google accounts with this email domain may sign in. |

#### Certificate signing (HMAC)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `CERT_HMAC_LEGACY` | `dev-secret-CHANGE-IN-PROD-…` | ✅ | HMAC secret for all certificates issued before the v2 cutover. Must match the original `SECRET_KEY` value so old certs keep verifying. |
| `CERT_HMAC_DEV` | _(empty)_ | In dev | HMAC secret for development-environment certs. Must differ from `CERT_HMAC_PROD`. |
| `CERT_HMAC_STG` | _(empty)_ | In staging | HMAC secret for staging-environment certs. |
| `CERT_HMAC_PROD` | _(empty)_ | In prod | Active production signing key. |

#### Database

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | `sqlite:///backend/q0.db` | ✅ for Postgres | Full SQLAlchemy connection URL. Remote Postgres example: `postgresql://ccdev:%40iQ%23FG%210%2A1@20.228.243.225:5432/codecoder-dev?sslmode=disable&connect_timeout=10`. **URL-encode special chars** in the password: `@` → `%40`, `#` → `%23`, `!` → `%21`, `*` → `%2A`. |
| `DB_POOL_SIZE` | `5` | — | SQLAlchemy connection pool size per worker. |
| `DB_MAX_OVERFLOW` | `5` | — | Extra connections above pool size allowed under burst. |

> ⚠️ **Alembic `%` bug**: `configparser` treats `%` as an interpolation prefix. The `backend/migrations/env.py` escapes it automatically (`url.replace("%", "%%")`). If you ever bypass `env.py` and set the URL directly, double every `%`.

#### Quiz behaviour

| Variable | Default | Description |
|----------|---------|-------------|
| `COOLDOWN_DAYS` | `7` | Days a learner must wait before retaking after a pass. |
| `QUIZ_DURATION_MIN` | `45` | Time limit per quiz attempt in minutes. |
| `QUESTIONS_PER_QUIZ` | `30` | Questions drawn per attempt. |
| `PASS_MARK_CORRECT` | `25` | Number of correct answers required to pass (≈83%). |

#### SMTP (email notifications)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SMTP_HOST` | _(empty)_ | For real email | SMTP server hostname. |
| `SMTP_PORT` | `587` | — | SMTP port. |
| `SMTP_USER` | _(empty)_ | — | SMTP auth username. |
| `SMTP_PASS` | _(empty)_ | — | SMTP auth password. |
| `SMTP_USE_TLS` | `true` | — | Use STARTTLS. |
| `FROM_EMAIL` | `no-reply@deptagency.com` | — | Sender address for cert emails. |
| `FROM_NAME` | `DEPT® Academy` | — | Sender display name. |

#### Cache

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_BACKEND` | `memory` | `memory` (default, single-process) or `redis` (multi-worker). |
| `REDIS_URL` | `redis://localhost:6379/0` | Used only when `CACHE_BACKEND=redis`. |
| `CACHE_TTL_FRAMEWORK` | `900` | Course framework JSON TTL in seconds. |
| `CACHE_TTL_FEED` | `30` | Feed items TTL in seconds. |
| `CACHE_TTL_APP_CONFIG` | `60` | `app_config` table TTL in seconds. |
| `CACHE_TTL_FAQ` | `900` | FAQ content TTL in seconds. |

#### CORS (local dev only)

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | _(empty)_ | Comma-separated origins allowed for CORS. Set to `http://127.0.0.1:8080,http://localhost:8080` in local dev so the static frontend (:8080) can call FastAPI (:8000). **Leave empty in production** — Apache serves both on the same origin. |

#### Directus seam

| Variable | Default | Description |
|----------|---------|-------------|
| `DIRECTUS_URL` | `http://localhost:8055` | Internal URL of the Directus instance. Used by FastAPI's webhook receiver and cache invalidation. |
| `DIRECTUS_ADMIN_TOKEN` | _(empty)_ | Static admin token for server-to-server calls (e.g. seeding collections). Generate in Directus → Settings → API Tokens. |

#### Media limits

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_VIDEO_SIZE_MB` | `30` | Maximum video upload size in megabytes. |
| `MAX_IMAGE_SIZE_MB` | `2.5` | Maximum image upload size in megabytes. |
| `MAX_VIDEO_DURATION_SEC` | `60` | Maximum video duration in seconds. |

#### LLM seam (future)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `none` | `none`, `anthropic`, or `openai`. Currently unused in any live route. |
| `LLM_API_KEY` | _(empty)_ | API key for the LLM provider. |

---

### 2.2 `cms/.env` — Directus

File location: `cms/.env` (gitignored). Copy from `cms/.env.example`.

| Variable | Example / Default | Description |
|----------|-------------------|-------------|
| `DB_CLIENT` | `pg` | Database driver. Always `pg` for Postgres. |
| `DB_HOST` | `20.228.243.225` | Remote Postgres host. |
| `DB_PORT` | `5432` | Postgres port. |
| `DB_DATABASE` | `codecoder-dev` | Database name. Prod: `codecoder`. Dev: `codecoder-dev`. |
| `DB_USER` | `directus_app_dev` | Scoped DB role. Prod: `directus_app`. Dev: `directus_app_dev`. |
| `DB_PASSWORD` | _(secret)_ | Password for the DB role. Set by DBA. Dev value: `$SA*#eY18(` — **stored only in `cms/.env`, never committed**. |
| `DB_SSL` | `true` | Require TLS to remote Postgres. |
| `DB_SSL__REJECT_UNAUTHORIZED` | `false` | `false` for `sslmode=require` without a provisioned CA. Flip to `true` once CA is provisioned. |
| `KEY` | _(random UUID)_ | Signs Directus internal cache keys. Generate: `node -e "console.log(require('crypto').randomUUID())"` |
| `SECRET` | _(random UUID)_ | Signs Directus session JWTs. Rotating this logs out all staff. |
| `PUBLIC_URL` | `http://localhost:8055` | Where Directus is publicly reachable. Prod: `https://<domain>/cms`. |
| `PORT` | `8055` | Port Directus listens on. |
| `HOST` | `127.0.0.1` | Bind address. Loopback only — Apache proxies externally. |
| `ADMIN_EMAIL` | `admin@deptagency.com` | Break-glass Directus local account. Created on first `directus bootstrap`. |
| `ADMIN_PASSWORD` | _(secret)_ | Password for the Directus break-glass account. |
| `AUTH_PROVIDERS` | `google` | SSO provider. Only `google` is configured. |
| `AUTH_GOOGLE_CLIENT_ID` | _(secret)_ | **Separate** OAuth client from the FastAPI learner one. Staff redirect URI: `<PUBLIC_URL>/auth/login/google/callback`. |
| `AUTH_GOOGLE_CLIENT_SECRET` | _(secret)_ | OAuth client secret for the Directus Google app. |
| `AUTH_GOOGLE_ALLOW_PUBLIC_REGISTRATION` | `false` | Admin must pre-create staff users. SSO then logs them in, never auto-provisions. |
| `AUTH_GOOGLE_ALLOW_LIST` | `deptagency.com` | Only `@deptagency.com` Google accounts may sign in to Directus. |
| `AUTH_GOOGLE_DEFAULT_ROLE_ID` | _(UUID)_ | Role for self-registered users (inert while public registration is off). Set to `content_author` role UUID from bootstrap. |
| `CORS_ENABLED` | `true` | Enable CORS for the API explorer. |
| `CORS_ORIGIN` | `http://localhost:8080,http://localhost:8000` | Origins allowed to call the Directus API. |
| `CACHE_ENABLED` | `true` | Directus response cache. |
| `CACHE_TTL` | `30m` | Directus cache TTL. |
| `FASTAPI_WEBHOOK_URL` | `http://127.0.0.1:8000/api/cms/webhook` | Cache-invalidation target. Directus Flows POST here when content changes. |
| `FASTAPI_ROLES_SYNC_URL` | `http://127.0.0.1:8000/api/cms/roles-sync` | Role-sync target. The `directus-extension-roles-sync` hook POSTs `{email, role}` here on staff-role changes. |
| `IMPORT_IP_DENY_LIST` | `169.254.169.254` | Blocks cloud-metadata IP. **Do not include `0.0.0.0`** — it would block the loopback webhook to FastAPI. |
| `TELEMETRY` | `false` | No phone-home. |

---

## 3 · Key URLs

### 3.1 Local development

| What | URL | Notes |
|------|-----|-------|
| **SPA (main app)** | `http://127.0.0.1:8080/frontend/index.html` | Static frontend served by Python `http.server`. |
| **Course HTML** | `http://127.0.0.1:8080/content/frozen/anatomy-of-code-course.html` | Frozen course page — no API needed. |
| **FAQs landing** | `http://127.0.0.1:8080/content/frozen/faqs/index.html` | |
| **AEM Banking FAQ** | `http://127.0.0.1:8080/content/frozen/faqs/aem-banking-faq.html` | |
| **Discovery Checklist** | `http://127.0.0.1:8080/content/frozen/code-coder-checklist.html` | |
| **Architect's Runbook** | `http://127.0.0.1:8080/content/frozen/architect-runbook.html` | |
| **FastAPI root** | `http://127.0.0.1:8000/` | Quiz app home (login / quiz / history). |
| **FastAPI Swagger UI** | `http://127.0.0.1:8000/docs` | Auto-generated OpenAPI docs for all routes. |
| **FastAPI ReDoc** | `http://127.0.0.1:8000/redoc` | Alternative API docs. |
| **Health check** | `http://127.0.0.1:8000/healthz` | Liveness probe. Returns `{status, version, env}`. |
| **Readiness check** | `http://127.0.0.1:8000/readyz` | Readiness probe. Checks DB (+ Redis if configured). Returns 200 or 503. |
| **Directus CMS** | `http://127.0.0.1:8055` | Directus admin UI. |
| **Directus login** | `http://127.0.0.1:8055/admin/login` | Staff login page (email/password or Google SSO). |

### 3.2 Authentication & session

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **Current session** | `/auth/me` | `GET` | Returns `{email, name, persona, permissions[]}` or 401. |
| **Google OAuth start** | `/auth/google` | `GET` | Redirects to Google. Requires `GOOGLE_CLIENT_ID` set. |
| **Google OAuth callback** | `/auth/google/callback` | `GET` | Google posts back here. Handled by FastAPI. |
| **Dev login** | `/login/dev` | `POST` | Form field `email`. Works only when `APP_ENV=development`. Used by the SPA sign-in modal. |
| **Logout** | `/logout` | `GET` | Clears session cookie, redirects to `/login`. |
| **Session key** | `/auth/session-key` | `GET` | Returns an AES-GCM payload encryption key for the session. |

### 3.3 Superadmin (break-glass)

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **Login page** | `/superadmin/login` | `GET` | Returns 404 if no account provisioned. |
| **Login submit** | `/superadmin/login` | `POST` | Form: `email`, `password`. Rate-limited: 5 failures / 5 min per IP. |
| **First-time TOTP setup** | `/superadmin/setup` | `GET` / `POST` | Shows provisioning URI + raw secret. POST confirms first code → enables 2FA. |
| **TOTP entry** | `/superadmin/totp` | `GET` / `POST` | Subsequent logins: enter 6-digit code from Google Authenticator. |
| **Logout** | `/superadmin/logout` | `POST` | Clears superadmin session. |

### 3.4 Quiz & certificates

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **Quiz home** | `/` | `GET` | Redirects to onboarding if persona not set, else quiz dashboard. |
| **Onboarding** | `/onboarding/role` | `GET` / `POST` | First-time role/persona selection. |
| **Start quiz** | `/quiz/start` | `POST` | Returns `{session_id, questions[], duration_min}`. Enforces cooldown. |
| **Take quiz** | `/quiz/take` | `GET` | Quiz UI. |
| **Submit quiz** | `/quiz/submit` | `POST` | Grades attempt. Returns `{pass, score, cert_id?}`. |
| **Certificate** | `/certificate/{cert_id}` | `GET` | Streams PDF. |
| **Verify certificate** | `/verify/{cert_id}` | `GET` | Public verification page. |
| **Attempt history** | `/history` | `GET` | Learner's own attempts. |

### 3.5 Content API

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **Framework JSON** | `/api/course/framework` | `GET` | The CODE-CODER ring/letter structure. Cached 900s. |
| **Framework explainer** | `/api/course/framework-explainer` | `GET` | Extended framework description. Cached 900s. |
| **Chapter JSON** | `/api/course/chapters/{filename}` | `GET` | E.g. `code-c.json`. Cached 900s. |

### 3.6 Feed API

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **List feed** | `/api/feed` | `GET` | Returns `{feed: [...]}`. Cached 30s. |
| **Post to feed** | `/api/feed` | `POST` | Requires `feed.create` permission. |
| **Flag item** | `/api/feed/flag` | `POST` | Body: `{item_id}`. Requires `feed.flag` permission. |
| **Moderation queue** | `/api/moderate/queue` | `GET` | Requires `moderate.view` permission. |
| **Moderation action** | `/api/moderate/action` | `POST` | Requires `moderate.action` permission. |

### 3.7 Media API

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **Upload media** | `/api/media/upload` | `POST` | Multipart. Requires `media.upload` permission. Stores in Postgres large objects. |
| **Stream video** | `/media/video/{asset_id}` | `GET` | HTTP Range-streaming from `pg_largeobject`. |
| **Stream image** | `/media/image/{asset_id}` | `GET` | Served from `pg_largeobject`. |

### 3.8 Admin API

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **List roles** | `/api/admin/roles` | `GET` | Requires `role.assign` permission (platform_admin only). |
| **Assign role** | `/api/admin/roles` | `POST` | Body: `{email, role}`. |
| **List questions** | `/api/admin/questions` | `GET` | Requires `question.write` permission. |
| **All attempts** | `/admin/attempts` | `GET` | Requires `attempts.view_all` permission. |

### 3.9 CMS webhook (internal)

| What | URL | Method | Notes |
|------|-----|--------|-------|
| **Cache invalidation** | `/api/cms/webhook` | `POST` | Called by Directus Flows when course content changes. Clears framework + chapter cache. |
| **Roles sync** | `/api/cms/roles-sync` | `POST` | Called by `directus-extension-roles-sync`. Body: `{email, role}`. Mirrors staff roles into FastAPI `user_roles`. |

### 3.10 Production URLs (Apache)

| What | Production URL |
|------|---------------|
| SPA | `https://internal.in.deptagency.com/app/` |
| Course HTML | `https://internal.in.deptagency.com/anatomy/anatomy-of-code-course.html` |
| FAQs | `https://internal.in.deptagency.com/anatomy/faqs/` |
| FastAPI API | `https://internal.in.deptagency.com/api/*` |
| Auth | `https://internal.in.deptagency.com/auth/*` |
| Directus CMS | `https://internal.in.deptagency.com/cms/` |
| Docs (planned) | `https://internal.in.deptagency.com/docs/` |

---

## 4 · Directus — what staff can do

| Role | What they can do in Directus |
|------|------------------------------|
| `platform_admin` (Directus Administrator) | Full access. Manage all collections, users, roles, flows. |
| `content_author` | Edit `course_chapters`, read `feed_items`. Cannot touch `attempts`, `users`, `signing_keys`. |
| `quiz_admin` | Edit `questions` (via `course_chapters`). Moderate `feed_items`. |
| `feed_moderator` | Read + update `feed_items` status only. |

> **Role grants from FastAPI, not Directus UI.** The `user_roles` table is SELECT-only for the `directus_app_dev` DB role — Directus cannot modify it. Role grants go through `POST /api/admin/roles` (requires `platform_admin`).

---

## 5 · Quick-start for a new team member

```bash
# 1. Clone and enter
git clone git@github.com:yashmody/code-anatomy.git
cd code-anatomy
git checkout v2

# 2. Install Python deps
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Copy and configure env (SQLite default works for smoke)
cp .env.example .env        # if available, else create from §2.1 defaults

# 4. Start everything
cd ..
./start_local.sh

# 5. Open the app
open http://127.0.0.1:8080/frontend/index.html

# 6. API docs
open http://127.0.0.1:8000/docs

# 7. Course HTML (no login needed)
open http://127.0.0.1:8080/content/frozen/anatomy-of-code-course.html
```

> See `LOCAL-SETUP.md` at the repo root for the full onboarding guide including Tier 1 / Tier 2a / Tier 2b levels.
