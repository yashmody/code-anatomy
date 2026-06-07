---
id: content-intro
title: Content architecture
sidebar_position: 7
---

# Content architecture

## Scan box

- The platform carries **four kinds of content**, and each has exactly one home:
  authored course prose and the feed both live in Postgres tables, media lives in
  Postgres large objects, and configuration lives in the `app_config` table.
  Nothing is duplicated across stores.
- **Postgres is the editable source of truth.** The JSON files under
  `content/source/` are a version-controlled seed and a diff-able export — not the
  runtime read path. This is a deliberate shift away from the older
  "files are canonical" stance once a real CMS arrived.
- **Two planes, one database.** Directus 11 (`cms/`) is the editorial *write*
  surface; the FastAPI app (`backend/`) is the runtime *read* surface. Both read
  and write the same Postgres rows. Directus is never on the request path —
  the SPA and the quiz read content through FastAPI `/api/*`, cache-backed.
- The seam that keeps the cache honest is a single loopback webhook: Directus
  publishes, fires `POST /api/cms/webhook`, and FastAPI invalidates the one cache
  key that changed. No shared secret, no remote dependency at read time.
- **Media is final: Postgres large objects, streamed by FastAPI with HTTP Range.**
  No S3, no object store, no filesystem media store. Directus holds media
  *metadata* only and never the bytes.

## What this section covers

This is the map of where content lives, who may write it, and how it reaches a
reader. It is written for an architect who has to reason about a content change
end to end — from an editor's keystroke in Directus to the byte a learner's
browser renders.

The grounding documents are the v2 design contracts and the code that implements
them:

- `docs/architecture/v2/03-data-model.md` — the Postgres schema: `course_chapters`,
  `frameworks`, `feed_items`, `questions`, `media_assets`, `app_config`, and the
  Directus coexistence rules.
- `docs/architecture/v2/05-config-cms.md` — the three-tier secret/config/content
  separation, the Directus collection map, and the webhook seam.
- `content/source/` — the JSON seed, the schemas (`schemas/*.json`), `validate.py`,
  and `SCHEMA.md` (the authored block-model contract).
- `cms/` — Directus-as-code: the pinned version, the collection snapshot, and the
  scoped DB role.

## Section map

| Page | What it answers |
|---|---|
| [The four content types](./four-content-types) | What content exists, and which store owns each kind |
| [The content tree and JSON schemas](./content-tree-and-schemas) | `content/{source,frozen}` layout, `schemas/`, `validate.py` |
| [The course block model](./course-block-model) | chapters → sections → blocks, every block type, the framework spine |
| [Directus: the editorial write plane](./directus-write-plane) | Directus over Postgres, read stays FastAPI, the cache-invalidation seam |
| [Config-as-content and media](./config-and-media) | `app_config` vs env secrets; media as Postgres large objects (final) |

:::caution[Common Pitfall]

Treating `content/frozen/anatomy-of-code-course.html` as a content source. It is
a frozen **visual-parity reference** — the artefact Apache serves at `/anatomy/`,
kept to prove a re-render hasn't drifted. It is never read by the runtime and
never edited as a source. Regenerating it from JSON would couple parity to a
transformation, which is exactly the coupling v2 broke.

:::

## A one-line statement of the model

Editors write through Directus into Postgres; Postgres is the truth; FastAPI reads
Postgres (cached) and serves it; the git-JSON under `content/source/` is the
seed-and-export record; media is Postgres large objects all the way down.
