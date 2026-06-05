# v2/05 · Config & CMS — secrets/config/content registry, Directus map, Google + LLM key seam

> Status: **Phase 0 — DESIGN ONLY.** No code changes, no Directus instance is
> stood up here. This is the contract that Phase 2d (config/secrets) and Phase
> 4a (Directus stand-up) + 4c (live authoring/moderation) build against.
> Owner agent: Config/CMS. Covers plan items **2** (CMS for 4 content types),
> **11** (configurable values incl. Google + LLM keys), and **3** (environment
> management). Coordinates with `v2/01-blueprint.md` (file tree),
> `v2/03-data-model.md` (`app_config`, `signing_keys`, `users.persona`,
> Directus coexistence), `v2/04-authz-model.md` (permission matrix, two-plane
> model, `ADMIN_EMAILS` seed), `v2/06-caching-performance.md` (cache layer for
> `app_config` reads), and `v2/07-security-baseline.md` (secret handling).

All file:line citations are against branch `v2` at the time of writing.

---

## 0 · Scan box

- **Today, "config" is a single 74-line `config.py`** (`quiz-certification/app/config.py`)
  that mixes secrets, runtime tunables, hardcoded constants, and derived
  values, all read from a flat `.env` and burned into module-level globals at
  import time. There are **17 env-driven values**, **5 hardcoded constants**
  (`MAX_VIDEO_*`, `MAX_IMAGE_*`, `DEV_QUIZ_*`), and **at least 4 values that
  should exist but don't** (`ADMIN_EMAILS`, LLM keys, env-mode label, Directus
  admin token).
- The new three-tier contract: **secrets in env (Pydantic Settings)** ·
  **configuration in `app_config` (Directus-edited, cached in app)** · **content
  in Directus collections (over the shared Postgres)**. This doc is the
  registry that decides what tier each value lives in; 03 §2.4 owns the
  `app_config` table shape.
- **Directus runs as a separate Node service over the existing Postgres**
  (v2-plan.md:26). It owns four content collections (`course_chapters`,
  `frameworks`, `feed_items`, `questions`) plus `app_config`, plus optionally
  `media_assets` metadata and `user_roles` grants. FastAPI never calls Directus
  to enforce permissions — both planes read the same Postgres facts.
- **Google OAuth keys keep the current env home but gain rotation discipline**;
  the `GOOGLE_REDIRECT_URI` per-env story finally becomes explicit (today
  `deploy.sh:546` hardcodes `https://${DOMAIN}/auth/google/callback` only on
  fresh install, never on update). **LLM keys are pure seam, no calls yet**:
  one env var (`LLM_API_KEY`), one provider-neutral interface
  (`core/llm.py`), one `app_config` row for the active model. The seam is ready
  so a later phase can wire actual calls without re-plumbing config.
- **Three run-modes**: `development` · `staging` (gate decision in §9) ·
  `production`. The label is a single env var `APP_ENV`; everything else
  (cookie `Secure` flag, cert dev-mode, dev-login form, outbox vs SMTP) keys
  off it. `QUIZ_DEV_MODE` becomes a derived alias, eventually retired.

---

## 1 · Inventory of every configurable value today

Format: **name · current default · file:line · type · current source.**

Type legend: **S** = secret (must never reach git or DB) · **C** = configuration
(non-secret runtime tunable, fine in DB) · **K** = constant/code-shape (only
changes with code) · **U** = content (authored, lives in CMS).

Source legend: **env** = environment variable / `.env` · **hc** = hardcoded
Python constant · **json** = static JSON file · **db** = Postgres column ·
**none** = does not exist today.

### 1.1 Backend — `quiz-certification/app/config.py`

| Name | Current default | File:line | Type | Current source |
|---|---|---|---|---|
| `QUIZ_DEV_MODE` | `"true"` → bool | `config.py:19` | **C** (mode flag) | env |
| `SECRET_KEY` | `"dev-secret-CHANGE-IN-PROD-7f8a9b0c1d2e3f4a"` | `config.py:22` | **S** (session HMAC + cert HMAC) | env (with weak default) |
| `ALLOWED_DOMAIN` | `"deptagency.com"` | `config.py:25` | **C** | env |
| `GOOGLE_CLIENT_ID` | `""` | `config.py:28` | **S** (client identifier, semi-public but env-bound) | env |
| `GOOGLE_CLIENT_SECRET` | `""` | `config.py:29` | **S** | env |
| `GOOGLE_REDIRECT_URI` | `"http://localhost:8000/auth/google/callback"` | `config.py:30` | **C** (env-dependent) | env |
| `SMTP_HOST` | `""` | `config.py:33` | **C** | env |
| `SMTP_PORT` | `587` | `config.py:34` | **C** | env |
| `SMTP_USER` | `""` | `config.py:35` | **S** (often the same as a mailbox login) | env |
| `SMTP_PASS` | `""` | `config.py:36` | **S** | env |
| `SMTP_USE_TLS` | `true` | `config.py:37` | **C** | env |
| `FROM_EMAIL` | `"no-reply@deptagency.com"` | `config.py:38` | **C** | env |
| `FROM_NAME` | `"DEPT® Academy"` | `config.py:39` | **C** | env |
| `QUIZ_RESULTS_DIR` | `BASE_DIR/"quiz_results"` | `config.py:42` | **C** (path) | env |
| `CERTIFICATES_DIR` | `BASE_DIR/"certificates"` | `config.py:43` | **C** (path) | env |
| `OUTBOX_DIR` | `BASE_DIR/"outbox"` | `config.py:44` | **C** (path) | env |
| `QUESTION_BANK` | `BASE_DIR/"data"/"question_bank.json"` | `config.py:45` | **K** (path) | hc |
| `DATABASE_URL` | `sqlite:///{BASE_DIR}/q0.db` | `config.py:48` | **S** (carries DB password) | env |
| `COOLDOWN_DAYS` | `7` | `config.py:50` | **C** (Directus-editable) | env |
| `QUIZ_DURATION_MIN` | `45` | `config.py:51` | **C** (Directus-editable) | env |
| `QUESTIONS_PER_QUIZ` | `30` | `config.py:52` | **C** (Directus-editable) | env |
| `PASS_MARK_CORRECT` | `25` | `config.py:56` | **C** (Directus-editable; cert-load-bearing — see §6) | env |
| `APP_PAYLOAD_SECRET` | `"dev-payload-secret-32bytes-long!"` | `config.py:59` | **S** (response encryption key) | env (with weak default) |
| `MAX_VIDEO_SIZE_MB` | `30` | `config.py:62` | **C** (Directus-editable) | **hc** — no env hook |
| `MAX_IMAGE_SIZE_MB` | `2.5` | `config.py:63` | **C** (Directus-editable) | **hc** — no env hook |
| `MAX_VIDEO_DURATION_SEC` | `60` | `config.py:64` | **C** (Directus-editable) | **hc** — no env hook |
| `PASS_THRESHOLD` | derived | `config.py:67-69` | **K** (computed) | derived |

### 1.2 Backend — values outside `config.py`

| Name | Current default | File:line | Type | Current source |
|---|---|---|---|---|
| `DEV_QUIZ_COUNT` | `2` | `dev_quiz.py:25` | **K** | hc |
| `DEV_QUIZ_PASS_MARK` | `1` | `dev_quiz.py:26` | **K** | hc |
| `DEV_QUIZ_DURATION_MIN` | `5` | `dev_quiz.py:27` | **K** | hc (and dev-quiz module is dead — 01-blueprint.md:16) |
| Feed flag-threshold | `1` | `content-architecture/SCHEMA.md` (default) | **C** | none (constant in code) |
| `_active_quizzes` in-memory dict | `{}` | `main.py` (per 03-data-model.md §2.3) | **K** | code state — to be replaced by `quiz_sessions` table |

### 1.3 Deploy — `deploy.env.example` / `deploy.sh`

| Name | Current default | File:line | Type | Current source |
|---|---|---|---|---|
| `POSTGRES_SUPERUSER_PASSWORD` | `'change-me'` | `deploy.env.example:20` | **S** | env |
| `DB_NAME` | `'codecoder'` | `deploy.env.example:23` | **C** | env |
| `DB_USER` | `'codecoder'` | `deploy.env.example:24` | **C** | env |
| `DB_PASS` | auto-generated 24-byte | `deploy.env.example:26`, `deploy.sh:541` | **S** | env (generated) |
| `DOMAIN` | `'internal.in.deptagency.com'` | `deploy.env.example:29` | **C** | env |
| `CERT_FILE`/`KEY_FILE`/`CHAIN_FILE` | TLS paths | `deploy.env.example:30-32` | **C** (path) | env |
| `APP_USER` | `'cca'` | `deploy.env.example:40` | **C** | env |
| `APP_HOME` | `'/opt/dept-anatomy'` | `deploy.env.example:41` | **C** | env |
| `QUIZ_PORT` | `'8000'` | `deploy.env.example:42` | **C** | env |
| `QUIZ_WORKERS` | `'2'` | `deploy.env.example:43` | **C** | env |

### 1.4 Front-end — `app/js/main.js`

| Name | Current default | File:line | Type | Current source |
|---|---|---|---|---|
| `QUIZ_URL` | computed from `location.protocol` | `main.js:13-15` | **C** | hc |
| `SECTION_FILES` | 31 strings | `main.js:18-28` | **K** (a manifest) | hc |
| `BASE` | `''` | `main.js` | **C** | hc |
| `THEME_KEY` | localStorage key | `main.js:29` | **C** | hc |
| `MANUAL_VIDEO_SRC` | path | `app/js/modes/scroll.js:21` | **U** (media path) | hc |

01-blueprint.md:101 already moves these to `frontend/core/config.js`.

### 1.5 Absent today, needed in v2

This table is the **canonical env-var registry** for v2. Every env var any
v2 doc invents lives here, with its tier (Tier 1 = secret, env only; Tier 2
= non-secret env config) and where it lands. Rows added during the Phase 0
sweep for cross-doc coverage (07-security-baseline.md, 06-caching-performance.md)
are marked with their originating doc in the "Why needed" column.

**Tier 1 — secrets (env only):**

| Name | Why needed | Lands in |
|---|---|---|
| `DEV_SEED_ADMINS` | Local-dev convenience replacing `QuizManager` auto-grant (04 §6.5) — dev-only allowlist | env |
| `LLM_API_KEY` | The bearer secret for `LLM_PROVIDER` | env |
| `DIRECTUS_ADMIN_TOKEN` | Service-to-service token if FastAPI ever pulls metadata from Directus | env |
| `DIRECTUS_KEY` | Directus's own internal key (required by Directus core, signs session tokens) — Directus-side env | env (Directus side) |
| `DIRECTUS_SECRET` | Directus's own internal secret (required by Directus core, signs JWTs) — Directus-side env | env (Directus side) |
| `DIRECTUS_DB_USER` / `_PASSWORD` | Scoped DB role Directus connects as (07 baseline) | env (Directus side) |
| `CERT_HMAC_LEGACY` | Cert HMAC key for legacy-prod signing-key row (03 §2.5; from 07) — decoupled from `SECRET_KEY` rotation | env |
| `CERT_HMAC_DEV` | Cert HMAC key for `signing_keys.environment='development'` row (from 07) | env |
| `CERT_HMAC_STG` | Cert HMAC key for `signing_keys.environment='staging'` row (from 07) | env |
| `CERT_HMAC_PROD` | Cert HMAC key for `signing_keys.environment='production'` row (from 07) | env |
| `SECRET_KEY_NEXT` | Pre-staged next-generation session HMAC key for in-flight rotation (from 07) — optional, only set during rotation window | env |
| `GOOGLE_CLIENT_SECRET_NEXT` | Pre-staged next-generation Google OAuth client secret for rotation (from 07) — optional | env |
| `BACKUP_TARGET_URL` | Destination URL for offsite DB backup (from 07). **Tier 1 if the URL embeds credentials** (e.g. `s3://AKIA…:secret@bucket`); Tier 2 if it is a plain URL with credentials carried separately. Default: treat as Tier 1 unless proven otherwise. | env |
| `REDIS_URL` | If 06 introduces Redis for the cache; **deferred to Phase 3b**. Tier 1 if the URL embeds the AUTH password. | env |

**Tier 2 — non-secret env config:**

| Name | Why needed | Lands in |
|---|---|---|
| `ADMIN_EMAILS` | Bootstrap the first Platform Admin allowlist; replaces dev auto-elevation (04 §7.3). **Allowlist, not a key** — re-tiered from Tier 1 per C-53 / Q-16. | env |
| `ADMIN_EMAIL` | Singular form, used by some legacy scripts / Directus seeding for the very first admin email (from 07). Distinct from `ADMIN_EMAILS` (allowlist). | env |
| `APP_ENV` | One label for `development`/`staging`/`production` — drives cookie flags, dev-login, log levels | env |
| `APP_BASE_URL` | Per-environment public URL; the derived `GOOGLE_REDIRECT_URI` is built from it | env |
| `GOOGLE_REDIRECT_URI` | **Optional override.** Deprecated in favour of the derived form (§4.1), but honoured if set — protects existing Google Console-registered redirects. | env |
| `LLM_PROVIDER` | Provider id (`anthropic` / `openai` / `none`) — feature off by default | env |
| `LLM_MODEL` | Active model name (e.g. `claude-opus-4-7`) — change without redeploy | `app_config` (Directus); env carries no LLM_MODEL row |
| `LLM_FEATURES` | Per-feature on/off flags (e.g. `quiz_explainer`, `feed_summary`) | `app_config` (Directus) |
| `DIRECTUS_URL` | Where the Directus service is reachable (FE link, Apache proxy origin) | env |
| `LOG_LEVEL` | Per-env log verbosity | env |
| `CSP_REPORT_ONLY` | Phase 2e/3c security headers toggle | env |
| `CORS_ORIGINS` | Comma-separated CORS allowlist (from 07) | env |
| `MEDIA_SCAN_ENABLED` | Toggle media-upload AV/content scan (from 07) | env |
| `KEEP_DEV_SECRET` | Dev-only override to suppress the "weak dev SECRET_KEY in non-dev" startup refusal (from 07) — never set outside development | env (dev only) |
| `OPERATOR_PUBKEY` | Operator's SSH/age public key for break-glass envelope wrap (from 07) — ops convenience, not a secret | env |
| `DB_POOL_SIZE` | SQLAlchemy pool size; consumed by `backend/core/db.py` per 06 | env |
| `DB_MAX_OVERFLOW` | SQLAlchemy pool overflow; consumed by `backend/core/db.py` per 06 | env |

**Cross-doc coverage note.** The webhook seam (§7.3) is now loopback-only
(C-52), so the previously-listed `DIRECTUS_WEBHOOK_SECRET` is **not** in the
registry — drop it from any prior reference.

**Per-env signing-key selection (no env var).** The `signing_keys` row used at
runtime is **not** picked by env var. Lookup is
`SELECT … FROM signing_keys WHERE environment = settings.app_env AND is_active = TRUE`,
and the secret material for that row is loaded from the env var named in the
row's `env_var_name` column (e.g. `CERT_HMAC_PROD` for production). The
previously-proposed `CERT_DEV_MODE_KEY_ID` / `CERT_PROD_KEY_ID` env vars are
therefore **removed** — they duplicated the DB selection (C-25).

---

## 2 · The three-tier separation

### 2.1 Tier definitions

**Tier 1 — Secrets (env only).** Values that, if leaked, allow an attacker to
forge identity, decrypt traffic, or read the database. **Never** in Postgres,
**never** in git, **never** in a Directus collection. Stored on disk in
`/opt/dept-anatomy/backend/.env` (mode `0600`, owner `cca`), loaded by Pydantic
Settings at process start, referenced through one strongly-typed `Settings`
singleton, rotated via deploy procedure. Reading a secret is a single attribute
access (`settings.secret_key`); there is no live-reload — secret changes
require an app restart.

The full secret set:

```
SECRET_KEY                  # session cookie + cert HMAC (storage.py:24)
APP_PAYLOAD_SECRET          # response encryption key (encryption.py:17)
GOOGLE_CLIENT_SECRET        # OAuth client secret
GOOGLE_CLIENT_ID            # technically discoverable, but env-bound
SMTP_PASS                   # mail relay password
SMTP_USER                   # often a mailbox login → treat as secret
DATABASE_URL                # carries DB role password
LLM_API_KEY                 # future LLM bearer
DIRECTUS_ADMIN_TOKEN        # service-to-service token (if FastAPI calls Directus)
DIRECTUS_KEY                # Directus internal key (Directus-side env)
DIRECTUS_SECRET             # Directus internal secret (Directus-side env)
CERT_HMAC_LEGACY            # legacy-prod signing-key material (03 §2.5)
CERT_HMAC_DEV               # dev signing-key material
CERT_HMAC_STG               # staging signing-key material
CERT_HMAC_PROD              # prod signing-key material
SECRET_KEY_NEXT             # rotation pre-stage (optional)
GOOGLE_CLIENT_SECRET_NEXT   # rotation pre-stage (optional)
DEV_SEED_ADMINS             # dev-only allowlist
POSTGRES_SUPERUSER_PASSWORD # deploy.sh only — never read by the app
DB_PASS                     # deploy.sh only — composed into DATABASE_URL
```

`ADMIN_EMAILS` is **not** in the secret set — it is an allowlist, classified
as Tier 2 (§1.5, C-53). The webhook seam is loopback-only (§7.3), so
`DIRECTUS_WEBHOOK_SECRET` is not in the inventory either.

**Tier 2 — Configuration (`app_config`, Directus-edited).** Non-secret runtime
tunables an operator wants to flip without a deploy. Stored as JSONB rows in
the `app_config` table (03 §2.4). Edited through Directus by Platform Admin
(see permission row 17/19 in 04 §3). Read by FastAPI through a **cached
read-path with webhook invalidation** (§7). Falls back to a compiled-in
default if the row is absent — so an empty `app_config` table behaves exactly
like today's hardcoded defaults.

The full config set (keys are dot-prefixed for Directus grouping):

```
# Quiz behaviour
quiz.cooldown_days              int     7
quiz.duration_min               int     45
quiz.questions_per_quiz         int     30
quiz.pass_mark_correct          int     25      # ⚠ cert-load-bearing; see §6
# Media limits
media.max_video_size_mb         float   30
media.max_image_size_mb         float   2.5
media.max_video_duration_sec    int     60
# Feed moderation
feed.flag_threshold             int     1
feed.require_review_on_post     bool    true
# Auth / identity
auth.allowed_domain             string  "deptagency.com"
# Branding / mail
mail.from_email                 string  "no-reply@deptagency.com"
mail.from_name                  string  "DEPT® Academy"
# Feature flags
features.llm.enabled            bool    false
features.llm.quiz_explainer     bool    false
features.llm.feed_summary       bool    false
features.feed.composer_v2       bool    false   # example future flag
# LLM model selection (no secrets here)
llm.provider                    string  "none"  # mirrors env LLM_PROVIDER for UI display
llm.model                       string  ""
llm.temperature                 float   0.2
# Environment label (read-only display only — actual value comes from env)
env.label                       string  "development"
```

**`quiz.pass_mark_correct` is special.** The score that an attempt is graded
against is what gets HMAC-signed into the certificate (`storage.py:23`,
03 §2.1, 03 §2.5). Changing `pass_mark_correct` at runtime is fine for **new**
attempts but must never alter the meaning of **existing** certs. The locked
policy (C-27 / Q-17):

1. **Cert verification reads the HMAC-signed score ONLY.** The verify path
   (`storage.verify_signature`, 03 §2.5) takes the cert ID + signature and
   recomputes the HMAC over the **signed fields** — `score`, `email`,
   `issued_at`, signing-key id. It **never** reads `attempts.payload.grading`
   or any `app_config` row. This means a `pass_mark_correct` edit cannot
   retroactively invalidate or revalidate any existing certificate, and there
   is no backfill required for legacy attempts.
2. The grader (`quiz_generator.py:169-188`) reads the live value *once per
   attempt* from `cms_client.cfg("quiz.pass_mark_correct")` and freezes it
   into the `attempts.payload.grading.pass_mark_correct` JSON. The frozen
   value is **display-only**: it is intended for future cert PDFs (so the
   PDF can show "passed: 26/30 against pass mark 25 set at the time"), and
   for forensic reconstruction. The verify path does not consult it.
3. The Directus row carries a `description` warning the editor (§3.5 schema)
   that the change affects new attempts only. Optional belt-and-braces: a
   Phase 2d `app_config` audit trigger that records the previous value, so
   a regression is forensically reconstructable.

Same policy is restated in 07-security-baseline.md's cert-verification
section — they are read-paired.

**Tier 3 — Content (Directus collections).** The four content types named in
plan item 2, plus their metadata. Authored in Directus over the existing
Postgres tables; FastAPI reads them at runtime through the same DB it
already does. No service-to-service traffic between the two; both read the
same rows.

### 2.2 How the app reads each tier (post-v2)

```
                       ┌──────────────────────────────────────────┐
SECRETS (env)          │  Pydantic Settings singleton              │
  os.environ ──────────▶ core/config.py: class Settings(BaseSettings)
                       │  Read once at startup. No live reload.    │
                       └─────────────┬────────────────────────────┘
                                     │
                                     │  settings.secret_key, settings.db_url, …
                                     ▼
CONFIG (app_config)    ┌──────────────────────────────────────────┐
  Directus edit ──────▶│  core/cms_client.py: cfg(key) — thin       │
  Postgres row         │  reader; one SQL loader function.          │
                       │     │ delegates to                          │
                       │     ▼                                       │
                       │  core/cache.py: get_or_compute(             │
                       │      "app_config:" + key,                   │
                       │      ttl=60,                                │
                       │      loader=<sql>)                          │
                       │  - shared TTL + SWR cache (owned by 06)     │
                       │  - invalidated via cache.invalidate(...)    │
                       │    from the loopback webhook (§7.3)         │
                       │  - fallback to compiled-in DEFAULT          │
                       └─────────────┬────────────────────────────┘
                                     │
                                     │  cms_client.cfg("quiz.duration_min")
                                     ▼
CONTENT (Directus      ┌──────────────────────────────────────────┐
collections over PG)   │  modules/{content,feed,quiz,media}/       │
  Directus edit ──────▶│      storage.py — direct DB reads         │
                       │  Same SQL the app already runs today.     │
                       │  Directus is invisible at read time.      │
                       └──────────────────────────────────────────┘
```

The seam is deliberately narrow: **Tier 1 is env, Tier 2 is one DB table read
through one cache, Tier 3 is the same DB reads the app already does.** No new
remote dependency at runtime; Directus is an authoring console, not a request-
path dependency.

---

## 3 · Directus collection map

Directus introspects the existing Postgres tables (03 §5). For each collection
we name: the underlying table, the Directus interface (the editor widget),
required/optional, validation, relations, role permissions (cross-ref 04 §3
matrix row), workflow, and webhooks.

### 3.1 `course_chapters` — the field manual

- **Table:** `course_chapters` (Postgres, owned by Directus per 03 §6).
- **Fields:**
  | Column | Directus interface | Required | Validation |
  |---|---|---|---|
  | `address` (PK, e.g. `coder.d`) | input | yes | `^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)*$` |
  | `title` | input | yes | length 1–255 |
  | `tag` | input | no | |
  | `scan` (jsonb array) | tags input | no | array of strings |
  | `sections` (jsonb) | JSON editor (raw) | yes | JSON Schema = `content/schemas/course.schema.json` |
  | `status` | dropdown | yes | `draft`/`pending_review`/`published`/`archived` |
  | `updated_at` | datetime (auto) | — | |
- **Relations:** soft — `sections[].blocks[].frameworkRef` is a string keyed
  to a `frameworks.id` row; Directus presents it as a related-collection
  picker (Directus *Many-to-Any* on string).
- **Role permissions (cross-ref 04 row 9 — *Course chapter authoring*):**
  | Role | C | R | U | D |
  |---|---|---|---|---|
  | `content_author` | ✅ (status=draft) | ✅ | ✅ (own drafts) | ❌ |
  | `quiz_admin` | ❌ | ✅ | ❌ | ❌ |
  | `feed_moderator` | ❌ | ✅ | ❌ | ❌ |
  | `platform_admin` | ✅ | ✅ | ✅ | ✅ |
- **Workflow:** `draft` → submit → `pending_review` → `platform_admin` or
  designated reviewer flips to `published` → optionally `archived`.
- **Webhook:** on update where `status = 'published'`, POST to
  `<FASTAPI>/api/cms/webhook` with `{table: "course_chapters", id, action}`.
  FastAPI invalidates the chapter cache.

### 3.2 `frameworks` — the spine (2 rows: `framework`, `explainer`)

- **Table:** `frameworks` (03 §6, populated by ETL `migrate_to_postgres.py:258-274`).
- **Fields:** `id` (`framework` | `explainer`), `data` (jsonb — entire payload),
  `updated_at`.
- **Directus interfaces:** `data` shows as a JSON editor with the schema
  attached (the existing `course.schema.json` framework subset). Editing the
  spine is rare and high-impact.
- **Permissions:** `platform_admin` and `content_author` C/R/U; nobody deletes
  (rows are seeded, not created).
- **Workflow:** no draft state (two-row reference data); a "preview" is by
  cloning the row in a dev environment.
- **Webhook:** publish → invalidate `framework` and `explainer` caches; the
  course front-end re-fetches on next route load.

### 3.3 `feed_items` — UGC + moderation surface

- **Table:** `feed_items` (03 §1.5, populated live by `main.py:649`).
- **Fields:** `id` (text PK), `type`, `status`, `author_email` (FK→`users`),
  `framework_ref`, `topics` (text[]), `created_at`, `updated_at`, `data`
  (jsonb, type-specific payload — see `content-architecture/SCHEMA.md:99-108`),
  `engagement` (jsonb counters).
- **Directus interfaces:** `type` as dropdown drives a *Field Group* showing
  only the matching subset of `data` fields (post/video/list/card/vocab/
  scenario). `status` as dropdown with workflow.
- **Relations:** `author_email` → `users` (read-only); `framework_ref` →
  `course_chapters.address` (related picker).
- **Role permissions (cross-ref 04 row 11 — feed moderation):**
  | Role | C | R | U | D |
  |---|---|---|---|---|
  | `feed_moderator` | ❌ | ✅ | ✅ (status only) | ❌ |
  | `platform_admin` | ✅ | ✅ | ✅ | ✅ |
  | `content_author` | ❌ | ✅ | ❌ | ❌ |
  | `quiz_admin` | ❌ | ✅ | ❌ | ❌ |
- **Workflow:** runtime creates `pending_review` (or `published` for trusted
  authors — `app_config.feed.require_review_on_post`); moderator approves
  → `published` or `removed`. `flagged` is set when flag count crosses
  `app_config.feed.flag_threshold` (today defaults to 1, SCHEMA.md).
- **Webhook:** status change → invalidate feed list cache for any filter that
  could have included this id; if the item carries a UGC scenario question
  (created via `main.py:660-672`), also invalidate the `questions` cache.

### 3.4 `questions` — quiz bank (official + UGC)

- **Table:** `questions` (03 §1.3).
- **Fields:** `id`, `text`, `options` (jsonb array), `correct_index`,
  `difficulty`, `category`, `framework_ref`, `status`, `is_user_submitted`,
  `version`, `created_by` (FK→users), `created_at`, `updated_at`.
- **Two views inside Directus:**
  1. *Official questions* filter: `is_user_submitted = false`. Edited by
     `quiz_admin` and `platform_admin`.
  2. *UGC questions queue* filter: `is_user_submitted = true AND status =
     'pending_review'`. Reviewed by `quiz_admin`; approval flips
     `status='published'`.
- **Permissions (cross-ref 04 rows 10–12, 14):**
  | Role | C | R | U | D |
  |---|---|---|---|---|
  | `quiz_admin` | ✅ (official) | ✅ | ✅ (review UGC) | ❌ |
  | `platform_admin` | ✅ | ✅ | ✅ | ✅ |
- **Workflow:** `draft` → `pending_review` → `published`; UGC starts at
  `pending_review` automatically.
- **Webhook:** publish/unpublish → invalidate question-pool cache (per
  `difficulty`).

### 3.5 `app_config` — config-as-content (item 11 home)

- **Table:** `app_config` (03 §2.4).
- **Fields:** `key`, `value` (jsonb), `value_type`, `description`,
  `updated_at`, `updated_by`. (Per 03 §2.4 / C-20, the `is_secret` column
  is not on the table — `value_type` is Directus rendering metadata only;
  this doc is the source of truth for what is or is not a secret.)
- **Directus interfaces:** typed display per row driven by `value_type`
  (`int` → number, `bool` → toggle, `string` → input, `json` → JSON editor).
  `description` is shown as helper text under the field.
- **Permissions (04 rows 17/19):** read = `platform_admin` only; write =
  `platform_admin` only. Other staff roles cannot see config rows. (Rationale:
  config changes are platform-wide; we don't want every Content Author to be
  able to flip the pass mark.)
- **Workflow:** none (single-state); writes are direct.
- **Webhook:** on **any** update, POST (over loopback, §7.3) to
  `http://127.0.0.1:<FASTAPI_PORT>/api/cms/webhook` with
  `{table: "app_config", key, action: "update"}`. FastAPI calls
  `core.cache.invalidate("app_config:" + key)`. Special handling for
  `quiz.pass_mark_correct` (§2.1 warning / C-27): the description text shown
  in Directus includes *"Changing this value affects new attempts only.
  Certificate verification reads the HMAC-signed score only and never reads
  this row, so already-issued certificates are unaffected."*

### 3.6 `media_assets` — metadata only (decision in §3.7 below)

If the gate decision keeps Directus over the existing table (recommended):

- **Table:** `media_assets` (03 §2.7).
- **Directus exposure:** read-mostly; Directus can edit `filename`/`mime_type`/
  `uploaded_by` metadata but **never** rewrites the binary (`large_object_oid`
  is read-only). Asset upload remains the FastAPI `/api/media/upload` path
  for streaming media; Directus has no upload path against `pg_largeobject`.
- **Permissions:** `content_author` R (browse), `platform_admin` R/U/D.

### 3.7 `user_roles` — grants (composite-PK decision)

03 §5 flagged that Directus handles composite PKs poorly. Two options:

- **(Recommended)** Expose `user_roles` **read-only** to Directus; the grant
  UI is a FastAPI admin endpoint (`POST /api/admin/roles`, 04 §8 step 9).
  This keeps the role-assignment audit cleanly inside `auth_audit` (04 §7.4).
- **(Alternative)** Add a surrogate `id BIGSERIAL` so Directus can edit grants
  directly. Tradeoff: easier UI for Platform Admins, but two write surfaces
  for the same table — audit has to handle both.

Recommendation: **read-only in Directus**. Grants are sensitive and rare; the
named admin endpoint is the better seam.

### 3.8 Resources / runbook / checklist / FAQs

Today these are HTML files in `app/resources/`. **Out of scope for v2 Directus
collections** (recommended): they are static content authored as HTML, and
fit content-as-git better than content-as-CMS. They are served as part of the
frozen content tree (01-blueprint.md:156-159). Revisit only if non-technical
editors need to edit them; gate decision §9.

---

## 4 · Google + LLM key integration plan (item 11)

> Cross-reference for both seams: the cert verify policy in §2.1 (C-27)
> applies regardless of how Google or the LLM evolve — verification reads the
> HMAC-signed score only, never any `app_config` row, never any Tier 2 value
> reachable through this section's seams.

### 4.1 Google OAuth — where keys live today and post-v2

**Today.** `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`
are read at module load (`config.py:28-30`) from `.env` in the backend
directory, populated either manually or by `deploy.sh` on a fresh install
(`deploy.sh:546,554-555`). When `QUIZ_DEV_MODE=true` the values can be empty
and the OAuth path is bypassed by a local email form (`main.py:188-210`).

**Problems:**
- `GOOGLE_REDIRECT_URI` is **only set on fresh deploy** (`deploy.sh:546`); on
  re-deploy the original `.env` is left alone (`deploy.sh:564 — "leaving
  untouched"`). A domain change requires hand-editing `.env`.
- No per-environment redirect URIs (the URI is whatever happens to be in the
  env at deploy time).
- No rotation procedure. There is no script for "new secret, old secret keeps
  working for the in-flight callbacks".
- Domain restriction is enforced client-side via the `hd` hint plus
  `is_allowed_email` (`auth.py:18-25`); the `id_token` is not verified at all
  (04 §6.2).

**Post-v2 (Phase 2d + 2b coordination).**

1. `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` stay in env (Tier 1). They are
   referenced through `settings.google_client_id` / `settings.google_client_secret`.
2. `GOOGLE_REDIRECT_URI` is **derived** from `settings.app_base_url` +
   `/auth/google/callback` by default — `app_base_url` is one env var per
   environment (`https://localhost:8000` / `https://staging…` /
   `https://internal.in.deptagency.com`). Deploy provisions exactly one Google
   client per environment; in the Google Console each environment is its own
   *OAuth client* with its own redirect URI registered. Rotating a secret in
   production never affects local-dev.
   The env var `GOOGLE_REDIRECT_URI` is **kept as an optional override** —
   deprecated in favour of the derived form, but honoured when set (C-26 /
   Q-14). This protects existing Google Console-registered redirects that do
   not match the derived form (e.g. legacy paths, non-standard ports, manual
   subdomain swaps). Operators are encouraged to delete the override once the
   derived form matches the registered URI.
3. `auth.allowed_domain` moves to `app_config` (Tier 2). The env still carries
   `ALLOWED_DOMAIN` as a fallback (so a bricked DB can't lock everyone out),
   but the runtime authority is the DB row. Editable in Directus by Platform
   Admin only.
4. **Rotation procedure** (Phase 2d documents this in DEPLOY.md):
   ```
   1. Create new OAuth client in Google Console with the SAME redirect URI.
   2. Update GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env on the host.
   3. systemctl restart quiz-cert.service
   4. After 24h with no auth errors, delete the old OAuth client in Google Console.
   ```
   No DB changes, no schema migration — secrets stay in env per the tier
   contract.
5. Staff (Directus) Google SSO — 04 §4.2 recommended yes. Directus has its own
   Google OAuth provider config; that lives in **Directus's own env file**
   (separate process, separate `.env`). Both planes can use the same Google
   Workspace / Cloud project; only the *OAuth client* differs. Coordinate the
   exact env keys in 4a checklist (§8.2).

### 4.2 LLM keys — the seam, no calls yet

There is **no LLM integration in the codebase today**. A grep for `openai`,
`anthropic`, `claude`, `gpt`, `llm` in `quiz-certification/` returns nothing
in `requirements.txt` and nothing in `app/*.py`. The course *talks about*
LLMs (LLMO, AI-Native ring); the platform doesn't use one.

The seam is exactly:

1. **Env (Tier 1):** `LLM_PROVIDER`, `LLM_API_KEY`. Default `LLM_PROVIDER=none`.
   When `none`, every call into the LLM module is a no-op that returns the
   "feature off" branch. No key needed in dev.
2. **`app_config` (Tier 2):** `llm.provider` (mirror for UI display),
   `llm.model`, `llm.temperature`, plus `features.llm.*` boolean flags. Model
   selection moves out of env on purpose — operators rotate models often
   (`opus-4-7` → `opus-4-8`), keys rarely.
3. **Code (`backend/app/core/llm.py`, NEW):**
   ```python
   # core/llm.py — provider-neutral seam. NO calls in Phase 2d; just the shape.
   from typing import Protocol

   class LLMClient(Protocol):
       def complete(self, *, system: str, user: str, max_tokens: int) -> str: ...
       def embed(self, text: str) -> list[float]: ...

   def get_client() -> LLMClient | None:
       """Return a configured client, or None if LLM_PROVIDER=none."""
       provider = settings.llm_provider
       if provider == "none" or not settings.llm_api_key:
           return None
       if provider == "anthropic":
           from .llm_anthropic import AnthropicClient   # not implemented in 2d
           return AnthropicClient(api_key=settings.llm_api_key,
                                  model=cms_client.cfg("llm.model"))
       if provider == "openai":
           from .llm_openai import OpenAIClient         # not implemented in 2d
           return OpenAIClient(api_key=settings.llm_api_key,
                                model=cms_client.cfg("llm.model"))
       raise ValueError(f"Unknown LLM_PROVIDER={provider}")
   ```
4. **Consumers (later phase, not 2d):** `modules/quiz/explainer.py`,
   `modules/feed/summariser.py`, etc. Each one early-returns when
   `get_client()` is `None` or `cms_client.cfg("features.llm.<feature>")` is
   false.

What Phase 2d delivers for LLM: env vars defined, `app_config` rows seeded,
`core/llm.py` Protocol present, **but no provider client module and no API
calls**. The seam is ready; the work to wire actual calls is a deliberate
later effort with its own gate (cost, rate-limit, PII review).

---

## 5 · Environment management (item 3)

### 5.1 Run modes

Three modes, identified by **one env var `APP_ENV`** with allowed values
`development` / `staging` / `production`. **Staging is a gate decision (§9)**
— if the user declines staging, the matrix collapses to two modes.

The legacy `QUIZ_DEV_MODE` boolean becomes a derived alias for
`APP_ENV == "development"` during the Phase 2d cutover and is removed in
Phase 5b.

**What `APP_ENV` controls (single source of truth):**

| Concern | development | staging | production |
|---|---|---|---|
| Session cookie `Secure` flag | False | True | True |
| Session cookie `SameSite` | `lax` | `lax` | `lax` |
| HTTPS-only redirect | off | on | on |
| OAuth path | local email form OR Google | Google | Google |
| SMTP | outbox dir | real SMTP (staging mailbox) | real SMTP |
| Cert signing key id | `dev-…` from `signing_keys` | `staging-…` | `prod-…` |
| Cert visual watermark | "DEV CERTIFICATE" | "STAGING CERTIFICATE" | (none) |
| Dev-only routes (`/dev/*`) | mounted | not mounted | not mounted |
| `LOG_LEVEL` default | `DEBUG` | `INFO` | `INFO` |
| Pydantic Settings strictness | warn on weak defaults | **error** on weak defaults | **error** on weak defaults |
| `CSP_REPORT_ONLY` | true | true (initial) | false (after baking) |

Everything that today reads `config.DEV_MODE` (`main.py:97,131,191,215,224`,
`storage.py:74,84`, `email_service.py:73`, `auth.py`) is repointed to
`settings.app_env` with the appropriate comparison.

### 5.2 File layout

```
/Users/yashmody/work/CODE-CODER/dept-deploy/
└── backend/                          # was quiz-certification/
    ├── .env                          # Tier 1 secrets, 0600, host-local, gitignored
    ├── .env.example                  # template (the rewrite of today's quiz-certification/.env.example)
    ├── .env.development.example      # dev-mode-friendly defaults (no real SMTP, no real Google)
    ├── .env.staging.example          # staging template (placeholders for staging Google/SMTP)
    └── .env.production.example       # production template (no defaults for secrets — must be filled)
└── cms/
    └── .env.example                  # Directus's own env (DIRECTUS_*, GOOGLE_* for Directus SSO if different client)
└── deploy.env.example                # rewrite: now mostly references APP_ENV + per-env file
```

**Per-env files are templates checked into git as `*.example`.** The real
`.env` is generated by `deploy.sh` from the template appropriate to `APP_ENV`,
filled in interactively or from `deploy.env`. **There is exactly one `.env`
per host at a time** — we are not running a multi-env tree on one host.

### 5.3 Switching modes locally

Developer flow:

```bash
# Option A: one-time, for the session
cd backend
APP_ENV=development uvicorn app.main:app --reload

# Option B: durable, in the .env
cp .env.development.example .env
$EDITOR .env   # paste your GOOGLE_CLIENT_ID/SECRET only if you want to test SSO
./start_local.sh
```

`start_local.sh` (today bootstraps the FastAPI + static + optional Postgres
multiplex) gains:

1. A `--env` flag (`development` / `staging` / `production`) that exports
   `APP_ENV` before starting uvicorn.
2. A sanity check: if `APP_ENV=production` and `.env` is missing required
   secrets, refuse to start and print which keys are missing.
3. **Removal** of the implicit "use SQLite if `DATABASE_URL` is unset"
   fallback (`config.py:48`) — Postgres-only per 03 §2. Print a clear error
   if `DATABASE_URL` is unset, with the `docker run` command to start a local
   Postgres.

### 5.4 How `deploy.sh` selects the env

Today `deploy.sh` only knows `QUIZ_DEV_MODE` and flips it based on the
presence of `GOOGLE_CLIENT_ID`/`SECRET` (`deploy.sh:553`). Post-v2:

1. `deploy.env` (the operator-facing config) gains `APP_ENV=production`
   (default) or `staging`.
2. `deploy.sh` reads `APP_ENV`, copies the matching `.env.<env>.example` to
   `.env`, then `env_set`s every required key (using values from `deploy.env`
   or interactive prompts).
3. The systemd `EnvironmentFile=` line (`deploy.sh:760`) is unchanged — it
   already reads `${QUIZ_DIR}/.env`.
4. The `GOOGLE_REDIRECT_URI` line at `deploy.sh:546` is deleted; the app
   derives the URI from `APP_BASE_URL`.
5. The Apache vhost generation already keys off `$DOMAIN`; nothing changes
   there.

### 5.5 How Directus reads/writes the same Postgres in each env

Directus is its own systemd unit (Phase 4a), running on a different port,
with its **own** `.env` and **own** DB role (`directus_app`, 07 baseline).
The DB role is *scoped*: DDL on `directus_*` tables, DML on the content
tables listed in 03 §5, **no** access to `attempts` / `quiz_sessions` /
`signing_keys` / the secret-bearing `users.preferences`. Per environment:

- **development:** Directus runs on the same machine, same Postgres, port
  8055. The dev SQLite path is dead per 03 §2.
- **staging / production:** Directus runs on the same VM, same Postgres
  cluster (saves a network hop and a CA setup), reverse-proxied via the same
  Apache under `/cms/*` or a dedicated subdomain (`cms.internal.in.deptagency.com`).
  Decision deferred to 4a; this doc only requires that the URL is one env var
  (`DIRECTUS_URL`).

---

## 6 · Migration of today's values

Per-row destination + migration step. **Implementation lives in Phase 2d,
seeded from this table.** All migrations are one-shot data loads with no
data loss — the fallback chain (DB → env → compiled default) means a missing
row behaves identically to today.

| Today | Tier in v2 | Destination | Migration step |
|---|---|---|---|
| `QUIZ_DEV_MODE` (`config.py:19`) | **C** | env `APP_ENV` | rename; map `true`→`development`, `false`→`production`; keep `QUIZ_DEV_MODE` as a derived alias for one phase |
| `SECRET_KEY` (`config.py:22`) | **S** | env (no change) | regenerate in `.env.production.example`; refuse to start if the dev default appears in `APP_ENV=production` |
| `ALLOWED_DOMAIN` (`config.py:25`) | **C** | `app_config` `auth.allowed_domain` (env fallback) | seed row from current env value at first migration |
| `GOOGLE_CLIENT_ID` (`config.py:28`) | **S** | env (no change) | unchanged |
| `GOOGLE_CLIENT_SECRET` (`config.py:29`) | **S** | env (no change) | unchanged |
| `GOOGLE_REDIRECT_URI` (`config.py:30`) | **C** | **derived** from `APP_BASE_URL` + `/auth/google/callback`; env var **retained as optional override** | deprecate in favour of the derived form, but honour the env value if set — protects existing Google Console-registered redirects that do not match the derived form (C-26) |
| `SMTP_HOST` (`config.py:33`) | **C** | env (per-env file) | unchanged |
| `SMTP_PORT` (`config.py:34`) | **C** | env | unchanged |
| `SMTP_USER` (`config.py:35`) | **S** | env | unchanged |
| `SMTP_PASS` (`config.py:36`) | **S** | env | unchanged |
| `SMTP_USE_TLS` (`config.py:37`) | **C** | env | unchanged |
| `FROM_EMAIL` (`config.py:38`) | **C** | `app_config` `mail.from_email` (seed value from env) | seed: read current env value at migration time, INSERT as `mail.from_email`; env var no longer consulted at runtime |
| `FROM_NAME` (`config.py:39`) | **C** | `app_config` `mail.from_name` | seed |
| `QUIZ_RESULTS_DIR` (`config.py:42`) | **C** | env (per-host path) | unchanged |
| `CERTIFICATES_DIR` (`config.py:43`) | **C** | env | unchanged |
| `OUTBOX_DIR` (`config.py:44`) | **C** | env | unchanged |
| `QUESTION_BANK` (`config.py:45`) | **K** | code constant | unchanged (it's a seed path, not config) |
| `DATABASE_URL` (`config.py:48`) | **S** | env (no SQLite fallback) | error out if unset in non-dev; coordinate with 03 §2 |
| `COOLDOWN_DAYS` (`config.py:50`) | **C** | `app_config` `quiz.cooldown_days` | seed |
| `QUIZ_DURATION_MIN` (`config.py:51`) | **C** | `app_config` `quiz.duration_min` | seed |
| `QUESTIONS_PER_QUIZ` (`config.py:52`) | **C** | `app_config` `quiz.questions_per_quiz` | seed |
| `PASS_MARK_CORRECT` (`config.py:56`) | **C** (cert-load-bearing) | `app_config` `quiz.pass_mark_correct` | seed; per §2.1, write Directus description warning |
| `APP_PAYLOAD_SECRET` (`config.py:59`) | **S** | env | regenerate; refuse to start if the dev default appears in non-dev |
| `MAX_VIDEO_SIZE_MB` (`config.py:62`, hc) | **C** | `app_config` `media.max_video_size_mb` | seed from constant value |
| `MAX_IMAGE_SIZE_MB` (`config.py:63`, hc) | **C** | `app_config` `media.max_image_size_mb` | seed |
| `MAX_VIDEO_DURATION_SEC` (`config.py:64`, hc) | **C** | `app_config` `media.max_video_duration_sec` | seed |
| `PASS_THRESHOLD` (`config.py:67`) | **K** | derived | unchanged |
| Feed flag-threshold (constant) | **C** | `app_config` `feed.flag_threshold` | seed `1` (today's default per SCHEMA.md) |
| `_active_quizzes` dict | **K** | `quiz_sessions` table | per 03 §2.3 |
| `MANUAL_VIDEO_SRC` (`scroll.js:21`) | **U** (media path) | `app_config` `media.manual_video_src` OR media-collection metadata | seed; FE reads via `core/config.js` |
| `QUIZ_URL` (`main.js:13`) | **C** | `frontend/core/config.js` constant + env at build time | per 01 §4 |
| `SECTION_FILES` (`main.js:18`) | **K** | `frontend/core/config.js` manifest | per 01 §4 |
| `ADMIN_EMAILS` (absent) | **C** (allowlist, not a key — C-53) | env | new; required in non-dev |
| `ADMIN_EMAIL` (absent, singular) | **C** | env | new; used for first-admin seeding (from 07) |
| `DEV_SEED_ADMINS` (absent) | **S** (dev allowlist, env-only) | env (dev only) | new |
| `LLM_PROVIDER` (absent) | **C** | env | new, default `none` |
| `LLM_API_KEY` (absent) | **S** | env | new, optional |
| `LLM_MODEL` (absent) | **C** | `app_config` `llm.model` | new |
| `LLM_FEATURES` (absent) | **C** | `app_config` `features.llm.*` | new, all false |
| `DIRECTUS_URL` (absent) | **C** | env | new (Phase 4a) |
| `DIRECTUS_ADMIN_TOKEN` (absent) | **S** | env | new (Phase 4a) |
| `DIRECTUS_KEY` (absent) | **S** | env (Directus side) | new (Phase 4a) — Directus internal |
| `DIRECTUS_SECRET` (absent) | **S** | env (Directus side) | new (Phase 4a) — Directus internal |
| `CERT_HMAC_LEGACY` (absent) | **S** | env | new (Phase 2c) — decouples legacy-prod cert HMAC from `SECRET_KEY` (C-21) |
| `CERT_HMAC_DEV` (absent) | **S** | env | new (Phase 2c) — keyed to `signing_keys.environment='development'` row |
| `CERT_HMAC_STG` (absent) | **S** | env | new (Phase 2c) — keyed to `signing_keys.environment='staging'` row |
| `CERT_HMAC_PROD` (absent) | **S** | env | new (Phase 2c) — keyed to `signing_keys.environment='production'` row |
| `SECRET_KEY_NEXT` (absent) | **S** | env (optional, rotation only) | new (07) |
| `GOOGLE_CLIENT_SECRET_NEXT` (absent) | **S** | env (optional, rotation only) | new (07) |
| `BACKUP_TARGET_URL` (absent) | **S** if URL embeds creds; else **C** | env | new (07) |
| `KEEP_DEV_SECRET` (absent) | **C** | env (dev only) | new (07) — opt-out of weak-secret refusal in dev |
| `OPERATOR_PUBKEY` (absent) | **C** | env | new (07) — ops-side public key for break-glass |
| `CORS_ORIGINS` (absent) | **C** | env | new (07) |
| `MEDIA_SCAN_ENABLED` (absent) | **C** | env | new (07) |
| `DB_POOL_SIZE` (absent) | **C** | env | new (06) — `core/db.py` SQLAlchemy pool size |
| `DB_MAX_OVERFLOW` (absent) | **C** | env | new (06) — `core/db.py` SQLAlchemy pool overflow |
| `APP_ENV` (absent) | **C** | env | new |
| `APP_BASE_URL` (absent) | **C** | env | new |
| `LOG_LEVEL` (absent) | **C** | env | new |
| `CSP_REPORT_ONLY` (absent) | **C** | env | new (07) |

---

## 7 · Where the values are read in code (post-v2)

### 7.1 `backend/app/core/config.py` — Pydantic Settings singleton

```python
# core/config.py — secrets + structural config only.
# Tier 2 values are NOT here; they come from cms_client.cfg().
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyHttpUrl, SecretStr

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # one deeper than today
REPO_ROOT = BASE_DIR.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore",
                                       case_sensitive=False)

    # --- env mode ----------------------------------------------------------
    app_env: str = Field("development", pattern="^(development|staging|production)$")
    app_base_url: AnyHttpUrl = "http://localhost:8000"

    # --- secrets (Tier 1) --------------------------------------------------
    secret_key: SecretStr
    app_payload_secret: SecretStr
    database_url: SecretStr
    google_client_id: SecretStr = SecretStr("")
    google_client_secret: SecretStr = SecretStr("")
    smtp_pass: SecretStr = SecretStr("")
    smtp_user: str = ""
    admin_emails: str = ""             # comma-separated; parsed at startup
    dev_seed_admins: str = ""          # dev only

    # --- non-secret env defaults (fallbacks for Tier 2) --------------------
    allowed_domain: str = "deptagency.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_use_tls: bool = True

    # --- paths -------------------------------------------------------------
    quiz_results_dir: Path = BASE_DIR / "quiz_results"
    certificates_dir: Path = BASE_DIR / "certificates"
    outbox_dir: Path = BASE_DIR / "outbox"
    static_dir: Path = BASE_DIR / "app" / "static"
    templates_dir: Path = BASE_DIR / "app" / "templates"

    # --- LLM seam ----------------------------------------------------------
    llm_provider: str = "none"          # 'none' | 'anthropic' | 'openai'
    llm_api_key: SecretStr = SecretStr("")

    # --- Directus seam -----------------------------------------------------
    directus_url: AnyHttpUrl = "http://localhost:8055"
    directus_admin_token: SecretStr = SecretStr("")
    # Webhook receiver is loopback-only (§7.3) — no shared HMAC secret.

    # --- ops ---------------------------------------------------------------
    log_level: str = "INFO"
    csp_report_only: bool = True

    # Optional override for the Google OAuth redirect. Leave unset to use
    # the derived form (APP_BASE_URL + /auth/google/callback). Set this when
    # the Google Console registered redirect URI cannot be matched by the
    # derived form — see §4.1 / C-26.
    google_redirect_uri_override: str = ""

    # --- DB pool (consumed by core/db.py, per 06) --------------------------
    db_pool_size: int = 5
    db_max_overflow: int = 10

    def google_redirect_uri(self) -> str:
        if self.google_redirect_uri_override:
            return self.google_redirect_uri_override
        return f"{self.app_base_url}/auth/google/callback".replace("//auth", "/auth")

    def validate_for_env(self) -> None:
        """Called once at startup. Raises if production lacks required secrets."""
        if self.app_env in ("production", "staging"):
            if self.secret_key.get_secret_value().startswith("dev-secret-"):
                raise RuntimeError("Refusing to start: dev SECRET_KEY in non-dev env")
            if self.app_payload_secret.get_secret_value().startswith("dev-payload-"):
                raise RuntimeError("Refusing to start: dev APP_PAYLOAD_SECRET in non-dev env")
            if not self.admin_emails:
                raise RuntimeError("ADMIN_EMAILS must be set in non-dev")
            if not self.database_url.get_secret_value():
                raise RuntimeError("DATABASE_URL must be set in non-dev")
            if self.app_env == "production" and not self.google_client_id.get_secret_value():
                raise RuntimeError("GOOGLE_CLIENT_ID required in production")

settings = Settings()
settings.validate_for_env()
```

Replaces the entire 74-line `config.py` shape with a typed singleton.

### 7.2 `backend/app/core/cms_client.py` — Tier 2 read-path

`cms_client` does **not** invent its own cache. It is a thin typed reader over
`app_config` that delegates caching + invalidation to the shared
`core.cache.get_or_compute(...)` seam owned by 06-caching-performance.md
(`backend/app/core/cache.py` per 01's tree). One cache implementation, one
invalidation surface, one TTL/SWR policy — for both Tier 2 config and Tier 3
content reads.

```python
# core/cms_client.py — typed reader over app_config.
# Caching is delegated to core.cache (owned by 06); this module only knows
# how to read a single row and to name the cache key.
from sqlalchemy import select
from . import cache, config, db
from ..models import AppConfig

# Compiled-in fallback defaults — preserve today's behaviour when DB is empty
DEFAULTS: dict[str, object] = {
    "quiz.cooldown_days":        7,
    "quiz.duration_min":         45,
    "quiz.questions_per_quiz":   30,
    "quiz.pass_mark_correct":    25,
    "media.max_video_size_mb":   30,
    "media.max_image_size_mb":   2.5,
    "media.max_video_duration_sec": 60,
    "feed.flag_threshold":       1,
    "feed.require_review_on_post": True,
    "auth.allowed_domain":       config.settings.allowed_domain,
    "mail.from_email":           "no-reply@deptagency.com",
    "mail.from_name":            "DEPT® Academy",
    "features.llm.enabled":      False,
    "features.llm.quiz_explainer": False,
    "features.llm.feed_summary": False,
    "llm.provider":              config.settings.llm_provider,
    "llm.model":                 "",
    "llm.temperature":           0.2,
    "env.label":                 config.settings.app_env,
}

def _load(key: str) -> object:
    """SQL loader for a single app_config row; called on cache miss."""
    with db.session() as s:
        row = s.execute(
            select(AppConfig).where(AppConfig.key == key)
        ).scalar_one_or_none()
        return row.value if row else DEFAULTS.get(key)

def cfg(key: str) -> object:
    """Read a config value through the shared cache.

    core.cache.get_or_compute owns the TTL window (60 s) and SWR behaviour;
    this call is a one-liner so the read-path stays uniform with content
    reads in modules/{content,feed,quiz}/.
    """
    return cache.get_or_compute(
        "app_config:" + key,
        ttl=60,
        loader=lambda: _load(key),
    )
```

**Properties:**
- One DB round-trip per key per TTL window. The TTL is the safety net for a
  missed webhook.
- The webhook (`POST /api/cms/webhook`, §7.3) calls `cache.invalidate("app_config:" + key)`
  on `app_config` writes — so an editor flipping a flag in Directus sees it
  reflected within seconds, not TTL.
- Compiled-in `DEFAULTS` means an empty `app_config` table is byte-identical
  to today (essential for parity).
- Thread-safe and multi-worker behaviour are owned by `core.cache`; this
  module no longer carries its own `RLock`. Phase 3b's Redis-backed cache
  swap (06 §10) is transparent here — only `core.cache` changes.
- 06-caching-performance.md is the source of truth for the cache size, TTL
  default, and SWR policy; this file is the *read-path*.

### 7.3 `backend/app/modules/cms/routes.py` — webhook receiver (loopback-only)

Directus and FastAPI are co-resident on one VM (§5.5). The webhook is **bound
to loopback only**: the FastAPI app listens on `127.0.0.1`, Apache denies the
`/api/cms/webhook` location from any non-loopback origin, and the application
itself rejects requests whose `request.client.host` is not `127.0.0.1`. There
is **no HMAC, no shared secret, no timestamp, no nonce** on this seam —
network reachability *is* the authentication.

Apache (owned by 07; cross-reference for v2 vhost):

```apache
<Location "/api/cms/webhook">
    Require ip 127.0.0.1
</Location>
```

Application:

```python
# modules/cms/routes.py — receive Directus invalidation events (loopback-only)
from fastapi import APIRouter, HTTPException, Request
from ...core import cache, cms_client

router = APIRouter()

@router.post("/api/cms/webhook")
async def cms_webhook(request: Request):
    if request.client is None or request.client.host != "127.0.0.1":
        raise HTTPException(403, "loopback only")
    event = await request.json()
    table = event.get("table")
    if table == "app_config":
        cache.invalidate("app_config:" + event.get("key", ""))
    elif table in ("course_chapters", "frameworks", "questions", "feed_items"):
        # 06-caching-performance.md owns the content cache namespace
        cache.invalidate(f"{table}:{event.get('id', '')}")
    return {"ok": True}
```

The `DIRECTUS_WEBHOOK_SECRET` env var that previously carried the HMAC key
is therefore removed from §1.5 and §2.1's secret inventory — see §1.5 below
for the updated set. Operators who insist on defence-in-depth can still add
a static header check via Apache, but it is not part of the contract.

### 7.4 Read-paths per tier — call-site summary

| Caller | Reads what | How |
|---|---|---|
| `main.py:61` (SessionMiddleware) | `SECRET_KEY` | `settings.secret_key.get_secret_value()` |
| `encryption.py:17` | `APP_PAYLOAD_SECRET` | `settings.app_payload_secret.get_secret_value()` |
| `db.py:14-18` | `DATABASE_URL` | `settings.database_url.get_secret_value()` |
| `storage.py:23-28` (HMAC) | `SECRET_KEY` | `settings.secret_key.get_secret_value()` |
| `auth.py:18-25` | `auth.allowed_domain` | `cms_client.cfg("auth.allowed_domain")` |
| `auth.py:43-77` | Google OAuth | `settings.google_client_id`/`_secret`, `settings.google_redirect_uri()` |
| `email_service.py:73,83-93` | `APP_ENV`, SMTP | `settings.app_env`, `settings.smtp_*` |
| `main.py:171-178` (`/`) | quiz constants | `cms_client.cfg("quiz.pass_mark_correct")` etc. |
| `quiz_generator.py:169-188` | `PASS_MARK_CORRECT` | `cms_client.cfg("quiz.pass_mark_correct")` — read **once per attempt** then frozen into `attempts.payload.grading` |
| `media_service.py:75-76` | `max_video_duration_sec` | `cms_client.cfg("media.max_video_duration_sec")` |
| `main.py:769` | `MAX_VIDEO_SIZE_MB`/`MAX_IMAGE_SIZE_MB` | `cms_client.cfg(...)` |
| `main.py:441,457-458` | quiz constants | `cms_client.cfg(...)` |

---

## 8 · What Phase 2d implements + What Phase 4a/4c implements

### 8.1 Phase 2d checklist (config + secrets — backend-only, no Directus yet)

Sequenced. Phase 2a (Alembic) must have created the `app_config` table.

1. **Add `pydantic-settings`** to `backend/requirements.txt`.
2. **Rewrite `core/config.py`** to the Settings shape in §7.1. Module-level
   `settings` singleton replaces the 17 module-level globals. Add
   `validate_for_env()` startup check.
3. **Migrate `DEV_MODE` → `APP_ENV`.** Add `app_env` to settings; introduce a
   deprecated `DEV_MODE` property that returns `app_env == "development"`;
   sweep 8 call sites (`main.py:97,131,191,215,224`, `storage.py:74,84`,
   `email_service.py:73`, `auth.py`).
4. **Drop the SQLite fallback** in `db.py:14` — Postgres-only per 03.
5. **Per-env `.env` templates.** Write `backend/.env.{development,staging,production}.example`.
   Update `backend/.env.example` to point at them.
6. **`deploy.sh` rewrite for env selection:** read `APP_ENV` from `deploy.env`;
   copy the matching template; stop *forcing* the `GOOGLE_REDIRECT_URI` line
   (`deploy.sh:546`) — leave the env var unset by default so the derived form
   wins, but allow operators to set it as an override (C-26); add a fail-fast
   for missing required keys.
7. **`start_local.sh`:** add `--env` flag; sanity-check secrets in non-dev;
   remove implicit-SQLite fallback message.
8. **Create `app_config` seed migration.** Alembic data migration that inserts
   the rows in §2.1 with values from `config.py` today (compile-time defaults).
   Idempotent: only inserts a row if the key is absent.
9. **Add `core/cms_client.py`** (§7.2). Wire `quiz_generator.py`,
   `media_service.py`, the seven `main.py` call-sites (§7.4) to read through
   `cms_client.cfg`.
10. **Pass-mark freezing rule** (§2.1 / C-27): change `quiz_generator.grade`
    to read `pass_mark_correct` *once* from `cms_client.cfg` and persist it
    into `attempts.payload.grading.pass_mark_correct` for display/forensics
    only. **Cert verification continues to read the HMAC-signed score only**
    — it does not read `payload.grading` or any `app_config` row. This is
    the cert-load-bearing rule the policy in §2.1 names.
11. **LLM seam:** add `core/llm.py` with the Protocol and `get_client()`. Seed
    `app_config` rows for `llm.*` and `features.llm.*`. Add env vars to
    `.env.*.example`. **No provider client modules in this phase.**
12. **`ADMIN_EMAILS` / `DEV_SEED_ADMINS` plumbing.** Add to settings; wire into
    the startup/login admin-seeding (04 §7.3 step 9). Refuse to start in
    non-dev if `ADMIN_EMAILS` is empty.
13. **Webhook seam stub.** Add `modules/cms/routes.py` with the receiver
    (§7.3) wired but **no Directus origin yet** — it accepts only loopback
    requests (`request.client.host == "127.0.0.1"`) and calls
    `core.cache.invalidate(...)`; the actual Directus sender lands in 4a.
    Apache `<Location "/api/cms/webhook">` deny-from-non-loopback rule
    coordinated with 07.
14. **Documentation:** rewrite `DEPLOY.md` env section, document the rotation
    procedure (§4.1), document the three modes (§5.1), add an `app_config`
    reference.
15. **Parity gate:** the parity harness (02-parity-method.md) re-runs against
    a fresh DB with an empty `app_config` table; defaults from `cms_client.DEFAULTS`
    must yield byte-identical output to today. Then again with the seeded
    rows; must yield byte-identical output. Cert verification of legacy
    `attempts` rows must still succeed (signing-key id from 03 §2.5).

**Phase 2d explicitly does NOT:** stand up Directus, wire a webhook sender,
implement any LLM provider call, add Redis. All four are later phases.

### 8.2 Phase 4a checklist (Directus stand-up)

1. **Install Directus** as a separate Node service. Decide systemd vs Docker
   (gate decision §9). Bind to localhost; reverse-proxy through Apache.
2. **Create the scoped DB role `directus_app`** with DDL on `directus_*` and
   DML on the content tables only (07 baseline owns the exact grants).
3. **Write `cms/.env.example`** with `DIRECTUS_KEY`, `DIRECTUS_SECRET`,
   `DB_*`, `PUBLIC_URL`, Google SSO provider config (separate OAuth client
   from the FastAPI one).
4. **Configure Google SSO** for staff (04 §4.2): new OAuth client in Google
   Console with redirect URI `<DIRECTUS_URL>/auth/login/google/callback`;
   restrict to `deptagency.com`; one break-glass local Directus admin.
5. **Define the 5 collections** (§3.1–3.5) via Directus schema snapshot
   (`cms/schema/<timestamp>.yaml`). Introspect over existing tables.
6. **Apply role permissions** per §3 tables (cross-ref 04 §3 matrix).
7. **Configure webhooks** for the five tables →
   `http://127.0.0.1:<FASTAPI_PORT>/api/cms/webhook` (loopback only — Directus
   and FastAPI are co-resident; no HMAC, see §7.3 / C-52). The receiver is
   already in place from Phase 2d.
8. **Mount Directus under Apache:** new vhost section, `ProxyPass /cms/ →
   127.0.0.1:8055/` with WS upgrade headers. Add CSP entry for the Directus
   origin. **Coordinate with 06 caching/performance** so static Directus
   assets are cached but not the admin app shell.
9. **Seed the admin user.** The first Platform Admin from `ADMIN_EMAILS` is
   pre-provisioned in `directus_users`; subsequent admins use SSO + role
   mirror (04 §4.3).
10. **Documentation:** new `docs/operations/directus.md` covering how to
    add an editor, how to recover from a misconfigured collection, where the
    schema snapshot lives.

### 8.3 Phase 4c checklist (live authoring + moderation)

1. **Webhook sender** in each Directus collection: install the Hooks
   extension that POSTs status-change events to the FastAPI webhook (§3.5).
2. **Content cache wiring** in `modules/content/`, `modules/feed/`,
   `modules/quiz/` (per 06): when the webhook receiver fires
   `content_cache.invalidate(table, id)`, the next read hits the DB.
3. **The 14 hardcoded constants/feature flags** (§2.1) become editable in
   Directus — the moment Phase 4c ships, an operator can tune them without
   redeploying.
4. **UGC moderation workflow:** the existing `pending_review` rows that
   today only surface via `/api/moderate/queue` (`main.py:622`) appear in
   Directus's *Feed Moderation* view; status transitions through Directus
   trigger the same webhook → cache invalidation → end-user view update.
5. **First content authoring:** edit one course chapter in Directus, observe
   the FE re-render after webhook → invalidation → fetch. Acceptance criterion
   for the 4c gate.
6. **`features.llm.*` flip-test:** Platform Admin flips a feature flag in
   Directus; the (still no-op) LLM seam observes it. This proves the path is
   ready for the LLM provider work in a later phase.

---

## 9 · Open gate decisions

Flag these explicitly for the Phase 0 user gate. Each carries a default.

1. **`ADMIN_EMAILS` — env allowlist or Directus role?**
   **Default: env allowlist** (coordinated with 04 §7.3). One env var, parsed
   once at startup, **mirrored** into both the FastAPI `user_roles` table and
   the Directus admin role. Alternative: Directus is sole authority — but the
   bootstrap-the-first-admin problem (04 §1) makes a fresh prod deployment
   un-bootstrappable. **Tradeoff:** the env-allowlist is a *floor* (removing
   does not auto-revoke), which is intentional but means revoking is a
   two-step manual.

2. **Staff (Directus) SSO — Google SSO or local Directus accounts?**
   **Default: Google SSO, same `deptagency.com` domain restriction, separate
   OAuth client from the FastAPI one + one break-glass local admin** (04 §4.2).
   Alternative: local Directus accounts only — simpler but a second password
   to manage. The Google client is per-environment; the env vars need
   confirmation at the 4a gate.

3. **Is staging a real environment?**
   **Default: yes — three modes** (`development` / `staging` / `production`).
   Staging gives a place to verify a config change before pushing to prod
   without affecting learners. Alternative: two modes (collapse staging into
   prod with a banner). **Tradeoff:** staging adds one Postgres + one VM + a
   second Google OAuth client; if budget is tight, defer to Phase 5b.

4. **`media_assets` — Directus collection or FastAPI-only?**
   **Default: Directus reads metadata, FastAPI owns the bytes** (03 §5
   media decision). Editors browse asset metadata in Directus but upload
   through the FastAPI path. Alternative: full Directus asset management via
   `directus_files` — clean editor UX but a second media pipeline.

5. **`user_roles` editable in Directus, or read-only?**
   **Default: read-only in Directus; grants via a FastAPI admin endpoint**
   (§3.7). Alternative: surrogate `id BIGSERIAL` + Directus editable — easier
   UX, two write surfaces.

6. **Resources / runbook / FAQs in CMS?**
   **Default: NO — keep as authored HTML in `content/resources/`** (§3.8).
   Alternative: HTML-block collection in Directus — adds editor convenience,
   but no non-technical author has asked.

7. **Directus deployment shape — systemd Node or Docker?**
   **Default: systemd Node service** to match how `deploy.sh` already runs
   uvicorn (one operational shape). Alternative: Docker Compose alongside
   the app. **Decision deferred to 4a** — neither blocks Phase 0/2d work.

8. **Redis for the config cache — Phase 2d or Phase 3b?**
   **Default: Phase 3b.** `core.cache.get_or_compute` (owned by 06) is the
   one cache surface; the in-process TTL+SWR implementation it ships with is
   correct for the read volume. Redis only buys cross-worker consistency,
   which the 60-second TTL bounds anyway. 06-caching-performance.md owns this
   decision — when 06 swaps the backing store, `cms_client.cfg` does not
   change.

9. **`SMTP_USER` — secret or config?**
   **Default: secret.** It's a mailbox login that, with `SMTP_PASS`, gives
   send-as authority. Some operators argue it's "just an identifier" — but the
   env layer doesn't care, so we err safe.

10. **LLM seam — provider-neutral now, or wait until needed?**
    **Default: build the seam now (Phase 2d) without a provider client.**
    Costs almost nothing, prevents a re-plumbing of config when the work
    starts, and the `features.llm.*` flags are useful as "future feature
    placeholders" in Directus UX. Alternative: defer until the LLM work has
    its own scope — but then config and Directus rows arrive late.

---

## 10 · Cross-references

- **Schema:** `app_config` table (03 §2.4), `signing_keys` table (03 §2.5),
  Directus coexistence rules (03 §5), source-of-truth resolution (03 §6).
- **AuthZ:** `ADMIN_EMAILS` allowlist (04 §7.3), Google SSO PKCE (04 §6),
  staff plane SSO (04 §4.2), permission matrix rows 9–14 + 17–19 (04 §3),
  role-assignment endpoint (04 §8 step 9).
- **Tree / mounts:** `core/config.py` location (01 §6 `app/config.py →
  core/config.py`), `modules/cms/routes.py` mount (01 §7 cms `/api/cms`),
  `frontend/core/config.js` (01 §4 — covers `QUIZ_URL`, `SECTION_FILES`,
  `THEME_KEY`).
- **Caching/perf:** `core.cache.get_or_compute` + `core.cache.invalidate`
  (06 §4.1 — the single cache seam this doc reads through), Apache caching
  exclusion of the Directus admin shell (06), `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`
  consumers (06).
- **Security:** secret rotation (07), Directus DB role grants (07),
  CSP for the Directus origin (07), session cookie flags per env (07 + 04 §6.4).

---

## Appendix A · The "before/after" of one config value

`PASS_MARK_CORRECT` is the most load-bearing example. The trip from
hardcoded-via-env to Directus-tunable looks like:

**Before (today):**

```
.env  PASS_MARK_CORRECT=25
        │
        ▼
config.py:56  PASS_MARK_CORRECT = int(os.getenv("PASS_MARK_CORRECT", "25"))
        │
        ▼
main.py:175  pass_mark_correct=config.PASS_MARK_CORRECT
quiz_generator.py:170  ... pass_mark = pass_mark or PASS_MARK_CORRECT
storage.py:23  signature input includes f"{score:.6f}"  ← cert HMAC
```

**After (post-2d):**

```
Operator opens Directus → app_config → "quiz.pass_mark_correct" → edits to 26 → save.
        │
        ▼
Directus webhook (loopback) → POST /api/cms/webhook
                              {table:"app_config", key:"quiz.pass_mark_correct"}
        │
        ▼
core.cache.invalidate("app_config:quiz.pass_mark_correct")
        │
        ▼
Next quiz_start  →  cms_client.cfg("quiz.pass_mark_correct") → 26
                  → frozen into attempts.payload.grading.pass_mark_correct
                  → that attempt is graded against 26 and the SCORE is signed
                    (the HMAC input is the score, not the pass mark)
        │
        ▼
Previously-issued certificates verify against their HMAC-signed score only.
The pass-mark edit does not retroactively affect any of them; verify never
reads payload.grading. (C-27 / §2.1.)
```

The pass-mark frozen into `attempts.payload` is display-only context for
future cert PDFs; the HMAC signs the score, not the pass mark, and verify
reads the HMAC-signed score only. This is the rule §2.1 names; it is what
keeps the "no loss of certificate verification" hard constraint
(`v2-plan.md:119`) intact across `app_config` edits.
