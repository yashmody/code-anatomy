---
id: intro
title: Front-end
sidebar_position: 1
---

# Front-end

The front-end is a buildless ES-module single-page application served as static
files by Apache. It renders the course, the social feed and the moderator queue
from one app shell, reading everything through the FastAPI `/api/*` plane and
never touching Directus or the database directly.

## Scan box

- **Buildless by choice.** No bundler, no transpile step, no `node_modules` in
  production. The browser loads `frontend/index.html`, which loads
  `core/main.js` as a native `<script type="module">`; the import graph is the
  build. What you read in `frontend/` is exactly what ships.
- **One shell, four surfaces.** A hash router in `core/main.js` drives three
  reader modes — **Manual**, **Read**, **Feed** — plus a role-gated
  **Moderation** view at `#/moderate`. The visible nav exposes Manual, Read,
  Feed and Resources; Moderation appears only for sessions that hold the
  `moderate.view` permission.
- **Read-only against `/api/*`.** Content flows in through
  `core/api-client.js` and `modules/feed/store.js`, which call FastAPI's
  cache-backed read endpoints. The SPA has no knowledge of Directus or
  Postgres — the editorial write plane is entirely server-side.
- **Visual parity is a hard constraint.** `frontend/styles/monolith.css` is the
  frozen design system copied from the 578 KB monolith
  (`content/frozen/anatomy-of-code-course.html`). It is never edited; the SPA
  renders to match it.
- **Centralised seams.** `core/config.js` holds every runtime constant
  (`API_BASE`, `QUIZ_URL`, `SECTION_FILES`, the theme key, media aliases);
  `core/theme.js` owns the single `anatomy-app-theme` key shared across the SPA,
  the resource islands and the quiz.

## What lives here

This section is the operating manual for the SPA: how it boots without a build
step, how the hash router selects a mode, where new content blocks and feed
items plug in, how the read path reaches the cache-backed API, how the theme is
unified across three same-origin surfaces, and how parity with the frozen
monolith is held and checked.

Everything documented here is grounded in the code under `frontend/` on the
`v2` branch and in the Phase 0 blueprint
(`docs/architecture/v2/01-blueprint.md`). Where the shipped tree diverges from
the blueprint's initial plan — the plan was a design sketch, parity-gated — the
pages call it out and describe what actually shipped.

## Section map

```text
frontend/
├── index.html      app shell — app-bar, nav, #view mount, module entry
├── core/           app-level wiring
│     main.js       hash router + boot + chrome  → Architecture, Router/modes
│     config.js     runtime constants (API_BASE, CONTENT_BASE, QUIZ_URL)
│     theme.js      unified theme manager        → Configuration and theming
│     api-client.js loadJSON content read path   → The content read path
│     auth-ui.js    global sign-in + gates       → Router and modes
├── shared/         framework-agnostic render toolkit
│     registry.js   block + feed-item dispatch   → Blocks and the registry
│     blocks/       14 renderers, one per type   → Blocks and the registry
│     render/       chapter · diagram · explainer
│     framework.js  dom.js
├── modules/        the surfaces
│     course/       manual.js · read.js          → Router and modes
│     feed/         feed.js + 12 files           → Blocks, Content read path
│     moderate/     moderate.js                  → Router and modes
└── styles/   monolith.css(frozen) app.css read.css feed.css moderate.css
```

| Page | Covers |
|---|---|
| [Architecture: buildless ES modules](./architecture.md) | Why no bundler; the import graph as the build; the app shell; the import-resolution baseline. |
| [Module layout and parity](./module-layout.md) | `core` / `shared` / `modules` / `styles` boundaries; the frozen monolith relationship; equivalence testing. |
| [Blocks and the renderer registry](./blocks-and-registry.md) | `shared/registry.js`; the 14 block renderers; the 6 feed-item renderers; the extensibility contract. |
| [Router and the four modes](./router-and-modes.md) | The hash router; Manual / Read / Feed; the role-gated Moderation view; nav and IA. |
| [The content read path](./content-read-path.md) | `core/api-client.js` → `/api/course/*`; `feed/store.js` → `/api/feed`; cache-backed, never Directus directly. |
| [Configuration and theming](./config-and-theming.md) | `core/config.js`; the unified `anatomy-app-theme` key; `theme.js` and `theme-boot.js`; brand tokens. |

:::tip[Why This Matters]
The buildless choice is a deliberate architectural position, not a shortcut. It
keeps the SPA diff-able in review, debuggable in DevTools without source maps,
and serveable by Apache as plain static files behind the same reverse proxy that
fronts FastAPI. The v2 reorganisation into `core` / `shared` / `modules` changed
where things *live*, not how they *run*.
:::

## Cross-references

- `docs/architecture/v2/01-blueprint.md` §1 (directory tree), §4 (front-end
  mapping), §7 (path-reference migration) — the design contract this section
  distils.
- `docs/architecture/v2/06-caching-performance.md` — the cache-backed read
  endpoints the SPA consumes.
- `docs/architecture/v2/07-security-baseline.md` — the same-origin assumption
  and the CSP the SPA relies on.
- Phase 1 and Phase 4b reports under `docs/architecture/v2/` — the restructure
  and the navigation/theme/moderator unification.
