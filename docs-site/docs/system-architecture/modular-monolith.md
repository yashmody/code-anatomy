---
id: modular-monolith
title: Modular monolith
sidebar_position: 2
---

# Modular monolith

## Scan box

- **One FastAPI app, internally partitioned.** `backend/app/main.py` is
  composition-only — it builds the app, installs middleware, mounts static and
  templates, and includes one router per module. No business logic lives there.
- **`core/` is shared infrastructure; `modules/` is domain logic.** `core/`
  holds db, config, auth, cache, security, observability, users, encryption.
  Each module under `modules/` owns its routes, service, storage, and schemas.
- **Every module follows the same file convention.** `routes.py` (thin),
  `service.py` (logic, no FastAPI imports), `storage.py` (this module's
  tables), `schemas.py` (Pydantic). The convention is the boundary.
- **Cross-module reads are allowed; cross-module writes go through the owning
  module.** Modules share ORM models from `core.models`, so a read can join
  another module's table — but a write to a table belongs to its module's
  service.
- **URLs are preserved exactly from the legacy monolith.** Issued certificates
  keep verifying and the SPA keeps fetching the same paths. The router prefixes
  were chosen to reproduce the old paths, not to prettify them.

The v2 backend is a *modular monolith*: a single deployable FastAPI process
whose internals are split along clean domain boundaries. This is a real
architectural choice with a clear payoff — the operational simplicity of one
process to deploy, log, and scale, with the internal discipline that lets a
module leave the monolith the day it needs to. It is not "we never got round to
splitting it."

## The two halves: `core/` and `modules/`

The package tree under `backend/app/` has exactly two halves.

`core/` is shared infrastructure with **no domain logic**. Anything a domain
module needs but does not own lives here:

| File | Responsibility |
|---|---|
| `config.py` | The settings registry (tiered secrets + structural config). |
| `db.py` | SQLAlchemy engine, `Session`, `Base`, `get_session()`, `init_db()`. |
| `models.py` | All ORM tables in one module — they share foreign keys. |
| `auth.py` | Google OAuth (PKCE + nonce) + the low-level auth primitives. |
| `users.py` | User CRUD and the role-membership reads/writes shared by every plane. |
| `deps.py` | `require_permission`, the permission matrix, session helpers. |
| `cache.py` | The `AppCache` seam (memory or Redis behind one facade). |
| `cms_client.py` | The Tier-2 config reader over `app_config`, cache-backed. |
| `security.py` | Session, CORS, and security-header middleware. |
| `observability.py` | Request-id middleware + structured logging. |
| `encryption.py` | AES-GCM payload crypto for the network-encryption seam. |
| `roles.py` | Persona definitions (job family → recommended quiz level). |

`modules/` is the domain logic, one directory per bounded context:

```text
backend/app/
├── main.py            composition only — builds app, mounts routers
├── core/              shared infrastructure (no domain logic)
│     config db models auth users deps cache cms_client
│     security observability encryption roles
└── modules/
      ├── auth/        /login, /auth/google*, /auth/me, /logout, session-key
      ├── quiz/        /, /quiz/*, /certificate/*, /verify, /history, /admin
      ├── content/     /api/course/*  (framework, chapters, explainer)
      ├── feed/        /api/feed, /api/feed/flag, /api/moderate/*
      ├── media/       /api/media/upload, /media/{video,image}/{id}
      ├── cms/         /api/cms/webhook, /api/cms/roles-sync
      ├── superadmin/  /superadmin/login, /superadmin/setup, /superadmin/totp
      └── admin/       /api/admin/roles  (role assignment REST)
```

The two halves map directly onto the locked decision in `v2-plan.md`: "ONE
FastAPI backend internally split into `core/` (shared) + `modules/`."

## The per-module file convention

Every module under `backend/app/modules/<name>/` follows the same shape. The
convention is what makes the boundary real — you can read any module and know
where each kind of code lives.

| File | Rule |
|---|---|
| `routes.py` | An `APIRouter` named `router`. Endpoints only — parse the request, call `service`, shape the response. Thin. |
| `service.py` | Business logic. **No FastAPI imports.** Calls `storage` and `core` helpers. |
| `storage.py` | Database access for this module's tables. Imports shared models from `core.models`. |
| `schemas.py` | Pydantic request/response models. |

Module-specific helpers (the quiz module's `certificate.py`, `verification.py`,
`email_service.py`; the content module's `etl.py`) live with the module that
owns them, never in `core/`.

The discipline that `service.py` carries no FastAPI import is the load-bearing
rule: it means the domain logic is testable without an HTTP layer and could be
called from a CLI, a worker, or a future second service unchanged.

:::tip[Agency Tip]
When you add a feature to a module, resist the pull to put logic in `routes.py`
"just for now". The route should read like a table of contents: authorise,
parse, delegate, respond. If you are writing a loop or a branch in a route,
it belongs in `service.py`. The media upload route is the worked example — it
owns multipart parsing and the byte-cap guard, then hands the validated file to
`media_service.store_media_asset`.
:::

## How modules talk to each other

Two rules govern cross-module interaction, and they are asymmetric on purpose.

**Cross-module reads are allowed via shared models.** Because every ORM table
lives in `core.models`, a module can read another module's table directly. The
moderation queue is the canonical case: it reads both `FeedItem` (feed-owned)
and `Question` (quiz-owned), so `feed/storage.py` imports `Question` from
`core.models` and joins across the boundary. This is fine — a read does not
mutate ownership.

**Cross-module writes go through the owning module's service.** A write to a
table belongs to the module that owns it. If the feed module needs a question
created, it calls the quiz service, not the questions table directly. This keeps
invariants (validation, signing, audit) in one place per table.

The single shared model module is also a pragmatic Alembic decision. The tables
share foreign keys — `Attempt.user_email`, `Question.author_id`,
`FeedItem.author_id`, `MediaAsset.uploaded_by` all reference `users.email` — and
Alembic autogenerate wants one metadata. Splitting models per module would
fragment the schema for no real isolation gain. Per-module `storage.py` files
give each module ownership of its *queries* without fragmenting the *schema*.

## The composition root

`backend/app/main.py` is the one place wiring is decided, and it does four
things in order:

1. **Lifespan startup.** `observability.configure_logging()` runs first so every
   later startup log carries the structured format, then `db.init_db()`, then a
   defensive `ensure_first_admin()` to seed the first `platform_admin` from
   `ADMIN_EMAILS`.
2. **Middleware.** `security.install_middleware(app)` stacks session, CORS,
   security headers, and the request-id middleware in one call (see
   [Security baseline](./security-baseline.md) and
   [Observability](./observability.md)).
3. **Static and templates.** `/static` stays FastAPI-served so Jinja
   `url_for('static', …)` references remain stable. The legacy `/app` SPA mount
   is **removed** — Apache serves the SPA at `/app/` in v2.
4. **Routers.** Health probes first (unauthenticated), then one
   `include_router` per module with the prefix that reproduces the legacy paths.

The router-mount scheme is what preserves every URL:

| Router | Prefix | Resulting paths |
|---|---|---|
| `health` | `""` | `/healthz`, `/readyz` |
| `auth` | `""` | `/login`, `/auth/google*`, `/auth/me`, `/logout` |
| `quiz` | `""` | `/`, `/quiz/*`, `/certificate/*`, `/verify`, `/history`, `/admin/attempts` |
| `content` | `/api/course` | `/api/course/framework`, `/api/course/chapters*` |
| `feed` | `/api` | `/api/feed`, `/api/feed/flag`, `/api/moderate/*` |
| `media` | `""` | `/api/media/upload`, `/media/video/{id}`, `/media/image/{id}` |
| `cms` | `/api/cms` | `/api/cms/webhook`, `/api/cms/health` |
| `admin` | `/api/admin` | `/api/admin/roles` |

:::caution[Common Pitfall]
Do not "tidy up" a route path. The prefixes look uneven — `quiz` and `media`
mount at root while `content` and `feed` carry prefixes — and the temptation is
to normalise them. But issued certificates embed `/verify/{cert_id}` and the
buildless SPA fetches these exact paths with no build step to rewrite them.
Changing a path silently breaks an already-issued certificate or a deployed
front-end. Path normalisation, if it ever happens, is a separate parity-gated
decision — not a cleanup.
:::

## Where the boundary is going

The modular monolith is the final v2 shape, with one explicit deferral. The
content module today serves the course from the frozen JSON/HTML artefact; the
**4c** slice would decompose the course into relational `course_chapters`
tables so Directus can author chapters directly. That is the last byte-identical
guarantee scheduled to fall, and it is deferred — the current state is stable
and complete without it. See [Directus topology](./directus-topology.md) for
where 4c picks up.
