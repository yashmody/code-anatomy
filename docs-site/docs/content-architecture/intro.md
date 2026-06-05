---
id: intro
title: Content architecture
sidebar_position: 1
---

# Content architecture

> **Phase 0 stub.** Phase 5a expands this into the page set listed below.

## Scan box

- v2 collapses today's triplicated content (`content-architecture/` + the
  frozen `content-system/` HTML + Postgres) into a single `content/` tree
  with a clear hierarchy: `source/` (git seed), `schemas/`, `frozen/`,
  `resources/`.
- **Postgres is the runtime source of truth** for course chapters, the
  framework, and the framework-explainer. `content/source/*.json` is the
  version-controlled seed and the diff-able record. ADR 0001 (filesystem
  as source) is superseded.
- The 578 KB `content/frozen/anatomy-of-code-course.html` is **not** a
  source — it is a frozen visual-parity reference and the artefact Apache
  serves at `/anatomy/`.
- Resources (runbook, checklist, FAQs) are de-duplicated. `content/resources/`
  is the single home; the SPA's three duplicate copies are deleted.
- All authored prose follows the **LAYER pattern**: Scan Box (3–5 bullets,
  ~30-second read) at the top, opinionated prose underneath, diagrams and
  callouts woven through.

## What lives here

This section explains the content tree, how editors will use Directus to
write into Postgres, how the git-JSON seed round-trips, the JSON schemas,
and the voice and language discipline (Indian English, LAYER pattern, four
callout types) from `CLAUDE.md`.

Source contracts:
- `docs/architecture/v2/01-blueprint.md` §5 — content consolidation map.
- `docs/architecture/v2/03-data-model.md` — `course_chapters`, `frameworks`
  tables and the Postgres-as-source decision.
- `docs/architecture/v2/05-config-cms.md` — Directus collection map.

## Planned pages (Phase 5a)

1. **Source of truth** — Postgres editable; git-JSON as seed/export.
2. **Schemas** — `content/schemas/{course,feed}.schema.json`, validate.py.
3. **Seed and export** — the ETL (`modules/content/etl.py`), how Directus
   exports back into `content/source/`.
4. **The frozen monolith** — what it is, what it is not, parity rules.
5. **Resources** — runbook, checklist, FAQs; the single source of truth.
6. **Voice and the LAYER pattern** — Indian English spelling, the four
   callout types, scan-box discipline.

:::warning Common Pitfall

Treating the frozen monolith as a content source. It is a **reference**.
Regenerating it from JSON would couple parity to a transformation — that
is exactly the coupling v2 is breaking.

:::

## Cross-references

- `content/SCHEMA.md` — the JSON schema authored contract.
- `content/MIGRATION-GAP.md` — known gaps between the JSON seed and the
  frozen monolith.
- `docs/architecture/v2/03-data-model.md` §2 — `course_chapters` and
  `frameworks` tables.
