---
id: intro
title: Front-end
sidebar_position: 1
---

# Front-end

> **Phase 0 stub.** Phase 5a expands this into the page set listed below.

## Scan box

- The front-end is a **buildless ES-module SPA** — no bundler, no framework.
  v2 keeps that choice and reorganises into `core/`, `shared/`, `modules/`,
  `styles/`.
- Three modes live under `frontend/modules/`: **Manual** (the scroll/video
  mode), **Read** (chapter reader), **Feed** (the social-style feed).
- Visual parity with the frozen monolith (`content/frozen/anatomy-of-code-course.html`)
  is a **hard constraint** — `frontend/styles/monolith.css` is the frozen
  design system and is never edited.
- Centralised seams new in v2: `core/config.js` (one place for `API_BASE`,
  `QUIZ_URL`, `SECTION_FILES`, theme key, media paths), `core/theme.js`,
  `core/api-client.js`.
- Brand discipline: ochre `#FF4900`, Syne for display, DM Sans for body,
  JetBrains Mono for labels — these tokens are mirrored in this docs site
  too.

## What lives here

This section is the operating manual for the SPA: how it boots, where new
blocks plug in, how `shared/registry.js` dispatches, where the three modes
sit, and how parity with the monolith is enforced.

Source contract: see `docs/architecture/v2/01-blueprint.md` §1 (directory
tree), §4 (front-end mapping) and §7 (path-reference migration map).

## Planned pages (Phase 5a)

1. **Architecture** — the buildless tree, why no bundler, hash router.
2. **Module layout** — `core/`, `shared/`, `modules/` boundaries.
3. **Blocks and the registry** — the 14 block renderers, dispatch contract.
4. **Router and modes** — Manual, Read, Feed; how the tab chrome works.
5. **Theming and brand** — the per-page `localStorage` theme keys; how the
   tokens in `styles/monolith.css` relate to the docs site.
6. **API client** — `core/api-client.js`, `API_BASE`, error shaping.
7. **Testing parity** — `frontend/tests/equivalence.html` and the monolith
   reference.

:::tip Why This Matters

The buildless choice is a feature, not a workaround. It keeps the SPA
diff-able, debuggable in DevTools without source maps, and trivially
serveable by Apache. The reorganisation in v2 is purely about *finding*
things — not changing how they run.

:::

## Cross-references

- `docs/architecture/v2/01-blueprint.md` §1, §4, §7 — directory + file
  map.
- `docs/architecture/v2/06-caching-performance.md` — Apache cache rules
  for the SPA assets (cache-busting strategy).
- `docs/architecture/v2/07-security-baseline.md` — CSP and the
  same-origin assumption the SPA relies on.
