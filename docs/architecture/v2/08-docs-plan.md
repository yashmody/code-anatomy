# v2/08 — Docs site plan (Docusaurus scaffold + the six sections)

> Phase 0 design contract · Owner: Docs-scaffold agent · Covers 12-item plan
> item **10** (Docusaurus documentation).
> Read [`docs/architecture/v2-plan.md`](../v2-plan.md) and the other Phase 0
> contracts first. This document is what **Phase 5a** executes.
> DESIGN ONLY — the scaffold exists at `docs-site/` but no `npm install` has
> run, no build has been produced. No code outside `docs-site/` is modified.

Phase 0 deliverable for item 10 is two things working together:

1. **A real scaffold** at `docs-site/` — Docusaurus 3.5.x classic preset,
   pinned deps, six section stubs, DEPT® brand tokens wired in.
2. **This plan** — what each section must cover, how it is authored, how it
   is sourced, where it is deployed, how it is versioned, how it is
   searched, how CI guards it, and what Phase 5a does in order.

The eight Phase 0 docs (`01`…`08`) hang together as one design. This doc
cross-references the others rather than restating them.

---

## 0 · Scan box

- The site is **Docusaurus 3.5.x classic** — Markdown/MDX content, six
  top-level sections, ochre `#FF4900` accent, Syne/DM Sans/JetBrains Mono
  typography, mermaid enabled. Source lives in `docs-site/`; built output
  goes to `docs-site/build/`.
- The **six sections** match the audit: Front-end, Content architecture,
  Database, Deployment, Quiz management, System architecture. Each gets
  5–10 concrete pages in Phase 5a (titles listed below).
- Authoring follows **CLAUDE.md**: Indian English, the LAYER pattern with
  a Scan Box at every page top, hybrid ASCII/Mermaid diagrams, the four
  callout types (*Why This Matters / Agency Tip / Common Pitfall / Before
  After*), ochre `#FF4900` as the only accent.
- **Deployment default**: an Apache `Alias /docs/` to `docs-site/build/`
  on the existing internal vhost. Alternative: a `docs.<internal>`
  subdomain (more isolation, more cert work). Default is chosen for
  parity with how `/anatomy/` is already served.
- **Versioning**: single-rolling-current for v2 launch. Docusaurus
  versioning is *available* but not turned on; the trigger to enable it
  is a major schema or platform change that breaks v2 docs.
- **Search**: local search only (Docusaurus built-in plugin) — Algolia
  DocSearch is the path forward when public traffic warrants it; not yet.

---

## 1 · Goals + audience

### Goals

| Goal | What "done" looks like |
|---|---|
| Single reference site for v2 | Six sections fully written; the eight Phase 0 contracts referenced from every section landing page. |
| Brand-faithful | Visual sympathy with the main app: ochre `#FF4900`, Syne display, DM Sans body, JetBrains Mono labels, four callout types only. |
| Operable | An IT generalist can deploy and run the platform using only the *Deployment* and *System architecture* sections. |
| Auditable | Every claim that depends on code/config cites a real `path:line`, the same discipline `v2/01-blueprint.md` uses. (`editUrl` is left `undefined` in the scaffold for v2 launch — linkifying `path:line` strings is revisited in Phase 5a; deferred per gate-report C-70.) |
| Future-proof | Versioning is *off* but the migration to *on* is a one-command flip when needed. Same for Algolia. |
| Lightweight | No backend, no signed-in users, no comments. Static site. Two-command run. |

### Audience

| Reader | What they want |
|---|---|
| Architects (DEPT® AEM practice, India + global) | The why — locked decisions, the modular-monolith shape, the two auth planes, parity guarantees. |
| Senior engineers | The how — module boundaries, schema, signing keys, the cache hierarchy, the API client. |
| IT generalists onboarding | The runbook — deploy, restart, back up, restore, where logs live, how to add a user. |
| Content authors / Quiz Admins | How to write content in Directus, how the seed round-trips, how questions are reviewed. |
| Future joiners | One landing page that orients them and points at the eight design contracts. |

The voice discipline in CLAUDE.md applies: Indian English spelling
(organise, behaviour, colour); plain professional English with no
Americanisms or Indian-business clichés; Indian examples land for an
Indian reader (Razorpay, Shiprocket, UPI, DPDP, BFSI) but global
examples are fine when they are the right reference.

---

## 2 · The six sections — what each covers

Each section is a Docusaurus *category* with its own `_category_.json` and
an `intro.md` that opens with a Scan Box. Phase 5a writes the page set
below; the scaffold's `sidebars.js` already lists them as comments under
each category so the next agent has a literal checklist.

### 2.1 Front-end — `docs/frontend/`

What it covers: the buildless ES-module SPA, module boundaries, the block
registry, the three modes, theming, parity.

Page set (7):

1. **Architecture** — buildless choice, hash router, why no framework.
2. **Module layout** — `core/` / `shared/` / `modules/` boundaries (cite
   `v2/01-blueprint.md` §4.1).
3. **Blocks and the registry** — the 14 renderers under
   `frontend/shared/blocks/`; the dispatch contract in `shared/registry.js`.
4. **Router and modes** — Manual (`modules/course/scroll.js`), Read
   (`modules/course/read.js`), Feed (`modules/feed/mode.js`).
5. **Theming and brand** — per-page `localStorage` theme key behaviour;
   `core/theme.js`; the relationship between `styles/monolith.css` (frozen)
   and the docs-site CSS tokens.
6. **API client** — `core/api-client.js`, `API_BASE`, error shaping; how
   `util/load.js` and `feed/store.js` migrate onto it.
7. **Testing parity** — `frontend/tests/equivalence.html` against the
   frozen monolith; the parity harness link to `tests/baseline/`.

Source: `v2/01-blueprint.md` §1, §4, §7; `v2/06-caching-performance.md`
(static caching); `v2/07-security-baseline.md` (CSP).

### 2.2 Content architecture — `docs/content-architecture/`

What it covers: the consolidated `content/` tree, Postgres as runtime
source of truth, the git seed and export round-trip, schemas, the frozen
monolith, the LAYER voice.

Page set (6):

1. **Source of truth** — Postgres editable; git-JSON as seed/export.
   ADR 0001 supersede note.
2. **Schemas** — `content/schemas/{course,feed}.schema.json`,
   `content/validate.py`.
3. **Seed and export** — the ETL (`modules/content/etl.py`); how
   Directus exports back into `content/source/` (Phase 4).
4. **The frozen monolith** — what `content/frozen/anatomy-of-code-course.html`
   is and is not; the visual-parity contract.
5. **Resources** — single source of truth at `content/resources/`; the
   five duplicates that get removed.
6. **Voice and the LAYER pattern** — Indian English, Scan Box discipline,
   the four callout types.

Source: `v2/01-blueprint.md` §5; `v2/03-data-model.md` (`course_chapters`,
`frameworks`); `v2/05-config-cms.md` (Directus collection map).

### 2.3 Database — `docs/database/`

What it covers: the Postgres schema, Alembic, the ER diagram,
Postgres-only features, large-object media, backup/restore.

Page set (6):

1. **Schema overview** — the v2 tables (7 existing + 4 new) in one map.
2. **ER diagram** — auto-generated from Alembic metadata (Sourcing §4
   below).
3. **Alembic and migrations** — baseline stamp, the reconcile migration,
   the per-phase migration cadence.
4. **Postgres-only features** — `tsvector`, `hstore`, `ARRAY`, large
   objects; why the SQLite shims are retired.
5. **Media large objects** — `MediaAsset` ↔ `pg_largeobject`; the cleanup
   trigger that prevents orphan OIDs.
6. **Backup and restore** — `pg_dump --format=custom` recipe; restore
   walk-through; retention.

Source: `v2/03-data-model.md` is the design contract; this section is its
public face.

### 2.4 Deployment — `docs/deployment/`

What it covers: the deploy script (now at `infra/deploy.sh`), Apache
vhost, systemd + uvicorn, env and secrets, upgrade and rollback.

Page set (6):

1. **Prerequisites** — VM specs, OS (RHEL 8+ / Rocky / Alma; Ubuntu
   22.04+ as tested alternative), OS packages, Postgres provisioning.
2. **`infra/deploy.sh` walkthrough** — every rsync, every systemd write,
   every Apache touch (cite `v2/01-blueprint.md` §7).
3. **Apache vhost** — TLS posture, Aliases (`/anatomy/`, `/app/`,
   `/docs/`), `ProxyPass`, cache/deflate/HTTP2 from Phase 3b.
4. **systemd and uvicorn** — unit file, log rotation, worker count.
5. **Env and secrets** — what is required, what defaults are fatal in
   prod; how Directus shares Postgres credentials; the secrets registry
   from `v2/05-config-cms.md`.
6. **Upgrade and rollback** — running the parity harness before deploy;
   the rollback recipe.

Source: today's `DEPLOY.md` (kept as the operator walkthrough);
`v2/01-blueprint.md` §7 (path-reference migration); `v2/06` (caching);
`v2/07` (TLS/HSTS, header hardening).

### 2.5 Quiz management — `docs/quiz-management/`

What it covers: the question bank, the quiz lifecycle, certificates,
real-vs-dev separation (Phase 2c), verification, admin flows.

Page set (6):

1. **Question bank** — schema, authoring, versioning, the `q.ugc.*`
   sub-tree.
2. **Quiz lifecycle** — start → take → submit → grade → cert → email
   (Mermaid sequence).
3. **Certificates** — signing, PDF render, verification URL,
   signing-key rotation via the new `signing_keys` table.
4. **Dev mode vs real (Phase 2c)** — visible watermark, separate dev
   signing key, `attempts.environment` column. HMAC input and signing-
   key selection are the source-of-truth concern of the security and
   data-model contracts; this page **references**, never restates them
   (see `07-security-baseline.md` §8 and `03-data-model.md` §2.5).
5. **Verification** — `/verify/{cert_id}` flow; the public view.
6. **Admin flows** — Quiz Admin and Platform Admin in Directus and via
   the FastAPI admin endpoints.

Source: `v2/04-authz-model.md` (Quiz Admin permissions);
`v2/03-data-model.md` §2 (`attempts`, `signing_keys`, `quiz_sessions`);
`v2/07-security-baseline.md` (signing posture); Phase 2c in `v2-plan.md`.

### 2.6 System architecture — `docs/system-architecture/`

What it covers: the modular monolith, the Directus topology, the two
auth planes, caching, security, observability.

Page set (6):

1. **Modular monolith** — `core/` + `modules/` shape, cross-module rules.
2. **Directus topology** — service layout, shared Postgres, webhook
   contract.
3. **Auth planes** — Google SSO + PKCE for learners; Directus auth for
   staff; the permission matrix from `v2/04-authz-model.md`.
4. **Caching and performance** — Apache layer, app-cache seam, Postgres
   tuning, SPA cache-busting (`v2/06`).
5. **Security baseline** — header hardening, CSP, HSTS, secret
   management, signing-key rotation (`v2/07`).
6. **Observability** — uvicorn logs, Postgres slow queries, Directus
   audit trail; what to alert on.

Source: every other Phase 0 contract rolls up here.

---

## 3 · Authoring policy (CLAUDE.md-compliant)

### 3.1 Language

- **Indian English spelling**: organise, optimise, behaviour, colour,
  centre, defence, programme (when meaning a plan; *program* for code).
- **Plain professional English**: no "y'all", "reach out", "circle back",
  no "do the needful", "kindly", "revert back", no overly British
  academic register.
- **Acronyms expanded on first use** per page (KYC, DPDP, AEMaaCS, CJA,
  AJO, LLMO).
- Crore/lakh acceptable when discussing Indian market context; otherwise
  standard digit grouping.
- Indian examples (Razorpay, Shiprocket, UPI, DPDP, Aadhaar, BFSI,
  Flipkart, Myntra) where they land naturally. Global examples (Stripe,
  Linear, Figma) when they are the right reference — do not force a
  localisation.

### 3.2 LAYER pattern, on every page

Every page opens with:

1. **`# Title`**.
2. **`## Scan box`** — 3 to 5 bullets, roughly a 30-second read, covering
   *what / why / so what*.
3. **Prose body** — declarative, opinionated, written for the architect.
   Not bulletised.
4. **Diagrams + callouts** woven through where they earn their place. Not
   piled at the end.

### 3.3 Diagram convention (hybrid)

- **ASCII** for static architecture (the `.arch-diagram` / `.arch-row` /
  `.arch-node` look in the main app). Use fenced code blocks; do not
  attempt to recreate the CSS-styled main-app blocks inside Docusaurus.
- **Mermaid** for flows: sequence diagrams, pipelines, decision trees,
  testing workflows. The docs site has `@docusaurus/theme-mermaid`
  enabled and `markdown.mermaid: true` in `docusaurus.config.js`, so
  `` ```mermaid `` fences just work.

### 3.4 Four callout types — and only four

Authors map them to Docusaurus admonitions:

| CLAUDE.md type | Docusaurus admonition | Use |
|---|---|---|
| Why This Matters | `:::tip[Why This Matters]` | The architect-level stake. |
| Agency Tip | `:::note[Agency Tip]` | Practical agency-context guidance. |
| Common Pitfall | `:::warning[Common Pitfall]` | What teams actually get wrong. |
| Before / After | `:::info[Before / After]` | Concrete example pairs. |

The bracket form (`:::tip[Title]`) is the canonical Docusaurus 3.x
syntax. The older quoted form (`:::tip "Title"`) renders inconsistently
in 3.x and must not be used.

`src/css/custom.css` ties all admonitions to the ochre left rule so they
read like the main app's `.arch-review` block.

Do not introduce a fifth admonition type without an explicit decision.

### 3.5 Brand tokens

- Ochre `#FF4900` is the **only** accent. Ink/paper/rule unchanged.
- Fonts: **Syne** (display, headings, navbar), **DM Sans** (body),
  **JetBrains Mono** (labels, code, table headers, kbd).
- Dark mode supported, default light, respect OS preference.
- DEPT® logo URL (canonical):
  `https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg`.
  Phase 5a vendors a copy to `static/img/logo-dept.svg`.

---

## 4 · Sourcing — auto-generated vs hand-written

A docs site is only as honest as its sourcing. v2 leans into
auto-generation where the source-of-truth is code or config, and reserves
hand-authoring for the why-and-how prose.

| Artefact | Source | How |
|---|---|---|
| API reference | FastAPI `app.openapi()` | Phase 5a adds a small script `backend/scripts/dump-openapi.py` that writes `docs-site/static/openapi.json` and a page in *System architecture* renders it via Swagger UI (or `redocly-react` if simpler). Auto-refreshed on each `npm run build`. |
| Database ER diagram | Alembic metadata (`models.py`) | Phase 5a adds `backend/scripts/render-erd.py` that uses `sqlalchemy_schemadisplay` or `eralchemy` against `app.core.models.Base.metadata` and emits `docs-site/static/img/db-erd.svg`. The *Database → ER diagram* page embeds the SVG. |
| Apache vhost dump | Generated by `infra/deploy.sh` | Phase 5a copies the rendered vhost (TLS, Aliases, ProxyPass) into `docs-site/static/apache/vhost.example.conf` so the *Deployment → Apache vhost* page can include it as a code block. |
| Permission matrix | `v2/04-authz-model.md` | Mirrored as a Markdown table on *System architecture → Auth planes*. Phase 5a links to the contract; the contract is the source. |
| Hand-written prose | This repo | Everything else — the why, the operator runbook, the LAYER prose. |

> The auto-generated artefacts are committed under `docs-site/static/` so
> a build does not require a live database, a live API, or `httpd -t -D
> DUMP_VHOSTS`. The generation scripts are run by the author or by CI on
> demand.

---

## 5 · Deployment — where the built site is served

### Proposed default · `/docs/` Alias on the existing vhost

`infra/deploy.sh` (Phase 5a addition) rsyncs `docs-site/build/` to the
deploy target (e.g. `/var/www/internal/docs/`) and the Apache vhost adds:

```apache
Alias /docs/ /var/www/internal/docs/
<Directory /var/www/internal/docs>
    Require all granted
    Options -Indexes
    AddDefaultCharset UTF-8
</Directory>

# Docusaurus emits content-hashed bundles under /docs/assets/*. These
# filenames change on every rebuild, so they are safe to mark immutable
# for one year. Aligns with the static-asset cache policy in
# `v2/06-caching-performance.md` §2.4.
<FilesMatch "^/docs/assets/.*\.(js|css|woff2?|svg|png|jpe?g|webp|avif|ico)$">
    Header always set Cache-Control "public, max-age=31536000, immutable"
</FilesMatch>

ProxyPass /docs !
```

The `ProxyPass /docs !` exclusion mirrors how `/anatomy/` and `/app/` are
already excluded from the FastAPI proxy (see
`v2/01-blueprint.md` §7 and today's `deploy.sh:871-915`). The site is
served at:

```
https://internal.in.deptagency.com/docs/
```

`docusaurus.config.js` already pins `baseUrl: '/docs/'` and `url:
'https://internal.in.deptagency.com'`. The build is path-relative, so
moving to a subdomain later is a config flip.

**Why this default**

- Parity with the existing pattern (`/anatomy/`, `/app/`, `/api/*`).
- No new TLS cert, no new DNS record, no CORS questions.
- The caching layer from `v2/06` (Apache `mod_cache`/`mod_expires`)
  applies the same rules to static files under `/docs/` as under `/app/`.

### Alternative · `docs.internal.in.deptagency.com` subdomain

| Pro | Con |
|---|---|
| Cleaner separation; can be made public without exposing the app vhost. | Needs a new TLS cert (LE or wildcard renewal cadence), a new DNS record, a second `<VirtualHost>`, and a separate vhost-level cache config. |
| Independent rate-limiting / WAF rules. | More moving parts at the gate where v2's hard constraint is *no loss*. |

Flag this as an open gate: **adopt the subdomain when the docs site goes
public, not before.**

---

## 6 · Versioning — single-rolling-current for v2

Docusaurus supports versioned docs (frozen snapshots under
`docs-site/versioned_docs/`). It is **off** for v2 launch.

**Why single-rolling-current**

- v2 is the only version that exists. main is being archived at cutover.
- The first months post-cutover will see steady doc churn against a
  steady runtime; freezing snapshots adds noise.
- All changes are diffable in git on branch `main` once v2 lands.

**When to enable versioning (the trigger)**

- A breaking change to the data model (e.g. cert HMAC input changes), or
- A breaking auth change (e.g. a third plane), or
- The platform forks (e.g. a public learner-facing instance separate
  from the internal one).

Enabling it is a one-command flip:

```bash
cd docs-site
npm run docusaurus -- docs:version v2.0
```

Phase 5a does **not** run this command. It is a future-phase decision.

---

## 7 · Search — local for v2, Algolia later

Phase 5a installs **`@easyops-cn/docusaurus-search-local`** pinned at
`^0.44.0` (the de-facto local search plugin for Docusaurus 3.5; the
classic preset ships no official local search). The dependency is pinned
in `docs-site/package.json` and registered in the `themes` array of
`docusaurus.config.js` with a small configuration block:

```js
themes: [
  '@docusaurus/theme-mermaid',
  [
    '@easyops-cn/docusaurus-search-local',
    {
      hashed: true,
      indexDocs: true,
      indexBlog: false,
      docsRouteBasePath: '/',
      language: ['en'],
      highlightSearchTermsOnTargetPage: true,
    },
  ],
],
```

It indexes at build time, ships a small JS payload, and works offline.
Sufficient for an internal six-section site.

**Algolia DocSearch** is the upgrade path. It is free for open-source and
documentation, but the application is gated on the site being public.
Until the site is public (see §5 alternative), local search is the right
call.

---

## 8 · CI — future build step that fails on broken links / typos

Phase 5a does not stand up CI; Phase 5b can. The contract Phase 5b
implements:

| Check | How |
|---|---|
| Build succeeds | `npm run build` (with `onBrokenLinks: 'throw'` flipped from `'warn'`). |
| No broken internal links | Native Docusaurus check, above. |
| No broken external links | `lychee` or `markdown-link-check` over `docs/`. |
| Spelling | `cspell` with a custom dictionary that includes DEPT®, AEMaaCS, Razorpay, Shiprocket, Directus, hstore, tsvector, uvicorn, alembic. Indian English locale (`en-GB` plus a custom word list). |
| Lint Markdown | `markdownlint` with the LAYER-pattern rule set (heading order, no bare lists at H1). |
| Brand check | A short script that fails the build if a non-`#FF4900` accent colour is found in `src/css/custom.css` or if `Helvetica`/`Arial`/`Open Sans` etc. appear (catches accidental font drift). |

The check set lives in `docs-site/.github/workflows/docs-ci.yml` (or
equivalent) when Phase 5b lands.

---

## 9 · What Phase 5a executes — ordered checklist

This is the literal Phase 5a runbook. The scaffold is already in place
from Phase 0; this list is what Phase 5a does *to* it.

1. **Install deps**: `cd docs-site && npm install`. Commit the resulting
   `package-lock.json`. Add `docs-site/node_modules` and
   `docs-site/build` to `.gitignore`.
2. **Smoke test**: `npm run start`. Confirm the navbar shows all six
   sections, the brand colours are ochre `#FF4900`, the fonts are Syne /
   DM Sans / JetBrains Mono.
3. **Vendor the logo**: download
   `https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg`
   to `docs-site/static/img/logo-dept.svg`. Generate `favicon.ico` from
   it.
4. **Build the auto-generated artefacts** (Sourcing §4):
   - OpenAPI dump → `docs-site/static/openapi.json`.
   - ER diagram → `docs-site/static/img/db-erd.svg`.
   - Apache vhost → `docs-site/static/apache/vhost.example.conf`.
5. **Write the section content** — fill every page listed in §2.1–§2.6.
   Each page opens with a Scan Box; prose follows; diagrams and the four
   callout types woven through; Indian English throughout.
6. **Wire local search** — install the plugin, configure it in
   `docusaurus.config.js`, confirm the search box appears.
7. **Production build**: `npm run build`. Confirm `docs-site/build/`
   exists.
8. **Apache integration** — add the `Alias /docs/` block to
   `infra/deploy.sh`'s vhost template (§5). Add an rsync of
   `docs-site/build/` to `/var/www/internal/docs/`. Add `ProxyPass /docs !`.
9. **Deploy dry-run** — `infra/deploy.sh` against a non-production host;
   confirm `https://<host>/docs/` serves the site, the search works, the
   navbar logo renders, ochre is the accent.
10. **Run the parity harness** (`tests/baseline/`) to confirm no other
    surface regressed.
11. **Cut over** — the docs go live alongside the v2 cutover in Phase 5b.

---

## 10 · Open gate decisions

Two questions are deliberately left open for the Phase 0 gate; both have
a proposed default above.

1. **Deployment URL pattern** — `/docs/` on the existing vhost (default)
   vs `docs.<internal>` subdomain (alternative). Decision needed at
   Phase 3a (infra refactor) so `deploy.sh` lands the right shape.
2. **Versioning trigger** — single-rolling-current for v2 launch
   (default) is the answer for *now*; the open question is which event
   triggers `docs:version`. Proposed triggers: breaking data-model
   change, breaking auth change, public learner-facing fork. Decision
   needed when one of those is on the horizon, not before.

A third soft question that does not block Phase 0:

3. **Algolia DocSearch** — when does the site go public enough to apply?
   Tied to (1) above.

---

## 11 · Cross-references

| This doc cites | Where the design lives |
|---|---|
| Module boundaries, file map, path migration | `v2/01-blueprint.md` |
| Parity harness (used by §9 step 10) | `v2/02-parity-method.md` |
| ER diagram source, Alembic, schema tables | `v2/03-data-model.md` |
| Auth planes, permission matrix, PKCE | `v2/04-authz-model.md` |
| Config registry, Directus collection map | `v2/05-config-cms.md` |
| Apache cache/deflate/expires/HTTP2 | `v2/06-caching-performance.md` |
| TLS, HSTS, header hardening, CSP | `v2/07-security-baseline.md` |
| Operator walkthrough (kept) | `DEPLOY.md` |
| Brand and voice rules | `CLAUDE.md` |

The eight Phase 0 docs hang together as one design. Item 10 (this doc +
the `docs-site/` scaffold) is the **public face** of the other seven.
