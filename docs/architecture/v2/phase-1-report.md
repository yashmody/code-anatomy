# v2/phase-1 · Restructure + clean code — gate report

> Status: **Phase 1 COMPLETE · awaiting user GO for Phase 2.**
> Branch `v2`. `main` untouched. Parity verified against the safety net
> ([02-parity-method.md](./02-parity-method.md)).

This report is the gate the user reviews before Phase 2 (backend hardening)
starts. It lists what each slice delivered, the parity verification
results, the cross-cutting decisions applied, and one open question the
operator must answer before Phase 2a touches the database.

---

## 1 · What was delivered

| Commit | Slice | One-line summary |
|---|---|---|
| `30ac697` | Phase 0 | Design contracts + parity safety net + Docusaurus scaffold (52 files, +10,844). |
| `d190bbb` | **A · backend** | `quiz-certification/` → `backend/app/{core,modules}`. `main.py` split 863 → 71 lines (composition-only). `storage.py` split per-module per [01-blueprint §2.4](./01-blueprint.md). Six new `core/` seams (`config`, `db`, `models`, `auth`, `encryption`, `users`, `deps`, `security`, `cache`, `roles`). Six modules: `auth`, `quiz`, `content`, `feed`, `media`, `cms`. The `app.main:app` uvicorn target is preserved. 62 files, +1,402 / −1,166. |
| `2c9c33e` | **C · content** | `content-architecture/` → `content/source/`. `content-system/` → `content/frozen/`. `app/resources/` HTML duplicates deduped to canonical `content/frozen/` copies. ETL and ADRs follow. 51 files, +6 / −2,601 (the deletions are the de-duplicated resource HTMLs; bytes preserved in `content/frozen/`). |
| `c1d7593` | **D · clean-code** | Deleted `dev_quiz.py`, `review.py`, every `__pycache__/`, `.pytest_cache/`, `.expo/`, `.DS_Store`. `.gitignore` hardened with v2 paths (kept v1 patterns under a "legacy" header for cross-branch safety). 2 files, +1 / −134. |
| `5ca675c` | **B · frontend** | `app/` → `frontend/`. Restructured into `core/` (api-client, auth-ui, config — NEW, theme — NEW, main), `shared/` (dom, framework, registry, 14 block renderers, 3 render helpers), `modules/{course,feed,quiz,resources}`, `styles/`. Buildless ES modules preserved. 47 files, +103. |
| `befaff9` | **B-fix** | Slice B committed every rename at 100 % similarity — i.e. the agent moved files but skipped the import-path update step. Caught in post-commit review. This fix-up patched 32 files: every `'../util/dom.js'` → `'../dom.js'`, `'./modes/'` → `'../modules/course/'`, `'./feed/'` (in registry) → `'../modules/feed/'`, etc. `main.js` rewritten to import from `config.js` + `theme.js`. `index.html` `css/* → styles/*`, `js/main.js → core/main.js`, resource `href`s → `/anatomy/*`. Final grep: zero broken imports. 32 files, +86 / −110. |
| `d30440d` | **E · infra** | Every hardcoded path in `deploy.sh`, `start_local.sh`, the Apache vhost template, the systemd unit, the smoke harness, `DEPLOY.md`, `MEDIA.md`, `README.md`, `CLAUDE.md` repointed to v2 layout. C-12 mitigation: `QUIZ_WORKERS=1` pinned with comment. Q-12 grep: zero hits — no redirect needed. Q-13: `/static/` confirmed FastAPI-proxied (no Apache Alias). Q-14: `GOOGLE_REDIRECT_URI` keeps existing values (first-create-only). `backend/migrations/README.md` added as Phase 2a Alembic placeholder. 16 files, +291 / −143. |
| `f07bde7` | **E-fix** | F1 smoke caught one missed in-app path: `backend/app/modules/content/routes.py`'s filesystem fallback for `/api/course/framework-explainer` still pointed at the legacy `content-architecture/...` path, returning 404 when the DB row was absent. Also folded ETL's content paths through a single `CONTENT_SOURCE` constant. 2 files, +19 / −13. |

**Phase 1 totals:** 220 files changed, +12,713 insertions, −4,128 deletions across 8 commits (1 Phase 0 + 6 Phase 1 + 1 fix-up + 1 fix-up).

---

## 2 · Parity verification (the numbers)

| Invariant | Method | Result |
|---|---|---|
| **API contract** | `tests/baseline/smoke.sh` (15 checks vs the Phase 0 baseline) | **15/15 PASS**, exit 0. |
| **Content preservation** | `tests/baseline/make-manifest.sh` regenerated against `content/source/` + `content/frozen/`; sha256 set diffed vs the Phase 0 manifest at `30ac697:tests/baseline/content-manifest.txt`. | **44/44 hashes identical.** Paths changed; bytes did not. |
| **Backend imports** | `backend/.venv/bin/python -c "from app.main import app"` from `backend/`. | OK; **38 route entries** (the 30 documented in `routes.md` + the four FastAPI auto-routes `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` + the four `/api/feed[/flag]` POST/GET variants the FastAPI router lists separately + the `/static` mount). |
| **Route SET vs `routes.md`** | Normalised `{param}` substitutions and `comm`-diffed. | Every documented route present. v1-only entries (`/api/course/explainer`, `/app`) are: (a) the routes.md docstring shorthand for `/api/course/framework-explainer` — present in v2; and (b) the `/app` FastAPI static mount, which Slice A intentionally removed because Apache serves `/app/` via `Alias` in the Slice E vhost (per gate decision Q-13). |
| **Frontend imports** | Grep for `from '../util/'`, `from './modes/'`, `from '../feed/'`, etc. | **Zero broken imports.** |
| **Content checksum spot-check** | `coder-d.json`, `framework.json`, `framework-explainer.json`, `feed.json`, the frozen monolith. | 5/5 hashes match the v1 baseline manifest. |
| **C-12 pin** | Grep `deploy.sh` for the comment + `QUIZ_WORKERS` line. | Confirmed at the tunables block (line 44 area). Comment cites Phase 2a's `quiz_sessions` table as the unlock. |
| **Q-12 grep** | `grep -rn "/app/resources/" backend/app/ content/source/ backend/outbox/`. | **Zero matches.** No `Redirect 301` needed. |
| **`bash -n` syntax check** | `deploy.sh`, `start_local.sh`, `tests/baseline/smoke.sh`, `tests/baseline/make-manifest.sh`. | All clean. |
| **`.gitignore` hardening** | Verified: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.expo/`, `.DS_Store`, `backend/.venv/`, `backend/.pytest_cache/`, plus legacy `quiz-certification/.venv/` etc. for cross-branch safety. | Clean. |

The single regression caught during F1 (the `/api/course/framework-explainer` 404 fallback) was fixed in `f07bde7` before the gate sealed.

---

## 3 · Cross-cutting decisions applied

These were the Phase-0-locked gate decisions ([00-gate-report.md §9](./00-gate-report.md)) consumed by Phase 1:

| ID | Decision | Phase 1 evidence |
|---|---|---|
| **C-12** | Pin `QUIZ_WORKERS=1` until `quiz_sessions` persistence lands in Phase 2a. | `deploy.sh` tunables block sets `QUIZ_WORKERS="${QUIZ_WORKERS:-1}"` with the explanatory comment. `DEPLOY.md` v2-transition callout repeats it. |
| **Q-8** | Delete `quiz-certification/app/review.py`. | Done in Slice D. `git ls-files \| grep review.py` returns empty. |
| **Q-12** | Grep for `/app/resources/` URLs in cert/email/outbox; add Apache `Redirect 301` if found. | Zero matches across `backend/app/`, `content/source/`, `backend/outbox/`. No redirect added. |
| **Q-13** | Lock `/static/` to FastAPI-proxied (no Apache Alias). | Vhost template carries no `Alias /static/` block; FastAPI's `app.mount("/static", ...)` handles it; Apache `ProxyPass /` covers it. |
| **Q-14** | Deprecate-but-honour `GOOGLE_REDIRECT_URI`. | `deploy.sh` only writes the var on first-create (wrapped in a guard). Existing operator overrides survive a re-deploy. |
| **Q-19** | OS prereqs documented as RHEL 8+/Rocky/Alma (Ubuntu 22.04+ as tested alternative). | Already in 08-docs-plan.md per the Phase 0 sweep. |

The other 20 locked decisions in [00-gate-report.md §9.2](./00-gate-report.md) attach to later phases (2a–2e, 3a–3c, 4a–4c, 5a–5b).

---

## 4 · The two fix-ups (what to learn from)

Two slice agents committed work that was structurally correct but functionally incomplete. Both were caught before Phase 1 closed:

- **B-fix** (`befaff9`) — Slice B did `git mv` on every JS file but never updated the import paths inside them (every rename landed at 100 % similarity). Without this fix-up the front-end would have 404'd on every module load. Caught immediately because the renames left every `import './util/dom.js'` pointing at non-existent paths; a single grep showed it.
- **E-fix** (`f07bde7`) — Slice E swept every operator-facing path (`deploy.sh`, vhost, smoke, docs) but missed two in-application path constants (`backend/app/modules/content/routes.py` filesystem fallback and `backend/scripts/migrate_to_postgres.py` ETL paths). Caught by the F1 smoke as `[FAIL] /api/course/framework-explainer → 404`.

Both fix-ups are tiny (32 files / 86 ins in B-fix; 2 files / 19 ins in E-fix). The lesson, recorded for Phase 2 agent prompts: **every slice's verification step must include a real exercise of the migrated surface** (frontend imports must resolve in a fresh browser tab; backend routes must be hit by the smoke harness), not just `git status` and `bash -n`.

---

## 5 · Adversarial parity review

The Phase 0 baseline (smoke + manifest + routes.md + the equivalence harness at `frontend/tests/equivalence.html`) is the safety net 02-parity-method.md committed us to. Phase 1 ran the smoke + manifest + import resolution + route-set diff + checksum spot-check end-to-end. Every check passes.

Two items that an adversary might flag — both are non-regressions, justified:

1. **`/app` static mount no longer registered by FastAPI.** Slice A removed `app.mount("/app", StaticFiles(...))`. Apache's `Alias /app → ${APP_HOME}/frontend` (in the Slice E vhost) serves the SPA directly. Per gate decision Q-13's spirit, the FastAPI app no longer serves the SPA; the smoke harness doesn't test `/app/index.html` because that's Apache's responsibility. In `start_local.sh` dev, the developer hits `http://127.0.0.1:8080/frontend/index.html` directly (documented in `start_local.sh`'s header).
2. **Frontend visual parity cannot be automated here.** The equivalence harness at `frontend/tests/equivalence.html` and the four resource-page screenshots at three viewports remain a content-quality agent / manual sign-off until Playwright captures land. Phase 0 baseline's `02-parity-method.md` already records this as the standing posture. Phase 5b's pre-cutover gate runs the visual check end-to-end.

No CRITICAL findings. No content drift. **GO for Phase 2.**

---

## 6 · Open questions for the user (before Phase 2 starts)

| ID | Question | Default if no answer |
|---|---|---|
| **Q-11** | Operator confirmation: is the current production deployment running `QUIZ_WORKERS > 1`? If yes, Phase 2a's `quiz_sessions` table moves up the priority list because the in-memory dict breaks under multi-worker. If no, the C-12 pin is a no-op for prod (since `1` is now the default in `deploy.sh`). | Assume "operator may have set 2 in `.env`" and ship `quiz_sessions` early in Phase 2a (it's already first in the [03-data-model.md](./03-data-model.md) §3 migration list). No code change needed in Phase 1; this is a sequencing question for Phase 2a. |

All other Phase 0 questions were locked at recommended defaults in [00-gate-report.md §9](./00-gate-report.md).

---

## 7 · What unlocks Phase 2

Phase 2 (**backend hardening**) starts with `2a · DB + migrations` per [v2-plan.md](../v2-plan.md). Its scope:
- Adopt Alembic; baseline-stamp from the live schema; reconcile the `models.py` ↔ `deploy_schema.sql` drift documented in [03-data-model.md §1](./03-data-model.md).
- Add the new tables: `quiz_sessions`, `signing_keys`, `roles`, `user_roles`, `app_config`, `auth_audit`.
- Reconcile `attempts.environment` + signing-key reference for the cert dev-mode work owned by 2c.
- Postgres-only stance: retire `db.py:_migrate()` and the sqlite TypeDecorator fallbacks.
- Large-object cleanup (`vacuumlo` schedule + trigger).

Phase 2a is followed in parallel by **2b** (SSO + RBAC + persona reframe), **2c** (cert dev-mode + visible DEV watermark + per-env signing key), **2d** (config + secrets + LLM key seam), **2e** (app-layer security headers + cookie flags + CORS tightening).

Conditions to unlock Phase 2:
- [x] Phase 1 commits clean on branch `v2`.
- [x] Parity safety net green (smoke 15/15, manifest set-identical, route set complete).
- [x] Cross-cutting decisions applied per §3.
- [x] No CRITICAL adversarial findings.
- [ ] **User GO** — the orchestrator surfaces this report; user says "begin Phase 2" (or answers Q-11 first, or flips any locked decision and then says go).
