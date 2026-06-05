# v2/01 — Blueprint: directory tree, module boundaries, migration maps

> Phase 0 design contract · Owner: Blueprint agent · Covers 12-item plan items **1** (restructure / modular monolith / buildless FE) and **12** (navigation / IA / segregation).
> Read [`docs/architecture/v2-plan.md`](../v2-plan.md) first. This document is what **Phase 1** executes literally.
> DESIGN ONLY — nothing here is applied yet. No code is modified in Phase 0.

This blueprint is grounded in a full read of the current tree on branch `v2`. Where a claim depends on a real file it is cited as `path:line`.

---

## 0. Current-state facts that shape the design (verified)

These pin the decisions below. Each is checked against the repo, not assumed.

1. **`quiz-certification/` is the whole backend, not the quiz.** One FastAPI app (`quiz-certification/app/main.py`) holds quiz, feed, course-content, media, moderation, admin, auth and session routes — see the route map at `main.py:1-30` and the mounts at `main.py:63-64`.
2. **`dev_quiz.py` and `review.py` are dead.** The live import line is `main.py:48` — `from . import auth, certificate, config, email_service, quiz_generator, roles, storage, encryption, media_service`. Neither `dev_quiz` nor `review` appears. `git ls-files` shows `dev_quiz.py` is **untracked**; `review.py` is tracked but imported by nothing in the app (it is a standalone CLI: `review.py:1-10`). The `{% if dev_mode %}` / `devQuiz` references in `templates/home.html` and `templates/quiz.html` are **stale leftovers** — the backend wiring they describe in the `dev_quiz.py` removal checklist (`dev_quiz.py:8-23`) was already partly removed (no `dev_quiz` import, no `dev_quiz` branch in `quiz_start`, `grade()` still carries a backward-compatible `pass_mark=None` at `quiz_generator.py:169-170`).
3. **The MP4 is not in git.** `media/Anatomy of Code.mp4` (48 MB) exists on disk and is referenced by `app/js/modes/scroll.js:21` (`../media/Anatomy%20of%20Code.mp4`) and by the ETL `scripts/migrate_to_postgres.py:29`, but it is **untracked**. v2 must define a home and a `.gitignore`/asset policy for it; it is not moved by git.
4. **Resources are duplicated, mostly byte-identical.** `app/resources/code-coder-checklist.html` ≡ `content-system/code-coder-checklist.html`; `app/resources/faqs/aem-banking-faq.html` ≡ `content-system/faqs/aem-banking-faq.html`; `app/resources/faqs/index.html` ≡ `content-system/faqs/index.html` (all `diff -q` IDENTICAL). `architect-runbook.html` differs **only** in three back-link `href` values (course/checklist/faqs relative paths). `RUNBOOK-TEMPLATE.html` and `runbook-outline.xlsx` exist **only** under `app/resources/`.
5. **Front-end talks to the API same-origin, with two relative-path exceptions.** `util/load.js:9-23` rewrites `content-architecture/...` URLs to `/api/course/...`; `feed/store.js` and `feed/auth.js` fetch `/api/feed*`, `/auth/me`, `/login/dev`, `/logout`. **But** `feed/validate.js:57` fetches `` `${base}/schemas/feed.schema.json` `` and `scroll.js:21` loads `../media/...` — relative paths that only resolve when served from repo root in dev, and **break** under Apache `/app/` in prod (there is no `/content-architecture/` or `/media/` Alias — see `deploy.sh:493-497, 852-915`). v2 fixes both via API endpoints.
6. **Apache layout (current).** `deploy.sh` serves `/anatomy/` → `content-system/` static (`deploy.sh:852-857, 895-900`), `/app/` → `app/` static SPA with `FallbackResource /app/index.html` (`deploy.sh:859-865, 902-908`), and proxies everything else `/` → FastAPI on `127.0.0.1:$QUIZ_PORT` (`deploy.sh:871-872, 914-915`). `ProxyPass /anatomy !` and `ProxyPass /app !` exclude the static aliases from the proxy.
7. **DB models already span all four content types.** `quiz-certification/app/models.py` defines `User, Attempt, Question, FeedItem, MediaAsset, CourseChapter, Framework` (`models.py:53-168`). Course content + framework + framework-explainer are **already in Postgres** (`storage.py:408-487`), and the API serves them DB-first with a filesystem fallback (`main.py:551-606`). This validates "Postgres-as-source" (Decision 2) as the smallest move.
8. **Naming drift.** `CLAUDE.md` says l0 outputs land in `prompts-library/`, but the real dir is `prompt-library/` (singular). v2 keeps the existing `prompt-library/` and does not rename it (out of scope; flagged only).

---

## 1. Exact v2 directory tree

Top-level layout. `[NEW]` = created in v2; everything else is a move/rename of an existing path. Runtime-only artefacts (`.venv/`, `__pycache__/`, `quiz_results/`, `certificates/`, `outbox/`, `*.db`) are git-ignored and not shown except where they need a `.gitkeep`.

```
dept-deploy/
├── backend/                              # the modular monolith  (was quiz-certification/)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                       # composes per-module APIRouters (skeleton in §3)
│   │   ├── core/                         # shared infrastructure — no business logic
│   │   │   ├── __init__.py
│   │   │   ├── config.py                 # was app/config.py  (settings registry)
│   │   │   ├── db.py                      # was app/db.py      (engine, Session, Base)
│   │   │   ├── models.py                  # was app/models.py  (all ORM tables — see §2 note)
│   │   │   ├── auth.py                    # was app/auth.py    (Google OAuth + RBAC dependency)
│   │   │   ├── encryption.py             # was app/encryption.py (AES-GCM payload crypto)
│   │   │   ├── security.py        [NEW]  # security middleware seam (headers/CORS/session) — Phase 2e fills
│   │   │   ├── cache.py           [NEW]  # app-cache seam (in-proc/Redis) — Phase 3b fills
│   │   │   └── deps.py            [NEW]  # shared FastAPI dependencies (require_user, require_role re-export)
│   │   ├── modules/
│   │   │   ├── __init__.py
│   │   │   ├── quiz/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── routes.py             # quiz/cert/history/admin/onboarding/profile routes
│   │   │   │   ├── service.py            # was app/quiz_generator.py (generate/grade/topic_summary)
│   │   │   │   ├── certificate.py        # was app/certificate.py (PDF render)
│   │   │   │   ├── email_service.py      # was app/email_service.py (cert email/outbox)
│   │   │   │   ├── roles.py              # was app/roles.py (persona→level; becomes profile attr — see authz doc)
│   │   │   │   ├── schemas.py     [NEW]  # Pydantic: StartQuizPayload, SubmitPayload, QuestionPayload (moved from main.py)
│   │   │   │   └── storage.py            # quiz/cert slice of app/storage.py (attempts, questions, users, signing)
│   │   │   ├── content/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── routes.py             # /api/course/* (framework, chapters, explainer)
│   │   │   │   ├── service.py            # course read logic + filesystem fallback
│   │   │   │   ├── etl.py                # was scripts/migrate_to_postgres.py (seed/import) — repointed paths
│   │   │   │   ├── schemas.py     [NEW]
│   │   │   │   └── storage.py            # chapters + framework + explainer slice of app/storage.py
│   │   │   ├── feed/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── routes.py             # /api/feed, /api/feed/flag, /api/moderate/* 
│   │   │   │   ├── service.py            # feed create/list, scenario→question fan-out, moderation actions
│   │   │   │   ├── schemas.py     [NEW]  # FlagFeedPayload, ModActionPayload (moved from main.py)
│   │   │   │   └── storage.py            # feed_items slice of app/storage.py
│   │   │   ├── media/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── routes.py             # /api/media/upload, /media/video/{id}, /media/image/{id}
│   │   │   │   ├── service.py            # was app/media_service.py (validate/store/stream large objects)
│   │   │   │   └── schemas.py     [NEW]
│   │   │   ├── auth/                [NEW]  # auth router — owns /auth/*, /login, /logout
│   │   │   │   ├── __init__.py     [NEW]
│   │   │   │   └── routes.py       [NEW]  # /auth/session-key, /auth/google, /auth/google/callback, /auth/me, /login, /login/dev, /logout
│   │   │   └── cms/                [NEW]  # Directus integration seam — Phase 4 fills
│   │   │       ├── __init__.py
│   │   │       ├── routes.py      [NEW]  # webhook receiver (Directus → invalidate cache / re-seed)
│   │   │       └── service.py     [NEW]  # read adapters over the shared Postgres
│   │   ├── templates/                    # was quiz-certification/templates/ (Jinja, 8 files)
│   │   └── static/                       # was quiz-certification/static/ (style.css)
│   ├── migrations/                [NEW]  # Alembic — Phase 2a (replaces db._migrate())
│   ├── scripts/
│   │   ├── __init__.py                   # was quiz-certification/scripts/__init__.py
│   │   ├── seed.py                       # thin CLI → modules/content/etl.py  (was migrate_to_postgres.py entry)
│   │   ├── upload_media.py               # was scripts/upload_media.py (import repointed)
│   │   ├── list_media.py                 # was scripts/list_media.py   (import repointed)
│   │   └── validate_questions.py         # was quiz-certification/validate_questions.py
│   ├── data/
│   │   └── question_bank.json            # was quiz-certification/data/question_bank.json (git seed)
│   ├── tests/
│   │   └── test_backend_features.py      # was quiz-certification/tests/
│   ├── requirements.txt                  # was quiz-certification/requirements.txt
│   ├── Dockerfile                        # was quiz-certification/Dockerfile (CMD path unchanged: app.main:app)
│   ├── .env.example                      # was quiz-certification/.env.example
│   └── README.md                         # was quiz-certification/README.md (rewrite scope-wise)
│
├── frontend/                             # buildless ES-module SPA  (was app/)
│   ├── index.html                        # was app/index.html (nav shell; resource hrefs repointed → §7)
│   ├── core/                             # app-level wiring
│   │   ├── main.js                       # was app/js/main.js (router + bootstrap)
│   │   ├── config.js             [NEW]   # centralised constants: API_BASE, QUIZ_URL, SECTION_FILES, THEME_KEY, MEDIA paths
│   │   ├── theme.js              [NEW]   # theme manager (extracted from main.js applyTheme/initTheme/toggle)
│   │   ├── api-client.js         [NEW]   # single fetch wrapper; absolute-from-config URLs (replaces ad-hoc fetch())
│   │   └── router.js             [NEW]   # hash router (extracted from main.js route()) — optional split; see §4
│   ├── shared/                           # framework-agnostic rendering toolkit
│   │   ├── registry.js                   # was app/js/registry.js (block + feed dispatch)
│   │   ├── blocks/                       # was app/js/blocks/* (14 renderers, unchanged)
│   │   │   ├── architectsReview.js  callout.js  cardgrid.js  chapterOpen.js  chips.js
│   │   │   ├── code.js  diagram.js  heading.js  lead.js  map.js
│   │   │   └── notes.js  prose.js  quote.js  tierlist.js
│   │   ├── render/                       # was app/js/render/*
│   │   │   ├── chapter.js  diagram.js  explainer.js
│   │   └── util/                         # was app/js/util/*
│   │       ├── dom.js                     # esc/raw helpers
│   │       ├── framework.js               # framework load/index/order
│   │       └── load.js                    # loadJSON → API rewrite (now reads core/config.js API_BASE)
│   ├── modules/
│   │   ├── course/
│   │   │   ├── scroll.js                  # was app/js/modes/scroll.js  ("Manual" mode; video src via config)
│   │   │   └── read.js                    # was app/js/modes/read.js    ("Read" mode)
│   │   ├── feed/                          # was app/js/feed/* + app/js/modes/feed.js
│   │   │   ├── mode.js                     # was app/js/modes/feed.js (the Feed view)
│   │   │   ├── store.js                    # was app/js/feed/store.js  (THE feed data seam)
│   │   │   ├── auth.js                     # was app/js/feed/auth.js   (sign-in gate)
│   │   │   ├── validate.js                 # was app/js/feed/validate.js (schema fetch repointed → API)
│   │   │   ├── composer.js  envelope.js  media.js
│   │   │   ├── card.js  list.js  post.js  scenario.js  video.js  vocab.js
│   │   ├── quiz/
│   │   │   └── link.js            [NEW]   # owns the Quiz launch (QUIZ_URL from config) — extracted from main.js initChrome
│   │   └── auth/
│   │       └── auth-ui.js                 # was app/js/auth-ui.js (global sign-in chrome)
│   ├── styles/                           # was app/css/*
│   │   ├── monolith.css                   # FROZEN design system, copied from the monolith — do not edit
│   │   ├── tokens.css            [NEW]    # (optional) extracted brand vars; only if §4 split is taken — else omit
│   │   ├── app.css                        # was app/css/app.css
│   │   ├── read.css                        # was app/css/read.css
│   │   └── feed.css                        # was app/css/feed.css
│   └── tests/                            # was app/tests/
│       ├── equivalence.html
│       └── monolith-refs.js
│
├── content/                              # consolidated source-of-truth  (was content-architecture/ + content-system/)
│   ├── source/                           # the editable git seed (exported from / imported into Postgres)
│   │   ├── course/
│   │   │   ├── framework.json
│   │   │   ├── framework-explainer.json
│   │   │   └── sections/                  # all 31 anatomy/code/coder/adobe/ai chapter JSON
│   │   └── feed/
│   │       └── feed.json
│   ├── schemas/                          # was content-architecture/schemas/
│   │   ├── course.schema.json
│   │   └── feed.schema.json
│   ├── validate.py                       # was content-architecture/validate.py (ROOT repointed → content/source)
│   ├── frozen/
│   │   └── anatomy-of-code-course.html   # the FROZEN 578 KB monolith — visual-parity reference + served at /anatomy
│   ├── resources/                        # SINGLE SOURCE OF TRUTH for runbooks/checklist/faqs (resolves the dup)
│   │   ├── architect-runbook.html
│   │   ├── code-coder-checklist.html
│   │   ├── RUNBOOK-TEMPLATE.html
│   │   ├── runbook-outline.xlsx
│   │   └── faqs/
│   │       ├── aem-banking-faq.html
│   │       └── index.html
│   ├── docs/adr/0001-storage.md          # was content-architecture/docs/adr/0001-storage.md (superseded note added)
│   ├── SCHEMA.md                         # was content-architecture/SCHEMA.md
│   └── MIGRATION-GAP.md                  # was content-architecture/MIGRATION-GAP.md
│
├── assets/                        [NEW]  # large binary media (NOT in git; documented + gitignored)
│   └── Anatomy of Code.mp4               # was media/Anatomy of Code.mp4 (untracked; ETL ingests → Postgres LO)
│
├── cms/                           [NEW]  # Directus project — Phase 4 fills
│   ├── README.md                 [NEW]
│   ├── docker-compose.directus.yml [NEW]
│   ├── schema/                   [NEW]   # Directus schema snapshots
│   └── extensions/               [NEW]
│
├── infra/                                # all deploy/runtime ops  (was root-level scripts)
│   ├── deploy.sh                         # was ./deploy.sh (all paths repointed — §7)
│   ├── start_local.sh                    # was ./start_local.sh (paths repointed — §7)
│   ├── deploy.env.example                # was ./deploy.env.example
│   └── apache/                   [NEW]   # (optional) extracted vhost template; deploy.sh may keep inlining
│
├── docs/
│   └── architecture/
│       ├── v2-plan.md
│       └── v2/                           # these Phase 0 contracts (01-blueprint.md … 08-docs-plan.md)
│
├── docs-site/                     [NEW]  # Docusaurus — Phase 5a (scaffold stubbed in Phase 0 docs task)
│
├── tests/
│   └── baseline/                  [NEW]  # parity safety net — owned by the Baseline/parity agent
│
├── prompt-library/                       # UNCHANGED (note: CLAUDE.md says "prompts-library"; real dir is singular)
├── CLAUDE.md                             # UNCHANGED in Phase 1 (paths inside reviewed in Phase 5)
├── README.md                             # rewrite to describe the v2 layout (Phase 1 tail)
├── CONTRIBUTING.md  DEPLOY.md  MEDIA.md  # updated for new paths (Phase 1 / Phase 3)
└── .gitignore                            # add assets/*.mp4, backend/**/.venv, *.db, etc.
```

### Notes on the tree

- **`backend/app/` keeps the `app` package name** so the systemd/uvicorn/Docker target `app.main:app` does not change (`deploy.sh:761`, `Dockerfile` CMD, `start_local.sh:93`). Only the *parent* folder renames `quiz-certification/` → `backend/`. This is the lowest-risk choice and keeps `from app import config` working in scripts.
- **`core/models.py` holds all ORM tables in one module** (`User, Attempt, Question, FeedItem, MediaAsset, CourseChapter, Framework`). Splitting models per-module is tempting but the tables share FKs (`Attempt.user_email`, `Question.author_id`, `FeedItem.author_id`, `MediaAsset.uploaded_by` all → `users.email`, see `models.py:79,110,125,145`) and Alembic autogenerate wants one metadata. Per-module `storage.py` files import the shared models — this gives module ownership of *queries* without fragmenting the schema. (Data-model agent owns the final call in `v2/03`.)
- **`styles/tokens.css` and `core/router.js` are marked optional.** They are clean extractions, but Phase 1's hard constraint is **visual + behavioural parity**. If extracting them risks parity, Phase 1 may leave `main.js` holding the router and `monolith.css` holding the tokens. The split is a nice-to-have, not a gate.

---

## 2. Backend module boundaries

### 2.1 Per-module file convention

Every module under `backend/app/modules/<name>/` follows:

| File | Responsibility |
|---|---|
| `routes.py` | `APIRouter` instance named `router`; endpoint functions only; thin — parse request, call `service`, shape response. |
| `service.py` | Business logic; no FastAPI imports; calls `storage` + `core` helpers. |
| `storage.py` | DB access for this module's tables (queries, writes). Imports shared models from `core.models`. |
| `schemas.py` | Pydantic request/response models (moved out of `main.py`). |
| module-specific | `certificate.py`, `email_service.py`, `roles.py`, `etl.py` live with the module that owns them. |

`core/` holds **shared infrastructure only** (no domain logic): `config.py`, `db.py`, `models.py`, `auth.py`, `encryption.py`, plus new seams `security.py`, `cache.py`, `deps.py`.

### 2.2 Every current `app/*.py` module → v2 home

| Current file | Lines | v2 home | Action |
|---|---|---|---|
| `app/main.py` | 863 | split across `core/` + every `modules/*/routes.py` + `app/main.py` (composition only) | **split** — see route table §2.3 |
| `app/config.py` | 74 | `core/config.py` | move; `BASE_DIR` recompute (§7) |
| `app/db.py` | 89 | `core/db.py` | move; `_migrate()` retired by Alembic in Phase 2a |
| `app/models.py` | 168 | `core/models.py` | move (all tables stay together) |
| `app/auth.py` | 137 | `core/auth.py` | move; `require_role` re-exported via `core/deps.py` |
| `app/encryption.py` | 57 | `core/encryption.py` | move |
| `app/storage.py` | 487 | **split** into `modules/quiz/storage.py` + `modules/content/storage.py` + `modules/feed/storage.py` (+ shared user helpers) | **split** — see §2.4 |
| `app/quiz_generator.py` | 196 | `modules/quiz/service.py` | move + rename |
| `app/certificate.py` | 160 | `modules/quiz/certificate.py` | move |
| `app/email_service.py` | 98 | `modules/quiz/email_service.py` | move |
| `app/roles.py` | 39 | `modules/quiz/roles.py` | move (persona→profile-attribute change is AuthZ doc's call, not Phase 1) |
| `app/media_service.py` | 153 | `modules/media/service.py` | move + rename |
| `app/dev_quiz.py` | 27 | — | **delete** (untracked, unimported; see §0.2) |
| `app/review.py` | 134 | — | **delete** (CLI superseded by `scripts/`; unimported by app) — *confirm with user; it is a tracked file* |
| `app/__init__.py` | — | `app/__init__.py` | keep |

### 2.3 Every `main.py` route → v2 module

Source line ranges from `quiz-certification/app/main.py`.

| Route | Method | `main.py` | v2 module → file | tag |
|---|---|---|---|---|
| `/auth/session-key` | GET | 139 | `auth` → `modules/auth/routes.py` | `auth` |
| `/` (home) | GET | 150 | `quiz` → `routes.py` | `quiz` |
| `/login` | GET | 181 | `auth` → `modules/auth/routes.py` (auth UI) | `auth` |
| `/login/dev` | POST | 188 | `auth` → `modules/auth/routes.py` | `auth` |
| `/auth/google` | GET | 213 | `auth` → `modules/auth/routes.py` | `auth` |
| `/auth/google/callback` | GET | 222 | `auth` → `modules/auth/routes.py` | `auth` |
| `/logout` | GET | 248 | `auth` → `modules/auth/routes.py` | `auth` |
| `/onboarding/role` | GET/POST | 256 / 267 | `quiz` → `routes.py` | `quiz` |
| `/profile/role` | GET/POST | 284 / 295 | `quiz` → `routes.py` | `quiz` |
| `/quiz/start` | POST | 306 | `quiz` → `routes.py` (svc: `service.generate`) | `quiz` |
| `/quiz/submit` | POST | 351 | `quiz` → `routes.py` (svc: `service.grade`, `certificate`, `email_service`) | `quiz` |
| `/quiz/take` | GET | 447 | `quiz` → `routes.py` | `quiz` |
| `/certificate/{cert_id}` | GET | 465 | `quiz` → `routes.py` (`certificate.generate`) | `quiz` |
| `/history` | GET | 479 | `quiz` → `routes.py` | `quiz` |
| `/verify`, `/verify/{cert_id}` | GET | 488 / 507 | `quiz` → `routes.py` | `quiz` |
| `/admin/attempts` | GET | 514 | `quiz` → `routes.py` (RBAC `QuizManager`) | `admin` |
| `/auth/me` | GET | 521 | `auth` → `modules/auth/routes.py` | `auth` |
| `/api/course/framework` | GET | 551 | `content` → `routes.py` | `content` |
| `/api/course/chapters` | GET | 560 | `content` → `routes.py` | `content` |
| `/api/course/chapters/{filename}` | GET | 567 | `content` → `routes.py` | `content` |
| `/api/course/framework-explainer` | GET | 576 | `content` → `routes.py` (FS fallback → `service`) | `content` |
| `/api/feed` | GET | 615 | `feed` → `routes.py` | `feed` |
| `/api/feed/flag` | POST | 621 | `feed` → `routes.py` | `feed` |
| `/api/feed` | POST | 649 | `feed` → `routes.py` (scenario→question fan-out → `service`) | `feed` |
| `/api/moderate/queue` | GET | 681 | `feed` → `routes.py` (RBAC `Moderator`) | `moderation` |
| `/api/moderate/action` | POST | 693 | `feed` → `routes.py` (RBAC `Moderator`) | `moderation` |
| `/api/admin/questions` | POST | 740 | `quiz` → `routes.py` (RBAC `QuizManager`) | `admin` |
| `/api/media/upload` | POST | 752 | `media` → `routes.py` (RBAC `FeedCreator`) | `media` |
| `/media/video/{asset_id}` | GET | 812 | `media` → `routes.py` (range streaming) | `media` |
| `/media/image/{asset_id}` | GET | 850 | `media` → `routes.py` | `media` |
| **Static mount** `/static` | — | 63 | `app/main.py` (`core` static) | — |
| **Static mount** `/app` | — | 64 | **REMOVE** — FE is served by Apache `/app/`, not FastAPI (§7) | — |
| **Helpers** `_require_user*`, `_template`, `_refresh_session_user`, `_decrypt_request_payload`, `_encrypt_response_payload` | — | 79-134 | `core/deps.py` + `quiz/routes.py` (template helper) | — |
| **In-mem** `_active_quizzes` | — | 69 | `modules/quiz/service.py` module-level (note: not multi-worker safe — flagged for Data-model/caching) | — |
| **Pydantic models** | — | 302, 346, 611, 687, 729 | respective `modules/*/schemas.py` | — |

> The `/api/media/upload` and `/api/feed` handlers carry real logic inline today (size caps `main.py:771-809`; scenario→question creation `main.py:657-675`). Phase 1 moves that logic into `media/service.py` and `feed/service.py` respectively, leaving `routes.py` thin.

### 2.4 `storage.py` split map

`app/storage.py` (487 lines) splits by table ownership; shared user/signing helpers go to a small `core` surface so all three modules can call them.

| Current `storage.py` region | Lines | v2 home |
|---|---|---|
| `_sign_payload`/`sign_attempt`/`verify_signature` | 21-46 | `modules/quiz/storage.py` (cert signing is quiz-owned) |
| test-code gen (`generate_test_code`, `_generate_unique_code`) | 54-63, 178-186 | `modules/quiz/storage.py` |
| user helpers (`upsert_user`, `set_user_role`, `get_user`, `_user_to_dict`) | 68-114 | `core/users.py` *(shared)* — every plane reads users |
| attempts (`save_attempt`, `attempts_for`, `last_attempt`, `cooldown_*`, `has_passed`, `all_attempts`, `attempt_by_cert_id*`, `_attempt_to_dict`) | 119-263 | `modules/quiz/storage.py` |
| questions (`save_question`, `get_questions_queue`, `_question_to_dict`) | 268-339 | `modules/quiz/storage.py` (shared read by feed via import) |
| feed (`save_feed_item`, `get_feed_items`, `get_moderation_queue`) | 344-396 | `modules/feed/storage.py` |
| course/framework (`save_chapter`, `get_chapter`, `get_all_chapters`, `save_framework`, `get_framework`, `save_framework_explainer`, `get_framework_explainer`) | 408-487 | `modules/content/storage.py` |
| `_parse_iso`, `get_session`/`init_db` re-export | 15, 401-405 | `core/db.py` (already there) + small shared util |

> `get_moderation_queue` (`storage.py:379-396`) reads **both** `FeedItem` and `Question`. It lives in `feed/storage.py` and imports `Question` from `core.models` (and the question→dict helper from quiz). Cross-module *reads* via shared models are allowed; cross-module *writes* go through the owning module's service.

---

## 3. Router-mount scheme + new `main.py` skeleton

`backend/app/main.py` becomes composition-only: build the app, attach middleware, mount static, register lifespan, and `include_router` each module. Prefixes/tags below.

| Router | `prefix` | `tags` | source |
|---|---|---|---|
| auth | `""` (root — keeps `/auth/*`, `/login`, `/login/dev`, `/logout`) | `auth` | `modules/auth/routes.py` |
| quiz (incl. onboarding/cert/verify/admin questions) | `""` (root — keeps `/`, `/quiz/*`, `/certificate/*`, `/verify`, `/history`, `/onboarding/*`, `/profile/*`, `/admin/*`) | `quiz`, `admin` | `modules/quiz/routes.py` |
| content | `/api/course` | `content` | `modules/content/routes.py` |
| feed | `/api` (so `/api/feed`, `/api/moderate/*`) | `feed`, `moderation` | `modules/feed/routes.py` |
| media | `""` (keeps `/api/media/upload` + `/media/*`) | `media` | `modules/media/routes.py` |
| cms (Phase 4) | `/api/cms` | `cms` | `modules/cms/routes.py` |

> Existing URLs are **preserved exactly** so the front-end and issued certificates keep working (hard constraint). Prefixes are chosen to reproduce today's paths, not to prettify them. Path normalisation (if any) is a later, parity-gated decision.

```python
# backend/app/main.py  (v2 skeleton — composition only)
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core import config, db, security
from app.modules.auth import routes as auth_routes
from app.modules.quiz import routes as quiz_routes
from app.modules.content import routes as content_routes
from app.modules.feed import routes as feed_routes
from app.modules.media import routes as media_routes
# from app.modules.cms import routes as cms_routes   # Phase 4


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()            # Phase 2a: replaced by Alembic-migrated startup check
    yield


app = FastAPI(title="DEPT® Anatomy of Code · Backend", lifespan=lifespan)

# --- middleware (order matters: outermost first) ---
security.install_middleware(app)   # CORS + SessionMiddleware + security headers
                                   # (moves main.py:54-61 behind one seam; Phase 2e/3c harden)

# --- static + templates ---
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
# NOTE: the old app.mount("/app", ...) (main.py:64) is REMOVED.
#       Apache serves the SPA at /app/; FastAPI no longer needs it.
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
quiz_routes.bind_templates(templates)   # quiz routes own the Jinja pages

# --- routers ---
app.include_router(auth_routes.router,    tags=["auth"])
app.include_router(quiz_routes.router,    tags=["quiz"])
app.include_router(content_routes.router, prefix="/api/course", tags=["content"])
app.include_router(feed_routes.router,    prefix="/api",         tags=["feed"])
app.include_router(media_routes.router,   tags=["media"])
# app.include_router(cms_routes.router,   prefix="/api/cms",     tags=["cms"])  # Phase 4
```

Where things live:
- **Middleware** — `core/security.py:install_middleware(app)` wraps the current `CORSMiddleware` + `SessionMiddleware` (`main.py:54-61`) so Phase 2e/3c can add CSP/HSTS/headers in one place. `SessionMiddleware` secret still comes from `config.SECRET_KEY`.
- **Static mount** — only `/static` remains. `/app` mount is deleted (Apache owns it).
- **`/static/` ownership (v2 lock).** `/static/` stays **FastAPI-proxied via Apache** for v2 — Apache forwards `/static/*` through the same `ProxyPass /` rule that serves the API; FastAPI's `StaticFiles` mount at `config.STATIC_DIR` answers. **Not** an Apache `Alias`. This keeps the Jinja templates' `{{ url_for('static', ...) }}` references stable and lets FastAPI own cache headers for templated pages. (The standalone SPA at `/app/` remains the only Apache-aliased static surface.) Caching doc `v2/06` and CSP doc `v2/07` reference this lock for cache-rule and `style-src` decisions.
- **Lifespan** — replaces the deprecated `@app.on_event("startup")` (`main.py:72-74`) with the `lifespan` context manager; still calls `db.init_db()` until Alembic lands.
- **Templates** — Jinja pages belong to the quiz module (it owns every HTML route). `bind_templates` injects the shared `Jinja2Templates` instance so `_template()` helper logic (`main.py:95-99`) moves into `quiz/routes.py`.

---

## 4. Front-end mapping

### 4.1 File-by-file: `app/js/*` and `app/css/*` → `frontend/*`

| Current | v2 path | Action / notes |
|---|---|---|
| `app/index.html` | `frontend/index.html` | move; repoint resource hrefs (`index.html:28-35`) → §7; `<script src="js/main.js">` → `core/main.js` |
| `app/js/main.js` | `frontend/core/main.js` | move; extract `QUIZ_URL`/`BASE`/`SECTION_FILES`/`THEME_KEY` (`main.js:13-29`) → `core/config.js`; theme fns (`main.js:34-48`) → `core/theme.js`; quiz-link (`main.js:52-54`) → `modules/quiz/link.js` |
| `app/js/registry.js` | `frontend/shared/registry.js` | move; import paths to `./blocks/*`, `./feed/*` (now `../modules/feed/*`) updated → §7 |
| `app/js/auth-ui.js` | `frontend/modules/auth/auth-ui.js` | move; import of `./feed/auth.js` → `../feed/auth.js` |
| `app/js/blocks/*.js` (14) | `frontend/shared/blocks/*.js` | move; imports `../util/dom.js` unchanged (sibling of `shared/`) |
| `app/js/render/*.js` (chapter, diagram, explainer) | `frontend/shared/render/*.js` | move; `../util/dom.js` import unchanged |
| `app/js/util/dom.js` | `frontend/shared/util/dom.js` | move |
| `app/js/util/framework.js` | `frontend/shared/util/framework.js` | move; imports `./load.js` unchanged |
| `app/js/util/load.js` | `frontend/shared/util/load.js` | move; rewrite to read `API_BASE` from `core/config.js` (currently hardcodes `/api/...` at `load.js:12-18`) |
| `app/js/modes/scroll.js` | `frontend/modules/course/scroll.js` | move; `MANUAL_VIDEO_SRC` (`scroll.js:21`) → API/config (§5, §7); imports `../util/*`,`../registry.js` → `../../shared/*` |
| `app/js/modes/read.js` | `frontend/modules/course/read.js` | move; imports → `../../shared/*` |
| `app/js/modes/feed.js` | `frontend/modules/feed/mode.js` | move + rename; imports `../feed/*` → `./` , `../registry.js`/`../util/*` → `../../shared/*` |
| `app/js/feed/*.js` (store, auth, validate, composer, envelope, media, card, list, post, scenario, video, vocab) | `frontend/modules/feed/*.js` | move; `validate.js:57` schema fetch repointed → API (§5,§7); cross-imports to `../util/*`,`../render/*` → `../../shared/*` |
| `app/css/monolith.css` | `frontend/styles/monolith.css` | move; **frozen** — never edited |
| `app/css/app.css` | `frontend/styles/app.css` | move |
| `app/css/read.css` | `frontend/styles/read.css` | move |
| `app/css/feed.css` | `frontend/styles/feed.css` | move |
| `app/tests/equivalence.html` | `frontend/tests/equivalence.html` | move; update relative refs in `monolith-refs.js` if any |
| `app/tests/monolith-refs.js` | `frontend/tests/monolith-refs.js` | move |

### 4.2 Where centralised concerns live (new files)

- **`core/config.js`** — single source for `API_BASE` (default `''` = same origin, the prod truth via Apache proxy), `QUIZ_URL` (the `location.protocol` logic from `main.js:13-15`), `SECTION_FILES` (the 31-entry list `main.js:18-28`), `THEME_KEY` (`main.js:29`), and `MEDIA` paths (the explainer MP4 — see §5). Everything that is "one constant to repoint" lives here.
- **`core/theme.js`** — `applyTheme`, `initTheme`, `window.toggleAppTheme` (extracted from `main.js:34-48`). Per-page `localStorage` theme key behaviour preserved (CLAUDE.md brand constraint).
- **`core/api-client.js`** — one `apiFetch(path, opts)` wrapper that prefixes `config.API_BASE`, sets `cache` defaults, and centralises error shaping. `util/load.js`, `feed/store.js`, `feed/auth.js`, `feed/validate.js` migrate their bare `fetch()` calls onto it. This is the seam the caching/perf doc (`v2/06`) and config doc lean on.
- **`core/router.js`** *(optional split)* — the hash router `route()`/`setActiveTab()` (`main.js:85-112`). May stay in `main.js` if extraction risks parity.
- **`modules/quiz/link.js`** — owns wiring the Resources→Quiz anchor to `config.QUIZ_URL` (`main.js:52-54`).
- **Nav shell** — stays in `frontend/index.html` `<header class="app-bar">` (`index.html:17-41`). The unified-navigation work (Phase 4b) edits this shell; Phase 1 only repoints its resource hrefs.

### 4.3 Resources duplication — single source of truth

**Decision: `content/resources/` is the canonical home.** The SPA links to it via Apache, not via a copy under `frontend/`.

Rationale (from §0.4): three of the five resource files are byte-identical across `app/resources/` and `content-system/`; keeping two copies is the bug. `content/resources/` sits beside the frozen monolith and the course source, which is where editors expect "the docs."

Phase 1 actions:
- Keep one copy of each file under `content/resources/` (and `content/resources/faqs/`).
- Delete `app/resources/*` and the duplicate `content-system/*.html` non-course files (the course HTML itself goes to `content/frozen/`).
- For `architect-runbook.html`, keep the **`content-system` variant's** internal back-links as the base and normalise its three differing hrefs (course/checklist/faqs) to the new `content/` relative layout (the diff is only those three lines).
- Apache: add an Alias for `/resources/` → `content/resources/` (new) **or** fold resources under the existing `/anatomy/` alias. Recommended: serve them under `/anatomy/` (course + companions together), so the SPA's Resources dropdown hrefs become `/anatomy/code-coder-checklist.html`, `/anatomy/architect-runbook.html`, `/anatomy/faqs/...` — consistent with the cert PDF's `verify` and the course's own home. `index.html` hrefs change accordingly (§7).

---

## 5. Content consolidation

**Decision: collapse `content-architecture/` + `content-system/` into one `content/` tree, with Postgres as the editable source-of-truth (Decision 2) and `content/source/` as the git seed/export.**

Mapping:
- `content-architecture/course/*` + `content-architecture/feed/feed.json` → `content/source/{course,feed}/` — the canonical **git seed**. The ETL (`modules/content/etl.py`) imports these into Postgres on deploy; a future Directus export writes back here.
- `content-architecture/schemas/*` → `content/schemas/*` — used by `frontend/modules/feed/validate.js` (now via an API endpoint, §7) and by `content/validate.py`.
- `content-architecture/validate.py` → `content/validate.py` — `ROOT` recompute so it reads `content/source/...` (§7).
- `content-architecture/{SCHEMA.md, MIGRATION-GAP.md, docs/adr/0001-storage.md}` → `content/` (ADR gets a "Superseded by v2/03 — Postgres is now source" header; the data-model doc owns the formal supersede).
- `content-system/anatomy-of-code-course.html` → `content/frozen/anatomy-of-code-course.html` — **the frozen monolith.** It is the visual-parity reference (hard constraint) **and** the artefact Apache serves at `/anatomy/`. It is not regenerated from the source JSON; it is a frozen snapshot.
- `content-system/{architect-runbook, code-coder-checklist}.html` + `content-system/faqs/*` → `content/resources/` (single source, §4.3).

**Source-of-truth statement.** Postgres is authoritative at runtime (the API already serves course/framework/explainer DB-first, `main.py:551-606`). `content/source/*.json` is the version-controlled seed that bootstraps a fresh DB and the diff-able record of content; Directus (Phase 4) edits Postgres and exports back to `content/source/`. The frozen HTML monolith is neither source nor seed — it is a parity reference and a served artefact. (The data-model agent formalises the export/round-trip in `v2/03`.)

**Why not regenerate the monolith from JSON?** Parity is the gate and the 578 KB monolith is the reference being matched. Treat it as frozen; do not couple it to the seed.

**`/anatomy/` post-Phase-4 behaviour.** Once Directus authoring opens in Phase 4, `/anatomy/` continues to serve the **historical frozen monolith snapshot** — it does not pick up live edits. Live content flows only via the SPA (Postgres-backed). Phase 4 adds a banner on the monolith making the snapshot-vs-live split explicit to readers.

---

## 6. FILE-BY-FILE migration map

Action key: **MV** move/rename · **SP** split into multiple targets · **MG** merge (dedupe) · **DEL** delete · **NEW** create · **KEEP** unchanged location.

### Backend
| Current | v2 | Action | Notes |
|---|---|---|---|
| `quiz-certification/` (dir) | `backend/` | MV | folder rename; inner `app/` package name kept |
| `quiz-certification/app/main.py` | `backend/app/main.py` + `modules/*/routes.py` + `core/*` | SP | composition-only main; routes by §2.3 |
| `quiz-certification/app/config.py` | `backend/app/core/config.py` | MV | `BASE_DIR` recompute (§7) |
| `quiz-certification/app/db.py` | `backend/app/core/db.py` | MV | `_migrate()` → Alembic (Phase 2a) |
| `quiz-certification/app/models.py` | `backend/app/core/models.py` | MV | all tables together |
| `quiz-certification/app/auth.py` | `backend/app/core/auth.py` | MV | — |
| `quiz-certification/app/encryption.py` | `backend/app/core/encryption.py` | MV | — |
| `quiz-certification/app/storage.py` | `modules/{quiz,content,feed}/storage.py` + `core/users.py` | SP | per §2.4 |
| `quiz-certification/app/quiz_generator.py` | `modules/quiz/service.py` | MV | rename |
| `quiz-certification/app/certificate.py` | `modules/quiz/certificate.py` | MV | — |
| `quiz-certification/app/email_service.py` | `modules/quiz/email_service.py` | MV | — |
| `quiz-certification/app/roles.py` | `modules/quiz/roles.py` | MV | persona→profile is AuthZ-doc work, not Phase 1 |
| `quiz-certification/app/media_service.py` | `modules/media/service.py` | MV | rename |
| `quiz-certification/app/dev_quiz.py` | — | DEL | untracked + unimported (§0.2) |
| `quiz-certification/app/review.py` | — | DEL | tracked but unimported CLI — confirm with user |
| `quiz-certification/app/__init__.py` | `backend/app/__init__.py` | KEEP | — |
| `quiz-certification/scripts/migrate_to_postgres.py` | `modules/content/etl.py` + `scripts/seed.py` (thin entry) | SP/MV | `BASE_DIR` + paths repointed (§7) |
| `quiz-certification/scripts/upload_media.py` | `backend/scripts/upload_media.py` | MV | import repoint |
| `quiz-certification/scripts/list_media.py` | `backend/scripts/list_media.py` | MV | import repoint |
| `quiz-certification/scripts/__init__.py` | `backend/scripts/__init__.py` | KEEP | makes `python -m scripts.X` work |
| `quiz-certification/validate_questions.py` | `backend/scripts/validate_questions.py` | MV | `ROOT` recompute |
| `quiz-certification/data/question_bank.json` | `backend/data/question_bank.json` | MV | git seed for questions table |
| `quiz-certification/deploy_schema.sql` | — | DEL | superseded by Alembic + `models.create_all` — confirm; may keep as `migrations/legacy/` reference |
| `quiz-certification/templates/*.html` (8) | `backend/app/templates/*.html` | MV | dedupe `dev_mode`/`devQuiz` blocks in `home.html`,`quiz.html` (§0.2) |
| `quiz-certification/static/style.css` | `backend/app/static/style.css` | MV | `/static` mount unchanged |
| `quiz-certification/tests/test_backend_features.py` | `backend/tests/test_backend_features.py` | MV | — |
| `quiz-certification/requirements.txt` | `backend/requirements.txt` | MV | — |
| `quiz-certification/Dockerfile` | `backend/Dockerfile` | MV | CMD `app.main:app` unchanged |
| `quiz-certification/.env.example` | `backend/.env.example` | MV | — |
| `quiz-certification/README.md` | `backend/README.md` | MV | rewrite scope |
| `quiz-certification/{certificates,outbox,quiz_results}/.gitkeep` | `backend/...` (runtime dirs) | MV | stay gitignored; `.gitkeep` kept |

### Front-end
See the full table in §4.1. Summary of actions: all of `app/js/*` → `frontend/{core,shared,modules}/`, all `app/css/*` → `frontend/styles/`, `app/index.html` → `frontend/index.html`, `app/tests/*` → `frontend/tests/`. `app/resources/*` → **MG/DEL** into `content/resources/` (§4.3).

### Content
| Current | v2 | Action |
|---|---|---|
| `content-architecture/course/framework.json` | `content/source/course/framework.json` | MV |
| `content-architecture/course/framework-explainer.json` | `content/source/course/framework-explainer.json` | MV |
| `content-architecture/course/sections/*.json` (31) | `content/source/course/sections/*.json` | MV |
| `content-architecture/feed/feed.json` | `content/source/feed/feed.json` | MV |
| `content-architecture/schemas/{course,feed}.schema.json` | `content/schemas/*` | MV |
| `content-architecture/validate.py` | `content/validate.py` | MV (ROOT repoint) |
| `content-architecture/SCHEMA.md` | `content/SCHEMA.md` | MV |
| `content-architecture/MIGRATION-GAP.md` | `content/MIGRATION-GAP.md` | MV |
| `content-architecture/docs/adr/0001-storage.md` | `content/docs/adr/0001-storage.md` | MV (+ supersede note) |
| `content-architecture/.DS_Store` | — | DEL |
| `content-system/anatomy-of-code-course.html` | `content/frozen/anatomy-of-code-course.html` | MV |
| `content-system/architect-runbook.html` | `content/resources/architect-runbook.html` | MG (canonical; normalise 3 hrefs) |
| `content-system/code-coder-checklist.html` | `content/resources/code-coder-checklist.html` | MV (canonical) |
| `content-system/faqs/aem-banking-faq.html` | `content/resources/faqs/aem-banking-faq.html` | MV (canonical) |
| `content-system/faqs/index.html` | `content/resources/faqs/index.html` | MV (canonical) |
| `app/resources/code-coder-checklist.html` | — | DEL (identical dup) |
| `app/resources/architect-runbook.html` | — | DEL (variant; canonical kept from content-system) |
| `app/resources/faqs/aem-banking-faq.html` | — | DEL (identical dup) |
| `app/resources/faqs/index.html` | — | DEL (identical dup) |
| `app/resources/RUNBOOK-TEMPLATE.html` | `content/resources/RUNBOOK-TEMPLATE.html` | MV (only copy) |
| `app/resources/runbook-outline.xlsx` | `content/resources/runbook-outline.xlsx` | MV (only copy) |

### Infra / root / assets
| Current | v2 | Action |
|---|---|---|
| `deploy.sh` | `infra/deploy.sh` | MV (paths repointed — §7) |
| `start_local.sh` | `infra/start_local.sh` | MV (paths repointed — §7) |
| `deploy.env.example` | `infra/deploy.env.example` | MV |
| `media/Anatomy of Code.mp4` | `assets/Anatomy of Code.mp4` | MV on disk (untracked; gitignored) |
| `DEPLOY.md` | `DEPLOY.md` | KEEP (content updated for new paths) |
| `MEDIA.md` | `MEDIA.md` | KEEP (content updated) |
| `README.md` | `README.md` | KEEP (rewrite for v2 layout) |
| `CONTRIBUTING.md` | `CONTRIBUTING.md` | KEEP (paths updated) |
| `CLAUDE.md` | `CLAUDE.md` | KEEP (Phase 1 untouched; agent file-area lines reviewed Phase 5) |
| `prompt-library/**` | `prompt-library/**` | KEEP |
| `.claude/launch.json` | `.claude/launch.json` | UPDATE (static server root / port note — see Memory: feed store seam) |
| `.gitignore` | `.gitignore` | UPDATE (add `assets/*.mp4`, `backend/**/.venv`, `*.db`, `__pycache__`) |
| `docs-site/` | — | NEW (Phase 5a) |
| `cms/` | — | NEW (Phase 4) |
| `tests/baseline/` | — | NEW (Baseline agent) |
| `backend/migrations/` | — | NEW (Phase 2a) |
| `backend/app/core/{security,cache,deps,users}.py` | — | NEW (seams) |
| `frontend/core/{config,theme,api-client,router}.js`, `frontend/modules/quiz/link.js` | — | NEW (extractions) |

---

## 7. PATH-REFERENCE migration map

Every hardcoded path / URL / import that must change. Grouped by file. `→` is current → new.

### `deploy.sh` → `infra/deploy.sh`
The script computes `SRC_DIR` from its own location (`deploy.sh:68` `SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`). Moving it into `infra/` means `SRC_DIR` is now the repo **/infra**, not the repo root — so the rsync source paths must point one level up.

| What | `deploy.sh:line` | Current | New |
|---|---|---|---|
| repo-root resolution | 68 | `SRC_DIR=$(... dirname BASH_SOURCE ...)` | `REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"` and use `$REPO_ROOT` below |
| rsync source: course html | 493 | `"$SRC_DIR/content-system"` | `"$REPO_ROOT/content/frozen" "$REPO_ROOT/content/resources"` (or sync whole `content/`) |
| rsync source: backend | 494 | `"$SRC_DIR/quiz-certification"` | `"$REPO_ROOT/backend"` |
| rsync source: SPA | 495 | `"$SRC_DIR/app"` | `"$REPO_ROOT/frontend"` |
| rsync source: content seed | 496 | `"$SRC_DIR/content-architecture"` | folded into `"$REPO_ROOT/content"` |
| rsync excludes | 485-489 | `quiz-certification/...`, `content-architecture/venv/` | `backend/quiz_results/`, `backend/certificates/`, `backend/outbox/`, `backend/.env` |
| backend dir var | 461, 504 | `$APP_HOME/quiz-certification` | `$APP_HOME/backend` |
| venv path | 461, 511-513, 520, 523, 536, 541, 643, 742, 761 | `$QUIZ_DIR/.venv` (`QUIZ_DIR=$APP_HOME/quiz-certification`) | `$QUIZ_DIR/.venv` with `QUIZ_DIR="$APP_HOME/backend"` |
| ETL invocation | 742 | `cd "$QUIZ_DIR"; .venv/bin/python -m scripts.migrate_to_postgres` | `.venv/bin/python -m scripts.seed` (entry → `modules/content/etl.py`) |
| systemd WorkingDirectory | 759 | `${QUIZ_DIR}` (=quiz-certification) | `${QUIZ_DIR}` (=backend) |
| systemd ExecStart target | 761 | `.venv/bin/uvicorn app.main:app` | **unchanged** (`app.main:app` preserved) |
| Apache Alias `/anatomy` | 852-853, 895-896 | `${APP_HOME}/content-system` | `${APP_HOME}/content/frozen` (course) — add `/anatomy` Alias for resources too, or a second alias |
| `/anatomy` DirectoryIndex | 855, 898 | `anatomy-of-code-course.html` | **unchanged** (file kept by that name under `content/frozen/`) |
| Apache Alias `/app` | 859-860, 902-903 | `${APP_HOME}/app` | `${APP_HOME}/frontend` |
| `/app` FallbackResource | 864, 907 | `/app/index.html` | **unchanged** (still `index.html` under the alias) |
| ProxyPass excludes | 869-870, 912-913 | `/anatomy !`, `/app !` | unchanged (+ add `/resources !` if a separate resources alias is used) |
| SELinux fcontext | 804-808 | `${APP_HOME}/content-system`, `${APP_HOME}/app` | `${APP_HOME}/content/frozen` (+`content/resources`), `${APP_HOME}/frontend` |
| final-output URLs | 985-989 | `/app/`, `/anatomy/...` | `/app/` (unchanged path), `/anatomy/...` (unchanged) — only the served dir moved |

> The deploy header comments (`deploy.sh:22-25`) describing the layout also need updating to `content/frozen` + `frontend`.

### `start_local.sh` → `infra/start_local.sh`
| What | line | Current | New |
|---|---|---|---|
| repo root | 29 | `ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"` | `ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"` (now lives in `infra/`) |
| backend dir | 30 | `QUIZ_DIR="$ROOT_DIR/quiz-certification"` | `QUIZ_DIR="$ROOT_DIR/backend"` |
| uvicorn `--app-dir` | 93 | `--app-dir "$QUIZ_DIR"` | unchanged (now backend); target `app.main:app` unchanged |
| static server root | 98 | `--directory "$ROOT_DIR"` | `--directory "$ROOT_DIR"` (still repo root, so `frontend/` is reachable) |
| printed SPA URL | 109 | `http://localhost:8080/app/` | `http://localhost:8080/frontend/` |

> Local-dev origin model changes slightly: today the static server serves the repo root and the SPA lives at `/app/`; in v2 it lives at `/frontend/`. The relative `../media/` and `../content-architecture/` references that worked in dev are being replaced by API/config endpoints anyway (below), so the FE no longer depends on its sibling-folder layout for content.

### `scripts/migrate_to_postgres.py` → `modules/content/etl.py`
| What | line | Current | New |
|---|---|---|---|
| sys.path bootstrap | 18 | `os.path.join(dirname,'..')` | recompute for `backend/` root so `from app...` resolves; or run as `python -m scripts.seed` (preferred — no sys.path hack) |
| `BASE_DIR` | 25 | `config.BASE_DIR` (=quiz-certification) | `config.BASE_DIR` (=backend) — value follows the config recompute below |
| `FEED_JSON_PATH` | 28 | `BASE_DIR.parent/"content-architecture"/"feed"/"feed.json"` | `REPO_ROOT/"content"/"source"/"feed"/"feed.json"` |
| `VIDEO_PATH` | 29 | `BASE_DIR.parent/"media"/"Anatomy of Code.mp4"` | `REPO_ROOT/"assets"/"Anatomy of Code.mp4"` |
| `FRAMEWORK_PATH` | 30 | `.../content-architecture/course/framework.json` | `.../content/source/course/framework.json` |
| `FRAMEWORK_EXPLAINER_PATH` | 31 | `.../content-architecture/course/framework-explainer.json` | `.../content/source/course/framework-explainer.json` |
| `SECTIONS_DIR` | 32 | `.../content-architecture/course/sections` | `.../content/source/course/sections` |

> Because `BASE_DIR.parent` no longer reaches `content/` (it now reaches repo root only if `backend/` is a direct child of root — which it is), define an explicit `REPO_ROOT = config.BASE_DIR.parent` and build content paths from `REPO_ROOT/"content"/"source"`. Verify `backend/` sits directly under repo root so `config.BASE_DIR.parent == repo root`.

### `app/config.py` → `core/config.py`
| What | line | Current | New |
|---|---|---|---|
| `BASE_DIR` | 12 | `Path(__file__).resolve().parent.parent` (→ `quiz-certification/`) | `Path(__file__).resolve().parent.parent.parent` (→ `backend/`), since file moves from `app/config.py` to `app/core/config.py` (one level deeper) |
| `load_dotenv` | 15 | `BASE_DIR/".env"` | unchanged (now `backend/.env`) |
| `QUESTION_BANK` | 45 | `BASE_DIR/"data"/"question_bank.json"` | unchanged (now `backend/data/...`) |
| dirs (`QUIZ_RESULTS_DIR` etc.) | 42-44, 72-73 | `BASE_DIR/...` | unchanged (now under `backend/`) |
| new derived consts | — | — | add `STATIC_DIR = BASE_DIR/"app"/"static"`, `TEMPLATES_DIR = BASE_DIR/"app"/"templates"` for the new `main.py` mounts (replaces inline `config.BASE_DIR / "static"` from old `main.py:63,65`) |

> Critical: `config.py` moves **one directory deeper** (`app/` → `app/core/`), so the `parent` chain gains one `.parent`. Get this exactly right or every `BASE_DIR`-derived path breaks.

### `main.py` StaticFiles + the FS fallback
| What | old `main.py:line` | Current | New |
|---|---|---|---|
| `/static` mount | 63 | `StaticFiles(directory=str(config.BASE_DIR / "static"))` | `StaticFiles(directory=str(config.STATIC_DIR))` |
| `/app` mount | 64 | `StaticFiles(directory=str(config.BASE_DIR.parent / "app"), html=True)` | **DELETE** (Apache serves SPA) |
| templates dir | 65 | `Jinja2Templates(directory=str(config.BASE_DIR / "templates"))` | `Jinja2Templates(directory=str(config.TEMPLATES_DIR))` |
| explainer FS fallback | 592 | `config.BASE_DIR.parent / "content-architecture" / "course" / "framework-explainer.json"` | `REPO_ROOT / "content" / "source" / "course" / "framework-explainer.json"` (in `content/service.py`) |

### Python imports (`from . import ...`)
| What | old `main.py:line` | Current | New |
|---|---|---|---|
| top-level imports | 48 | `from . import auth, certificate, config, email_service, quiz_generator, roles, storage, encryption, media_service` | split: `from app.core import config, auth, encryption, db`; `from app.modules.quiz import service as quiz_service, certificate, email_service, roles, storage as quiz_storage`; etc. — each module imports only what it needs |
| models import | 49 | `from .models import MediaAsset` | `from app.core.models import MediaAsset` (in `media/routes.py`) |
| `storage.py` imports | 14-16 | `from . import config` / `from .db import ...` / `from .models import ...` | `from app.core import config` / `from app.core.db import ...` / `from app.core.models import ...` |
| `models.py` imports | 17-18 | `from . import config` / `from .db import Base` | `from app.core import config` / `from app.core.db import Base` |
| `db.py` import | 11 | `from . import config` | `from app.core import config` |
| `auth.py` imports | 14-15 | `from . import config` / `from . import storage` | `from app.core import config`; user lookups → `from app.core import users` |
| `quiz_generator.py` imports | 14-16 | `from . import config` / `from .db import get_session` / `from .models import ...` | `from app.core import config` / `from app.core.db import ...` / `from app.core.models import ...` |
| `media_service.py` imports | 20-22 | `from . import config` / `from .db import ...` / `from .models import ...` | `from app.core import config` / `from app.core.db import ...` / `from app.core.models import ...` |
| `certificate.py`, `email_service.py` | 17 | `from . import config` | `from app.core import config` |
| `encryption.py` | 14 | `from . import config` | `from app.core import config` |

> Recommendation: switch from implicit-relative (`from . import`) to **absolute package imports** (`from app.core import ...`). It is unambiguous across the deeper nesting and matches the `app.main:app` run target. The `scripts/` already rely on `from app import config` (`migrate_to_postgres.py:20`).

### Front-end fetch endpoints + constants
| What | file:line | Current | New |
|---|---|---|---|
| API rewrites | `util/load.js:12-18` | hardcoded `/api/course/...` | read `config.API_BASE` prefix (default `''`); logic otherwise unchanged |
| feed framework fetch | `feed/store.js:32` | `fetch('/api/course/framework')` | via `api-client` / `config.API_BASE` |
| feed list/create/flag | `feed/store.js:63,112,123,140` | `/api/feed*` | via `api-client` |
| `BASE` default | `feed/store.js:8` | `'../content-architecture'` | remove (content is API-only now); keep `configureFeedStore` no-op or drop |
| schema fetch | `feed/validate.js:57` | `` `${base}/schemas/feed.schema.json` `` | **new API** `GET /api/course/feed-schema` (content module serves `content/schemas/feed.schema.json`) — fixes the prod-broken relative path |
| auth fetches | `feed/auth.js:33,47,61,85` | `/auth/me`,`/auth/google`,`/login/dev`,`/logout` | via `config.API_BASE` (paths preserved) |
| Manual video src | `modes/scroll.js:21` | `'../media/Anatomy%20of%20Code.mp4'` | `config.MEDIA.explainer = '/media/video/explainer'` — a **stable server-side alias** that the media module resolves to the current explainer MP4 asset (the active row in `media_assets` tagged `slug='explainer'`). This lets `frontend/core/config.js` hold a static constant across all environments without re-baking the UUID `asset_id` per env. See §7.1 below for the MP4-delivery contract. |
| `QUIZ_URL` | `main.js:13-15` | inline ternary | `config.QUIZ_URL` |
| `BASE` (content) | `main.js:17` | `'../content-architecture'` | `config.CONTENT_BASE` (kept as the logical key load.js rewrites away) |
| `SECTION_FILES` | `main.js:18-28` | inline 31-item array | `config.SECTION_FILES` |
| `THEME_KEY` | `main.js:29` | `'anatomy-app-theme'` | `config.THEME_KEY` |
| import paths | all moved JS | `./blocks/*`, `../util/*`, `../registry.js`, `./feed/*`, `../feed/*` | rewritten to `frontend/{core,shared,modules}` layout per §4.1 (e.g. block→util stays `../util/dom.js`; mode→shared becomes `../../shared/...`) |
| script tag | `index.html:47` | `src="js/main.js"` | `src="core/main.js"` |
| CSS hrefs | `index.html:11-14` | `css/monolith.css` etc. | `styles/monolith.css` etc. |
| resource hrefs | `index.html:28-35` | `resources/code-coder-checklist.html`, `resources/architect-runbook.html`, `resources/faqs/...`, `http://localhost:8000` | `/anatomy/code-coder-checklist.html`, `/anatomy/architect-runbook.html`, `/anatomy/faqs/...` (served from `content/resources/`), Quiz href via `config.QUIZ_URL` |

### `content-architecture/validate.py` → `content/validate.py`
| What | line | Current | New |
|---|---|---|---|
| `ROOT` | 16 | `pathlib.Path(__file__).parent` (resolves `course/...` siblings) | `Path(__file__).parent / "source"` so `load("course/framework.json")` reads `content/source/course/...` |

### Templates (`home.html`, `quiz.html`)
Stale `dev_quiz`/`dev_mode` UI (§0.2): the `{% if dev_mode %}` dev-bar in `home.html`, the `#devQuizBanner` + `isDevQuiz`/`sessionStorage`/`dev_quiz`-flag JS in `quiz.html`. These reference a backend path that no longer exists. Phase 1 (clean-code slice) removes them. No route or URL change — just dead UI deletion.

### 7.1 MP4-delivery contract (explainer video)

The explainer MP4 lives in Postgres as a large object (ETL ingests it; `migrate_to_postgres.py:198-253`). Each environment has its own `media_assets.id` UUID, so the FE cannot hold a hardcoded `asset_id`. v2 fixes this with a **stable server-side alias**:

| Concern | Decision |
|---|---|
| Stable URL | `GET /media/video/explainer` — the media module resolves `slug='explainer'` to the active `media_assets` row and Range-streams its large object. |
| FE constant | `frontend/core/config.js → MEDIA.explainer = '/media/video/explainer'` (one constant, all envs). |
| `scroll.js` use | `<video src>` is set from `config.MEDIA.explainer`; no UUID ever appears in FE code. |
| Asset slug | `media_assets.slug` is the alias key (added in `v2/03` data model). ETL writes `slug='explainer'` on the explainer row; only one row per slug per env is `is_active=TRUE`. |
| Existing UUID route | `GET /media/video/{asset_id}` is kept for direct/admin access and for backwards compatibility. The alias route is layered above it (delegates internally to the resolved UUID). |
| Why alias over fetch-then-stream | A two-call dance (`GET /api/course/framework-explainer` → returns `asset_id` → `GET /media/video/{id}`) duplicates the resolution on every page load and complicates caching. A single stable URL is the cleaner contract and works with HTML `<video preload>` semantics. |

> The data-model doc (`v2/03`) owns adding `media_assets.slug` (`VARCHAR(64)`, unique per env + active) and the seed/ETL update. The blueprint pins the FE-visible URL contract here.

---

## 8. Item-12 segregation statement

The v2 tree cleanly separates the four planes; each top-level directory is one concern and they communicate only through declared seams:

- **Content** lives in `content/` — the editable source seed (`content/source/`), schemas, the frozen monolith (`content/frozen/`), and companion resources (`content/resources/`). It contains **no executable application code** (only `validate.py`, a content-CI helper). At runtime, content is authoritative in Postgres; `content/source/` is the version-controlled seed/export. Editors (Directus, Phase 4) and the seed ETL are the only writers.
- **Front-end** lives in `frontend/` — buildless ES modules (`core/` wiring, `shared/` rendering toolkit, `modules/` features) and `styles/`. It holds **no content** (fetches everything from the API) and **no server code**. Its only outward dependency is `config.API_BASE` (same-origin in prod via Apache proxy).
- **Back-end** lives in `backend/` — the modular monolith. `core/` is shared infrastructure (db, config, auth, encryption, security, cache) with **no domain logic**; `modules/{quiz,content,feed,media,cms}` own their domains behind the `routes/service/storage/schemas` convention. It holds **no content** (reads Postgres) and **no front-end** (the `/app` static mount is removed; Apache serves the SPA).
- **Config** is segregated by layer and never hardcoded across layers: backend config in `backend/app/core/config.py` + `backend/.env` (registry formalised in `v2/05`); front-end constants centralised in `frontend/core/config.js`; deploy/runtime config in `infra/deploy.env.example` + `infra/deploy.sh` tunables. Secrets stay in `.env`/`deploy.env` (gitignored), with the dev-default audit handled by `v2/05` + `v2/07`.
- **Infra** (`infra/`), **CMS** (`cms/`), **docs** (`docs/`, `docs-site/`), **tests/parity** (`tests/baseline/`), and **large binary assets** (`assets/`, gitignored) are each their own top-level concern.

The seams between planes: FE→BE via HTTP at `config.API_BASE`; BE→content via Postgres (seeded from `content/source/` by the ETL); CMS→content via the shared Postgres + a webhook into `modules/cms`; Apache routes `/app`→`frontend/`, `/anatomy`→`content/frozen`+`content/resources`, everything else→FastAPI.

---

## 9. What Phase 1 executes

Ordered, partitionable checklist. Slices **A–E** can run in parallel on disjoint path areas (per the plan's "disjoint file areas" rule); **F** integrates and is the gate. Each slice ends by leaving the tree importable/servable in isolation where possible.

> Use `git mv` for every move so history is preserved. Do **not** edit `main`. Commit only when the user asks.

### Slice A — Backend move + module split  *(owns `backend/`)*
1. `git mv quiz-certification backend`.
2. Create `backend/app/core/` and `git mv` `config.py, db.py, models.py, auth.py, encryption.py` into it; add new empty seams `security.py, cache.py, deps.py, users.py`.
3. Fix `config.py` `BASE_DIR` depth (+1 `.parent`, §7) and add `STATIC_DIR`/`TEMPLATES_DIR`.
4. Create `backend/app/modules/{auth,quiz,content,feed,media,cms}/` with `__init__.py`.
5. Split `main.py` into `modules/*/routes.py` per §2.3; move `quiz_generator→quiz/service`, `certificate`, `email_service`, `roles`, `media_service→media/service`.
6. Split `storage.py` per §2.4; split inline Pydantic models into `modules/*/schemas.py`.
7. Write the composition-only `backend/app/main.py` (§3 skeleton); delete the `/app` static mount.
8. Rewrite all Python imports to absolute `app.core.*` / `app.modules.*` (§7).
9. `git mv scripts/* backend/scripts/`; turn `migrate_to_postgres.py` into `modules/content/etl.py` + thin `scripts/seed.py`; repoint its paths (§7). `git mv validate_questions.py backend/scripts/`.
10. Delete `app/dev_quiz.py` (untracked → `rm`) and `app/review.py` (tracked → `git rm`, **confirm with user**). Decide `deploy_schema.sql` fate (keep as `migrations/legacy/` or `git rm`).
11. Verify: `cd backend && uvicorn app.main:app` boots; `/docs` lists all routes from §2.3; `python -m scripts.seed` runs against a scratch DB.
12. **Phase 1 acceptance item (`_active_quizzes` multi-worker hazard).** The in-process `_active_quizzes` dict (§2.3, current `main.py:69`) is not multi-worker safe — with `--workers > 1` shipping today, `/quiz/submit` 404s roughly `(n-1)/n` of the time. Phase 1 must either **pin `QUIZ_WORKERS=1`** in `infra/deploy.env.example` + the systemd unit (interim) **or** bring `quiz_sessions` persistence forward from `v2/03` (Phase 2b) into Phase 1. The data-model doc (`v2/03`) and caching doc (`v2/06`) own the final call; this acceptance gate must be cleared before Slice F.

### Slice B — Front-end move + centralisation  *(owns `frontend/`)*
1. `git mv app frontend` (then reshape) — or `git mv` each subtree into `frontend/{core,shared,modules,styles,tests}` per §4.1.
2. Create `core/config.js` (API_BASE, QUIZ_URL, SECTION_FILES, THEME_KEY, MEDIA), `core/theme.js`, `core/api-client.js`, `modules/quiz/link.js`; optionally `core/router.js`.
3. Move `main.js→core/main.js`; extract constants/theme/quiz-link; wire router.
4. Rewrite every intra-FE import path to the new layout (§4.1).
5. Repoint FE fetches onto `api-client`/`config.API_BASE`; fix `validate.js` schema fetch → API endpoint; fix `scroll.js` video src → media asset URL from config (§7).
6. Update `index.html`: script src, CSS hrefs, resource hrefs (→ `/anatomy/...`), Quiz href via config.
7. Verify: serve `frontend/` against a running backend; Manual/Read/Feed render; sign-in, feed list/create/flag, quiz launch all work; no console 404s; **visual parity** against `content/frozen/anatomy-of-code-course.html`.

### Slice C — Content consolidation  *(owns `content/`)*
1. Create `content/{source/course,source/feed,schemas,frozen,resources,docs/adr}`.
2. `git mv` course/feed JSON → `content/source/...`; schemas → `content/schemas/`; `validate.py`, `SCHEMA.md`, `MIGRATION-GAP.md`, ADR → `content/`; fix `validate.py` `ROOT` (+`/source`).
3. `git mv content-system/anatomy-of-code-course.html → content/frozen/`.
4. Resolve resources (§4.3): keep `content-system` runbook/checklist/faqs as canonical under `content/resources/`; normalise `architect-runbook.html`'s 3 back-link hrefs; `git mv` `RUNBOOK-TEMPLATE.html` + `runbook-outline.xlsx` from `app/resources/`; `git rm` the duplicate `app/resources/*` and now-empty `content-system/`.
5. Add the "Superseded" note to ADR 0001.
6. Verify: `cd content && python validate.py` exits 0 (schema + reference integrity over `content/source`).

### Slice D — Clean-code deletions  *(cross-cutting; coordinate with A & B)*
1. Confirm & delete dead backend code (`dev_quiz.py`, `review.py`) — done in A but tracked here as the clean-code ledger.
2. Remove stale `dev_mode`/`devQuiz` UI from `backend/app/templates/home.html` and `quiz.html` (§7).
3. Drop the dead `BASE='../content-architecture'` defaults in `feed/store.js`/`main.js` once API-only is confirmed.
4. Update `.gitignore` (assets/*.mp4, backend/**/.venv, *.db, __pycache__).

### Slice E — Infra path updates  *(owns `infra/`)*
1. `git mv deploy.sh start_local.sh deploy.env.example infra/`.
2. Repoint `deploy.sh`: `REPO_ROOT`, rsync sources/excludes, `QUIZ_DIR=$APP_HOME/backend`, ETL → `scripts.seed`, Apache `/app`→`frontend`, `/anatomy`→`content/frozen` (+resources), SELinux contexts, header comments, output URLs (§7).
3. Repoint `start_local.sh`: `ROOT_DIR` (../), `QUIZ_DIR=backend`, printed SPA URL `/frontend/`.
4. Move the MP4 on disk `media/ → assets/` (untracked; not a git op) and document in `MEDIA.md`.
5. Update `.claude/launch.json` static root/port note.
6. Verify (dry-run, no prod): `bash -n infra/deploy.sh` parses; `infra/start_local.sh` boots both servers locally; the generated vhost block paths point at `frontend`/`content/frozen`.

### Slice F — Integration + verification gate  *(serial; the gate)*
1. Land A–E on `v2`; resolve any boundary import mismatches.
2. Full local bring-up via `infra/start_local.sh` (backend on 8000, static on 8080).
3. Run the **parity harness** from `tests/baseline/` (owned by the Baseline agent, `v2/02`): route inventory matches §2.3 exactly (same paths/methods/status codes), content checksums unchanged, DB snapshot intact, smoke script green.
4. Visual-parity check of the SPA Manual/Read against `content/frozen/anatomy-of-code-course.html` (Memory: visual-diagram-verification — system Chrome + Playwright screenshot).
5. Confirm issued-cert verification still works (`/verify/{cert_id}`) and the cert PDF still renders (`certificate.generate`).
6. Update `README.md`/`DEPLOY.md`/`MEDIA.md`/`CONTRIBUTING.md` for the new paths.
7. **Gate:** parity harness matches baseline → Phase 1 done.

### Partition summary (who can run concurrently)
| Slice | Path area | Depends on |
|---|---|---|
| A backend | `backend/` | — |
| B frontend | `frontend/` | needs backend API contract (stable per §2.3) for runtime test, not for the move |
| C content | `content/`, deletes `content-system/`, `content-architecture/` | — |
| D clean-code | edits in `backend/app/templates`, FE consts, `.gitignore` | A, B (touches their files) |
| E infra | `infra/`, `assets/` | knows target paths from A/B/C (this doc) |
| F integrate | whole tree | A–E |

A, C, E touch disjoint areas and can run fully in parallel from the start. B is independent for the move; its runtime verification wants A up. D is a thin pass that should land after A and B settle. F is the serial gate.

---

### Open items to confirm at the Phase 0 gate (blueprint-specific)
1. **Delete `review.py`?** It is tracked but unimported by the app (standalone attempt-review CLI, `review.py:1-10`). Recommend delete (superseded by `scripts/`); confirm it is not used in any ops runbook.
2. **`deploy_schema.sql` fate** — superseded by `models.create_all` + Alembic (Phase 2a). Keep as `backend/migrations/legacy/` reference or delete.
3. **Resources URL home** — recommend serving `content/resources/` under the existing `/anatomy/` alias (course + companions together) rather than a new `/resources/` alias. Affects `index.html` hrefs and the deploy vhost.
4. **MP4 delivery** — recommend the media-API streaming path (the ETL already ingests it into a Postgres large object) over an Apache `/assets/` alias, to kill the last filesystem dependency in the FE.
5. **`tokens.css` / `router.js` extraction** — only if parity is unaffected; otherwise defer.
