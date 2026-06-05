# Phase 2 — Backend Hardening Report

**Branch:** `v2` (main untouched)
**Phase 1 base:** `bd6aff3`
**Phase 2 head:** `2017e4f`
**Author:** Phase 2 orchestrator, v2 re-architecture

---

## 1. Status: **GO (conditional)** for Phase 3

Phase 2 is internally consistent against the design contracts (`00-gate-report.md §9`, `03`–`07`). All five slices landed, the cross-environment HMAC isolation contract holds end-to-end, the real-cert canary (`CCA-F-20260605-E79E74AB`) verifies byte-identical to the pre-Phase-2 state, and `bash tests/baseline/smoke.sh` is 15/15 — both standard and strict (`SMOKE_REAL_CERT_CHECK=1`) modes.

The conditional flag covers a single parity-fixup blocker carried forward from Phase 1: `backend/app/modules/media/{routes,storage,schemas}.py` are present and imported by `app/main.py:34` but untracked in git because the Phase 1 `.gitignore` line 57 (`media/`) swallows them. A fresh clone will not boot. This is a one-commit fix (force-add the three files or narrow the gitignore from `media/` to `/media/`) and is the single item that MUST land on `v2` before Phase 3a starts. The four other adversarial findings (F3) are documentation gaps and can ride with Phase 3a.

After the parity-fixup commit, Phase 3 (infra hardening — Postgres ops, Redis, Apache vhost, observability) is unblocked.

---

## 2. Per-slice one-line summaries

- **2a · Schema + migrations** (`2c917f6`) — Alembic introduced; six revisions (`0001_baseline` → `0006_lo_cleanup`) install the v2 schema (13 tables, 6 new) idempotently across sqlite + Postgres; existing `attempts` backfilled to `signing_key_id=1` (`legacy-prod`); pool tuning split by dialect.
- **2b · AuthZ + SSO** (`2017e4f`) — Google PKCE + `id_token` verify replace the legacy callback; `require_permission(perm)` + `PERMISSION_GRANTS` (10 permissions) replace `require_role`; dev auto-elevation removed; `users.persona` and `user_roles` backfilled (5 `FeedCreator → {learner}` demotes audited); `ADMIN_EMAILS`-driven `ensure_first_admin` runs at startup.
- **2c · Cert per-environment signing** (`fdb495c`) — `verification.py` introduces per-env HMAC lookup via `signing_keys.env_var_name`; `apply_env_prefix` stamps `DEV-`/`STG-` non-prod; PDF watermark + verify-page banner make non-prod certs visually unmistakable; production cert HMAC remains byte-identical (parity invariant preserved).
- **2d · Config service + CMS seam** (`43955c3`) — `pydantic-settings` `Settings` model with `validate_for_env` model-validator; 27 backward-compat module constants preserved on `app.core.config`; `cms_client.cfg()` reads through cache+DB+DEFAULTS (19 keys seeded); loopback-only `POST /api/cms/webhook` invalidation receiver; `llm.py` provider seam; per-env `.env` templates.
- **2e · App-level security baseline** (`cc582df`) — `SecurityHeadersMiddleware` stamps six headers (HSTS+CSP intentionally deferred to Apache/3c); `SessionMiddleware` set to `aoc_session`, `Max-Age=28800` (Q-1), `HttpOnly`, `SameSite=Lax`, `Secure` only in production; CORS tightened (production = no CORS middleware, same-origin via Apache); media upload hardening (`assert_mime_allowed` denies SVG/XML/HTML; `create_secure_tempfile` chmod 0o600).

---

## 3. Numbers

| Metric | Value |
|---|---|
| Slices landed | 5 (2a, 2b, 2c, 2d, 2e) |
| Commits on `v2` | 5 (atop Phase 1 `bd6aff3`) |
| Files touched (cumulative, deduped) | 37 distinct paths |
| Alembic revisions | 6 (`0001_baseline` through `0006_lo_cleanup`) |
| Tables in metadata | 13 (was 7; 6 new: `signing_keys`, `roles`, `user_roles`, `quiz_sessions`, `app_config`, `auth_audit`) |
| New columns on existing tables | 3 (`users.persona`, `attempts.environment`, `attempts.signing_key_id`) |
| Indexes reconciled | 3 portable + 2 Postgres-only GIN (per `0002_reconcile`) |
| Roles seeded | 6 (`learner`, `feed_contributor`, `content_author`, `quiz_admin`, `feed_moderator`, `platform_admin`) |
| Signing keys seeded | 1 (`legacy-prod`, env_var `CERT_HMAC_LEGACY`) |
| `app_config` keys seeded | 19 (parity contract for v1 hardcoded constants) |
| Permissions defined | 10 (`PERMISSION_GRANTS` in `core/deps.py`) |
| Routes (Phase 1 baseline → Phase 2 head) | 38 → 40 (+2 from `/api/cms/api/cms/{health,webhook}` double-prefix; see F1 note 1) |
| Backfill row counts | 15 users touched · 9 personas set · 15 learner-floor rows · 5 demotes audited · 2 admin grants audited |
| Smoke (baseline) | 15/15 PASS |
| Smoke (strict, `SMOKE_REAL_CERT_CHECK=1`) | 15/15 PASS — real cert HMAC `948f2a88…2cf6c0` byte-identical to pre-Phase-2 |
| Cross-environment cert canary (F2 Test 1) | 3/3 positive paths PASS · 3/3 negative paths PASS (signature_mismatch across env boundary) |
| Cross-env prefix idempotency (F2 Test 2) | 4/4 PASS |
| Alembic re-run on live DB | no-op (`current=0006_lo_cleanup (head)` before and after) |

---

## 4. Locked cross-cutting decisions applied (`00-gate-report.md §9`)

| Decision | Applied as | Verified |
|---|---|---|
| **C-01** RBAC strict mapping | `FeedCreator → {learner}` only; admin grants are explicit via `ADMIN_EMAILS` + `grant_role` | 2b backfill: 5 `migration.role.demote` audit rows; `roles_for('u.sumit@deptagency.com')` → `{learner}` |
| **C-02** Permission seam | `require_permission(perm)` + `roles_for(email)` everywhere; `require_role` retained as deprecated shim only | `grep require_role backend/app/modules/` → 0 hits |
| **C-12** `quiz_sessions` + `QUIZ_WORKERS=1` | Table created (`0003_new_tables`); worker pin preserved from Phase 1 | Table present in metadata; `start.sh` pin unchanged |
| **Q-1** Session lifetime 8h | `aoc_session` cookie `Max-Age=28800` | Observed in `Set-Cookie` header (F2 Test 5) |
| **Q-2** Cert-ID prefix policy | `DEV-`/`STG-` non-prod; production unchanged; idempotent (no double-stamp) | F2 Test 2 PASS across all three envs + already-stamped input |
| **Q-3** Logout method | `POST /logout` (CSRF-safe) | Implemented in 2b auth routes |
| **Q-7** Cert verify-page badge | `.verify-envbanner` for non-prod; existing valid/legacy/invalid badges preserved verbatim | 2c — visible in `verify-real-cert.html` fixture |
| **Q-15** CMS webhook loopback-only | `_is_loopback` accepts `127.0.0.1`, `::1`, `::ffff:127.0.0.1`, `localhost`; non-loopback → 403 | F1 verification: 403 on non-loopback client |
| **Q-16** `ADMIN_EMAILS` Tier 2 bootstrap | `ensure_first_admin()` reads env, grants `platform_admin`, audits `role.grant` | F2 Test 3: `yash@deptagency.com` → `{learner, platform_admin}` |
| **Q-17** HMAC-only verifier | `verification.verify_attempt` uses HMAC; no asymmetric path on prod | 2c verifier flipped; cross-env negative paths return `signature_mismatch` |
| **Q-22** No impersonation | Removed; no dev backdoor login as another user | 2b: `upsert_user` writes `role=None`, `users.py:43` documents removal |
| **Q-23** `google-auth` for id_token verify | `google-auth>=2.30` pinned; PKCE + `id_token.verify_oauth2_token` callback | 2b: dependency pinned, callback uses google-auth |

---

## 5. Adversarial findings from F3

| # | Severity | Area | Finding | Recommendation |
|---|---|---|---|---|
| 1 | **HIGH (Phase 3 blocker)** | Phase 1 latent / 2e | `backend/app/modules/media/{routes,storage,schemas}.py` exist on disk and are imported by `app/main.py:34` but are **untracked in git** — `.gitignore` line 57 (`media/`) swallows them. Fresh clone fails to boot with `ImportError`. | One-commit fix on `v2`: `git add -f backend/app/modules/media/{routes,storage,schemas}.py` OR narrow gitignore from `media/` to `/media/`. MUST land before Phase 3a. |
| 2 | MEDIUM | 2d config | `CORS_ORIGINS` is read by `core/security.py:_resolve_cors_origins` but not documented in any `.env*.example`. | Add `CORS_ORIGINS=` with comment ("comma-separated origins; empty in production = no CORS middleware, same-origin only via Apache") to all four `.env` example files. |
| 3 | LOW | 2d config | `DB_POOL_SIZE` and `CACHE_TTL_{FRAMEWORK,FEED,APP_CONFIG}` documented in per-env templates but missing from canonical `backend/.env.example`. | Mirror these into `backend/.env.example`. |
| 4 | LOW (informational) | 2c storage | `quiz/storage.sign_attempt` signature changed from `(cert_id, email, score, submitted_at)` to `(record: Dict)`; private `_sign_payload` removed. No external callers — `grep` returns 0 hits outside storage/verification. | None required. Note in `02-parity-method.md` that private helpers were reshaped without caller-visible regressions. |
| 5 | LOW | 2d hygiene | `backend/.env.example` defaults `APP_ENV=production` (line 41) which trips `validate_for_env` if an operator copies it verbatim with the dev `SECRET_KEY` default. | Change default to `APP_ENV=development` OR add explicit "if production, you MUST also set SECRET_KEY + CERT_HMAC_PROD" note. |

Findings 2–5 are documentation/UX gaps and can ride with Phase 3a. Finding 1 is the only blocker.

---

## 6. Open questions for the user

1. **Parity-fixup approach (Finding 1).** Two equally valid options:
   - **(a)** Single follow-up commit on `v2`: `git add -f backend/app/modules/media/{routes,storage,schemas}.py` + add the missing `.env.example` stanzas (Findings 2–3). Cleanest history; Phase 3 starts unblocked.
   - **(b)** Narrow the gitignore from `media/` to `/media/` (root-scoped). Slightly more correct fix semantically because the gitignore was over-broad; risk is that any future `media/` directory anywhere else in the tree no longer gets ignored.
   Recommendation: (a) plus a one-line gitignore comment explaining why. Confirm before I dispatch a parity-fixup agent.

2. **`.env.example` default for `APP_ENV` (Finding 5).** Flip to `development`, or keep as `production` with a louder warning comment? Recommendation: flip to `development` — the example file is meant to be safe-to-copy.

3. **`/api/admin/roles` POST endpoint.** Per `04 §7.2`, the role-assignment REST route is the half of 2b deliverable item 10 that did not land (seed + audit are in place; route wiring is not). Defer to Phase 3b alongside the admin console, or land as a 2b-followup on `v2`?

4. **Signing-key rotation runbook (`07 §8.4`).** Live `signing_keys` holds only `legacy-prod`. Should Phase 3 ops insert `dev-2026-01` / `stg-2026-01` rows now (so cert issuance works in those environments at any time), or wait until non-prod environments come online?

5. **CMS webhook double-prefix.** F1 noted `/api/cms/api/cms/{health,webhook}` is the observed URL — both the router decorators and the `include_router(prefix=...)` carry `/api/cms`. Fix in the parity-fixup commit (drop the decorator prefix) or treat as Phase 4a's contract surface? Recommendation: fix now — Directus Hooks payload contract assumes one URL.

---

## 7. What unlocks Phase 3

Phase 3 (infra hardening) presupposes a backend that:
- builds and boots from a fresh clone (Finding 1 blocks this);
- has a tested Alembic chain (✓);
- enforces auth + authz fail-closed (✓ — 2b + F2 Test 3);
- has a config service that refuses prod boot with dev defaults (✓ — 2d + F2 Test 4);
- has a security baseline at the app layer that Apache can extend without conflict (✓ — 2e + F2 Test 5);
- preserves cert parity end-to-end (✓ — strict smoke + F2 Tests 1+2).

After the parity-fixup commit (Finding 1, optionally bundling Findings 2 + 3 + 5 + the CMS double-prefix), Phase 3a (Postgres ops + observability) is the next agent and can proceed.

Phase 3 scope reminder:
- **3a** Postgres ops (backup runbook, restore drill, connection lifecycle, slow-query log).
- **3b** Redis swap behind `AppCache` (per-worker → cluster-wide; `cms_client.invalidate` semantics preserved).
- **3c** Apache vhost (HSTS, two CSP profiles per `07 §3.2`, SRI hashes for CDN-loaded mermaid/esm.sh/Ajv per `07 §3.3`, `Require ip 127.0.0.1` on the CMS webhook upstream).
- **3d** Observability seam (request-id, structured logs, healthchecks beyond `/healthz`).

Phase 2 hands these slices a backend they can build on without touching application semantics again.

---

## Appendix · Verification log (condensed)

```
git branch --show-current  -> v2
git log --oneline -6
  2017e4f phase-2/2b
  fdb495c phase-2/2c
  43955c3 phase-2/2d
  cc582df phase-2/2e
  2c917f6 phase-2/2a
  bd6aff3 phase-1 gate (base)

alembic upgrade head (live Postgres)  -> no-op, current=0006_lo_cleanup (head)
alembic upgrade head (sqlite q0.db)   -> no-op, current=0006_lo_cleanup (head)

bash tests/baseline/smoke.sh                       -> 15/15 PASS
SMOKE_REAL_CERT_CHECK=1 bash tests/baseline/smoke.sh -> 15/15 PASS
  GET /verify/CCA-F-20260605-E79E74AB -> valid=true (strict)
  HMAC 948f2a88…2cf6c0 byte-identical to pre-Phase-2

cross-env cert canary (F2 Test 1):
  prod cert verifies under prod key                       -> valid=True
  dev cert verifies under dev key                         -> valid=True
  stg cert verifies under stg key                         -> valid=True
  dev cert relabelled as prod key                         -> signature_mismatch
  prod cert with mutated score                            -> signature_mismatch
  dev cert relabelled as stg key                          -> signature_mismatch

permission grants (F2 Test 3):
  PERMISSION_GRANTS keys = 10  (matches 04 §3.1)
  fresh dev login -> roles_for(...) = {'learner'}  (no auto-elevation)
  yash@deptagency.com -> {'learner','platform_admin'}

config (F2 Test 4):
  cms_client.DEFAULTS count = 19  (matches seeded app_config)
  APP_ENV=production with dev SECRET_KEY -> ValidationError, both offending keys named

security (F2 Test 5):
  6 security headers stamped on every response
  Set-Cookie aoc_session ... Max-Age=28800; HttpOnly; SameSite=Lax
  Secure flag absent in dev (correct); will set on APP_ENV=production
```
