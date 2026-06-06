---
id: module-layout
title: Module layout and parity
sidebar_position: 3
---

# Module layout and parity

## Scan box

- **Three top-level zones.** `core/` is app-level wiring (boot, router, config,
  theme, the content read helper, the sign-in chrome). `shared/` is the
  framework-agnostic render toolkit (the registry, the block renderers, the
  render helpers). `modules/` holds the surfaces (course, feed, moderate).
- **`styles/` carries the frozen design system.** `monolith.css` is copied
  verbatim from the monolith and never edited; `app.css`, `read.css`,
  `feed.css`, `moderate.css` layer mode-specific styling on top of it.
- **Parity with the frozen monolith is the gate.** The SPA must render to match
  `content/frozen/anatomy-of-code-course.html`. The frozen file is the
  reference, not a target to regenerate.
- **The shipped tree differs from the blueprint sketch.** The Phase 0 blueprint
  proposed `shared/util/`, a `core/router.js` split and a `modules/quiz/link.js`;
  parity considerations led to a flatter, simpler tree. This page documents what
  actually shipped.

## The three zones

```text
frontend/
├── core/        app-level wiring — knows about the environment and the shell
│   ├── main.js        router + boot + app-bar chrome
│   ├── config.js      every runtime constant (API_BASE, CONTENT_BASE, QUIZ_URL)
│   ├── theme.js       the single theme manager
│   ├── api-client.js  loadJSON — the course content read helper
│   └── auth-ui.js     global sign-in slot + permission helpers
├── shared/      render toolkit — knows nothing about the environment
│   ├── registry.js    block + feed-item dispatch tables
│   ├── blocks/        14 block renderers (one file each)
│   ├── render/        chapter.js · diagram.js · explainer.js
│   ├── framework.js   framework.json load / index / order
│   └── dom.js         esc() and raw-HTML helpers
├── modules/     the surfaces — compose shared + core into a view
│   ├── course/        manual.js · read.js
│   ├── feed/          feed.js · store.js · auth.js · validate.js · composer.js
│   │                  envelope.js · media.js · card.js · list.js · post.js
│   │                  scenario.js · video.js · vocab.js
│   └── moderate/      moderate.js
└── styles/      monolith.css (frozen) · app.css · read.css · feed.css · moderate.css
```

The dependency direction is one-way and worth holding in mind: `modules/`
imports from `shared/` and `core/`; `shared/` imports only from `shared/` and
from `core/api-client.js` (the content read helper); `core/` is the root. No
`shared/` block renderer reaches into a `module/`. The one place the two meet is
`shared/registry.js`, which imports the feed-item renderers from
`modules/feed/*` to build the feed dispatch table — a deliberate seam, covered
in [Blocks and the renderer registry](./blocks-and-registry.md).

## What shipped versus the blueprint

The Phase 0 blueprint (`docs/architecture/v2/01-blueprint.md` §4) was explicit
that some splits were optional and parity-gated. The shipped tree took the
simpler path in several places. Documenting the deltas matters because the
blueprint is a design contract, not a description of the final state.

| Blueprint sketch | What shipped | Why |
|---|---|---|
| `shared/util/{dom,framework,load}.js` | `shared/dom.js`, `shared/framework.js` directly; no `util/` | Flatter; the helpers are few. |
| `core/api-client.js` as a generic `apiFetch` wrapper | `core/api-client.js` is `loadJSON` — the course-content read helper | The real need was the course read rewrite, not a universal fetch shim. |
| `core/router.js` split out of `main.js` | Router stays inside `core/main.js` | The split risked parity; it was left as a nice-to-have. |
| `modules/quiz/link.js` | Quiz link wired inline in `main.js` `initChrome()` | One line; no module earned. |
| `modules/course/scroll.js`, `modules/feed/mode.js` | `modules/course/manual.js`, `modules/feed/feed.js` | "Scroll" was renamed "Manual" in the nav; files follow. |
| `modules/auth/auth-ui.js`, `styles/tokens.css` | `core/auth-ui.js`; no `tokens.css` | Sign-in chrome is app-level; tokens stayed in `monolith.css`. |

:::tip[Agency Tip]
When you inherit a project with a design doc and a shipped tree, reconcile the
two before you change anything. The blueprint here was honest about which splits
were optional — but a reader who trusts it literally will look for
`shared/util/dom.js` and not find it. Treat the design contract as intent and
the code as truth; this table is the reconciliation.
:::

## The frozen monolith relationship

`content/frozen/anatomy-of-code-course.html` is the original 578 KB single-file
course — the monolith. v2 froze it and the SPA reproduces it. Two facts make the
relationship precise:

1. **The design system is copied, not shared.** `frontend/styles/monolith.css`
   is the monolith's CSS, copied. `index.html` loads it first, before the
   mode-specific stylesheets, so the SPA inherits the exact brand surface — ochre
   `#FF4900`, Syne / DM Sans / JetBrains Mono, the `[data-theme]` dark-mode
   pivot. The file is **frozen**: never edited. Mode CSS layers on top; it never
   forks the base.
2. **The monolith is the parity reference, not a build target.** The SPA renders
   authored content (course JSON, feed items) through the block renderers to
   *match* the monolith. The monolith is not regenerated from the source JSON —
   it is a snapshot, kept byte-identical across phases (Phase 4b confirmed its
   sha256 unchanged from the 4a baseline). It is also a live served artefact: the
   resource islands under `/anatomy/` sit beside it.

## Equivalence testing

Parity is checked, not asserted. `frontend/tests/` carries two pieces:

- **`monolith-refs.js`** — verbatim component instances extracted from the live
  monolith (scan boxes, the four callout variants, card grids, code examples,
  blockquotes, headings, the lede). It is auto-generated and not hand-edited; it
  is the reference *side* of the comparison.
- **`equivalence.html`** — a browser harness that renders the same components
  through the SPA's block renderers and compares the output against
  `monolith-refs.js`.

The contract: a block renderer's output for a given input must equal the
monolith's hand-authored HTML for the same component. When a renderer drifts,
the equivalence harness shows it. This is the front-end's parity safety net, the
counterpart to the backend smoke suite.

:::caution[Common Pitfall]
Visual parity is not the same as DOM parity, and neither is caught by the import
baseline. A renderer can resolve its imports, boot cleanly, and still emit subtly
different markup that breaks a `monolith.css` selector. Run the equivalence
harness — and, for anything touching layout, render the SPA mode against the
frozen monolith in a real browser. The import check, the equivalence harness and
a visual diff are three different gates; passing one does not pass the others.
:::

## Cross-references

- `docs/architecture/v2/01-blueprint.md` §4 — the front-end file-by-file map and
  the optional-split notes.
- `docs/architecture/v2/02-parity-method.md` — the parity methodology this
  section's equivalence testing implements.
- [Blocks and the renderer registry](./blocks-and-registry.md) — the `shared`
  ↔ `modules/feed` seam in detail.
