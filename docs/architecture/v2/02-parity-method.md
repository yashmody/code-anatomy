# v2/02 — Parity method: what "no loss" actually means, gate by gate

> Phase 0 design contract · Owner: Baseline/Parity agent · Covers the locked
> constraint **"NO LOSS of content, data, or functionality"** from `v2-plan.md`.
> Read [`v2-plan.md`](../v2-plan.md) first. This document defines what every
> later phase must prove before it can claim a gate is met.
>
> DESIGN ONLY — Phase 0. No code modified to write this. The artefacts under
> `tests/baseline/` are the live receipts the gates compare against.

This is a method document. It pins five definitions of "parity" — API
contract, content, DB data, FE visual, quiz/cert functional — and gives each
phase gate a literal checklist to run.

Cross-references:
- Restructure tree + per-route migration: [`01-blueprint.md`](./01-blueprint.md)
- Target schema, Alembic adoption, large-object plan: [`03-data-model.md`](./03-data-model.md)
- Roles, capability matrix, persona-as-profile: [`04-authz-model.md`](./04-authz-model.md)
- Route inventory: [`../../../tests/baseline/routes.md`](../../../tests/baseline/routes.md)
- DB inventory: [`../../../tests/baseline/db-snapshot.md`](../../../tests/baseline/db-snapshot.md)
- Content manifest: [`../../../tests/baseline/content-manifest.txt`](../../../tests/baseline/content-manifest.txt)
- Smoke runner: [`../../../tests/baseline/smoke.py`](../../../tests/baseline/smoke.py)
- Manifest generator: [`../../../tests/baseline/make-manifest.sh`](../../../tests/baseline/make-manifest.sh)
- FE equivalence harness: [`../../../app/tests/equivalence.html`](../../../app/tests/equivalence.html)

---

## 0. Scan box

- **Parity = five independent invariants**: API contract, content bytes, DB
  rows, FE visual diff, quiz/cert functional flow. Each must be re-asserted
  at every phase gate; one failing invariant blocks the gate.
- **Artefacts are committed**, results are not. `routes.md`, `db-snapshot.md`,
  `content-manifest.txt`, `smoke.py`, and the `fixtures/` directory go into
  git. Phase-gate output goes under `tests/baseline/.gate/` (gitignored) and
  is reviewed in the PR description, not stored.
- **The load-bearing real certificate (`CCA-F-20260605-E79E74AB`) is the
  canary.** Every cert ever issued in production must still verify after the
  cutover; the smoke suite verifies the local proxy of this guarantee.
- **The content manifest is byte-exact.** v2 may move files (the manifest
  paths change) but each file's `sha256` must match a row in the pre-cutover
  manifest under its new path. A "move and edit in the same change" is
  disallowed by default; allowed with an ADR/waiver column in
  `path-map.csv` (see §1.2 rule 3).
- **FE parity = `app/tests/equivalence.html` clean + manual screen diff** of
  the four resource pages (runbook, checklist, FAQs, course monolith) in
  light and dark mode at three viewports (mobile/tablet/desktop).

---

## 1. The five invariants

### 1.1 API contract parity

Source of truth: `tests/baseline/routes.md` (30 endpoints + 2 static mounts).

For every row in `routes.md` the post-change backend must keep:
- the **exact path string** (`/api/course/framework-explainer`, not
  `/api/course/explainer`);
- the **HTTP method**;
- the **status code for the unauthenticated case** documented in `routes.md`
  (401 for API/JSON paths, 302 for page paths);
- the **top-level response shape** for `GET /api/course/chapters`,
  `GET /api/course/framework-explainer`, `GET /api/feed`,
  `GET /auth/me`.

How to assert: run `bash tests/baseline/smoke.sh`. The script spawns the
backend in dev mode against local sqlite, hits 15 representative endpoints
(including the real-cert canary `GET /verify/CCA-F-20260605-E79E74AB`,
which must return `valid=true` against prod and a documented
"DB-unseeded" body locally — see §1.3 + the canary toggle below), saves
each response under `tests/baseline/fixtures/`, and exits non-zero if any
check fails. The full inventory in `routes.md` is the human-eyeball list;
the 15-shot smoke is the *automatable* subset.

**Caveat (necessary-but-not-sufficient).** The default `smoke.sh` runs
against the local sqlite copy bundled in `quiz-certification/q0.db`.
That is enough to catch route-shape regressions, but several parity
claims — `/api/course/framework` returning the framework dict, the
real-cert canary returning `valid=true`, the `/media/video/{id}` large-
object Range path — require **production Postgres** to actually
exercise. A `smoke.sh --prod` invocation against a Postgres snapshot
(read-only, on the bastion host or a restored copy) is a Phase 1
acceptance item; until it lands, the gate operator runs the suite twice
— once locally, and once manually against the prod snapshot with the
canary toggle (`SMOKE_REAL_CERT_CHECK=1`) enabled. The canary can also
be skipped entirely (`SMOKE_SKIP_REAL_CERT=1`) when the verifier server
is offline or firewalled — the assertion stays in the script so it
cannot be silently dropped.

Expanded coverage Phase ≥2 owns:
- **Authenticated quiz round-trip** (`POST /quiz/start` → `POST /quiz/submit`)
  — needs a session cookie. Added once `quiz_sessions` is persisted
  (`03-data-model.md` §2.3).
- **Media upload** (`POST /api/media/upload`) — needs a multipart fixture
  + a real Postgres for large objects. Added at the Phase 2c gate
  (`03-data-model.md` §2.7).

### 1.2 Content parity (byte-exact via SHA-256 manifest)

Source of truth: `tests/baseline/content-manifest.txt` (44 entries: 38 JSON
course/feed/schema/ADR files + 6 HTML pages).

Scope (matches `make-manifest.sh`):
- `content-architecture/**/*.json`
- `content-system/**/*.html`
- `app/resources/**/*.html`

What "no loss" means:
1. Every line in the **pre-cutover** manifest must reappear in the
   **post-cutover** manifest with the same `<sha256>` and `<bytecount>`.
   The relative path is allowed to change (v2 reorganises directories per
   `01-blueprint.md` §6).
2. Map old→new paths in a single CSV called `tests/baseline/.gate/path-map.csv`
   (gitignored) when running the gate. Each row is `old_path,new_path,sha256`;
   each row must exist verbatim in both manifests.
3. **A file should not change content and move in the same phase by
   default.** Either the path changes (manifest sha matches under the new
   path) or the bytes change (path stays put, sha changes, separate
   review). The byte-changed case requires an explicit ADR.
   *Waiver:* simultaneous move+edit is permitted when the row in
   `path-map.csv` carries an `adr=<ADR-id>` waiver column (e.g. the Phase 1
   `architect-runbook.html` back-link fix) — the new sha and ADR id are
   both recorded, and the gate reviewer signs off against the ADR.

Why this is strict: the frozen monolith at
`content-system/anatomy-of-code-course.html` (578 KB) is the **frozen
reference** — three separate front-end modes render against it. Any silent
edit invalidates the equivalence harness.

### 1.3 DB-data preservation

Source of truth: `tests/baseline/db-snapshot.md` (7 tables, ~525 rows
locally).

Gate procedure runs on production Postgres (the local sqlite is a sanity
proxy, not the gate target). The procedure is documented step by step in
`db-snapshot.md` §3 and produces three artefacts:

| Artefact                       | Purpose                                   |
|--------------------------------|-------------------------------------------|
| `prod-schema-pre.sql`          | `pg_dump --schema-only`, before the change |
| `prod-schema-post.sql`         | same, after the change                    |
| `prod-rowcounts-pre.txt`       | per-table `COUNT(*)`, before              |
| `prod-rowcounts-post.txt`      | per-table `COUNT(*)`, after               |
| `prod-certs-pre.txt`           | `(cert_id, test_code, user_email)` for every passed attempt, before |

Pass criteria:
- `diff prod-schema-pre.sql prod-schema-post.sql` shows **only `+` lines**
  (or the renamed-table equivalent — see `03-data-model.md` §3 for Alembic
  expectations).
- For each row in `prod-rowcounts-pre.txt`, the corresponding row in
  `prod-rowcounts-post.txt` is `>=`. Decreases block the gate; the only
  exception is a table explicitly retired by an ADR (none planned in
  Phase 1–2).
- Every `cert_id` in `prod-certs-pre.txt` returns `valid=true` from
  `GET /verify/{cert_id}` after the change. (The HMAC secret itself stays
  in environment variables — `SECRET_KEY` today, `CERT_HMAC_LEGACY` going
  forward for legacy-prod certs — never in the database. The new
  `signing_keys` table only records *which* key signed each cert via a
  `key_id` reference; key material is **not** stored in the DB. See
  `03-data-model.md` §2.5 + `05-config-cms.md` §1.5.)

### 1.4 Front-end visual parity

Source of truth: `app/tests/equivalence.html` + the four resource pages
(`app/resources/architect-runbook.html`, `code-coder-checklist.html`,
`faqs/index.html`, `faqs/aem-banking-faq.html`).

Procedure:
1. Serve the repo from root (`python3 -m http.server 8754` per the
   `feed-store-seam` memory note) on **two checkouts** simultaneously: the
   pre-change branch (`main`) and the post-change branch (`v2-step-N`).
2. Open `app/tests/equivalence.html` on both at the same viewport (1440px
   wide, light theme, then 1440px wide, dark theme, then 375px mobile light).
   The page renders side-by-side `monolith ↔ renderer` pairs for every block
   type — see `app/tests/equivalence.html:38-49`.
3. The summary banner must read `0 diffs`. Any reported diff is a parity
   failure unless the change explicitly adds a new block (in which case the
   "new on-brand components" section grows, but the diff list stays empty).
4. For each of the four resource pages, take a full-page screenshot at the
   three viewport sizes using system Chrome via Playwright (see the
   `visual-diagram-verification` memory note) and visually diff against
   the equivalent pre-change capture. The acceptance bar is **brand-
   intact, layout-identical, ochre `#FF4900` exact** — small font-rendering
   drift is acceptable; structural drift is not.

   **Numeric threshold.** The pixel-diff is run with `pixelmatch` (or the
   equivalent in `playwright-test`) at the 1440 px viewport in light mode:
   the acceptance bar is **≤ 0.5% non-anti-aliased differing pixels** per
   page (i.e. `pixelmatch` invoked with `{ includeAA: false }`). Pages that
   fail this bar — or scenarios where pixelmatch cannot be run (CI without
   Chrome) — fall back to a DOM-shape check: the post-change DOM must have
   the same element count (± 1%) per top-level section *and* a computed-style
   sweep must still find ochre `#FF4900` on the same number of nodes as the
   pre-change capture. Either gate (pixel ≤ 0.5% OR DOM-count + ochre
   presence) is sufficient; a fail on both blocks the gate.

This invariant is the one that **cannot be fully automated** in Phase 0; it
remains a manual gate signed off by the content-quality agent (per the
project rules in `CLAUDE.md`).

### 1.5 Quiz/cert functional parity

Source of truth: the in-memory transcript of one full passing attempt.

Procedure (run once per gate, capture as text/screenshot):
1. Boot the backend in dev mode against a copy of production data
   (`pg_dump` restore into a throwaway DB).
2. Sign in via `POST /login/dev` with a known test email.
3. `POST /quiz/start {"difficulty":"intermediate"}` — assert HTTP 200, JSON
   with a `quiz_id` and 30 `questions[]` (per `config.QUESTIONS_PER_QUIZ`).
4. Compute the answer key. **This step cannot be executed end-to-end
   today** — `quiz_generator.grade` is server-side and the in-process
   `_active_quizzes` mirror is not exposed over HTTP. Two paths unblock it,
   both deferred to Phase 1 as a side-task:
   - **Option A (preferred):** ship a `GET /debug/active-quiz/{quiz_id}`
     route gated by `QUIZ_DEV_MODE=true` that returns the cached question +
     answer key for the active session. Trivial to add; lives behind the
     same dev-mode flag as `POST /login/dev`.
   - **Option B:** seed a known-answers question bank in the test DB so the
     gate test feeds back a deterministic answer set without needing to
     read server state.
   Until one of the above lands, step 4 is run by hand: the gate operator
   eyeballs the question payload, fills in the correct answers from the
   source-of-truth question bank in `quiz-certification/app/questions/`,
   and feeds them to `POST /quiz/submit`. This honest manual fallback is
   what we use at Phase 0 and Phase 1 gates; the automation lands at the
   Phase 2a gate when `quiz_sessions` is persisted.
5. `POST /quiz/submit` — assert `passed=true`, `cert_id` matches the
   `CCA-F-YYYYMMDD-........` pattern, `test_code` matches `AOC-YYYYMMDD-XXXXXX`,
   and `review[]` has the expected per-question shape.
6. `GET /certificate/{cert_id}` — assert HTTP 200 with `Content-Type:
   application/pdf` and a non-zero body.
7. `GET /verify/{cert_id}` — assert HTML body contains "Valid" (or whatever
   the `verify.html` template renders for `valid=True`).

Pass criteria: every step exits with the documented status; the PDF file is
written under `certificates/`; the public verifier confirms the freshly
issued cert.

Phase 2a will refactor steps 4-7 into a Python test (`pytest`) once
`quiz_sessions` is persisted; for the moment the gate accepts a recorded
manual run logged in the PR description.

---

## 2. Gate procedure (what each phase runs)

Every phase gate runs the same five steps. The output goes under
`tests/baseline/.gate/<phase>-<step>/` (gitignored).

### 2.1 The five gate steps

```bash
# 0. Working directory.
cd /path/to/dept-deploy

# 1. Re-generate the content manifest.
bash tests/baseline/make-manifest.sh > tests/baseline/.gate/$STEP/manifest-post.txt
diff tests/baseline/content-manifest.txt \
     tests/baseline/.gate/$STEP/manifest-post.txt \
     > tests/baseline/.gate/$STEP/manifest.diff
# Acceptance: manifest.diff is empty OR consists only of path-renames that
#             match path-map.csv (every {old → new} row preserves the sha).

# 2. Run the API smoke suite.
bash tests/baseline/smoke.sh 2>&1 \
     | tee tests/baseline/.gate/$STEP/smoke.log
# Acceptance: smoke.sh exits 0; the [PASS] count equals the [TOTAL] count.

# 3. Take a fresh DB inventory.
#    Local sanity (sqlite):
cd quiz-certification && .venv/bin/python \
     ../tests/baseline/scripts/db-inventory.py \
     > ../tests/baseline/.gate/$STEP/db-counts-local.txt && cd -
#    Production (Postgres) — run on bastion host, NOT committed:
psql --command="..." > .gate/$STEP/db-counts-prod.txt   # see db-snapshot.md §3
# Acceptance: every prod row count >= corresponding pre-snapshot count;
#             schema diff additive only.

# 4. Re-render the FE equivalence harness.
#    Open app/tests/equivalence.html on the pre and post checkouts;
#    capture screenshots at 1440 light / 1440 dark / 375 light.
#    Acceptance: 0 diffs reported; resource-page screenshots match.

# 5. Run one quiz round-trip end-to-end (logged in dev mode).
#    Acceptance: cert issued, PDF generated, /verify confirms.
```

### 2.2 Gate checklist template

Copy this block verbatim into the phase PR description and fill the marks:

```
## Parity gate — Phase X step Y

- [ ] **API contract** — `bash tests/baseline/smoke.sh` exits 0, all checks PASS.
      Output attached as smoke.log.
- [ ] **Content manifest** — manifest.diff is empty OR every change row is in
      path-map.csv with sha preserved.
- [ ] **DB schema** — `diff prod-schema-pre.sql prod-schema-post.sql` is
      additive only. (Attach diff.)
- [ ] **DB rows** — every table row count is `>=` pre-snapshot. (Attach the
      two count files.)
- [ ] **Cert verification** — all `cert_id`s in prod-certs-pre.txt return
      valid=true via `GET /verify/{cert_id}` after the change.
- [ ] **FE equivalence** — `app/tests/equivalence.html` reports 0 diffs at
      1440-light, 1440-dark, 375-light. (Attach screenshots.)
- [ ] **Resource pages** — runbook / checklist / FAQs / monolith course HTML
      pixel-match the pre-change captures at the three viewports.
- [ ] **Quiz round-trip** — one full pass-and-cert flow recorded. cert_id,
      test_code, PDF size and /verify output pasted into the PR.

Sign-off: <content-quality agent name>, <date>.
```

A gate is **passed** when every box is ticked AND the relevant artefacts are
linked. A single unticked box blocks the merge.

---

## 3. What each phase specifically re-runs

Mapping each plan phase to the steps above. (Phases are the ones declared in
`v2-plan.md`; the table is the contract those phase agents must keep.)

| Phase | What it changes (summary)              | Steps required at the gate | Notes |
|-------|----------------------------------------|----------------------------|-------|
| 0     | Design docs only (this doc, 01/03/04)  | None — docs review only.   | This phase produces the harness; nothing is exercised against running code yet. |
| 1     | Restructure + clean-code pass: file moves per `01-blueprint.md` §1, §6, **and FE module reorg** (`01-blueprint.md` §4) | 1 (manifest), 2 (smoke), 4 (FE) | No DB change yet. Steps 3 + 5 not required *unless* migrations were added accidentally. FE reorg is folded in here — visual parity is the lead invariant. **Phase 1 acceptance items:** wire a `bash tests/baseline/smoke.sh --prod` invocation against a Postgres snapshot (the local sqlite smoke is necessary-but-not-sufficient — see §4 caveat); land the quiz round-trip automation per §1.5 step 4. |
| 2a    | Alembic adoption + `quiz_sessions`, `app_config`, `user_roles`, `auth_audit` tables (`03-data-model.md` §2) | **All five steps.** | The largest backend gate. Step 5 should be tightened into an automated pytest here once `quiz_sessions` is persisted. |
| 2b    | Persona-as-profile + new RBAC (`04-authz-model.md`)  | 1, 2, 3 (rowcount only), 5 | The smoke suite gains capability-coverage checks (`feed.create`, `moderate.action`, `quiz.admin` via the locked 04 vocabulary). |
| 2c    | Cert dev-mode + `signing_keys` table (`03-data-model.md` §2.5, `07-security-baseline.md` §8) | 1, 2, 3, 5 | New env-aware cert-ID prefix per §1.5; smoke gains a `can_verify=false` rejection check and the real-cert canary continues to pass under the new key-id lookup. |
| 2d    | Config/secrets seam (`05-config-cms.md` §1.5 + §3) — app_config-backed runtime config, env tier-1 secret registry | 1, 2, 3 (rowcount + schema) | Smoke gains an `app_config` defaults check: known keys return their seeded values via the cache seam. No FE change. |
| 2e    | App security headers + cookie/session hardening (`07-security-baseline.md` §3 + §4) | 1, 2 (with header assertions) | Smoke gains CSP / COOP / CORP presence checks for `/anatomy/*` and `/app/*`; `/logout` GET → 405 and POST-without-CSRF → 403 regression checks. |
| 3a    | Environment management (per-env config, deploy.sh)  | 1, 2 | Mechanical; the env-mode label `APP_ENV` propagates everywhere. |
| 3b    | Apache caching / `mod_deflate` / ETag / HTTP/2     | 1, 2 (with new caching assertions) | Caching headers become part of API contract; smoke flips the `Cache-Control` check from "absent" (§5 baseline) to a positive assertion per route. |
| 3c    | Network / process security (rate-limit, systemd, large-object decommission, media metadata) | 1, 2, 3, 4, 5 | Step 2 grows a `/api/media/upload` + `/media/video/{id}` Range test. |
| 4     | Directus rollout (CMS plane) — collections, staff RBAC, unified nav + SSO-into-quiz, live authoring + moderation | 1, 3, 5  | New Directus REST surface is **out of scope** for the parity gate — its own functional tests live elsewhere. The `/anatomy/` monolith continues to serve from manifest; only the SPA reads Directus live. |
| 5a    | Docusaurus six sections (docs-site/)               | 1 only | Docs are a parallel surface; parity only checks that no v1 route 404s under the `/docs/` alias. |
| Cut (5b) | DNS / Apache vhost switch                       | All five, on prod data.    | The cut-over is the only gate that runs the manual visual diff at three viewports against the **live production** site. **Rollback drill:** before the cutover, the gate operator performs a dry-run vhost swap and back-swap — Apache's `/etc/httpd/conf.d/anatomy.conf` is a symlink to `anatomy-v1.conf` (current) or `anatomy-v2.conf` (new); rollback is `ln -sf anatomy-v1.conf … && systemctl reload httpd`. The drill is logged in the cutover PR. **Deferred artefact:** `prod-certs-post.txt` (post-cutover cert dump + set-difference-must-be-empty rule) is added here at Phase 5b — not in scope for Phase 0. |

---

## 4. Files this method document depends on

These files exist at Phase 0 freeze (verified):

```
tests/baseline/
├── content-manifest.txt          # 44 entries — actually generated
├── db-snapshot.md                # actual sqlite snapshot, prod procedure documented
├── fixtures/                     # 16 captured response bodies (executed)
│   ├── api-course-chapters.json
│   ├── api-course-framework.json           ← 404 (DB unseeded locally, expected)
│   ├── api-course-framework-explainer.json
│   ├── api-feed.json
│   ├── auth-me-unauth.json
│   ├── login.html
│   ├── session-key-unauth.json
│   ├── moderate-queue-unauth.json
│   ├── quiz-start-unauth.json
│   ├── admin-attempts-unauth.html
│   ├── history-unauth.html
│   ├── root.html
│   ├── static-app-index-head.txt
│   ├── verify.html
│   ├── verify-cert.html
│   └── verify-real-cert.html                ← positive case using
│                                              CCA-F-20260605-E79E74AB
├── make-manifest.sh              # idempotent, re-runnable
├── routes.md                     # full inventory (30 routes)
├── smoke.py                      # 15-check parity smoke incl. real-cert canary (executed: 15/15 PASS)
└── smoke.sh                      # shell wrapper around smoke.py
```

If any of these files moves under the v2 restructure, this doc and the
references in 01/03/04 are updated in the **same** patch.

---

## 5. Gate questions to resolve before Phase 2a

These are open by design — they need a human decision before the parity bar
becomes machine-checkable:

1. **Where does the production schema baseline live?** Phase 0 documents the
   procedure but does not commit a `prod-schema-2026-06-05.sql` dump (PII
   surface in attempt payloads). Either commit a redacted version under
   `tests/baseline/prod/` (sanitising names/emails) or rely on the bastion
   host snapshot pattern. Decision needed before Phase 2a.
2. **Should the quiz round-trip step be hardened into pytest now?** This
   doc leaves it manual at Phase 0/1 and recommends pytest at Phase 2a. The
   alternative is wiring the pytest harness in Phase 1 alongside the file
   moves; the trade-off is "more upfront work" vs "manual rerun every gate
   until 2a".
3. **Is `framework-explainer.json` allowed to live in *two* sources for the
   long run?** The route currently does DB-first / FS-fallback
   (`main.py:576-606`). The manifest pins the FS copy byte-exact;
   `03-data-model.md` §1.7 keeps the DB row. If Phase 2c removes the FS
   fallback, this doc's content-parity invariant becomes single-source —
   confirm at the Phase 2c gate.
4. **Apache vhost as part of the contract?** The current vhost has no
   caching / compression headers (`v2-plan.md` "Current state"). Phase 3
   adds them. Decide whether Phase 1's gate should already assert that
   the `Cache-Control` header is **absent today** on all the routes (a
   *negative* assertion, to pin today's behaviour — Apache emits no
   `Cache-Control` header at all, so the smoke check is `header not in
   response.headers`, *not* `Cache-Control: no-store`) — that lets
   Phase 3b grow into a positive per-route assertion without
   retro-fitting the smoke suite.
5. **Definition of "FE visual parity" under dark mode.** The per-page
   `localStorage` theme keys (`CLAUDE.md` "Brand") mean a screenshot taken
   in a fresh profile may default to light even when the harness is set to
   dark. Document the exact `localStorage` seed for the harness so the
   visual check is reproducible.
