# ADR 0002 · Content source-of-truth & authoring — files-as-runtime-truth, git-backed composer, Directus removed

**Status:** Accepted · 2026-06
**Context owner:** Yash Mody
**Supersedes:** ADR 0001's "Postgres later" lean for the course domain.
**Revises:** `docs/architecture/v2/05-config-cms.md` (Directus stand-up) and
`docs/CONTENT-AUTHORING.md` (course = "files/CMS → DB → API").
**Decision basis:** a 15-agent architecture evaluation (four target
architectures designed, adversarially stress-tested and scored) plus a
read-only Phase 0 reconciliation run against the live database.

---

## Context

ADR 0001 said course content belongs in version control and should move to a
database "only if non-technical editors need a CMS, or full-text search becomes
a requirement." Between then and now, an ETL (`backend/scripts/migrate_to_postgres.py`)
loaded the course JSON into Postgres and the SPA was re-pointed at
`/api/course/*`, which serve from `course_chapters` + `frameworks`. The result
is the system's **#1 architectural defect — a dual source of truth**:

- The JSON files under `content/source/course/` are git-canonical for **authoring**.
- Postgres (`course_chapters.content`, `frameworks.data`) is what the live app
  actually **serves**.
- **There is no automatic re-sync.** Editing a file changes nothing in production
  until the ETL re-seeds; editing in the DB never round-trips to the file. The two
  can drift silently.

On top of that DB sits **Directus**, registered as a generic table-binder over the
*same* app-owned Postgres tables (`cms/register-collections.mjs`). It surfaces one
opaque JSONB blob per chapter — the "each block is just a JSON dump" complaint that
opened this review. The learner-facing app **never reads Directus** (grep-verified:
zero references to Directus or port 8055 in any read path).

The product direction sharpens the decision: course content will be **mostly
LLM-generated**; authors mainly supply a chapter/section **skeleton**; a scheduled
job regenerates content with an **Anthropic key**; authors must still **edit**
generated content; and **non-technical authors need a visual editor**.

## Decision

Adopt the **Hybrid (right-tool-per-content-type)** architecture. It was the only
option the evaluation rated *viable* (8/10; the git-native, Postgres-thin-admin,
and keep-Directus options scored 6/5/4 and *conditional*).

1. **Course text → versioned JSON files, served straight from disk** = the single
   runtime source of truth. `course_chapters` and `frameworks` are dropped.
2. **Postgres keeps only the workloads that genuinely need a relational DB:**
   dynamic/community (feed, quiz, what's-new), auth/identity, `app_config`, and
   media **metadata**. (Media **bytes** move out of `pg_largeobject` to an object
   store as a separate, non-blocking ticket.)
3. **Directus is removed entirely** — service, collection registration, webhook,
   and the `directus_app` role. Its genuinely-used capability (staff-role grants)
   already exists outside it.
4. **Authoring = a git-backed, git-*invisible* block composer** (a new SPA route
   modelled on the proven feed composer). The author sees **Draft → In review →
   Published**; the backend maps that to **commit → PR → merge**. Two generation
   modes, both requested by the product owner:
   - **Full-generate** — author gives a `frameworkAddress` + brief; the AI drafts
     the **section spine *and* fills every block**.
   - **Spine-then-fill** — author hand-writes the spine; the AI fills blocks per
     section.
   Every block is editable (typed fields for structured blocks; a rich-HTML field
   for the prose blocks that carry verbatim HTML under the "re-shell only" rule).
5. **The AI refresh is just another committer.** The scheduled Anthropic job opens
   a **reviewable PR** at the **CI/operator checkout** — never on the production
   box, whose content tree is wiped by `rsync -a --delete` on every deploy.
6. **Curation is bifurcated.** Course text: PR → `validate.py` + HTML-sanitise lint
   in CI → `rv` reviews brand/voice/AI-tell → TM merges; versioning = git history,
   rollback = `git revert`, audit = `git blame`. Dynamic content: keep the existing
   in-DB status workflows, moderated through small purpose-built admin screens.
7. **Publish gate (default): review-before-live.** A `content_author` drafts but
   cannot self-publish; "Submit for review" opens a PR that `rv`/`c0`/TM gate.
   Adjustable to author-publishes-with-sampled-review if the review queue can't keep
   pace — but on an internal certification platform where the architect voice *is*
   the product, and with content mostly AI-drafted, review-before-live is the right
   posture.

## Evidence — why removing the DB layer + Directus is safe (verified, not assumed)

- **Phase 0 reconciliation (run for this ADR, read-only against `codecoder-dev`):
  CLEAN.** All **31/31** chapters and **both** framework blobs (`framework`,
  `explainer`) are byte-identical between the git files and the live DB. No
  Directus edit ever diverged the database from source → promoting files to
  source-of-truth is **lossless**, and the risky "export DB edits and commit them"
  step is **not needed**.
- **No learner read-path touches Directus** or `:8055`.
- **Staff-role administration does not die with Directus** —
  `backend/app/modules/admin/routes.py` (`/api/admin/roles`, registered at
  `main.py:225`) already grants/revokes capability roles via the *same*
  `core.users.grant_role` the Directus hook called.
- **No referential integrity is lost** — `course_chapters`/`frameworks` have **no
  FK dependents** outside the baseline and the Directus-role migration.
- **Files already ship next to the backend**, and the `framework-explainer`
  endpoint *already* reads from exactly that disk path — the file-served path is a
  generalisation of code already live.

## Consequences

**Positive**

- Collapses the dual source-of-truth into one artefact you author, review, and
  serve. The class of "files drifted from what users see" bug disappears.
- Removes a whole service (Directus) and a whole datastore concern (course tables);
  git becomes versioning + audit + rollback for course text, replacing the
  never-built `course_chapter_versions` machinery for free.
- Editors get a typed composer and never see raw JSON again; AI-generated content
  is editable exactly like hand-authored content (it is a draft block in a file).
- The deploy restart (workers=1) flushes the content cache atomically — strictly
  *more* correct than today's per-worker Directus webhook.

**Negative / costs (each with a mitigation)**

- **Publish latency** rises from an instant Directus Save to merge-PR + deploy →
  mitigate with a content-only fast deploy (rsync files + restart, no migration).
- **A new credentialed surface** — the composer/AI PR-opening seam runs at the
  CI/operator checkout with a git identity + `gh` auth → scope and security-review it.
- **`validate.py` is not a safety gate today** (reference-integrity + word-count
  only; no schema enforcement, no HTML sanitisation) → a mechanical **HTML-sanitise
  lint is non-negotiable before any LLM writes HTML**.
- **With content mostly AI-generated, the PR review queue *is* the curation system**
  → it must be staffed to capacity or governance becomes rubber-stamping. Size the
  refresh cadence to review capacity, not to a cron.

## Migration (phased; reversible until Phase 4)

| Phase | Goal | Status |
|---|---|---|
| **0 — Reconcile** | Prove files == live DB before anything | **DONE — clean (31/31 + 2 frameworks)** |
| **1 — Harden validation** | Close the gaps the file-served model exposes | brief written |
| **2 — Flip read path to files** | Serve course from disk; renderer/API contract unchanged; DB routes behind a flag for instant rollback | brief written |
| **3 — Retire Directus + cut ETL course path** | Remove the dead write plane | pending |
| **4 — Drop `course_chapters`/`frameworks`** | Finalise files as sole source (point of no easy return) | pending |
| **5 — Composer + AI generation** | The authoring centrepiece (funded as core, not deferred) | brief written |
| **6 — Polish** | Content-only fast deploy; docs; media bytes → object store | pending |

## Open questions

- **Publish gate:** a `content.publish` role split (draft vs self-publish), or is
  `rv`-on-the-PR a sufficient gate? (Git review may make an in-app split redundant.)
- **Refresh cadence + per-chapter token budget**, sized to review capacity.
- **Media bytes → object store** — recommended, but a separate ticket (orthogonal to
  the content-source decision).
- **Two-repo reconciliation** — the operating-model repo and this app repo both carry
  an app skeleton; see `docs/architecture/v2/repo-migration-plan.md`. Out of scope
  here, but it must be settled before the harness (`make verify`/`rv`) gates this
  app's PRs cleanly.
