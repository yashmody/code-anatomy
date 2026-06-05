---
id: intro
title: DEPT® Anatomy of Code — v2 Documentation
sidebar_position: 1
slug: /
---

# DEPT® Anatomy of Code — v2 documentation

> **Status:** scaffold only. Phase 5a fills every section. This landing page is
> a stub so the navigation, brand tokens and section structure can be reviewed
> at the Phase 0 gate.

The Anatomy of Code platform teaches, certifies and references the CODE-CODER
framework for DEPT®'s Adobe Experience Cloud practice. v2 re-architects the
system into a clean modular monolith with a real CMS (Directus), proper
authorisation, environment management, caching and — these docs.

## Who this is for

- **Architects and senior engineers** building on the platform.
- **IT generalists** onboarding to the practice who need to operate, deploy
  and extend it.
- **Content authors and quiz administrators** working through Directus.

## The six sections

| Section | What it covers |
|---|---|
| [Front-end](/frontend/) | The buildless ES-module SPA — `core/`, `shared/`, `modules/`, styles, the registry, the three modes (Manual, Read, Feed). |
| [Content architecture](/content-architecture/) | The consolidated `content/` tree, the source-of-truth shift to Postgres, schemas, the frozen monolith, the LAYER pattern. |
| [Database](/database/) | The Postgres schema, Alembic migrations, the ER diagram, large-object media, backup/restore. |
| [Deployment](/deployment/) | `infra/deploy.sh`, the Apache vhost, systemd + uvicorn, environment and secrets, upgrade and rollback. |
| [Quiz management](/quiz-management/) | The question bank, the quiz lifecycle, real-vs-dev certificates, verification, admin flows. |
| [System architecture](/system-architecture/) | The modular monolith, the Directus topology, the two auth planes, caching, security, observability. |

## Where these docs live in the design

This site is the user-facing surface of the **Phase 0 design contracts** in
`docs/architecture/v2/`. The contracts are the design; this site is the
reference.

| Design contract | Section it primarily feeds |
|---|---|
| [`v2-plan.md`](https://internal.in.deptagency.com/) — the shared contract | this landing page + System architecture |
| `v2/01-blueprint.md` — directory tree, module boundaries, migration maps | Front-end, System architecture |
| `v2/02-parity-method.md` — baseline + parity harness | Deployment (verification), Quiz (certificate parity) |
| `v2/03-data-model.md` — target Postgres schema, Alembic | Database |
| `v2/04-authz-model.md` — role taxonomy, SSO + PKCE | System architecture (auth planes), Quiz (admin flows) |
| `v2/05-config-cms.md` — config registry, Directus collection map | Content architecture, Deployment (env), System architecture |
| `v2/06-caching-performance.md` — Apache + Postgres + app cache | Deployment, System architecture |
| `v2/07-security-baseline.md` — security checklist | Deployment, System architecture, Quiz |
| `v2/08-docs-plan.md` — this site's design contract | (meta) |

:::tip Why This Matters

The v2 effort's hard constraint is **no loss of content, data or
functionality**. These docs are how the team — and future joiners —
understand which decision lives where, why it was made, and what the
parity harness is protecting.

:::

## How to read this site

- **Scan box first.** Every page leads with a Scan Box — three to five
  bullets, roughly a 30-second read covering *what / why / so what*.
- **Prose underneath.** Architect-level, opinionated, written to be read
  end-to-end. Not bullet-form.
- **Diagrams woven through.** ASCII for static architecture (matches the
  main app's `.arch-diagram`/`.arch-row` blocks); Mermaid for flows.
- **Four callout types**: *Why This Matters*, *Agency Tip*, *Common
  Pitfall*, *Before / After*. No fifth.

See [`v2/08-docs-plan.md`](https://internal.in.deptagency.com/) for the
authoring policy.

## Status

This site is a Phase 0 scaffold:

- Branch `v2` (main is untouched).
- No `npm install` has been run yet — Phase 5a does that.
- Each section has only an intro stub. Phase 5a writes the rest.
