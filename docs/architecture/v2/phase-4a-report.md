# Phase 4a Report — Directus CMS, additively over the existing Postgres

**Branch:** `v2` (never switched, never pushed) · **Tree:** clean at start and end
**Slice commits:** `0cd9050` (4a-1) · `ac79b2e` (4a-2) · `a7d68a4` (4a-3)
**Baseline anchor:** `8c2dfcd` (phase-3 orchestrator head) · **Alembic head:** `0008_directus_app_role`
**Date:** 2026-06-06

---

## 1. Gate decision

**GO for the 4a gate.**

Phase 4a stood Directus up as the editorial write plane over the existing
codecoder Postgres by introspection only — no DDL against application tables,
no content moved, no media migrated off Postgres large objects. The guarantee
that mattered held on every axis we tested:

- The FastAPI application plane is **byte-identical** from the phase-3 baseline
  to HEAD. `git diff 8c2dfcd..v2 -- 'backend/app/**'` is empty. The only
  backend change is the new additive migration `0008`.
- **Smoke 15/15** throughout, against the isolated sqlite path. The cert canary
  `CCA-F-20260605-E79E74AB` returns 200 (and `valid=true` under the strict
  `SMOKE_REAL_CERT_CHECK=1` run).
- The `directus_app` Postgres role is correctly scoped: runtime and audit
  tables (`attempts`, `quiz_sessions`, `signing_keys`, `auth_audit`) are hard-
  denied at the DB GRANT layer — confirmed live with `has_table_privilege`.
- Directus booted live against the real DB, introspected the existing tables,
  served real rows through `/items/*`, and the cache-invalidation webhook fired
  end-to-end into the FastAPI receiver (200 OK).
- Migration `0008` reverses cleanly (downgrade drops the role, upgrade restores
  it with grants intact).

The work is additive and reversible. Three INFO-level items (a stale content
manifest, a Node-25 build constraint, and one SSO config divergence in
`deploy.sh`) are documented below; none weakens the additive guarantee or
blocks the gate.

---

## 2. Per-slice summaries

### 4a-1 — `directus_app` Postgres role (the DB-level grant boundary)

Commit `0cd9050`. Single new file:
`backend/migrations/versions/0008_directus_app_role.py` (down_revision
`0007_seed_nonprod_signing_keys`).

The migration creates a `LOGIN`, password-less `directus_app` role and applies
a scoped GRANT/REVOKE matrix so that Directus — even with full admin in its own
UI — can only ever touch the tables the editorial plane is allowed to touch.
It is dialect-guarded (sqlite no-op, so local smoke is unaffected), idempotent
(CREATE ROLE wrapped in a `pg_roles` existence check; GRANT/REVOKE are
inherently idempotent), and reversible (`DROP OWNED BY` + `DROP ROLE IF EXISTS`
on downgrade).

`backend/migrations/env.py` was **not** modified — the required
`include_object` hook that skips any `directus_*` table was already wired into
both offline and online migration paths in an earlier phase (commit `2c917f6`),
so the requirement was already satisfied verbatim. No redundant no-op edit was
made.

The DB-level deny set is the foundation of the defense-in-depth posture: the
RBAC layer in slice 4a-2 sits on top of it, never beneath it.

### 4a-2 — Directus as-code (`cms/`)

Commit `ac79b2e`. Self-contained `cms/` tree, no `backend/`, `deploy.sh`, or
`start_local.sh` touched:

```
cms/
├── package.json              pins directus 11.17.4; engines.node ">=22"
├── package-lock.json         locked dependency tree
├── docker-compose.yml        prod deploy shape (directus/directus:11.17.4)
├── .env.example              committed template, every var documented
├── bootstrap.sh              idempotent operator script (source of truth)
├── register-collections.mjs  the Directus-API work bootstrap.sh drives
├── snapshot.yaml             captured data model (9 collections, 61 fields)
└── README.md                 local/VM standup, SSO, media=Postgres-LO, Node-22
```

Directus is pinned to **11.17.4** in `package.json`, the lockfile, and the
compose image. Runtime artefacts (`cms/node_modules`, `cms/.env`,
`cms/uploads/`, `cms/database/`) are gitignored and verified not committed.

The registrar binds 9 collections over the existing tables (introspection, no
DDL), creates 4 staff roles, 3 policies carrying 26 permissions, and 1 Flow.
The Flow watches `items.create/update/delete` on the 5 cached collections and
POSTs `{collection, keys}` to the FastAPI loopback receiver to invalidate cache.

### 4a-3 — Infra wiring

Commit `a7d68a4`. Touched `deploy.sh` (+351), `start_local.sh` (+38),
`docs/RUNBOOK.md` (+231, new §7). All Directus behaviour is gated behind
`DEPLOY_DIRECTUS=true` (deploy.sh) and `--with-cms` (start_local.sh), so the
default deploy path is unchanged.

Delivers a `cms-directus.service` systemd unit (mirrors the cca-quiz unit,
including the deliberate `MemoryDenyWriteExecute` omission for V8 JIT), and an
Apache `/cms/` reverse-proxy block to `127.0.0.1:8055` interpolated into the
HTTPS vhost. The `/cms/` proxy sits **before** the FastAPI catch-all `/` and
after the `/anatomy !` and `/app !` exclusions; `'unsafe-eval'` CSP is scoped
to `<Location "/cms/">` only via Report-Only, so application paths keep the
tighter default profile. WebSocket upgrade is proxied for the Directus
realtime channel. The Google SSO callback rides the same `/cms/` proxy.

Live boot of the full stand-up was deferred (needs root, the sealed `cms/`
deliverable, and the `0008` role) — but `httpd -t` passed live on the rendered
vhost with Directus both ON and OFF, and both shell scripts pass `bash -n`.

---

## 3. Numbers

**Role grants/revokes (4a-1, verified live against codecoder):**

| Table / object | Granted | Denied |
|---|---|---|
| `users`, `roles`, `user_roles` | SELECT | (no write; grant UI gated to 05) |
| `course_chapters`, `questions` | SELECT/INSERT/UPDATE/DELETE | — |
| `frameworks` | SELECT/INSERT/UPDATE | DELETE |
| `feed_items` | SELECT/UPDATE | INSERT, DELETE |
| `app_config` | SELECT/INSERT/UPDATE | DELETE |
| `media_assets` | SELECT | UPDATE |
| all sequences in `public` | USAGE, SELECT | — |
| `attempts`, `quiz_sessions`, `signing_keys`, `auth_audit` | — | **REVOKE ALL** |

Schema `public`: CREATE + USAGE granted. Spot-checks: `course_chapters`
SELECT = **true**, `attempts` SELECT = **false**. 18 `has_table_privilege`
checks ran live; all matched the design.

**Directus registration (4a-2, created live):**

- **9 collections** bound over existing tables (no DDL): `course_chapters`,
  `frameworks`, `questions`, `feed_items`, `app_config`, `media_assets`
  (metadata-only), `users` (read), `roles` (read), `user_roles` (read).
- **61 fields** captured in `snapshot.yaml`.
- **4 staff roles:** `content_author`, `quiz_admin`, `feed_moderator`,
  `platform_admin`.
- **3 policies carrying 26 permissions** (Directus 11 attaches permissions to
  policies via the `access` junction, not directly to roles):
  - content_author — CRU on `course_chapters` + `frameworks` (no delete)
  - quiz_admin — CRU on `questions`
  - feed_moderator — update `feed_items.status` (+ `questions.status`)
  - all three — read content + `media_assets` metadata
  - platform_admin — admin bypass; `app_config` exposed to platform_admin only
- **1 Flow:** `cache-invalidation` (active; event/action trigger on
  items.create/update/delete for the 5 cached collections) → Request op
  POSTing `{collection, keys}` to `http://127.0.0.1:8000/api/cms/webhook`.

**Introspection:** `course_chapters` count = **31 rows**; first row
`{filename:"adobe-aa.json", ring:"adobe", title:"Adobe Analytics"}`.

**Files touched across the phase:**
`backend/migrations/versions/0008_directus_app_role.py` (new) ·
8 committed `cms/` as-code files · `deploy.sh` · `start_local.sh` ·
`docs/RUNBOOK.md` · `.gitignore` (cms block).

---

## 4. The locked architecture boundary

```
   EDITORIAL WRITE PLANE            APPLICATION PLANE
   ┌──────────────────────┐        ┌──────────────────────────┐
   │  Directus 11.17.4     │        │  FastAPI                  │
   │  content + media +    │        │  quiz · cert sign/verify  │
   │  config authoring     │        │  learner SSO · runtime    │
   │  (staff RBAC, Flows)  │        │  read API (cache-backed)  │
   └──────────┬───────────┘        └────────────┬─────────────┘
              │ directus_app (scoped GRANT)      │ app role
              ▼                                  ▼
        ┌─────────────────────────────────────────────┐
        │   EXISTING Postgres 18.3 — codecoder DB      │
        │   (single shared schema, alembic head 0008)  │
        └─────────────────────────────────────────────┘

   SPA + quiz  ──reads──►  FastAPI /api/* (cache)   [NOT Directus directly]
   Directus    ──webhook─►  FastAPI /api/cms/webhook (cache invalidate)
```

Directus is the **content + media + config plane** (the headless CMS, the
editorial write surface, staff-facing). FastAPI remains the **application
plane** (quiz engine, certificate signing/verification, learner SSO, and the
cache-backed runtime read API the SPA and quiz consume). The frontend reads
content via FastAPI `/api/*`, never from Directus directly. Directus reaches
the DB only through the scoped `directus_app` role; the two planes share one
schema but hold disjoint, GRANT-enforced table footprints.

**Media — FINAL (2026-06-06): Postgres large objects, permanently.** The owner
confirmed: the only database is Postgres and **all media streams from it**. There
is **no S3, no object store, and no filesystem media store, ever.** Phase 0
decision C stands as written and is now permanent — there is **no media
migration** (the earlier "move media to a Directus storage adapter / S3-flip"
idea is **cancelled**). Media bytes live in `media_assets.large_object_oid` +
`pg_largeobject`; FastAPI owns upload (`/api/media/upload`) and Range-streaming
(`/media/{video,image}/{asset_id}`). Directus binds `media_assets` as **read-only
metadata** only (editors reference assets by id); app-media uploads into Directus
Files are disabled by permission so nothing app-facing lands on disk. The
`cms/` artifacts and `cms/.env.example`/`README.md` have been updated to remove
the S3 seam.

---

## 5. Verified LIVE vs documented

**Verified LIVE against the real codecoder Postgres / a real Directus boot:**

- Migration `0008` apply against Postgres 18.3; `\du directus_app`; all 18
  `has_table_privilege` checks; schema privileges; idempotent re-run;
  downgrade→0007→upgrade→head round-trip (role dropped then restored with
  grants). DB left at head `0008`.
- `directus bootstrap` (created `directus_*` tables + admin) and `directus
  start`; `GET /server/health` → `{"status":"ok"}`.
- **Introspection:** authenticated `GET /items/course_chapters?limit=1`
  returned a real row; count 31; `app_config` rows readable. Unauthenticated →
  `FORBIDDEN` (correct RBAC posture).
- **Role isolation at the Directus layer:** bootstrap logged "Could not set
  primary key" / "unknown table" for `attempts`, `signing_keys`,
  `quiz_sessions`, `auth_audit` — invisible to `directus_app` by GRANT,
  independently of the RBAC layer.
- **Webhook roundtrip end-to-end:** PATCH on `app_config/quiz.duration_min` and
  on `course_chapters/adobe-aa.json` each fired the Flow → loopback POST →
  **200 OK** in the co-booted FastAPI log. Cache invalidation proven in-process
  (`cms_client.cfg(...)` populates the namespace; the receiver's `invalidate()`
  removes it). DB restored to pristine after testing.
- `httpd -t` on the rendered HTTPS vhost — **Syntax OK** with
  `DEPLOY_DIRECTUS=true` and `=false`; proxy ordering and reserved-path
  integrity asserted programmatically.
- `bash -n deploy.sh start_local.sh` → OK; `bash tests/baseline/smoke.sh` →
  **15/15**.

**Documented, not booted live (best-effort live deferred, scripted path
complete and committed):**

- The full `deploy.sh` Directus stand-up end-to-end (DB role password set,
  `npm ci`, `directus bootstrap`, `bootstrap.sh`, `schema apply`, systemd
  enable/start) — requires root and a populated `node_modules` from a supported
  Node LTS. The as-code path is complete and syntax-verified.
- The Docker container itself (daemon down) — `docker compose config`
  validated the YAML; the npm/`directus start` path was the live verifier.
- `start_local.sh --with-cms` actual boot — needs a populated `cms/node_modules`.

---

## 6. Adversarial findings (F3)

The independent adversarial pass returned **GO** with no blockers. Every
hostile check passed:

- **Content drift — PASS.** 5 source JSON sha256 match the manifest; the frozen
  monolith sha256 (`530707e2…`) is identical at `8c2dfcd` and HEAD;
  `git diff 8c2dfcd..HEAD -- content/` empty.
- **FastAPI untouched — PASS.** `git diff --stat 8c2dfcd..HEAD -- backend/app/`
  empty; `env.py` unchanged.
- **Secret / junk hygiene — PASS.** No `node_modules`/`.env`/`uploads` tracked;
  only 8 as-code files committed; all `.env.example` secrets are placeholders
  (`replace-with-…`, `change-me-local-dev-only`); base64 scan clean.
- **Role over-grant — PASS.** Deny set all SELECT=false live; the no-DELETE set
  (`frameworks`, `feed_items`, `app_config`) and the no-INSERT/no-UPDATE rules
  match `03-data-model.md §5`.
- **Migration reversibility — PASS.** Live round-trip clean.
- **Apache proxy scope — PASS.** `/cms/`→8055 before catch-all `/`→8000; `/api`
  never proxied to Directus; the `/api/cms/webhook` `Require ip 127.0.0.1 ::1`
  rule (FastAPI receiver, not the Directus proxy) untouched.
- **CSP scoping — PASS.** `'unsafe-eval'` confined to `<Location "/cms/">`;
  app profiles unchanged; `frame-ancestors 'none'` on `/cms`.
- **Additive constraint — PASS.** No DDL against app tables anywhere in `cms/`
  as-code; snapshot binds metadata only.
- **Commit hygiene — PASS.** 3 descriptive `phase-4a/N:` commits, full bodies,
  Co-Authored-By trailer; tree clean.

**INFO (non-blocking) from F3:**

- **Manifest staleness.** `content-manifest.txt` references pre-restructure
  paths (`content-architecture/…`) vs the current `content/source/…`; hashes
  still matched by manual path-mapping. Refresh in a future housekeeping slice.
- **Node version.** Local Node 25 cannot build `isolated-vm` (Directus's
  Flow-script sandbox, eagerly required at boot even though our Flow uses a
  Webhook op). 4a-2 fell back to Homebrew `node@22` (22.22.3) and compiled
  against it; `deploy.sh` warns rather than dies on a non-LTS Node; the Docker
  image avoids the build entirely.

**Additional F2 finding (operator-facing, non-blocking):**

- **SSO config divergence between template and deploy.sh.**
  `cms/.env.example` documents the two-way `deptagency.com` enforcement
  (`AUTH_GOOGLE_ALLOW_PUBLIC_REGISTRATION=true` **and**
  `AUTH_GOOGLE_ALLOW_LIST=deptagency.com`, plus `AUTH_GOOGLE_DEFAULT_ROLE_ID`).
  But `deploy.sh:1052` writes `AUTH_GOOGLE_ALLOW_PUBLIC_REGISTRATION=false` into
  the deployed `.env` and does **not** set `ALLOW_LIST` or `DEFAULT_ROLE_ID`.
  Consequence on a real deploy: staff cannot self-register via Google SSO (every
  account must be pre-created by an admin), the documented allow-list is never
  written, and if SSO self-registration is ever turned on there is no default
  role to land in. This is a defensible conservative posture, but it diverges
  from the committed template's documented contract. Reconcile so the prod
  config matches the SSO contract (and `DEFAULT_ROLE_ID` is set) — folded into
  the 4b scope below.

**Environment note (verifier-discovered, not a 4a defect).** The system
Homebrew Node 25 on PATH (`/usr/local/Cellar/node/25.8.1_1`) is now broken at
launch with `dyld: Library not loaded: libsimdjson.31.dylib`, unrelated to
Directus. Live boots succeeded via `node@22` (`/usr/local/opt/node@22/bin`).
The RUNBOOK §7.2 / `cms/README` Node-22 pin is therefore required on this box,
not merely advisory. Worth flagging to the owner.

---

## 7. Open items and the DEFERRED gated slices

**Open items (housekeeping, none gate 4a):**

1. Refresh `content-manifest.txt` paths to `content/source/`.
2. Reconcile the SSO config divergence in `deploy.sh` against `.env.example`
   (set or intentionally drop `ALLOW_LIST` / `DEFAULT_ROLE_ID`; align the
   public-registration posture). Belongs in 4b.
3. Pin Node 22 LTS on the VM; the local Node 25 PATH is broken and unsupported.

**Deferred gated slices (each its own gate, none started in 4a):**

- **~~4a.2 — Media migration off Postgres large objects~~ — CANCELLED
  (2026-06-06).** The owner finalised: Postgres is the only database and all
  media streams from it. Media stays in `pg_largeobject` permanently, served by
  FastAPI `/media/*` with Range. No S3, no object store, no filesystem media
  store. There is nothing to migrate. (Phase 0 decision C, kept.)
- **4b — Nav/theme unify + moderator UI + resources integration.** Unify
  navigation and theme across the SPA and Directus surfaces, build the
  moderator UI, integrate resources. The SSO reconciliation (open item 2) folds
  here. UI/UX layer, no data migration.
- **4c — Live authoring + live moderation queue + relational course
  decomposition.** Turn on live authoring through Directus, run the moderation
  queue live, and decompose `course_chapters` from the JSON-blob shape into a
  relational model. The most invasive slice (schema change) — strictly last.

---

## 8. What unlocks the next slice

The 4a gate is **GO**, so the next slice is unblocked. With media settled
(Postgres-LO, permanent — the 4a.2 slice is cancelled), the order is:

- **4b — Nav/theme unify + moderator UI** is the next slice. It needs: the 4
  staff roles + policies from 4a (present), the moderator-scoped permissions
  (present), and the SSO reconciliation (open item 2). It builds on the sealed
  Directus plane, the `directus_app` role, and the cache-invalidation seam.
- **4c (live authoring + relational decomposition)** is gated behind 4b (so
  authors have a usable surface) and a deliberate decision to change the
  `course_chapters` schema. It is strictly last because it is the only slice
  that mutates the application data model.

**Next: 4b (nav/theme unify + moderator UI).** Media is finalised on Postgres
large objects (FastAPI-streamed), so there is no separate media slice. Both 4b
and 4c are unblocked in that order; neither blocks the
other. 4c waits until 4b lands.
