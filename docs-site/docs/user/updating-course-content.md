---
id: updating-course-content
title: Update course content
sidebar_position: 2
---

# Update course content

Course content — the chapters of the Anatomy of Code course and the CODE-CODER
framework that frames them — lives in Directus and is served by the read API.
This guide shows you how to edit a chapter and see it live.

## Scan box

- **Two collections hold the course.** `course_chapters` holds each chapter
  (keyed by `filename`, e.g. `anatomy-m08.json`); `frameworks` holds the
  framework spine and the framework explainer.
- **The body is JSON.** A chapter's `content` field is a JSONB block tree, not
  free HTML. You edit it in Directus's code editor. Keep the shape valid or the
  reader will skip the bad block.
- **Publishing is automatic.** Saving in Directus writes Postgres and fires a
  webhook that clears `course_chapters:{filename}` (and the chapter list). The
  change is live in seconds.
- **You need `content.write`.** That permission is held by the
  `content_author` role. Platform admins have it implicitly.
- **The frozen HTML is not editable.** `content/frozen/anatomy-of-code-course.html`
  is a historical snapshot for visual parity. The live course is the database.

## Before you start

You need a Directus account with the **content_author** role (or platform
admin). If you open Directus and do not see the **course_chapters** collection,
you do not have the permission yet — ask a platform admin.

## Steps — edit a chapter

1. Open the Directus admin for your environment and go to
   **Content → course_chapters**.
2. Find the chapter by its `filename` (for example `anatomy-m02b.json`). The
   `title` and `ring` columns help you scan.
3. Open the row and edit the `content` field in the code editor. It is a JSON
   block tree — sections, prose blocks, callouts, diagrams. Edit the text
   inside the existing block structure; do not reshape the tree unless you know
   the [block model](../developer/data-model/course-block-model).
4. Save and set the status to **published**.
5. Verify: load the course in the SPA (Manual or Read mode), or hit the API
   directly:

   ```bash
   curl -s https://internal.in.deptagency.com/api/course/chapters/anatomy-m02b.json | head
   ```

The read API caches chapters for fifteen minutes, but the webhook clears the
cache on publish, so you should see the change immediately.

## Editing the framework

The framework spine and the explainer live in **frameworks** (ids `framework`
and `explainer`). They drive the framework diagram and the Manual-mode intro.
Edit them the same way; the read endpoints are `GET /api/course/framework` and
`GET /api/course/framework-explainer`.

## What's where

| Thing | Collection | Read endpoint |
|---|---|---|
| A chapter | `course_chapters` (PK `filename`) | `GET /api/course/chapters/{filename}` |
| Chapter list | `course_chapters` | `GET /api/course/chapters` |
| Framework spine | `frameworks` (id `framework`) | `GET /api/course/framework` |
| Framework explainer | `frameworks` (id `explainer`) | `GET /api/course/framework-explainer` |

:::caution[Common Pitfall]

The `content` field is JSON. If you paste in malformed JSON — a trailing comma,
an unclosed bracket — Directus may still let you save, but the reader will fail
to render that chapter or drop the broken block. After a large edit, load the
chapter in the SPA and read it through before you walk away.

:::

:::note[Agency Tip]

For anything bigger than a typo — a new section, a reworked module — draft it,
set status to **draft**, and preview through a staging environment first.
Drafts are visible to signed-in authors but not to learners.

:::

For the underlying block grammar and the full list of block types, see the
developer reference: [the course block model](../developer/data-model/course-block-model)
and [the content tree and schemas](../developer/data-model/content-tree-and-schemas).
