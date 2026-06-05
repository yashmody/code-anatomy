# Phase 3 — Infra Hardening — Orchestrator Report

**Branch:** `v2` (never switched, not pushed) · **main untouched** (`52dae68`)
**Date:** 2026-06-06 · **Tree:** clean at seal
**Smoke:** 15/15 · **Cert canary** `CCA-F-20260605-E79E74AB` → strict `valid=true` (200) · **Alembic head** `0007`

Phase 3 was partitioned by **file ownership** across three build slices (infra / app / ops)
plus three read-only verification passes (F1 functional, F2 structural lint, F3
adversarial). No slice touched another's files; every parity invariant held throughout.

---

## 1. Status — GO / NO-GO for Phase 4

**GO.**

All three build slices committed clean on `v2`. main untouched. The content corpus is
bit-identical baseline → HEAD → worktree (36 content JSON + frozen monolith + 4 frozen
pages, sha256 match). Smoke stays 15/15 with the real cert canary verifying strict.
Alembic is at head `0007`, reversible, and legacy-prod-safe. The Apache vhost parses
`Syntax OK` under `httpd -t` in both Report-Only and enforced CSP modes. The app defaults
to in-process cache and degrades gracefully when redis is absent. No junk tracked, no
caller-surface drift, config additions minimal (2 fields). F1, F2 and F3 each returned
ALL-PASS / GO independently.

No blockers carried forward. Open items (section 6) are policy decisions for the user, not
defects.

---

## 2. Per-slice summaries

### 3-INFRA — `deploy.sh` (exclusive) · commit `c8e56af`
Authored the full Apache CACHE + SECURITY + webhook + systemd + env-management blocks
into the generated HTTPS vhost and systemd unit. Discovered the live CDN allowlist by
grepping `frontend/` + `content/frozen/` (jsdelivr, esm.sh, fonts.googleapis,
fonts.gstatic, deptagency). Key finding: the SPA loads **both** CDNs (mermaid via
jsdelivr, Ajv via esm.sh), so the DEFAULT `script-src` lists both — wider than doc-07's
draft. Two CSP profiles ship: DEFAULT (vhost scope, adds esm.sh to script-src +
connect-src) and COURSE (`/anatomy/` scope, drops esm.sh, adds `media-src 'self'`).
Fixed a real quoting bug: the spec's `\047` octal-escape would stay literal inside a
double-quoted bash assignment, so Apache would have received `\047self\047`; switched to
literal single quotes. `bash -n` OK; `httpd -t` (Apache 2.4.66) `Syntax OK` for both CSP
variants. +325/−6, single file.

### 3-APP — `backend/app/**` + `requirements.txt` (exclusive) · commit `0a1f710`
Introduced a pluggable `CacheBackend` Protocol seam in `core/cache.py`. `AppCache` is the
facade that computes ETag + expiry and delegates to `MemoryBackend` (default, the Phase-2d
dict+RLock behaviour) or `RedisBackend` (lazy import, ping on first use, JSON envelope +
`SET EX`, `SCAN`+`DEL` prefix invalidation under an `aoc:` namespace). If redis is selected
but unavailable, it logs a warning and degrades to memory — verified live (boots, no crash,
`backend_name == "memory"`). Public surface preserved byte-for-byte, including the
`cache.cache.keys()`/`.size` callers in `cms_client.py` and `cms/routes.py`. Added
`core/observability.py` (request-id middleware, structured logs), `/healthz`, `/readyz`,
and the `/api/admin/roles` REST endpoint (POST grant / DELETE revoke / GET list on one
path). Only edits to `config.py`: two new fields. Respected the partition — staged only its
9 owned paths, leaving the concurrent infra/ops changes untouched.

### 3-OPS — `infra/**`, `start_local.sh`, migration `0007`, `frontend/` SRI, `docs/RUNBOOK.md` · commit `fa5022b`
Created `infra/postgres/cca-tuning.conf` (4 vCPU / 8 GB single-VM PG conf.d snippet, every
setting commented with rationale), `infra/cron/vacuumlo.sh` (nightly orphaned-LO sweep),
`infra/certbot/obtain-cert.sh` (idempotent `certbot --apache` wrapper, standalone operator
tool), and `docs/RUNBOOK.md` (backup/restore drill with cert-canary re-verify as the
acceptance gate, signing-key rotation, cache switch, vacuumlo). Added `--env` selection to
`start_local.sh` (seeds `.env` from `.env.<env>.example`, never overwrites). Authored
migration `0007` (down-revision `0006_lo_cleanup`, seeds dev/stg signing keys,
name-guarded). **Hardening finding:** the production partial-unique index `(environment)
WHERE is_active` would abort a blind `is_active=true` insert, so the migration claims the
active slot only when none exists for that environment — fresh deploys come up active,
local (with existing fixtures) comes up inactive, `can_verify=true` either way. Pinned
mermaid `@11` → `@11.4.1` with a real computed sha384 + `crossOrigin="anonymous"`; kept
Ajv/ajv-formats pinned with an in-code SRI TODO note (dynamic `import()` cannot carry
`integrity`; CSP `script-src` allowlist is the real gate).

---

## 3. Numbers

| Metric | Value |
|---|---|
| Apache directives added | 13 `Header always set` (HSTS ×1, CSP ×2, Report-To ×1, Vary ×1, Cache-Control ×7, + commented immutable block) |
| Apache structural blocks | Location ×4, LocationMatch ×4 (cache/security contexts); `Protocols h2 http/1.1`; mod_deflate filter |
| Apache modules enabled | `deflate expires http2 ratelimit` (RHEL verify-loop) |
| Security headers (live, app layer) | 6 (Phase-2, unchanged) + HSTS/CSP set once at Apache layer (no dup) |
| Cache backends | 2 (`memory` default, `redis` opt-in via `CACHE_BACKEND`/`REDIS_URL`) |
| New config fields | 2 (`cache_backend: Literal["memory","redis"]="memory"`, `redis_url`) |
| New routes | 3 paths (`/healthz`, `/readyz`, `/api/admin/roles`); roles carries POST+DELETE+GET |
| Route total | ~44 route objects / 40 unique paths (was 41/37) |
| Migration | `0007_seed_nonprod_signing_keys` (head; reversible; legacy-prod-safe) |
| systemd hardening keys added | 7 (ProtectKernelTunables, ProtectControlGroups, ProtectKernelModules, RestrictAddressFamilies, RestrictNamespaces, LockPersonality, SystemCallFilter=@system-service) |
| infra files created | 3 (`cca-tuning.conf`, `vacuumlo.sh`, `obtain-cert.sh`) + `RUNBOOK.md` |
| Commits | 3 (`c8e56af` infra, `0a1f710` app, `fa5022b` ops) |
| Slice file conflicts | 0 |

---

## 4. Cross-cutting decisions applied

| ID | Decision | Where landed |
|---|---|---|
| **C-09** | Cache headers always-set | All 7 Cache-Control entries use `Header always set`; immutable `/app/` block commented "enable when cache-bust versioning lands (06 §3)" |
| **C-10** | Certificate `Vary: Cookie` | `^/certificate/` → `private, max-age=86400, must-revalidate` + `Vary "Cookie"` |
| **C-29** | Rate-limit media upload | `/api/media/upload` → `SetOutputFilter RATE_LIMIT` + `SetEnv rate-limit 4096` (mod_ratelimit) |
| **C-30** | Media not immutable | `^/media/` → `public, max-age=86400, must-revalidate` (NOT immutable) |
| **C-31** | `report-to`, not `report-uri` | CSP uses `report-to csp-endpoint`; `Report-To` header defines the group; `report-uri` only in an explanatory comment |
| **C-64** | systemd softened | 7 hardening keys present; **no** `MemoryDenyWriteExecute`, **no** `~@resources`/`~@privileged` deny-list |
| **C-67** | `media-src` in course CSP | COURSE profile (`/anatomy/`) adds `media-src 'self'` for the monolith `<video>` |
| **Q-3** | Admin-roles REST landed | `/api/admin/roles` (POST grant / DELETE revoke / GET list), single-prefixed |
| **Q-4** | Non-prod signing keys | Migration `0007` seeds `dev-default`/`stg-default`; legacy-prod untouched |
| **Q-15** | Webhook `Require` | `/api/cms/webhook` → `Require ip 127.0.0.1 ::1`, placed before ProxyPass `/` so it is not shadowed (C-52) |

CSP-enforcement gate: `CSP_ENFORCE` defaults to **Report-Only** with a safe-rollout comment;
`CSP_ENFORCE=1` flips to enforced. Both variants parse `Syntax OK`.

---

## 5. Adversarial findings (F3)

| Severity | Area | Finding |
|---|---|---|
| PASS | Content drift | Zero. 36 content JSON bit-identical baseline→HEAD→worktree; frozen monolith + 4 pages identical; no phase-3 commit touched `content/`. |
| PASS | 3-ops SRI vs frozen | SRI changes landed in `frontend/` only; `content/frozen/*` untouched. |
| PASS | SRI integrity tags | mermaid `@11.4.1` + real sha384 + `crossOrigin`; Ajv pinned, correctly no integrity (dynamic import); no malformed attrs; `node --check` clean. |
| PASS | Cache public surface | Module-level `cache.cache.size`/`.keys()` work; `get_or_compute(key, ttl=, loader=)` keyword-only preserved; no caller signature changed. |
| INFO | Cache (self-correction) | First probe asserted `.cache` on the instance and false-alarmed; callers import the module where `cache.cache` is the singleton. Re-tested correctly — surface sound. |
| PASS | config.py over-reach | Exactly 2 fields, 8 lines incl. comments. |
| PASS | healthz/readyz vs auth | Auth is per-route DI, not a global redirect; probes have no auth dep. Live: `/healthz`→200 (no redirect), `/readyz`→200, X-Request-ID echoed/minted, admin roles→401. |
| PASS | Apache header dup | App middleware skips HSTS+CSP and only adds `if name not in existing`; Apache sets each once; `/anatomy/` override uses `always set` (replaces). No dup at either layer. |
| PASS | deploy.sh syntax + vhost | `bash -n` OK; `httpd -t` Syntax OK in both CSP modes; quoting-bug fix confirmed. |
| PASS | Migration 0007 | down_revision `0006_lo_cleanup`; idempotent; downgrade keeps legacy-prod; active-slot guard safe against prod partial-unique index. |
| PASS | Junk tracked | None — only `.env.*.example` templates; no `.env`/`__pycache__`/`.venv`/`.rdb`. |
| PASS | Commit messages | All 3 descriptive and slice-prefixed. |
| PASS | Route delta | New: `/healthz`, `/readyz`, `/api/admin/roles` (POST+DELETE+GET). Matches 3-app report. |

**F3 verdict: GO for Phase 4.** No blockers.

---

## 6. Open questions for the user

1. **CSP enforcement cutover.** Ship as Report-Only first (current default), collect
   `/csp/report` traffic, then flip `CSP_ENFORCE=1`? Agree the soak window before the
   course/SPA go enforced.
2. **`/app/` immutable caching.** The immutable Cache-Control block is authored but
   commented; it unlocks only once cache-bust versioning (06 §3) lands on the SPA build.
   Confirm that is a Phase-4 (or later) deliverable.
3. **Ajv/ajv-formats SRI.** Dynamic `import()` cannot carry `integrity`; the CSP allowlist
   is today's gate. If hard SRI on Ajv is required, we need an import map or
   `<link rel=modulepreload integrity>`. Is the CSP allowlist acceptable as the control?
4. **certbot wrapper wiring.** `obtain-cert.sh` is a standalone operator tool by design;
   `deploy.sh` does not invoke it. Confirm cert issuance stays a manual operator step.
5. **Redis in production.** App defaults to in-process memory and was verified only in that
   mode locally (no redis available). Before enabling `CACHE_BACKEND=redis` in prod, we
   need a live redis-up integration pass.
6. **Local `.venv` pip shebang** points at a non-existent interpreter (stale path). Cosmetic
   for runtime, worth fixing outside any slice.

---

## 7. What unlocks Phase 4 — Directus CMS + navigation / IA

Phase 3 lays the operational floor Phase 4 builds on:

- **CMS webhook is locked down** (`Require ip 127.0.0.1 ::1`), so a Directus instance
  publishing via the webhook has a defined, host-local trust boundary.
- **Two CSP profiles + the allowlist are authored**, so adding Directus admin/preview
  origins is a bounded edit, not a from-scratch policy.
- **Cache seam is pluggable** — Directus-driven content can be cached/invalidated by prefix
  through the existing `AppCache` surface without touching callers; redis can be switched on
  per the RUNBOOK when load warrants.
- **Admin-roles REST (`/api/admin/roles`)** gives the role plumbing Phase 4's editorial /
  nav-admin surfaces will need.
- **Config + env management** (`APP_ENV`, `.env.<env>.example`, `start_local.sh --env`,
  non-prod signing keys via `0007`) means Phase 4 can stand up dev/staging Directus
  environments cleanly.
- **Parity gate intact** — content bit-identical, smoke 15/15, cert canary verifies — so
  Phase 4's nav/IA work starts from a known-good baseline.

**Next: Phase 4 — Directus CMS + navigation / IA.**
