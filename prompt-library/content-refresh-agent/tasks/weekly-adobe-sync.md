# Weekly Adobe Sync — Task

Executable workflow for the Content Refresh Agent (`*run-sync`). Follow the steps
in order. This task is the agent-facing mirror of the backend pipeline
(`backend/scripts/sync_adobe_updates.py`); where that script exists, the agent
runs it and verifies the result, where it does not yet, the agent performs the
steps and prepares the data for the implementation.

CRITICAL: This is an executable workflow, not reference material. Honour every
guardrail in `checklists/content-refresh-governance-checklist.md`.

## Inputs / preconditions

- `config.llm_provider = anthropic` and `llm_api_key` present (else STOP — tell the user to provide the key).
- Tables `whats_new_items` and `course_chapter_versions` exist (Alembic head applied).
- `data/adobe-sources.md` allow-list loaded.

If any precondition fails, run `*doctor`, report red items, and STOP.

## Steps

1. **Pre-flight (`*doctor`).** Verify key/provider, tables, and that each
   allow-listed source responds. Present a numbered red/green list. If anything
   is red, STOP and report.

2. **Fetch.** For each source in the allow-list, pull its RSS/Atom feed (or the
   release-notes page via its adapter). Network timeout + size cap on every
   request. A source that fails is logged and SKIPPED — never abort the run.
   Output: raw candidate items (title, url, published_at, product).

3. **Dedup.** Drop any candidate whose `source_url` already exists in
   `whats_new_items`. Output: the NEW items only. If zero new items, jump to
   step 8 (report "nothing new") and finish.

4. **Summarise + classify (Claude).** For each NEW item, one Claude call returns:
   (a) a short DEPT®-voice summary (Indian English, acronyms expanded, no
   AI-tells), and (b) the related course ring/chapter constrained to the known
   chapter list, or `none`. On LLM error: store the item WITHOUT a summary
   (title + link still useful) and flag it for next run. Never block the run on
   one bad summary.

5. **Store.** Upsert each item into `whats_new_items` (status `new`), keyed by
   `source_url`. Use `templates/whats-new-item-tmpl.yaml` for the row shape.

6. **Publish What's New.** The items are now served by `GET /api/whatsnew`
   (any signed-in user). No course content is touched in this step. (Phase 1
   stops here — see the plan doc.)

7. **Governed course refresh (Phase 2).** For each chapter that (a) opted into an
   `auto-adobe-updates` block AND (b) has ≥1 new item classified to it:
   1. **Snapshot** the chapter's current content JSON into
      `course_chapter_versions` (reason: `adobe-sync <date>`). This is the
      rollback point — no snapshot, no write.
   2. **Compose** the `auto-adobe-updates` block ONLY ("Latest from Adobe — as
      of <date>", a short dated list of the new items with source links). Do NOT
      read-modify-write any curated prose section.
   3. **Validate** the block against `checklists/content-refresh-governance-checklist.md`
      (schema, brand tokens, AI-tell scan, link integrity, accessibility).
   4. **Publish or hold.** PASS → write `course_chapters` and fire the Directus→
      FastAPI cache-invalidation webhook. FAIL → mark the item `held`, do NOT
      write the chapter, and record the reason for the report.

8. **Report.** Emit the audit report (via the SMTP/outbox seam): per source —
   fetched / new / summarised / failed; per chapter — written (with version id
   for rollback) / held (with reason). Set run status. This report is what
   `*report` replays.

## Notes

- Idempotent: safe to re-run. Dedup (step 3) + snapshot (step 7.1) make a repeat
  run harmless.
- Scope guard: if a step would require editing curated prose to satisfy a
  request, STOP and route it to the human review queue (c0 → content-quality),
  per the governance rule. Auto-publish is for the `auto-adobe-updates` block
  only.
