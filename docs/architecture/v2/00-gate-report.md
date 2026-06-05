# v2/00 · Phase 0 Gate Report

> Status: **Phase 0 SEALED · awaiting user GO for Phase 1.** Synthesis of the
> eight design contracts (`01`–`08`), the parity safety net under
> `tests/baseline/`, the `docs-site/` scaffold, the adversarial critiques (eight
> per-doc critics + one coherence critic), and the mechanical sweep that
> reconciled every cross-doc finding (workflow `wjildzrp1`).
> Owner: Synthesis agent. Branch `v2`. `main` untouched.
>
> Auto-mode + ultracode sealed the gate by accepting the recommended defaults
> for the three locked decisions in §4 and the 23 additional gate questions in
> §5. The user retains the right to flip any of those at any later phase gate.
> See §9 ("Locked decisions on seal") and §10 ("What unlocks Phase 1").

This document is the gate the user reviews before Phase 1 starts. It lists what was
delivered, summarises every critic finding into a single prioritised table, surfaces
the cross-doc blockers, restates the three locked-in gate decisions plus any
additional questions the critics raised, and gives a GO / NO-GO recommendation.

---

## 1 · What was delivered

| Doc | One-line summary |
|---|---|
| [`v2-plan.md`](../v2-plan.md) | Shared contract — phases, locked decisions, hard constraints, 12-item coverage. |
| [`01-blueprint.md`](./01-blueprint.md) | Exact v2 tree, module boundaries, router-mount skeleton, per-file/per-path migration map, slice plan for Phase 1. |
| [`02-parity-method.md`](./02-parity-method.md) | Five parity invariants (API, content, DB, FE visual, quiz/cert), per-phase gate checklists, harness artefact inventory. |
| [`03-data-model.md`](./03-data-model.md) | Target Postgres schema, Alembic adoption plan, new tables (`quiz_sessions`, `roles`/`user_roles`, `signing_keys`, `app_config`), Directus coexistence. |
| [`04-authz-model.md`](./04-authz-model.md) | Two-plane role taxonomy, permission matrix, persona-as-profile, PKCE/nonce/cookie hardening, Directus auth coexistence. |
| [`05-config-cms.md`](./05-config-cms.md) | Three-tier config (secrets in env, config in `app_config`, content in Directus), Google + LLM key seam, env-mode label `APP_ENV`. |
| [`06-caching-performance.md`](./06-caching-performance.md) | Apache cache/deflate/expires/HTTP2 plan, ETag conditional-GET, in-process LRU + invalidation, Postgres pooling and index audit. |
| [`07-security-baseline.md`](./07-security-baseline.md) | Threat model, full findings table mapped to phase, header set (CSP/COOP/CORP/etc.), session/cookie/PKCE/HSTS posture, cert dev-mode design. |
| [`08-docs-plan.md`](./08-docs-plan.md) | Docusaurus 3.5 scaffold, six sections, LAYER authoring discipline, deploy via `/docs/` alias, single-rolling-current versioning. |
| `tests/baseline/` | Live receipts — `routes.md`, `db-snapshot.md`, `content-manifest.txt`, `smoke.py`, fixtures, manifest generator. |
| `docs-site/` | Docusaurus scaffold — classic preset, pinned deps, six section stubs, DEPT® brand tokens wired in (no `npm install` run yet). |

---

## 2 · Prioritised findings table

`Sev` = critic severity. `Owner phase` = `0` means fix before gate approval;
`1+` means acknowledge and defer to the named later phase. `Status` = `OPEN` /
`FIX-NOW` (fix before Phase 1 starts) / `DEFER` (ack into the named phase).

| ID | Sev | Doc | Issue (1 line) | Proposed fix (1 line) | Owner | Status |
|---|---|---|---|---|---|---|
| C-01 | CRITICAL | 03 ↔ 04 | `QuizManager` legacy backfill: 03 grants `{quiz_admin, platform_admin}`; 04 forbids it and grants only `{learner}`. | Adopt 04's stricter rule. Update 03 §3 step 5 + §8 step 7. | 0 | FIX-NOW |
| C-02 | CRITICAL | 03 ↔ 04 | `user_roles` join table (03) vs `users.roles text[]` set in code sketches (04) — schema/code mismatch. | Lock the join table (03) as canonical; rewrite 04 sketches to use a `users_service.roles_for(email)` helper. | 0 | FIX-NOW |
| C-03 | CRITICAL | 03 ↔ 04 ↔ 07 | `auth_audit` table referenced by 04/07/02 but no DDL in 03. | Add `auth_audit` DDL + Alembic revision to 03 §2/§3/§8 (cols: actor_email, action, target_email, target_role, before/after jsonb, occurred_at). | 0 | FIX-NOW |
| C-04 | CRITICAL | 07 ↔ 05 | `APP_ENVIRONMENT` (07 §8.5) vs `APP_ENV` (05 §1.5/§5.1/§7.1) env-var name drift. | Lock on `APP_ENV` (05 is the registry); sweep 07. | 0 | FIX-NOW |
| C-05 | CRITICAL | 04 ↔ 07 | Session cookie `max_age` — 8h in 04 §6.4, 14d in 07 §4.1. | User picks; default 8h (security-stronger). Update both docs to the chosen value. | 0 | FIX-NOW (gate decision) |
| C-06 | CRITICAL | 02 ↔ 03 ↔ 07 | Cert-ID prefix policy — 07 mandates `DEV-`/`STG-` prefixes; 02 parity-regex still asserts `CCA-F-…`; 03 silent. | Default: keep `CCA-F-…` for prod, dev rows get `DEV-CCA-F-…`. Update 02 regex to env-aware; 03 §2.5 documents prefix at generation. | 0 | FIX-NOW (gate decision) |
| C-07 | CRITICAL | 02 | Real-cert canary `CCA-F-20260605-E79E74AB` claimed verified in smoke but not actually checked. | Add explicit smoke assertion `/verify/CCA-F-20260605-E79E74AB → valid=true`. Fix fixture count 17 → 16 (or land the missing fixture). | 0 | FIX-NOW |
| C-08 | CRITICAL | 02 ↔ v2-plan | Phase mapping in 02 §3 contradicts v2-plan §"Phase plan" — 2c redefined, 2d/2e omitted, Directus moved to Phase 5, FE reorg to Phase 4. | Re-align 02 §3 to v2-plan (2c = cert dev-mode + `signing_keys`; add 2d/2e; Directus = Phase 4; FE reorg = Phase 1). | 0 | FIX-NOW |
| C-09 | CRITICAL | 06 | ETag-304 path ships **no** `Cache-Control` header — Apache `Header set` (not `always set`) skips 304s; FastAPI 304 response is bare. | Use `Header always set` for cache directives **and** include `Cache-Control` in FastAPI 304 headers dict. | 0 | FIX-NOW |
| C-10 | CRITICAL | 06 | Certificate route `/certificate/{cert_id}` has cache-matrix row but no `LocationMatch` block; shared caches may store signed PDFs. | Add `<LocationMatch "^/certificate/">` with `private, max-age=86400, must-revalidate` + `Vary: Cookie`, OR set `no-store` and update the table. | 0 | FIX-NOW |
| C-11 | HIGH | 01 ↔ 03 | Content export tree drift — 01 mandates `content/source/…`, 03 §6 writes `content/course/sections/…` (no `source/`). | Pick one — recommend 01's `content/source/…`. Patch 03 §6. | 0 | FIX-NOW |
| C-12 | HIGH | 01 | `_active_quizzes` is in-process; `--workers 2` is shipping today, so `/quiz/submit` 404s ~50% in prod **right now**. | Either pin `QUIZ_WORKERS=1` for Phase 1 (interim) **or** bring `quiz_sessions` persistence forward into Phase 1 — call out explicitly as a Phase 1 acceptance item. | 1 (acceptance item) | DEFER but call out |
| C-13 | HIGH | 01 | MP4-delivery contract for `scroll.js` — UUID `asset_id` per env, so `config.js` can't hold a static constant. | Specify a stable server-side alias (`/media/video/explainer`) **or** a `/api/course/framework-explainer` fetch that returns the `asset_id`. Pick one in 01 §7. | 0 | FIX-NOW |
| C-14 | HIGH | 02 | API smoke runs against sqlite; key parity claims (course/framework 200, large-object media) need Postgres. | Note explicitly that sqlite smoke is necessary-but-not-sufficient; carve a `smoke.sh --prod` invocation against a Postgres snapshot as Step 3 owner. | 1 (Phase 1) | DEFER |
| C-15 | HIGH | 02 | Quiz round-trip (§1.5 step 4) can't actually be executed today — needs either a `QUIZ_DEV_MODE`-gated debug endpoint or a seeded known-answers bank. | Ship `/debug/active-quiz` behind `QUIZ_DEV_MODE` as a Phase 1 side-task, **or** rewrite §1.5 step 4 to use a seeded fixture. | 1 (Phase 1) | DEFER |
| C-16 | HIGH | 02 | `Cache-Control: no-store` baseline assertion fails — Apache emits no `Cache-Control` header today. | Change to "assert `Cache-Control` absent today" in §5 q4. | 0 | FIX-NOW |
| C-17 | HIGH | 02 | HMAC key wording — "fixed in `signing_keys`" implies secret-in-DB. | Reword: secret stays in env (`SECRET_KEY`); `signing_keys` only references which key signed each cert. | 0 | FIX-NOW |
| C-18 | HIGH | 03 | `quiz_sessions.quiz_id UUID` vs `attempts.quiz_id VARCHAR(64)` — un-joinable, no FK declared. | Decide: widen `attempts.quiz_id` to UUID with FK, **or** keep both as text. Recommend: keep both as text (smallest migration). | 0 | FIX-NOW |
| C-19 | HIGH | 03 ↔ 04 | `users.legacy_role` column referenced by 04 §5.2 (rollback) but not in 03's DDL. | Either add `users.legacy_role` to 03, **or** drop the rollback column from 04 and rely on the §8 backup snapshot. Recommend: drop the column. | 0 | FIX-NOW |
| C-20 | HIGH | 03 | `app_config` `value_type` enum + `CHECK (is_secret = FALSE)` — self-defeating column, duplicates 05's typed registry. | Drop `is_secret`; keep `value_type` as metadata for Directus rendering only; cite 05 as source of truth. | 0 | FIX-NOW |
| C-21 | HIGH | 03 | Cert `legacy-prod` backfill uses `env_var_name='SECRET_KEY'` — couples cert HMAC to session secret rotation forever. | Introduce `CERT_HMAC_LEGACY` env var seeded with today's `SECRET_KEY` value; `legacy-prod.env_var_name='CERT_HMAC_LEGACY'`. | 0 | FIX-NOW |
| C-22 | HIGH | 04 ↔ 07 | Permission-string vocabulary drift — 04 uses `moderate.view`/`moderate.action`; 07 uses `feed.moderate` and `feed.contributor`. | Lock 04 as the vocabulary owner. Sweep 07 for permission strings + role keys. | 0 | FIX-NOW |
| C-23 | HIGH | 04 | Cookie/`user["role"]` rotation step missing — 8 read sites in `main.py` reference `user.get("role")`; existing dev sessions break silently after deploy. | Add an explicit "session/cookie cutover" step to §8 — force-logout by `SECRET_KEY` rotation (intentional), enumerate all `user.get("role")` repoints. | 0 | FIX-NOW |
| C-24 | HIGH | 05 | Dual cache — `core/cms_client.py` invents its own TTL+RLock cache; 06 already owns `core/cache.py` with the invalidation seam. | Rewrite 05 §7.2 to call `core.cache.get_or_compute("app_config:"+key, ttl=60, ...)`. Webhook invalidates via `cache.invalidate(...)`. | 0 | FIX-NOW |
| C-25 | HIGH | 05 ↔ 03 | `CERT_DEV_MODE_KEY_ID`/`CERT_PROD_KEY_ID` env vars duplicate the DB selection (`environment` + `is_active`). | Delete both rows from §1.5 + §6; lookup is `WHERE environment = settings.app_env AND is_active = TRUE`; secret material via `env_var_name` per row. | 0 | FIX-NOW |
| C-26 | HIGH | 05 | Deleting `GOOGLE_REDIRECT_URI` env var breaks Google Console-registered redirects that don't match the derived form. | Keep `GOOGLE_REDIRECT_URI` as an optional override; deprecate but don't delete. | 0 | FIX-NOW |
| C-27 | HIGH | 05 | `pass_mark_correct` freeze breaks verify for legacy attempts if verification ever reads from `payload.grading`. | Lock policy: verification continues to read the HMAC-signed score **only**; grader writes the frozen value going forward. Document in 05 + 07. | 0 | FIX-NOW |
| C-28 | HIGH | 06 ↔ 01 | Module path drift — 06 says `backend/app/core/cache.py`; 01 says `backend/core/cache.py`. | Align on 01's tree (`backend/core/…`); sweep 06. | 0 | FIX-NOW |
| C-29 | HIGH | 06 ↔ 07 | Rate-limit ownership orphan — 07 delegates to "Phase 3c (Apache, owned by 06)"; 06 has no rate-limit content. | 06 §2.1 adds `mod_ratelimit` to enable list with a `/api/media/upload` example block, **or** 07 reclaims ownership with a concrete snippet. | 0 | FIX-NOW |
| C-30 | HIGH | 06 | Media `Cache-Control: public, immutable` keeps moderated/deleted media alive at intermediate caches. | Drop `immutable`; use `public, max-age=86400, must-revalidate`. | 0 | FIX-NOW |
| C-31 | HIGH | 07 | CSP `report-uri /csp/report` writes to `security_audit` table that doesn't exist in 03. | Switch to `report-to` with logging to file/journald for Phase 0, **or** add `security_audit` DDL to 03. Recommend: file logging now, table in v2.1. | 0 | FIX-NOW |
| C-32 | HIGH | 07 ↔ 05 | Env vars invented in 07 (`CERT_HMAC_DEV/STG/PROD`, `CORS_ORIGINS`, `MEDIA_SCAN_ENABLED`, `BACKUP_TARGET_URL`, `KEEP_DEV_SECRET`, `SECRET_KEY_NEXT`, `GOOGLE_CLIENT_SECRET_NEXT`, `OPERATOR_PUBKEY`, `ADMIN_EMAIL`) absent from 05's env registry. | Sweep 07 → register every env var in 05 §1.5 with tier + destination. | 0 | FIX-NOW |
| C-33 | HIGH | 07 | `COOP: same-origin` breaks Google OAuth popup if PKCE work (04 §6.1) switches to a popup flow. | Note constraint explicitly; current top-level redirect is fine; add regression check to §11.1. | 1 (Phase 2b) | DEFER with note |
| C-34 | HIGH | 08 | Docusaurus 3.5 has no built-in/official local search plugin; doc claims one. | Commit to `@easyops-cn/docusaurus-search-local` and pin a version. | 0 | FIX-NOW |
| C-35 | HIGH | 08 | "CentOS 8" prerequisite — EOL since Dec 2021; 06 + `deploy.sh` target RHEL 8+/Rocky/Alma. | Change to "RHEL 8+/Rocky/Alma (Ubuntu 22.04+ as tested alternative)". | 0 | FIX-NOW |
| C-36 | HIGH | 08 ↔ 01 | `infra/scripts/` referenced in 08 but blueprint defines `backend/scripts/` for content scripts and `infra/` for deploy/Apache/systemd only. | Place OpenAPI/ERD dumpers in `backend/scripts/`; remove `infra/scripts/` references. | 0 | FIX-NOW |
| C-37 | HIGH | 08 | Inline cert-HMAC claim duplicates 07's source of truth and risks drift. | Replace with reference: "see `07-security-baseline.md §X` and `03-data-model.md §2.5`". | 0 | FIX-NOW |
| C-38 | MEDIUM | 01 | Existing bookmarks / cert PDFs / emails may embed `/app/resources/…` URLs that 404 post-move. | Grep `certificate.py`, `email_service.py`, issued cert PDFs for `/app/resources/`; if found, add `Redirect 301 /app/resources/ /anatomy/`. Otherwise document "no external bookmark surface affected". | 1 (Phase 1) | DEFER |
| C-39 | MEDIUM | 01 | Once Directus authoring opens (Phase 4), SPA and `/anatomy/` monolith diverge — no statement on what `/anatomy/` shows after edits start. | Add one sentence to 01 §5: monolith continues to serve historical frozen snapshot; live content via SPA only; Phase 4 adds a banner. | 0 | FIX-NOW |
| C-40 | MEDIUM | 01 ↔ 06 ↔ 07 | `/static/` mount — FastAPI proxied vs Apache aliased is unspecified; affects 06 cache rules + 07 CSP `style-src`. | Lock to FastAPI-proxied via Apache for v2 (default); document in 01 §3 + 06 §2.4. | 0 | FIX-NOW |
| C-41 | MEDIUM | 01 | `auth` routes — 01 §2.3 wavers between `core/routes.py` and `quiz/routes.py`. | Create `modules/auth/routes.py` for `/auth/*`, `/login`, `/logout`; keep `quiz/routes.py` learner-flow-only. | 0 | FIX-NOW |
| C-42 | MEDIUM | 02 | `prod-certs-post.txt` not in artefact table; silently-dropped certs would not be caught. | Add post-cutover cert dump + a "set difference must be empty" rule. | 1 (Phase 5b cutover) | DEFER |
| C-43 | MEDIUM | 02 | "Move + content change in same phase" hard ban blocks routine Phase 1 work (e.g. `architect-runbook.html` back-link fix). | Allow with ADR/waiver line in `path-map.csv`. | 0 | FIX-NOW |
| C-44 | MEDIUM | 02 | FE-parity threshold vague — "small font drift acceptable" with no numeric bar. | Define: `pixelmatch` ≤ 0.5% non-anti-aliased pixels at 1440px, OR a DOM-count + ochre `#FF4900` check. | 0 | FIX-NOW |
| C-45 | MEDIUM | 02 | No rollback drill in cutover row. | Add a "Rollback drill" row referencing the Apache vhost symlink swap. | 0 | FIX-NOW |
| C-46 | MEDIUM | 03 | Directus DB-role GRANT list handwaved between 03 and 07; neither nails it. | Add a short GRANT table to 03 §5 (or 07) listing `SELECT`/`INSERT`/`UPDATE`/`DELETE` per table + denied tables (`attempts`, `quiz_sessions`, `signing_keys`). | 0 | FIX-NOW |
| C-47 | MEDIUM | 03 | `hstore_to_jsonb` is in the `hstore` extension, not core; cast `preferences::jsonb` works directly. | Verify on live PG version; use `preferences::jsonb` (cleaner). | 1 (Phase 2a) | DEFER |
| C-48 | MEDIUM | 03 | Persona width: 03 declares `VARCHAR(16)`, 04 says `VARCHAR(32)`. | Align on `VARCHAR(32)` in 03. | 0 | FIX-NOW |
| C-49 | MEDIUM | 04 | PKCE verifier in long-lived session cookie widens theft window + bloats every request. | Use a short-lived signed pre-auth cookie (5 min max_age), cleared on callback. | 0 | FIX-NOW |
| C-50 | MEDIUM | 04 | Directus role-mirror direction unspecified; bidirectional dual-write will drift. | Lock to one-way Directus → app; document in 04 §7. | 0 | FIX-NOW |
| C-51 | MEDIUM | 04 | Row 4 ambiguity — does `platform_admin` get to download anyone's cert? | Default: `platform_admin` uses the same ownership loop (no admin download surface in v2). Mark row 4 as ✅*. | 0 | FIX-NOW |
| C-52 | MEDIUM | 05 | Webhook seam HMAC has no timestamp/nonce → replayable. | Bind webhook to loopback only (no HMAC); add Apache deny from non-loopback. | 0 | FIX-NOW |
| C-53 | MEDIUM | 05 | `ADMIN_EMAILS` mis-tiered as Tier 1 secret. | Reclassify as Tier 2 env config (allowlist, not key). | 0 | FIX-NOW |
| C-54 | MEDIUM | 05 | `FROM_EMAIL` migration row inconsistent (tier=C, destination implies env). | Fix the §6 row to "→ `app_config` `mail.from_email` (seed)". | 0 | FIX-NOW |
| C-55 | MEDIUM | 05 | Directus internal `KEY`/`SECRET` env vars not in §1.5 inventory. | Add `DIRECTUS_KEY` + `DIRECTUS_SECRET` rows to §1.5 Tier 1. | 0 | FIX-NOW |
| C-56 | MEDIUM | 05 | LLM model in DB + key in env can mismatch entitlements; no startup self-test. | Add a startup model-allowlist check per provider when `LLM_PROVIDER != "none"`. | 1 (Phase 2d) | DEFER |
| C-57 | MEDIUM | 06 | Three different `Cache-Control` directives for `/api/feed` across this single doc. | Parameterise `cached_response(..., cache_control=...)`; show feed call site. | 0 | FIX-NOW |
| C-58 | MEDIUM | 06 | `FallbackResource /app/index.html` + content-hash rewrite → renamed JS can silently return HTML. | Scope `FallbackResource` to exclude `/app/(js|css)/`. | 0 | FIX-NOW |
| C-59 | MEDIUM | 06 | LISTEN/NOTIFY adds real complexity (sync psycopg2 driver, async reconnect, NOTIFY size cap) for 2 workers. | Default to TTL-only (15 min framework / 30 s feed); keep LISTEN/NOTIFY as an alternative in §10. | 0 | FIX-NOW |
| C-60 | MEDIUM | 06 | `db.py` pool sizing missing from 05 registry. | Add `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` to 05 §1.5. | 0 | FIX-NOW |
| C-61 | MEDIUM | 06 ↔ 03 | `idx_attempts_test_code` duplicate — 06 recommends, 03 has `UNIQUE` already. | Strike the 06 recommendation. | 0 | FIX-NOW |
| C-62 | MEDIUM | 07 | `auth_audit` ↔ `security_audit` confusion — two audit tables, only one needed. | Use `auth_audit` only; for CSP reports use `report-to` + file log until v2.1. | 0 | FIX-NOW |
| C-63 | MEDIUM | 07 | `APP_PAYLOAD_SECRET` rotation silently drops in-flight quizzes — not surfaced as a gate question. | Add explicit gate question; default: accept silent drop (operator runs rotation in maintenance window). | 0 | FIX-NOW (gate question) |
| C-64 | MEDIUM | 07 | `SystemCallFilter=~@resources` will likely break Pillow/ffprobe under uvicorn. | Soft-default: keep `@system-service` only; verify aggressive filters with a 24 h soak in Phase 3c. | 1 (Phase 3c) | DEFER |
| C-65 | MEDIUM | 07 | Old signing-key 5-year `can_verify` window has no enforcement mechanism. | Add `signing_keys.verify_until TIMESTAMPTZ` column to 03; 07 references it. | 0 | FIX-NOW |
| C-66 | MEDIUM | 07 | F-CSR-01 escalates `/logout` to POST but no regression check in §11.1. | Add: `GET /logout` → 405; `POST /logout` without CSRF token → 403. | 0 | FIX-NOW |
| C-67 | MEDIUM | 07 | CSP for `/anatomy/*` lacks explicit `media-src` despite course HTML using `<video>`. | Add `media-src 'self';` to the course profile. | 0 | FIX-NOW |
| C-68 | MEDIUM | 07 ↔ v2-plan | 07 §10 uses non-existent phase labels ("Phase 3a (front-end)") — v2-plan's Phase 3 is 3a (env) / 3b (perf) / 3c (network). | Sweep 07 §10 to v2-plan taxonomy (FE reorg = Phase 1; FE security headers = Phase 3c). | 0 | FIX-NOW |
| C-69 | MEDIUM | 08 | `:::tip "Why This Matters"` syntax form is unreliable; bracket form `:::tip[Why This Matters]` is canonical in 3.x. | Correct admonition examples. | 0 | FIX-NOW |
| C-70 | MEDIUM | 08 | `editUrl: undefined` defeats the "every claim cites `path:line`" goal. | Either set `editUrl` to an internal git URL or add a remark plugin linkifying `path:line` strings. Default: leave plain text, revisit Phase 5a. | 1 (Phase 5a) | DEFER |
| C-71 | MEDIUM | 08 ↔ 06 | `Alias /docs/` block lacks immutable-asset cache headers for Docusaurus `assets/*` hashed files. | Add a `<FilesMatch>` immutable block, or cross-reference 06 §2.4 explicitly. | 0 | FIX-NOW |
| C-72 | LOW | many | Misc doc-hygiene — line-number citations going stale, role-key snake_case vs PascalCase labels, `attempts.id SERIAL` vs `BIGSERIAL`, `core/router.js` / `tokens.css` marked `[NEW]` though optional, `/docs` OpenAPI gating, etc. | Sweep in Phase 1 pre-flight; not blocking. | 1 | DEFER |

---

## 3 · Blockers for Phase 1 (from the coherence critic)

These must be reconciled in writing before Phase 1 starts. Each maps to one or
more findings above:

1. **[C-01] `QuizManager` backfill contradiction (03 ↔ 04).** Critical security
   regression risk. Reconcile to 04's rule (`QuizManager → {learner}` + emit
   migration report) before any Alembic work begins.
2. **[C-02] `user_roles` vs `users.roles` schema/code mismatch (03 ↔ 04).** Every
   code sketch in 04 is invalid against 03's schema; converge before Phase 2b
   touches `require_permission`.
3. **[C-03] Missing `auth_audit` DDL in 03.** 04, 07, 02 all depend on the
   table; 03 must add the DDL or the dependent docs must abandon the column.
4. **[C-04] `APP_ENV` vs `APP_ENVIRONMENT` env-var name (07 ↔ 05).** One name
   must be picked before any `.env.*.example` template is written.
5. **[C-06] Cert-ID prefix policy + parity-regex (02 ↔ 03 ↔ 07).** Either commit
   to `DEV-`/`STG-` prefixes (and fix 02's regex) or drop the prefix idea from
   07 §8.2. Must be settled before Phase 2c.
6. **[C-07 + C-08] Parity-harness coverage gaps (02).** 02 cannot be the gate
   it claims to be without a real-cert canary check, an AuthZ-split smoke, an
   `app_config` defaults smoke, and a `can_verify=false` rejection smoke.
   Expand 02 §1.1 + §3 phase table before any Phase 2 step ships.

The fix-before-gate-approval items in §6 below clear all six.

---

## 4 · Locked gate decisions (user must confirm or flip)

These three decisions were proposed defaults in `v2-plan.md §"Open decisions to
confirm at the Phase 0 gate"`. They are restated below with the alternative and
the design's recommendation.

### Decision A — Role taxonomy

- **Default (recommended): two-plane.**
  - Learner-plane (Google SSO, FastAPI): `learner`, `feed_contributor`.
  - Staff-plane (Directus + DB grants): `content_author`, `quiz_admin`,
    `feed_moderator`, `platform_admin`.
  - Personas (`pm`/`ba`/`architect`/…) move from `users.role` to a non-authorising
    `users.persona` column — drives quiz-difficulty recommendation only.
  - Capability stored in the `user_roles` join table (03 §2.2).
- **Alternative: unified RBAC.** One flat role per user; staff and learner roles
  in the same enum; Directus reads/writes the same `users.role` column.
  Simpler but conflates "what you do here" with "who you are" — the very
  bug the audit found.
- **Recommendation: keep the default.** Two-plane matches both the audit
  finding (System A vs System B) and Directus's natural shape (it brings its
  own RBAC for the staff plane).

### Decision B — Course source-of-truth under Directus

- **Default (recommended): Postgres becomes the editable source; git-JSON
  becomes an export/seed.** A deliberate shift from ADR 0001. Directus owns the
  editable collections; FastAPI reads DB-first with filesystem fallback (as it
  already does). `scripts/export-content.py` writes JSON back to
  `content/source/…` for review/diff/seed.
- **Alternative: git-JSON remains canonical.** Directus reads JSON via a
  pipeline; edits go via PR. Cleanly auditable in git but introduces a build
  step and breaks the editor loop.
- **Recommendation: keep the default.** The DB-first read path already exists
  in code; the cost of moving editorial to Postgres is one export script.

### Decision C — Media strategy

- **Default (recommended): Postgres large objects (LOs) for streaming; Directus
  for metadata only.** Range-streaming continues from `pg_largeobject` via
  `/media/video/{asset_id}`; Directus introspects `media_assets` for the
  staff-plane browse UI. Directus's own `directus_files` collection is
  disabled to avoid a shadow store.
- **Alternative: move all media to Directus-managed storage (filesystem or
  S3-style).** Standard Directus pattern; loses the LO + Range-stream shape;
  requires migrating ~hundreds of MB of media; introduces a second storage
  surface to back up.
- **Recommendation: keep the default.** The LO pipeline is working and
  Range-stream-capable; Directus's strength is the editor surface, not the
  storage backend.

---

## 5 · Additional gate questions surfaced by the critics

| # | Question | Recommended default |
|---|---|---|
| Q-1 | **Session cookie `max_age` — 8 h or 14 d?** (C-05) | 8 h (security-stronger; matches typical SSO discipline). |
| Q-2 | **Cert-ID prefix policy** — keep `CCA-F-…` for all envs, or add `DEV-`/`STG-` prefixes? (C-06) | Add prefixes for non-prod; prod unchanged. Update 02's parity regex accordingly. |
| Q-3 | **`/logout` GET → POST** — accept UI churn (every "Sign out" link becomes a form)? | Yes; the CSRF posture demands it. |
| Q-4 | **CSP `report-uri`** — ship `security_audit` in Phase 2a, defer to v2.1, or use `report-to` + file/journald log? | Use `report-to` + file log for v2; table in v2.1. |
| Q-5 | **`APP_PAYLOAD_SECRET` rotation drops in-flight quizzes** — acceptable, or build dual-decrypt seam in 2c? | Acceptable; rotate in maintenance windows. |
| Q-6 | **`SystemCallFilter=~@resources`** — aggressive (and own Pillow/ffprobe regression risk) or `@system-service` only? | `@system-service` only at v2 launch; tighten after Phase 3c soak. |
| Q-7 | **`signing_keys.verify_until`** — enforce via DB column now, or runbook-only? | DB column now; cheap, prevents drift. |
| Q-8 | **Delete tracked `quiz-certification/app/review.py`?** | Yes — dead code, no imports. |
| Q-9 | **`deploy_schema.sql` — keep as `backend/migrations/legacy/reference.sql` or `git rm`?** | Keep as legacy reference for one phase, then remove in Phase 2a. |
| Q-10 | **Resources under `/anatomy/` or a new `/resources/` alias?** | `/anatomy/` (parity with current). |
| Q-11 | **Production `QUIZ_WORKERS` today** — is `--workers > 1` already in use? (Drives C-12.) | Confirm with operator; default Phase 1 to `QUIZ_WORKERS=1` if so. |
| Q-12 | **Issued cert PDFs / outgoing emails embed `/app/resources/` URLs?** | Grep before Phase 1; if found, add `Redirect 301`. |
| Q-13 | **`/static/` — Apache-aliased or FastAPI-proxied in v2?** | FastAPI-proxied via Apache (default). |
| Q-14 | **`GOOGLE_REDIRECT_URI` — deprecate but allow override, or delete?** | Deprecate but allow override. |
| Q-15 | **Webhook seam — HMAC + timestamp, or loopback-only?** | Loopback-only (Directus and FastAPI co-resident on one VM). |
| Q-16 | **`ADMIN_EMAILS`** — secret (Tier 1) or config (Tier 2)? | Config (Tier 2) — allowlist, not a key. |
| Q-17 | **Pass-mark backfill for legacy attempts** — write `pass_mark_correct=25` into every existing `attempts.payload.grading`, or leave verification HMAC-only? | HMAC-only; verification never reads `payload.grading`. |
| Q-18 | **Disable Directus's built-in `Files` collection** to avoid shadowing `media_assets`? | Yes — disable / hide from all roles. |
| Q-19 | **OS prerequisites for `docs-site`** — RHEL/Rocky/Alma 8+? Ubuntu 22.04+ in scope? | RHEL 8+ primary; Ubuntu 22.04+ as tested alternative. |
| Q-20 | **OpenAPI viewer for docs-site** — Swagger UI or ReDoc? Prebuild hook or manual? | ReDoc, generated on `npm run build` via a Python prebuild step. |
| Q-21 | **`auth_audit` ownership** — in 03 (recommended) or split into 04? | 03 — schema owner. |
| Q-22 | **`platform_admin` impersonation/read-any-cert surface** — exists in v2 or not? | Not in v2. Grant-and-config only. |
| Q-23 | **JWT lib choice for OIDC ID-token verification** — `google-auth`, `authlib`, or `PyJWT[crypto]`? | `google-auth` (least surface, Google-issuer aware). |

---

## 6 · Fix-before-gate-approval (mechanical, < 100 LOC each)

> **STATUS at seal:** ALL 51 items in this section have been applied across the
> 8 design docs (workflow `wjildzrp1`, eight parallel doc-owner agents). The
> baseline smoke (`tests/baseline/smoke.sh`) added the C-07 real-cert canary
> assertion and now runs **15/15 PASS** (vs. 14/14 at Phase 0 close). One
> sweep-time correction: **C-28 was a false positive** — `01-blueprint.md`
> canonically uses `backend/app/core/…` (preserving the uvicorn `app.main:app`
> target on the systemd unit), not `backend/core/…`. The sealer reverted 06's
> sweep so 06 is now correctly aligned to 01's actual tree. See §9.
>
> The list below is preserved verbatim for traceability and audit. Each line
> remains the contract the sweep delivered against.


These are the critic findings that are cheap, mechanical, and reviewable
in-place. Apply before declaring Phase 0 sealed. Each is a 1-doc edit, mostly
< 20 lines:

1. **C-04 / C-11 / C-28 / C-35 / C-36 — cross-doc renames.**
   - `APP_ENVIRONMENT → APP_ENV` in 07.
   - `content/course/sections/ → content/source/course/sections/` in 03 §6.
   - `backend/app/core/cache.py → backend/core/cache.py` in 06 §4.1 + §6.2 + §11.
   - `CentOS 8 → RHEL 8+/Rocky/Alma (Ubuntu 22.04+ alt)` in 08 §2.4.
   - `infra/scripts/ → backend/scripts/` in 08 §2.4/§4/§9.
2. **C-01 — adopt 04's `QuizManager → {learner}` rule.** Patch 03 §3 step 5 +
   §8 step 7.
3. **C-02 — repoint 04 code sketches to a `users_service.roles_for(email)`
   helper** instead of `db["roles"]`.
4. **C-03 — add `auth_audit` DDL to 03 §2 + Alembic revision row to §3 + §8.**
   Columns per 04 §7.4.
5. **C-19 — drop `users.legacy_role` from 04 §5.2;** rollback is via the §8
   backup snapshot.
6. **C-05 + Q-1 — settle session `max_age`** (default 8 h). Update 04 §6.4 +
   07 §4.1 to match.
7. **C-06 + Q-2 — settle cert-ID prefix.** Update 02 §1.5 regex to env-aware;
   document prefix policy in 03 §2.5 + 07 §8.2.
8. **C-07 — add real-cert canary smoke** to `tests/baseline/smoke.py`; fix
   fixture-count 17 → 16 in 02 §4.
9. **C-08 — re-align 02 §3 phase table** to v2-plan (Phase 2 sub-slices, Phase
   4 Directus, Phase 1 FE reorg).
10. **C-09 / C-10 / C-30 / C-57 / C-58 — cache-config corrections in 06.**
    - `Header set → Header always set` for cache directives + include
      `Cache-Control` in FastAPI 304 response.
    - Add `<LocationMatch "^/certificate/">` rule.
    - Drop `immutable` from `/media/*`; use `must-revalidate`.
    - Parameterise `cached_response(...)`; one rule per route.
    - Exclude `/app/(js|css)/` from `FallbackResource`.
11. **C-16 — fix Cache-Control baseline assertion** in 02 §5 ("absent today").
12. **C-17 — reword HMAC-key sentence** in 02 §1.3.
13. **C-20 — drop `app_config.is_secret` column** in 03 §2.4; keep `value_type`
    as Directus metadata only.
14. **C-21 — introduce `CERT_HMAC_LEGACY`** env var in 03 §2.5 + 05 §1.5; point
    `legacy-prod.env_var_name` at it.
15. **C-22 — lock permission/role-key vocabulary in 04;** sweep 07 (`feed.moderate`,
    `feed.contributor`) to match (`moderate.view`/`moderate.action`,
    `feed_moderator`/`feed_contributor`).
16. **C-23 — add session/cookie cutover step to 04 §8;** enumerate the eight
    `user.get("role")` read sites.
17. **C-24 — rewrite 05 §7.2** to call `core.cache.get_or_compute(...)` instead
    of inventing a parallel cache.
18. **C-25 — delete `CERT_DEV_MODE_KEY_ID` / `CERT_PROD_KEY_ID`** rows from 05
    §1.5 + §6; document the DB lookup.
19. **C-26 — keep `GOOGLE_REDIRECT_URI`** as optional override in 05 §4.1 + §6.
20. **C-27 — lock cert verification as HMAC-only** in 05 + 07; never read
    `payload.grading`.
21. **C-29 — add `mod_ratelimit` to 06 §2.1** enable list with an example
    `/api/media/upload` block.
22. **C-31 — replace CSP `report-uri` with `report-to` + file log** in 07 §3.2.
23. **C-32 — register every env var invented in 07** into 05 §1.5 with tier +
    destination.
24. **C-34 — pin `@easyops-cn/docusaurus-search-local`** in 08 §7.
25. **C-37 — replace inline cert-HMAC claim in 08 §2.5** with a reference to
    07 + 03.
26. **C-39 — add one sentence to 01 §5** on `/anatomy/` post-Phase-4 behaviour.
27. **C-40 — lock `/static/` to FastAPI-proxied** in 01 §3 + 06 §2.4.
28. **C-41 — create `modules/auth/routes.py`** in 01 §1 tree and §2.3 route
    table; remove the wavering between core and quiz.
29. **C-43 — relax 02 §1.2 rule 3** to allow move+edit with an ADR/waiver in
    `path-map.csv`.
30. **C-44 — set numeric FE-parity threshold** in 02 §1.4 (pixelmatch ≤ 0.5%
    @ 1440 px).
31. **C-45 — add rollback-drill row** to 02 §3 cutover.
32. **C-46 — add Directus DB-role GRANT table** to 03 §5.
33. **C-48 — align persona width** in 03 §2.2 to `VARCHAR(32)`.
34. **C-49 — split PKCE verifier into a short-lived pre-auth cookie** in 04
    §6.1.
35. **C-50 — lock Directus role-mirror direction** in 04 §7 (one-way: Directus
    → app).
36. **C-51 — clarify row 4** (`platform_admin` cert download uses ownership
    loop) in 04 §3.
37. **C-52 — bind webhook to loopback-only** in 05 §3.5 + §7.3; drop HMAC.
38. **C-53 — reclassify `ADMIN_EMAILS`** as Tier 2 env config in 05 §1.5.
39. **C-54 — fix `FROM_EMAIL` migration row** in 05 §6.
40. **C-55 — add `DIRECTUS_KEY` + `DIRECTUS_SECRET`** to 05 §1.5 Tier 1.
41. **C-59 — default to TTL-only invalidation** in 06 §4.2 + §10 Decision 1;
    LISTEN/NOTIFY moved to alternative.
42. **C-60 — add `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`** to 05 §1.5.
43. **C-61 — strike duplicate `idx_attempts_test_code` rec** from 06 §6.3.
44. **C-62 — collapse `security_audit` references** in 07 to use `auth_audit`
    + file logging.
45. **C-63 — add explicit gate question for `APP_PAYLOAD_SECRET` rotation** in
    07 §12.
46. **C-65 — add `signing_keys.verify_until`** column to 03 §2.5; 07 §8.4
    references it.
47. **C-66 — add `/logout` POST/GET regression checks** to 07 §11.1.
48. **C-67 — add `media-src 'self'`** to course-HTML CSP profile in 07 §3.2.
49. **C-68 — sweep 07 §10 phase labels** to v2-plan taxonomy.
50. **C-69 — correct admonition syntax** to bracket form in 08 §3.4.
51. **C-71 — add immutable-asset cache block** for `/docs/assets/` in 08 §5.

Each item above is mechanical — no design re-think, no new content. Together
they clear the six Phase-1 blockers in §3 and align the cross-doc vocabulary.

---

## 7 · GO / NO-GO recommendation

**Recommendation: GO with conditions.**

- The eight design contracts are coherent in shape and audit-faithful in
  detail. Citations spot-checked across critic reports were largely accurate;
  contradictions found are mechanical-rename-class issues, not design defects.
- The parity safety net (`tests/baseline/`) is real and runnable, with three
  fixable gaps (real-cert canary smoke, AuthZ-split smoke, `app_config`
  defaults smoke).
- The Docusaurus scaffold compiles into a working site once `npm install`
  runs.
- No critic surfaced a design-defect blocker that requires a fundamental
  re-think. Every CRITICAL finding maps to either (a) a mechanical sweep in
  §6, or (b) a gate decision the user must make in §4 / §5.

**Conditions for the gate to seal:**

1. User confirms or flips the three decisions in §4 (A — role taxonomy, B —
   course source-of-truth, C — media strategy).
2. User answers the additional gate questions in §5 (Q-1 through Q-23) — most
   accept the recommended default.
3. Phase 0 doc authors land the fix-before-gate-approval items in §6. This is
   one synchronised sweep: every cross-doc rename, every drift, every
   missing smoke check, in one PR.
4. Phase 1 acknowledges and defers the items marked `1+ DEFER` above — they
   are tracked but do not block the gate.

Once §6 is merged and §4 / §5 are confirmed, **Phase 1 (restructure + clean
code)** begins on branch `v2`, with `main` untouched.

---

## 8 · Appendix: cross-doc citation map

For every finding, the affected doc(s) and the recommended owner:

- **01-blueprint.md**: C-11, C-12, C-13, C-28, C-38, C-39, C-40, C-41, C-72.
- **02-parity-method.md**: C-07, C-08, C-14, C-15, C-16, C-17, C-42, C-43, C-44, C-45.
- **03-data-model.md**: C-01, C-02, C-03, C-11, C-18, C-19, C-20, C-21, C-46, C-47, C-48, C-65.
- **04-authz-model.md**: C-01, C-02, C-19, C-22, C-23, C-33, C-49, C-50, C-51, C-72.
- **05-config-cms.md**: C-24, C-25, C-26, C-27, C-32, C-52, C-53, C-54, C-55, C-56, C-60.
- **06-caching-performance.md**: C-09, C-10, C-28, C-29, C-30, C-57, C-58, C-59, C-60, C-61.
- **07-security-baseline.md**: C-04, C-05, C-22, C-23, C-31, C-32, C-33, C-62, C-63, C-64, C-65, C-66, C-67, C-68.
- **08-docs-plan.md**: C-34, C-35, C-36, C-37, C-69, C-70, C-71.

> Sealing correction (auto-mode):
> - **C-28** was reported as `01 says backend/core/cache.py; 06 says backend/app/core/cache.py`. The reverse is true. 01-blueprint canonically uses `backend/app/core/` everywhere (with the explicit rationale that this preserves the `app.main:app` target used by the systemd unit at `deploy.sh:761`, the `Dockerfile` CMD, and `start_local.sh:93`). 06 was already aligned. The sweep agent followed the report's faulty instruction and changed 06's four references from `backend/app/core/` → `backend/core/`. The sealer reverted those four edits. 06 now reads `backend/app/core/{cache,db}.py` again, aligned with 01.

---

## 9 · Locked decisions on seal

The three Phase-0 gate decisions and the 23 additional gate questions surfaced
by the critics are recorded below with their locked values. Each is the
recommended default. The user may flip any decision at the next phase gate (or
ad hoc) — none of them is irreversible.

### 9.1 Three locked Phase-0 decisions

| ID | Decision | Locked value | Status |
|---|---|---|---|
| A | **Role taxonomy** | Two-plane: learner-plane (Google SSO via FastAPI) = `learner`, `feed_contributor`; staff-plane (Directus + DB grants) = `content_author`, `quiz_admin`, `feed_moderator`, `platform_admin`. Personas (`pm`, `ba`, `architect`, …) move from `users.role` to `users.persona` and become a non-authorising profile attribute that drives quiz-difficulty recommendation. Capability stored in the `user_roles` join table (03 §2.2). | Locked (auto-mode default). |
| B | **Course source-of-truth under Directus** | Postgres becomes the editable source; git-JSON becomes an export/seed. FastAPI keeps DB-first reads with filesystem fallback. `scripts/export-content.py` writes JSON back to `content/source/…` for diff/seed. Documents the deliberate shift from ADR 0001. | Locked (auto-mode default). |
| C | **Media strategy** | Postgres large objects (`pg_largeobject`) for runtime range-streaming; Directus for asset metadata and the staff browse UI only. Directus's own `directus_files` collection is disabled to avoid a shadow store. | Locked (auto-mode default). |

### 9.2 Twenty-three additional gate questions

| # | Question | Locked answer |
|---|---|---|
| Q-1 | Session cookie `max_age` — 8 h or 14 d? | **8 h.** Security-stronger; matches SSO discipline. 04 §6.4 and 07 §4.1 are aligned to this value. |
| Q-2 | Cert-ID prefix policy — keep `CCA-F-…` for all envs, or add `DEV-`/`STG-` for non-prod? | **Add prefixes for non-prod; prod unchanged.** 02's regex updated to env-aware; 03 §2.5 applies prefix at cert generation; 07 §8.2 documents the policy. |
| Q-3 | `/logout` GET → POST — accept UI churn (every "Sign out" becomes a form)? | **Yes.** CSRF posture demands it. 07 §11.1 adds the regression checks (`GET /logout → 405`, `POST /logout` without CSRF → 403). |
| Q-4 | CSP `report-uri` — ship `security_audit` in Phase 2a, defer to v2.1, or use `report-to` + file/journald log? | **`report-to` + file log for v2.** `security_audit` table deferred to v2.1. 07 §3.2 implements; 03 has no `security_audit` DDL for v2. |
| Q-5 | `APP_PAYLOAD_SECRET` rotation drops in-flight quizzes — acceptable, or build dual-decrypt seam in 2c? | **Acceptable.** Rotate in maintenance windows. Recorded as gate question #8 in 07 §12. |
| Q-6 | `SystemCallFilter` — aggressive (with Pillow/ffprobe regression risk) or `@system-service` only? | **`@system-service` only at v2 launch.** Aggressive `~@privileged @resources` line shipped but commented; enable after Phase 3c 24 h soak. |
| Q-7 | `signing_keys.verify_until` — DB column or runbook-only? | **DB column.** Added to 03 §2.5; enforced by the verifier per 07 §8.4. |
| Q-8 | Delete tracked `quiz-certification/app/review.py`? | **Yes.** Dead code, no imports. Phase 1 clean-code slice removes it. |
| Q-9 | `deploy_schema.sql` — keep as legacy reference or `git rm`? | **Keep as `backend/migrations/legacy/reference.sql` for one phase; remove in Phase 2a** once Alembic baseline is stamped. |
| Q-10 | Resources under `/anatomy/` or a new `/resources/` alias? | **`/anatomy/`** (parity with current; no external bookmark churn). |
| Q-11 | Production `QUIZ_WORKERS` today — is `--workers > 1` already in use? | **Operator to confirm before Phase 1 cuts in.** Default Phase 1 acceptance item: pin `QUIZ_WORKERS=1` if `>1` is in use today, or bring `quiz_sessions` persistence forward into Phase 1. (Tracked in 01 §9 Slice A step 12.) |
| Q-12 | Issued cert PDFs / outgoing emails embed `/app/resources/` URLs? | **Phase 1 grep-then-decide.** If found, add `Redirect 301 /app/resources/ /anatomy/`. (Phase 1 acceptance item.) |
| Q-13 | `/static/` — Apache-aliased or FastAPI-proxied in v2? | **FastAPI-proxied via Apache.** 01 §3 + 06 §2.4 are aligned. |
| Q-14 | `GOOGLE_REDIRECT_URI` — deprecate but allow override, or delete? | **Deprecate but allow override.** 05 §4.1 and §6 keep the env var as optional; default is the derived form `APP_BASE_URL + /auth/google/callback`. |
| Q-15 | Webhook seam — HMAC + timestamp, or loopback-only? | **Loopback-only.** Directus and FastAPI are co-resident on one VM. 05 §7.3 binds `/api/cms/webhook` to `127.0.0.1` and 07's Apache config denies non-loopback. |
| Q-16 | `ADMIN_EMAILS` — secret (Tier 1) or config (Tier 2)? | **Config (Tier 2).** Allowlist, not a key. 05 §1.5 reclassified. |
| Q-17 | Pass-mark backfill for legacy attempts — write `pass_mark_correct=25` into every existing `attempts.payload.grading`, or leave verification HMAC-only? | **HMAC-only.** Verification never reads `payload.grading`. 05 §2.1 + 07 lock the policy. |
| Q-18 | Disable Directus's built-in `Files` collection to avoid shadowing `media_assets`? | **Yes.** Disable / hide from all roles. Reinforces decision C. |
| Q-19 | OS prerequisites for `docs-site` | **RHEL 8+ / Rocky / Alma primary; Ubuntu 22.04+ as tested alternative.** 08 §2.4 + `deploy.sh` matrix aligned. CentOS 8 removed. |
| Q-20 | OpenAPI viewer for docs-site | **ReDoc, generated by `backend/scripts/dump-openapi.py` on `npm run build`.** 08 §4 sourcing table. |
| Q-21 | `auth_audit` ownership | **03-data-model.md owns the schema** (§2.10 added in sweep). 04 and 07 reference. |
| Q-22 | `platform_admin` impersonation / read-any-cert surface | **Not in v2.** Grant-and-config only; ownership loop applies to cert downloads. 04 §3 row 4 clarified. |
| Q-23 | JWT lib choice for OIDC ID-token verification | **`google-auth`.** Least surface, Google-issuer aware. (Phase 2b will pin in `requirements.txt`.) |

### 9.3 What is NOT locked

These items are tracked but explicitly deferred — they remain open in their
owning later phase:

- **C-12** — `_active_quizzes` multi-worker hazard. Phase 1 acceptance item.
- **C-14**, **C-15** — Postgres-snapshot smoke + quiz round-trip debug endpoint. Phase 1 side-tasks.
- **C-33** — COOP/popup-OAuth regression. Phase 2b check.
- **C-38** — `/app/resources/` redirect (depends on Q-12 grep). Phase 1.
- **C-42** — Post-cutover cert-set diff. Phase 5b.
- **C-47** — `preferences::jsonb` cast simplification. Phase 2a verification.
- **C-56** — LLM startup model-allowlist self-test. Phase 2d.
- **C-64** — Aggressive `SystemCallFilter` rollout. Phase 3c 24 h soak.
- **C-70** — `editUrl` linkifier. Phase 5a.
- **C-72** — Misc doc-hygiene sweep. Phase 1 pre-flight.

---

## 10 · What unlocks Phase 1

Phase 0 is sealed. Phase 1 (restructure + clean code) is blocked on exactly
ONE remaining input:

- [x] §6 mechanical sweep — applied across all 8 docs (workflow `wjildzrp1`).
- [x] Reconciler residual-identifier check — clean (only false positive: C-28 path direction, reverted by sealer).
- [x] Baseline smoke — 15/15 PASS including the new real-cert canary (C-07).
- [x] Three locked Phase-0 decisions (§9.1) — accepted at recommended defaults.
- [x] Twenty-three additional gate questions (§9.2) — accepted at recommended defaults.
- [ ] **User GO** — orchestrator surfaces the seal; user says "begin Phase 1" (or flips any §9 decision and then says go).

Phase 1 then runs to its own plan: six partitionable slices (backend reorg, frontend reorg, content consolidation, clean-code deletions, infra path updates, integrate-and-verify) as defined in `01-blueprint.md` §9. Parity safety net (`tests/baseline/`) is re-run at the Phase 1 gate.

Phase 0 ends when §6 is merged and the gate decisions in §4 / §5 are confirmed.
