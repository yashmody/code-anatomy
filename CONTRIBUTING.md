# Contributing — DEPT® Anatomy of Code

This is a monorepo with three deliverables:

- **Course** — `content/frozen/` (the static HTML field manual + checklist, runbook, FAQs)
- **Backend** — `backend/` (FastAPI app, deployable)
- **Frontend** — `frontend/` (the buildless SPA)
- **Prompts** — `prompt-library/` (reusable prompts and sample apps)

We use **GitHub Flow**: `main` is always publishable, work happens on short-lived
branches, and changes are reviewed through pull requests where it helps. The team
is trusted — `main` is lightly protected, not locked down.

---

## Branches

- **`main`** — the only long-lived branch. Always publishable. **Lightly
  protected**: no force-pushes, no deletion, linear history. Direct pushes are
  allowed and need no approval — but for anything non-trivial, prefer a
  short-lived branch and a PR.
- **Working branches** — cut from the latest `main`, short-lived, deleted after
  merge. Name them `<scope>/<short-slug>`:

  | Scope      | For                                              | Example                   |
  |------------|--------------------------------------------------|---------------------------|
  | `course/`  | Course content (`content/frozen/…course.html`)   | `course/llmo-refresh`     |
  | `quiz/`    | Backend app (`backend/`)                         | `quiz/proctoring`         |
  | `ref/`     | Checklist, runbook, FAQs                         | `ref/api-gateway-section` |
  | `prompts/` | `prompt-library/`                                | `prompts/aem-migration`   |
  | `fix/`     | Bug fixes (any area)                             | `fix/dark-mode-toast`     |
  | `chore/`   | Tooling, dependencies, CI, housekeeping          | `chore/bump-sqlalchemy`   |
  | `docs/`    | Repo docs / process                              | `docs/branching-strategy` |

Keep one branch to one scope. If a change spans the course and the quiz, prefer
two branches and two PRs.

---

## Pull requests

PRs are **encouraged, not required** — you can merge your own PR, or push to
`main` directly. Use a PR when a second pair of eyes helps, or to run checks.

1. Branch off the latest `main`.
2. Make the change; keep it focused.
3. Open a PR into `main` (or push directly for small, low-risk changes).
   - Content changes should run through the **content-quality** review (brand,
     voice, structure, accessibility, AI-tells) before they land.
   - A change that adds a new section, deep-dive, or architectural concept also
     gets **q0** quiz-question drafts.
4. **Squash-merge** to keep `main` linear and readable; delete the branch.

No approval is required to merge. Reviews are about quality, not gatekeeping.

---

## Releases — versioned per component (SemVer)

The course and the quiz ship on their own cadence, so they carry **separate,
prefixed tags**:

- Course: `course-vMAJOR.MINOR.PATCH`
- Quiz:   `quiz-vMAJOR.MINOR.PATCH`

Pre-1.0, append a pre-release suffix (`-beta`, `-rc.1`). Current baseline:
`course-v0.1.0-beta`, `quiz-v0.1.0-beta`. A whole-system snapshot may also carry
an un-prefixed tag (e.g. `v0.1.0-beta`).

| Bump  | Course                                       | Quiz                                       |
|-------|----------------------------------------------|--------------------------------------------|
| MAJOR | Restructure that breaks anchors / information architecture | Schema or scoring change that breaks stored data |
| MINOR | New section, deep-dive, or reader feature    | New question pools or app feature          |
| PATCH | Copy fixes, diagram tweaks, small CSS/JS     | Bug fixes, question corrections            |

Cut a release by tagging an annotated tag on `main` at the release commit:

```
git tag -a course-v0.2.0 -m "Course 0.2.0 — <summary>"
git push origin course-v0.2.0
```

The course publishes from `main` (or its tag); the quiz app deploys from its
`quiz-v*` tag.

---

## Hotfixes

Branch `fix/<slug>` off `main` (or push the fix directly), then bump the affected
component's PATCH tag (`course-v0.1.1` / `quiz-v0.1.1`).

---

## Commit messages

Short imperative subject line; the body explains the *why*. Conventional-Commits
prefixes (`feat:`, `fix:`, `docs:`, `chore:`) are encouraged for clean changelogs.

---

## Branch protection on `main` (current ruleset)

- Pull requests / approvals: **not required** — you may push to `main` directly
  and merge your own work without review
- Require **linear history** (squash / rebase merges only; no merge commits)
- Block **force pushes** and branch **deletion**
- Status checks: none yet — wire them in here when CI is added

Tighten this later (e.g. require a PR + one review) by updating the rule and this
section together.
