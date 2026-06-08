---
id: CONTENT-ARCH-5
title: Git-backed block composer + AI generation (authoring centrepiece)
role: swe (composer + pipeline) · c0 (house-style prompt) · pb (PR-opening seam)
tier: L
adr: content/source/docs/adr/0002-content-source-of-truth-and-authoring.md
depends_on: [CONTENT-ARCH-1, CONTENT-ARCH-2]
branch: feat/content-arch-5-composer
gates: [plan-first, rv (auth/credentialed surface), security-review (PR seam), make verify]
status: ready (plan-first — design before build)
---

## Context

The authoring surface, funded as **core** (product-owner decision: non-technical
authors need a visual editor from day one). A **git-backed, git-*invisible***
block composer: the author sees **Draft → In review → Published**; the backend
maps that to **commit → PR → merge** at the **CI/operator checkout** — never the
production box (`rsync -a --delete` wipes a server-side working tree).

Content is **mostly AI-generated**, with two modes the product owner asked for:
**full-generate** (AI drafts the section spine *and* the blocks) and
**spine-then-fill** (author writes the spine, AI fills blocks). Authors edit
anything. Publish gate: **review-before-live** — `content_author` drafts but
cannot self-publish.

## Acceptance criteria

1. New SPA route under `frontend/modules/course/` renders a chapter as **typed,
   editable blocks** using the **same `shared/registry.js` renderer the reader
   uses** (live preview). The author **never sees raw JSON**.
2. **Generate full chapter** — from a `frameworkAddress` + brief, the AI proposes
   `sections[]` (spine: ids + titles + order) **and** fills each block.
   **Generate section** — author supplied the spine; the AI fills that section's
   blocks. Both run through the existing `core/llm.py` Anthropic seam.
3. Inline edit of every block: typed fields for structured blocks (`cardgrid`,
   `tierlist`, `map`, `chips`, `notes`, `architects-review`, `diagram`); a
   rich-HTML field for prose blocks (`prose`/`lead`/`heading`/`quote`/`callout`).
4. **Submit for review** opens a PR on a `content/<slug>` branch **via the
   operator/CI checkout** — git is invisible to the author, the composer never
   writes `main`, never a DB row, never on the box. Gated by the `content_author`
   role (granted through `/api/admin/roles`).
5. A **new course house-style system prompt** authored by `c0` — explicitly NOT
   the `whatsnew` `_SYSTEM` (tuned for 1-2 sentence release notes). Long-form
   architect prose in Indian English, LAYER pattern, the four callout types.
6. Everything the composer/AI produces passes `validate.py` + the sanitise lint
   (CONTENT-ARCH-1) in CI before a human can merge.
7. If an AI "auto-block" type is introduced, it is registered in
   `course.schema.json` + `content/source/SCHEMA.md` + `shared/registry.js` before
   it can render.

## Gates / definition of done

**Plan-first** (swe + c0 present the design; TM approves before build). `rv`
reviews before merge — this is an auth-adjacent, credentialed surface. The
**PR-opening seam** (git identity + `gh` auth at the CI/operator checkout) gets a
dedicated **security review** (`pb` builds it; `rv` + devops gate). `make verify`
green.

## Dev notes

- Pattern to reuse: `frontend/modules/feed/composer.js` (typed-card composer +
  JSON-schema validation — this is the UX the product owner praised).
- Renderer: `frontend/shared/registry.js` (single-dispatch; one file per block in
  `shared/blocks/*`).
- AI seam: `backend/app/core/llm.py` + `llm_anthropic.py` (proven live by What's
  New). House-style prompt is NEW (c0).
- Roles: `content_author` via `backend/app/modules/admin/routes.py`
  (`/api/admin/roles`); `platform_admin` grants it.
- Hard constraint: the commit/PR happens at the operator or CI checkout, NOT the
  deployed box. See ADR 0002 §Decision.5 and the open question on `content.publish`.

## Prerequisite from rv (CONTENT-ARCH-1 review · RV-3)

Before the AI is allowed to generate the **framework-explainer**, extend the sanitise lint
to cover it. `frontend/shared/render/explainer.js` emits its prose via `raw()` (un-escaped)
straight into `innerHTML` — as XSS-exposed as the chapter `prose` blocks — yet
`content/source/sanitise_lint.py` currently **excludes `framework-explainer.json` by name**,
and the explainer schema only checks `type:string`. Point `lint_html()` at the explainer's
`raw()`-rendered string fields (`masthead.html`, `parts.*.body`, `code/coder.heading/intro/desc`,
`watch.*.body`, `*.asks[].html`, …) so it gets the same mechanical XSS backstop. It is
hand-authored + validate-green today, so this is a prerequisite for the AI path, not a live
defect — but it MUST close before an LLM writes the explainer.
