# DEPT® Anatomy of Code — Master Context Document

> **Purpose**: Platform-agnostic project context for any AI coding assistant
> (Claude, Gemini, Codex, Grok, etc.). Share this file to onboard any agent
> onto the codebase. Generated 2026-06-06 from the v2 branch, cross-checked
> against the project's knowledge graph (3,832 nodes, 4,484 edges,
> 456 communities).

---

## 1. What This Project Is

A **teaching, certification, and reference system** for DEPT® architects and
engineers, built around the CODE-CODER framework. It serves the Adobe
Experience Cloud practice across India and globally.

**Three deliverables in one monorepo:**

| Deliverable | Path | Tech | Purpose |
|---|---|---|---|
| Course + reference docs | `content/frozen/` (HTML) + `content/source/` (JSON) | Static HTML, no build | Field manual, checklist, runbook, FAQ collection |
| Backend + Frontend | `backend/` (FastAPI) + `frontend/` (ES modules) | Python 3.11+, vanilla JS | Quiz/certification app (CCA-F), feed, media, moderation |
| Prompt library | `prompt-library/` | Markdown + sample apps | Reusable agent-coding sequences (e.g. AEM → React Native) |

**Supporting infrastructure:**

| Path | Purpose |
|---|---|
| `cms/` | Directus CMS (content write plane for staff) |
| `docs-site/` | Docusaurus documentation site for the v2 platform |
| `docs/architecture/v2/` | Architecture decision records — the source of truth for v2 design |
| `tests/baseline/` | Smoke tests, API fixtures, parity contracts |
| `infra/` | Certbot, cron jobs (vacuumlo) |

---

## 2. Architecture Overview

### 2.1 Two-Plane Model

The system has two independent planes sharing one Postgres database:

```
┌─────────────────────────┐    ┌─────────────────────────┐
│   FastAPI (Learner)     │    │   Directus (Staff)      │
│   Port 8000             │    │   Port 8055             │
│                         │    │                         │
│  auth/ quiz/ feed/      │    │  Content editing        │
│  media/ content/ cms/   │    │  Media management       │
│  admin/                 │    │  Collection registration │
├─────────────────────────┤    ├─────────────────────────┤
│  uvicorn (2 workers)    │    │  Node 22 runtime        │
└────────────┬────────────┘    └────────────┬────────────┘
             │                              │
             └──────────┬───────────────────┘
                        │
                ┌───────┴───────┐
                │   PostgreSQL  │
                │  (remote, TLS)│
                │  per-env DB   │
                └───────────────┘
```

**Apache** sits in front of both, handling TLS termination, HSTS, CSP headers,
and reverse-proxying.

### 2.2 Module Layout (Backend)

The backend follows a **modular monolith** pattern:

```
backend/app/
├── main.py              # composition-only entry point (no business logic)
├── core/                # shared horizontal layers
│   ├── config.py        # env-driven Settings singleton (pydantic-settings)
│   ├── db.py            # get_session() — the single DB session factory
│   ├── models.py        # SQLAlchemy models (User, Attempt, FeedItem, etc.)
│   ├── users.py         # user CRUD + RBAC (the ONLY writer of user_roles + auth_audit)
│   ├── cache.py         # AppCache with pluggable MemoryBackend / RedisBackend
│   ├── cms_client.py    # Directus API client with cache integration
│   ├── security.py      # ASGI middleware stack (CORS, CSP, session)
│   ├── observability.py # request-id middleware
│   ├── deps.py          # FastAPI dependencies (require_permission, etc.)
│   ├── roles.py         # role definitions and capability strings
│   └── encryption.py    # payload encryption
└── modules/             # vertical feature slices
    ├── auth/            # Google OAuth, session management, audit logging
    ├── quiz/            # question bank, exam sessions, certificates, HMAC verification
    ├── feed/            # community feed, flagging, moderation actions
    ├── media/           # image/video upload via Postgres large objects
    ├── content/         # course chapters, framework, framework-explainer storage
    ├── cms/             # Directus webhook receiver (cache invalidation)
    └── admin/           # role assignment REST API (thin pass-through to core.users)
```

### 2.3 Frontend

**Buildless ES-module SPA** — no bundler, no transpiler, no node_modules.

```
frontend/
├── index.html           # entry point
├── core/
│   ├── main.js          # router + bootstrap
│   ├── api-client.js    # loadJSON() — all API calls go through here
│   ├── auth-ui.js       # permission checks, auth modal, nav sync
│   ├── config.js        # API base URL, feature flags
│   └── theme.js         # dark/light mode, localStorage persistence
├── modules/
│   ├── course/          # manual.js (scroll reader), read.js (chapter renderer)
│   ├── feed/            # composer, cards, envelopes, media, store, validation
│   └── moderate/        # moderation queue UI
└── shared/
    ├── blocks/          # block renderers (prose, diagram, callout, code, etc.)
    ├── render/          # chapter, diagram, explainer renderers
    ├── registry.js      # block type → renderer mapping
    ├── framework.js     # loadFramework(), indexFramework()
    └── dom.js           # esc() — HTML escaping (72-edge god node, used everywhere)
```

### 2.4 Content Architecture

Four content types, two storage backends:

| Type | Source of truth | Storage | Managed by |
|---|---|---|---|
| Course (chapters, framework, explainer) | `content/source/course/` JSON | Postgres (via FastAPI content storage) | JSON files → API |
| Feed | `content/source/feed/feed.json` (seed) | Postgres `feed_items` table | Directus + FastAPI |
| Media | Uploaded by users | Postgres large objects (lo) | FastAPI media module |
| Config | `app_config` table | Postgres | Directus → webhook → cache |

Content follows the **LAYER pattern**:
1. Scan Box (3–5 bullets, 30-second read)
2. Prose (declarative, opinionated, architect-grade)
3. Diagrams + callout blocks woven through

---

## 3. Critical Code Paths

### 3.1 `get_session()` — The God Node

`backend/app/core/db.py:L99` — the single DB session factory. **Every backend
module depends on it.** It bridges 13 communities in the knowledge graph.

Direct callers span: auth storage, quiz storage, quiz verification, feed
routes, media service, content storage, core users, and 5+ scripts.

**Risk**: a signature change or connection-pool configuration change affects
all 13 modules simultaneously.

### 3.2 HMAC Certificate Chain

```
verify_attempt()  →  _get_legacy_prod_key()    →  get_session()  (DB read: key)
                  →  _get_signing_key_by_id()   →  get_session()  (DB read: key)
                  →  attempt_by_cert_id_public() → get_session()  (DB read: attempt)

sign_record()     →  get_active_signing_key()   →  get_session()  (DB read: active key)
```

Every certificate operation hits the DB at least twice. Signing keys are in
the hard-denied table set (only the app DB role can read them). The legacy key
fallback path (`_get_legacy_prod_key`) is the safety net during key rotation.

### 3.3 Feed Moderation (Read+Write in One Request)

`moderate_action()` at `feed/routes.py:L111` is the only route that touches
**three tables in one request**:

1. **Reads** moderation queue (feed_items + questions)
2. **Writes** status change to feed_items — committed first
3. **Writes** audit row to auth_audit — best-effort, in try/except

The status change and audit are in **separate sessions** — if audit fails,
the moderation action still succeeds (by design, tagged V2-F-05). This
contrasts with RBAC grant/revoke, where audit is mandatory and transactional.

After the status write, the code manually calls
`cache.invalidate_prefix("feed_items:")` because moderation writes bypass the
Directus webhook path.

### 3.4 Cache Invalidation (Dual-Plane)

```
Directus plane:  staff edit → webhook POST → cms/routes.py → cache.invalidate_prefix()
FastAPI plane:   moderate_action() → manual cache.invalidate_prefix("feed_items:")
```

Both planes converge on the same cache prefix strings. There is no shared
constant — if someone changes the prefix in the webhook handler without
updating `moderate_action()`, stale data leaks silently.

`AppCache` (`cache.py:L395`) is thread-safe with a pluggable backend:
- `MemoryBackend` (default, for ≤2 workers)
- `RedisBackend` (opt-in via `CACHE_BACKEND=redis`, for 4+ workers)

### 3.5 Content Read Path (Frontend → Backend)

```
frontend/core/api-client.js          frontend/modules/course/read.js
         loadJSON(url)          →    renderChapter() / renderRead()
              │                              │
              ▼                              ▼
     FastAPI /api/content/*          renderBlock() via registry.js
              │                              │
              ▼                              ▼
     content/storage.py              block renderers (shared/blocks/)
     get_chapter() / get_framework()         │
              │                              ▼
              ▼                      esc() for all user-facing text
     AppCache.get_or_compute()
              │
              ▼
     get_session() → Postgres
```

---

## 4. RBAC Model

### 4.1 Role Hierarchy

Every known user holds `learner` as a **floor** (cannot be revoked). Additional
capability roles are granted via the admin API.

| Role | Capabilities | Gate |
|---|---|---|
| `learner` | Course read, quiz take, feed read/post | Automatic on first login |
| `moderator` | `moderate.view`, `moderate.action` | Granted by platform_admin |
| `platform_admin` | `role.assign` + all moderator caps | Seeded from `ADMIN_EMAILS` env var |

### 4.2 Two-Tier Implementation

```
admin/routes.py  (HTTP layer, permission-gated)
       │
       ▼
admin/storage.py (thin pass-through, zero SQL)
       │
       ▼
core/users.py    (the ONLY writer of user_roles + auth_audit)
       │
       ├── grant_role()             → _ensure_role_membership() + _write_audit()
       ├── revoke_role()            → DB delete + _write_audit()
       ├── ensure_first_admin()     → seeds from ADMIN_EMAILS
       └── roles_for()              → always includes 'learner'
```

All role mutations write an `auth_audit` row naming the acting admin.

### 4.3 Hard-Denied Tables (Directus Cannot Access)

`attempts`, `quiz_sessions`, `signing_keys`, `auth_audit` — these are only
accessible to the FastAPI app DB role. The CMS (Directus) DB role is
explicitly denied access via `GRANT`/`REVOKE` matrix.

---

## 5. Database

### 5.1 Stack

- **PostgreSQL** (remote, TLS-enforced outside dev via `validate_db_tls`)
- **SQLAlchemy** ORM with **Alembic** migrations (chain: 0001–0008)
- One DB per environment (dev/staging/prod on same Postgres server)
- Media stored as **Postgres large objects** (seekable streaming, `lo_unlink`
  trigger, `vacuumlo` cron sweep)

### 5.2 Key Tables

| Table | Module | Notes |
|---|---|---|
| `users` | core | Google OAuth profiles |
| `user_roles` | core | Many-to-many capability grants |
| `auth_audit` | auth | Immutable audit trail |
| `attempts` | quiz | Exam attempts with HMAC-signed scores |
| `quiz_sessions` | quiz | Active exam state |
| `signing_keys` | quiz | Per-environment HMAC keys |
| `questions` | quiz | 300-question bank (100 per difficulty tier) |
| `feed_items` | feed | Community posts with moderation status |
| `media_assets` | media | Large object references |
| `course_chapters` | content | Chapter metadata |
| `framework` | content | CODE-CODER framework spine |
| `framework_explainer` | content | Explainer content |
| `app_config` | config | Runtime tunables (Tier-2 config via Directus) |

### 5.3 Migration Chain

```
0001_baseline       → initial schema from SQLite migration
0002_reconcile      → align with v2 blueprint
0003_new_tables     → feed_items, media_assets, framework, etc.
0004_new_columns    → status fields, moderation columns
0005_seed_data      → initial data seeding
0006_lo_cleanup     → large object trigger + cleanup
0007_seed_nonprod_signing_keys → dev/staging HMAC keys
0008_directus_app_role → CMS DB role with restricted grants
```

---

## 6. Configuration

### 6.1 Three-Tier Config Model

| Tier | Source | Examples | Mutability |
|---|---|---|---|
| Tier 1: Secrets | Environment variables / `.env` | `SECRET_KEY`, `CERT_HMAC_PROD`, OAuth creds | Deploy-time only |
| Tier 2: Runtime tunables | `app_config` table (via Directus) | Feature flags, copy strings | Hot-reloadable via webhook |
| Tier 3: Structural | Code constants | Module layout, route paths | Code change required |

### 6.2 Key Environment Variables

```bash
APP_ENV=development|staging|production  # fail-closed: refuses dev secrets in non-dev
DATABASE_URL=postgresql://...?sslmode=require  # TLS enforced for remote
SECRET_KEY=...                          # session cookie signing
APP_PAYLOAD_SECRET=...                  # payload encryption
GOOGLE_CLIENT_ID=...                    # OAuth (restricted to @deptagency.com)
GOOGLE_CLIENT_SECRET=...
ADMIN_EMAILS=admin@deptagency.com       # seeds platform_admin on first boot
CACHE_BACKEND=memory|redis              # pluggable cache backing store
DIRECTUS_URL=http://localhost:8055
DIRECTUS_ADMIN_TOKEN=...
CERT_HMAC_DEV=... / CERT_HMAC_STG=... / CERT_HMAC_PROD=...
```

### 6.3 Security Validators (Fail-Closed)

- `validate_for_env()`: refuses to start if non-dev env carries dev-default secrets
- `validate_db_tls()`: refuses cleartext connection to remote Postgres outside dev
- `APP_ENV` is `Literal["development", "staging", "production"]` — no fallback

---

## 7. Deployment Topology

### 7.1 Single-VM Layout

```
┌─────────────────────────────────────────────────────┐
│                    CentOS 8 / RHEL 8 VM             │
│                                                     │
│  Apache (TLS/HSTS/CSP)                              │
│  ├── /anatomy/  →  content/frozen/  (static alias)  │
│  ├── /          →  proxy to uvicorn :8000            │
│  └── /cms/      →  proxy to Directus :8055           │
│                                                     │
│  systemd: uvicorn (2 workers, FastAPI)               │
│  systemd: directus (Node 22)                         │
│                                                     │
│  Remote PostgreSQL (TLS, per-env DB)                 │
└─────────────────────────────────────────────────────┘
```

### 7.2 Deploy Command

```bash
sudo ./deploy.sh   # handles SELinux, firewalld, venv, systemd, Apache config
```

### 7.3 Apache CSP Profiles

Three CSP profiles based on route:
- Static content: tight (no scripts beyond inline)
- FastAPI app: moderate (API calls, OAuth redirects)
- Directus: permissive (CMS needs broader script/style access)

---

## 8. Quiz System (CCA-F)

### 8.1 Lifecycle

```
User logs in (Google OAuth, @deptagency.com only)
    → Cooldown check (7 days after last failed attempt)
    → Generate exam: 30 questions (10 beginner + 10 intermediate + 10 advanced)
    → 45-minute timer
    → Score: pass ≥ 25/30 (83%)
    → Pass: HMAC-signed certificate (PDF via reportlab) + email
    → Fail: cooldown begins, attempt recorded
```

### 8.2 Anti-Cheat

- Server-side timer enforcement
- Question randomisation from 300-question bank
- HMAC-signed scores (tamper detection)
- Per-environment signing keys stored in hard-denied DB table

### 8.3 Certificate Verification

Public URL `/verify?cert=XXXX` — stateless verification via HMAC. The
verification chain hits the DB twice (once for signing key, once for attempt
record). Legacy key fallback handles key rotation gracefully.

---

## 9. Language & Voice Rules

**These are mandatory for any content generation or editing.**

- **Indian English** spelling: organise, optimise, behaviour, colour, centre
- **Plain professional English** — no Americanisms ("y'all", "reach out"),
  no Indian business-English clichés ("do the needful", "kindly")
- Examples should land for an **Indian reader**: Razorpay, UPI, DPDP, Aadhaar,
  BFSI, Flipkart. Global examples (Stripe, Linear, Figma) fine when apt.
- Acronyms expanded on first use
- Crore/lakh acceptable in Indian market context

### Content Style — Path 3 (Layered)

The course voice is **declarative, opinionated prose written for the architect**.
Do not bulletise the prose. Follow the LAYER pattern:
1. Scan Box (3–5 bullets at the top)
2. Prose underneath (untouched in voice)
3. Diagrams + callout blocks woven through

### Callout Block Types (exactly four)

- "Why This Matters" — architect-level stake
- "Agency Tip" — practical agency-context guidance
- "Common Pitfall" — what teams get wrong
- "Before / After" — concrete example pairs

### Diagram Convention

- **ASCII** (`.arch-diagram` CSS classes) for static architecture diagrams
- **Mermaid** for flows, pipelines, sequences, decision trees

### Brand

- Ochre: `#FF4900` (exact)
- Fonts: Syne (display), DM Sans (body), JetBrains Mono (labels)
- Dark mode with per-page localStorage theme keys

---

## 10. Agent Orchestration

Four subagents when working on content:

| Agent | Role | When to invoke |
|---|---|---|
| **c0** | Content builder — edits `content/source/` JSON + `content/frozen/` HTML | Any content change |
| **content-quality** | Read-only reviewer (brand, voice, structure, a11y, AI-tells) | ALWAYS after c0 completes |
| **q0** | Quiz curator — drafts question-bank additions | Only when c0 introduces new architectural concepts |
| **l0** | Skill/prompt-library builder | When generating reusable prompts |

**Workflow**: c0 plans → c0 builds → content-quality reviews → q0 if needed →
present reports before next c0 turn. Do NOT invoke q0 for typo fixes, CSS
tweaks, or scan-box additions.

---

## 11. Development Setup

### 11.1 Prerequisites

- Python 3.11+ with venv
- Node 22 (for Directus — Node 25 is broken locally)
- PostgreSQL (remote or local)
- Google OAuth credentials (dev mode stubs these)

### 11.2 Quick Start

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in or leave defaults for dev
APP_ENV=dev uvicorn app.main:app --reload --port 8000

# Or use the all-in-one launcher
./start_local.sh       # boots backend :8000 + static server :8080
```

### 11.3 Tests

```bash
# Backend tests
cd backend && pytest tests/

# Smoke tests (requires running server)
cd tests/baseline && python smoke.py

# Frontend import check
python tests/baseline/check-frontend-imports.py
```

### 11.4 Git Workflow

- **GitHub Flow**: `main` is always publishable
- Branch naming: `<scope>/<short-slug>` (e.g. `course/llmo-refresh`, `fix/dark-mode`)
- Squash-merge to keep linear history
- Separate version tags: `course-vX.Y.Z`, `quiz-vX.Y.Z`

---

## 12. Key Architectural Decisions

These are documented in `docs/architecture/v2/` and confirmed by the knowledge
graph analysis.

### 12.1 Single Session Factory

`get_session()` is the sole entry point for DB access. Every module uses it.
This is intentional — it ensures consistent connection pooling, transaction
boundaries, and makes the remote-TLS migration transparent to callers.

### 12.2 Audit Trail is Mandatory for RBAC, Best-Effort for Moderation

- `core/users.py` grant/revoke: audit is transactional (same session, same commit)
- `feed/routes.py` moderate: audit is try/except (status change must not fail on audit)

Rationale: RBAC mutations are rare admin ops where integrity > availability.
Moderation is frequent and user-facing where availability > audit completeness.

### 12.3 Cache Prefix Coupling

Both the Directus webhook handler and `moderate_action()` must use the same
cache prefix strings (`feed_items:`, `questions:`). There is no shared constant
enforcing this — it's a known coupling point.

### 12.4 Admin Storage is a Pass-Through

`admin/storage.py` delegates entirely to `core/users.py`. It holds zero SQL.
The shim exists so the route layer stays HTTP-only and admin-specific read
shaping can be added later without touching core.

### 12.5 Media as Large Objects

Media is stored as Postgres large objects (not filesystem, not S3). This is a
final decision (ADR 0001). Benefits: transactional consistency, seekable
streaming, single backup unit. Cost: `vacuumlo` cron sweep needed to clean
orphans; `lo_unlink` trigger handles deletions.

---

## 13. File Map (Quick Reference)

```
dept-deploy/
├── CLAUDE.md                  # AI agent project rules (voice, style, brand, agents)
├── CONTRIBUTING.md            # branching, PRs, releases
├── DEPLOY.md                  # production deploy guide
├── LOCAL-SETUP.md             # local development setup
├── README.md                  # bundle overview
├── MEDIA.md                   # media pipeline docs
├── deploy.sh                  # one-command VM installer
├── start_local.sh             # local dev launcher
│
├── backend/                   # FastAPI application
│   ├── app/core/              #   shared layers (config, db, cache, users, security)
│   ├── app/modules/           #   feature modules (auth, quiz, feed, media, content, cms, admin)
│   ├── data/question_bank.json #  300-question CCA-F bank
│   ├── migrations/            #   Alembic (0001–0008)
│   ├── scripts/               #   ops scripts (migrate, seed, backfill, upload)
│   ├── templates/             #   Jinja2 HTML (login, quiz, admin, verify)
│   └── tests/                 #   pytest suite
│
├── frontend/                  # Buildless ES-module SPA
│   ├── core/                  #   router, API client, auth UI, theme
│   ├── modules/               #   course reader, feed, moderation
│   └── shared/                #   block renderers, registry, framework
│
├── content/
│   ├── frozen/                # rendered HTML (course, runbook, checklist, FAQs)
│   └── source/                # JSON source of truth + schemas + validation
│
├── cms/                       # Directus CMS config
│   ├── docker-compose.yml
│   ├── bootstrap.sh
│   ├── register-collections.mjs
│   └── snapshot.yaml
│
├── docs-site/                 # Docusaurus documentation
│   └── docs/                  #   system-architecture, database, frontend, deployment, etc.
│
├── docs/architecture/v2/      # v2 architecture decision records (00–08 + phase reports)
├── prompt-library/            # reusable prompts + sample apps
├── tests/baseline/            # smoke tests, fixtures, parity contracts
├── infra/                     # certbot, cron
└── graphify-out/              # knowledge graph outputs (graph.json, GRAPH_REPORT.md)
```

---

## 14. Known Coupling Points & Risks

Derived from knowledge graph analysis (god nodes, surprising connections,
community boundaries).

| Risk | Location | Impact |
|---|---|---|
| `get_session()` change | `core/db.py:L99` | Breaks all 13 dependent communities |
| `esc()` change | `shared/dom.js:L4` | Breaks all frontend block renderers (72 edges) |
| Cache prefix mismatch | `feed/routes.py` vs `cms/routes.py` | Stale data in feed/questions |
| Remote Postgres latency | `config.py` TLS requirement | +5–15ms per cert verification |
| Admin storage alias import | `admin/storage.py:L15` | AST tools may miss the delegation edge |
| `moderate_action()` audit gap | `feed/routes.py:L161` | Non-transactional audit (by design) |

---

## 15. How to Use This Document

1. **Drop this file** into the system prompt, project context, or CLAUDE.md
   equivalent of any AI coding assistant.
2. **For codebase questions**, prefer the knowledge graph if available:
   ```bash
   graphify query "How does X connect to Y?"
   graphify path "FunctionA" "FunctionB"
   graphify explain "ConceptName"
   ```
3. **For content changes**, follow the agent orchestration workflow (§10).
4. **For code changes**, understand the module boundaries (§2.2) and coupling
   points (§14) before editing.
5. **For deployment**, follow `DEPLOY.md` for production or `LOCAL-SETUP.md`
   for local dev.

---

*Generated from the dept-deploy v2 branch knowledge graph (graphify) and
verified against source code. Last updated: 2026-06-06.*
