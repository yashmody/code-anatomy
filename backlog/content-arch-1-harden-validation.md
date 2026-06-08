---
id: CONTENT-ARCH-1
title: Harden content validation for a file-served, AI-generated course
role: swe (+ c0 for the explainer schema)
tier: M
adr: content/source/docs/adr/0002-content-source-of-truth-and-authoring.md
depends_on: [CONTENT-ARCH-0 (Phase 0 reconcile — DONE, clean)]
branch: feat/content-arch-1-validation
gates: [validate-content, sanitise-lint (NEW), lint, make verify]
status: built · rv APPROVED · pending merge
---

## Context

Before we serve the course from files (CONTENT-ARCH-2) and let an AI write into
those files (CONTENT-ARCH-5), `content/source/validate.py` must become a real
gate. Today it checks reference-integrity (`frameworkAddress`/`frameworkRef`
resolve against `framework.json`) and a feed word-count — **no JSON Schema
enforcement at runtime, no HTML sanitisation**, and it derives a chapter's ring
from the **filename prefix** (the same shortcut as `migrate_to_postgres.py:293`),
which mislabels anything off-convention as `other`.

This is the **safety phase**: an LLM block with malformed markup or a script
payload passes CI today. The sanitise lint is **non-negotiable before any LLM
writes HTML** — we do not rely on `rv` eyeballing a large generated diff.

## Acceptance criteria

1. `validate.py` derives ring from the in-file `frameworkAddress`, not the
   filename prefix. Off-convention filenames still validate correctly.
2. `framework-explainer.schema.json` exists under `content/source/schemas/` and
   `validate.py` enforces it on the ~17 KB explainer blob (currently untyped).
3. A **mechanical HTML-sanitise lint** runs over every html-bearing block
   (`chapter-open`, `lead`, `prose`, `heading`, `quote`, `callout`) and **fails
   CI** on `<script>`, inline event handlers (`on*=`), `javascript:`/`data:` URLs,
   and unbalanced/unknown tags. Wired into both CI and the fast pre-commit tier.
4. CI **fails** on any unresolved `frameworkAddress`/`frameworkRef` (promote from
   advisory to blocking).
5. The hand-maintained `SECTION_FILES` manifest in `frontend/core/config.js` is
   deleted; the section list is derived by enumerating
   `content/source/course/sections/` (kills one of the three drift sources).

## Gates / definition of done

`make verify` green; the new sanitise lint present in CI + `.pre-commit` (fast
tier, `--check` only). `rv` reviews the diff before merge. No behaviour change to
the still-DB-served read path (that flips in CONTENT-ARCH-2).

## Dev notes

- `content/source/validate.py` — current checks; extend, don't rewrite.
- `content/source/schemas/course.schema.json` — block typing reference.
- Ring-from-filename bug: `backend/scripts/migrate_to_postgres.py:293-307`.
- Prose blocks carry **verbatim HTML** ("re-shell only" rule) — the sanitise lint
  must allow the existing course HTML vocabulary while blocking the unsafe set;
  baseline it against the current 31 chapters (all must pass on day one).

## CI-wiring note (from rv re-review)

The app repo's `backend/.venv` does **not** carry `jsonschema`; `validate.py` runs only
under a system `python3` that has it. When the harness/CI wiring lands (the repo-
reconciliation follow-on), it MUST pin the interpreter that has `jsonschema`, or the
schema gate silently no-ops. `sanitise_lint.py` is stdlib-only and runs anywhere.

## Outcome (built · rv APPROVED)

Delivered: `sanitise_lint.py` (allow-list `{b,strong,em,code,span,div,p,br}`+`class`;
blocks `<script>`/`on*`/`javascript:`/`data:`/unknown/unbalanced **and** the comment/CDATA/PI
swallow-class per rv RV-1), `framework-explainer.schema.json` + its validate.py enforcement,
`ring_from_address` helper, ETL ring fix, `SECTION_FILES` → `/api/course/chapters` fetch.
Gates green: validate.py (40 items), sanitise_lint.py (31 chapters), check-frontend-imports
(107). rv attacked the lint with ~60 payloads; no live-XSS bypass.
