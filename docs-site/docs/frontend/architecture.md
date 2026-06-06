---
id: architecture
title: Architecture — buildless ES modules
sidebar_position: 2
---

# Architecture: buildless ES modules

## Scan box

- **No bundler, no build step.** The SPA is plain ES modules. `index.html`
  loads `core/main.js` with `<script type="module">`, and the browser walks the
  `import` graph itself. There is no Webpack, Vite, Rollup or transpile stage;
  the source under `frontend/` is the deployed artefact.
- **The import graph *is* the build.** Every module names its dependencies with
  relative specifiers (`../../shared/registry.js`). The browser resolves them at
  load time. This makes the dependency structure legible — and means a wrong
  relative path is a silent, browser-only failure, which is why parity tooling
  checks every specifier.
- **Apache serves it as static files.** The same reverse proxy that fronts
  FastAPI serves `frontend/` at `/app/` as static assets and proxies `/api/*`,
  `/auth/*` and `/media/*` through to the backend on the same origin.
- **Same origin is load-bearing.** Same-origin is what lets the SPA, the quiz at
  `/`, and the resource islands at `/anatomy/*` share cookies and one
  `localStorage` theme key — and it is what makes `API_BASE = ''` the correct
  production default.

## Why buildless

The decision predates v2 and v2 keeps it. The course is a teaching and reference
artefact for architects; the front-end should be as readable as the prose it
renders. A bundler buys minification, tree-shaking and a module graph the
browser would otherwise have to discover at runtime. Against that, it costs a
toolchain, a lockfile, a `dist/` that diverges from source, and source maps to
get back to something reviewable. For a SPA of this size — three reader modes
and a moderator view, served behind Apache to an authenticated audience — the
trade does not pay.

What you gain by going without:

- **Reviewability.** A pull request diff is the change. There is no generated
  output to reconcile against source.
- **Debuggability.** DevTools shows the real files with the real names. No
  source-map indirection.
- **Operational simplicity.** Deploy is a file copy. Apache needs no Node
  runtime to serve the SPA; `docs-site/node_modules` is the only Node footprint
  in the repo and it is git-ignored and used solely for this documentation site.

The cost you accept is that the browser does dependency resolution on every load
(mitigated by HTTP caching — see `docs/architecture/v2/06-caching-performance.md`)
and that there is no compile-time check that an `import` specifier resolves. The
project answers the second cost with an explicit import-resolution baseline
(below) and with browser-level equivalence tests.

## The app shell

`frontend/index.html` is deliberately thin. It is the shell, not the app:

- The font preconnect and the stylesheet links — `monolith.css` (frozen design
  system) first, then `app.css`, `read.css`, `feed.css`, `moderate.css`.
- A single `<header class="app-bar">` with the DEPT® brand, the mode tabs
  (Manual / Read / Feed / Moderation), the Resources dropdown, the sign-in slot
  (`#appAuth`) and the theme toggle.
- A single mount point: `<main id="view" class="view"></main>`. Every mode
  renders into `#view`.
- One entry point: `<script type="module" src="core/main.js"></script>`.

The Moderation tab ships `hidden` in the markup and is unhidden by JavaScript
only for authorised sessions (see [Router and the four modes](./router-and-modes.md)).

```mermaid
sequenceDiagram
    participant B as Browser
    participant H as index.html
    participant M as core/main.js
    participant Auth as feed/auth.js
    participant API as FastAPI /api,/auth

    B->>H: GET /app/  (static, via Apache)
    H->>M: <script type=module> load
    M->>Auth: initializeAuth()
    Auth->>API: GET /auth/me
    API-->>Auth: session JSON (roles, permissions) or 401
    M->>M: initTheme() · initChrome()
    M->>M: route()  (reads location.hash)
    Note over M: default hash → #/manual
    M->>API: GET /api/course/* (via api-client)
    API-->>M: course JSON (cache-backed)
    M->>B: render into #view
```

The boot sequence is exactly the IIFE at the bottom of `core/main.js`:
`initializeAuth()` (best-effort — a 401 is fine and means "signed out"), then
`initTheme()`, then `initChrome()`, then a `hashchange` listener, then the first
`route()`.

## The import-resolution baseline

Because there is no compiler, a mistyped relative import does not fail the build
— it fails silently in one browser surface. v2 treats the set of resolvable
imports as a baseline to defend.

The check is mechanical: walk every `.js` under `frontend/`, extract each
relative `import`/`export … from` and dynamic `import()` specifier, and confirm
the target file exists on disk. CDN specifiers (the Ajv loader in
`feed/validate.js`) and bare specifiers are excluded — only the project's own
relative graph is in scope.

The current baseline is **98/98 local relative imports resolve**.

:::caution[Common Pitfall]
The most common breakage in a buildless ES-module SPA is a relative import that
is off by one directory — `'../render/diagram.js'` where the file actually lives
at `'../../shared/render/diagram.js'`. The Phase 4b report recorded exactly this
class of bug in three feed/course files; it has since been corrected, which is
why the baseline now resolves cleanly. There is no compiler to catch the next
one. Re-run the import-resolution check on every front-end change, and verify the
affected mode boots in a real browser, not only in tests.
:::

## Where the runtime constants come from

Nothing about the environment is hard-coded into module logic. `API_BASE`,
`QUIZ_URL`, the chapter file list, the theme key and the media aliases all live
in `core/config.js`, derived from `window.location` so the same files run under
`python -m http.server` in dev and behind Apache in production. That
centralisation is what makes the buildless approach safe to ship to multiple
environments without a per-environment build. See
[Configuration and theming](./config-and-theming.md).
