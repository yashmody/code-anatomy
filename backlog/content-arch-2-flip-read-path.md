---
id: CONTENT-ARCH-2
title: Serve the course from files (flip the read path off Postgres)
role: swe (+ devops for the Apache alias + status filter)
tier: M
adr: content/source/docs/adr/0002-content-source-of-truth-and-authoring.md
depends_on: [CONTENT-ARCH-1]
branch: feat/content-arch-2-file-read-path
gates: [smoke, security-smoke (alias scope), make verify]
status: ready
---

## Context

Serve `/api/course/*` from the `content/source/course/` file tree instead of
`course_chapters`/`frameworks`, with **zero renderer and zero API-contract
change**. Phase 0 proved files == live DB (31/31 + both frameworks), so this is
**lossless and reversible**. This is the step that actually collapses the
dual-source-of-truth defect — the merged file becomes the served artefact.

## Acceptance criteria

1. `backend/app/modules/content/routes.py` resolves **framework**, **explainer**,
   and **`chapters/{filename}`** from `content/source/course/`, returning byte-
   identical JSON to today. `AppCache` and `Cache-Control` headers are preserved
   verbatim. The `framework-explainer` disk-read path becomes the **normal** path
   for framework + chapters too (fixes the asymmetric DB-only fallback footgun).
2. A feature flag (`COURSE_SOURCE=files|db`, default `files`) toggles file vs DB
   serving; the DB routes stay alive for **one deploy** for instant rollback.
3. `frontend/core/api-client.js`'s URL rewrite is **untouched** — the SPA still
   "thinks" it fetches files; the backend just reads them now.
4. **Draft/archived chapters are NOT world-readable.** Either serve-time status
   filtering or publish-only emission. The Apache alias for the published course
   tree is **scoped** — it must not expose `content/source/schemas/`,
   `content/source/feed/`, or any draft/archived prose.
5. Manual mode, Read mode (page flag), and telescoping (`opensInto`) verified in a
   preview against the file-served path. `/api/course/*` smoke tests green.

## Gates / definition of done

`make verify` + endpoint smoke green. The Apache alias scope + status filter is a
**security-review gate** (`rv` + devops) — over-broad serving leaks unpublished
content. Reversible: re-point the flag to `db` to roll back instantly.

## Dev notes

- `backend/app/modules/content/routes.py` — the four loaders to rewrite.
- `backend/app/modules/content/storage.py` — `get_chapter`/`get_framework`/
  `get_framework_explainer` (the shapes to reproduce from files).
- `content/source/course/` — sections + framework{,-explainer}.json.
- Cache: `backend/app/core/cache.py`; on workers=1 the deploy restart flushes it
  atomically (replaces the Directus webhook — do not reintroduce the webhook).
- Do NOT drop the tables here — that is CONTENT-ARCH-4, after a soak.
