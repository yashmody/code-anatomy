---
id: intro
title: DEPT® Anatomy of Code — v2 Documentation
sidebar_position: 1
slug: /
---

# DEPT® Anatomy of Code — v2 documentation

## Scan box

- **What this is.** The architect-grade reference for the v2 Anatomy of Code
  platform — the teaching, certification and reference system for DEPT®'s
  Adobe Experience Cloud practice, built on the CODE-CODER framework.
- **The shape.** A modular-monolith FastAPI application (the learner plane)
  and Directus 11 (the staff write plane) over **one** Postgres, fronted by
  Apache, serving a buildless ES-module SPA. Media lives in Postgres large
  objects — no S3, no object store.
- **Why it exists.** v2's hard constraint was *no loss of content, data or
  functionality*. These docs record which decision lives where, why it was
  made, and what the parity harness protects.
- **So what.** Six sections, each opening with its own scan box. Start with
  **System architecture** for the whole picture, then drop into the plane you
  are working in.

The Anatomy of Code platform teaches, certifies and references the CODE-CODER
framework for DEPT®'s Adobe Experience Cloud practice. v2 re-architected the
system from a single frozen HTML monolith into a clean two-plane platform: a
modular-monolith FastAPI application that owns the runtime read API, the quiz
and the signed certificates, and Directus 11 as the editorial write plane —
both over the same `codecoder` Postgres database. The browser still loads a
buildless ES-module single-page app; Apache still terminates TLS and serves
it. What changed underneath is the discipline: real authorisation, real
environment management, a cache-backed read path, and these docs.

## Who this is for

- **Architects and senior engineers** building on or extending the platform.
- **IT generalists** onboarding to the practice who need to operate, deploy
  and reason about it.
- **Content authors and quiz administrators** working through the Directus
  staff plane.

The audience is DEPT®, India-based and globally distributed. The voice is
plain, professional and opinionated — written to be architected from, not
skimmed and forgotten.

## The six sections

Read **System architecture** first — it is the overview the other five hang
off. After that the order does not matter; jump to the plane you are in.

| Section | What it covers |
|---|---|
| [System architecture](/system-architecture/intro) | The capstone overview — the two-plane model (FastAPI learner plane + Directus staff plane) over one Postgres, the modular monolith, the cache-backed read path, the auth model, the security baseline, and observability. |
| [Front-end](/frontend/intro) | The buildless ES-module SPA — `core/`, `shared/`, `modules/`, the block and feed renderer registry, the modes (Manual, Read, Feed, role-gated Moderation), and the unified theme. Visual parity with the frozen monolith is the gate. |
| [Content architecture](/content-architecture/intro) | The four content types and where each lives — course prose, feed UGC, media, config — over one Postgres, written by Directus, read by FastAPI, with media as Postgres large objects. |
| [Database](/database/intro) | The thirteen-table schema, the 0001–0008 Alembic chain, the scoped `directus_app` role, large-object media, and the Postgres-only features the platform leans on. |
| [Quiz management](/quiz-management/intro) | The certification quiz — lifecycle, the question bank and UGC questions, HMAC-signed certificates, public verification, and the RBAC and admin surfaces. |
| [Deployment](/deployment/intro) | Single-VM topology, `deploy.sh`, the Apache vhost (TLS / CSP / cache), environments and secrets, the Directus stand-up, and day-two operations. |

## The two planes, in one diagram

```mermaid
flowchart TB
    BR(["🧑 Browser\n(ES-module SPA)"])

    AP["Apache\nTLS · CSP · /"]

    subgraph LP["Learner plane"]
        FA["FastAPI application\nquiz · certs · feed\ncache-backed read"]
    end

    subgraph SP["Staff plane"]
        DIR["Directus 11\nauthors content + config"]
    end

    PG[("PostgreSQL\napp tables · content\nconfig · media LOs")]

    BR -->|HTTPS| AP
    AP -->|"/api /media /"| FA
    AP -->|"/cms/ proxy"| DIR
    FA -->|writes runtime data| PG
    DIR -->|"writes content/config\nscoped directus_app role"| PG
    DIR -->|"loopback webhook\ncache invalidation"| FA

    style LP fill:#fff8f5,stroke:#FF4900,stroke-width:2px
    style SP fill:#f5f8ff,stroke:#4466cc,stroke-width:2px
    style PG fill:#f5fff8,stroke:#338855,stroke-width:2px
```

The FastAPI plane reads content through a cache; it never reaches into
Directus at runtime. Directus writes content and config, then fires a webhook
that invalidates the relevant cache entry. That loopback seam — not a shared
library, not a shared cache key by accident — is the whole coexistence story.
**System architecture** and **Content architecture** tell it in full.

## Where these docs sit in the design

This site is the reader-facing surface of the **Phase 0 design contracts** in
the repository at `docs/architecture/v2/`. The contracts are the design record;
this site is the worked reference distilled from them and from the shipped
code. Where the two diverge, these pages document **what shipped** — the final
v2 state — and say so explicitly.

| Design contract (in the repo) | Section it primarily feeds |
|---|---|
| `v2-plan.md` — the shared contract | System architecture |
| `v2/01-blueprint.md` — directory tree, module boundaries, migration maps | Front-end, System architecture |
| `v2/02-parity-method.md` — baseline + parity harness | Deployment, Quiz |
| `v2/03-data-model.md` — Postgres schema, Alembic, media-final | Database, Content architecture |
| `v2/04-authz-model.md` — role taxonomy, SSO + PKCE | System architecture, Quiz |
| `v2/05-config-cms.md` — config registry, Directus collection map | Content architecture, Deployment |
| `v2/06-caching-performance.md` — Apache + Postgres + app cache | Deployment, System architecture |
| `v2/07-security-baseline.md` — security checklist | Deployment, System architecture, Quiz |
| `v2/08-docs-plan.md` — this site's authoring contract | (meta) |

:::tip[Why This Matters]

The v2 effort's hard constraint was **no loss of content, data or
functionality**. The cutover preserved every certificate, every question and
every byte of media. These docs are how the team — and future joiners —
understand which decision lives where, why it was made, and what the parity
harness is protecting. When something looks surprising in the code, the
answer is almost always here, written down on purpose.

:::

## How to read this site

- **Scan box first.** Every page leads with a scan box — three to five
  bullets, roughly a thirty-second read covering *what / why / so what*.
- **Prose underneath.** Architect-level, opinionated, written to be read
  end-to-end. Not bullet-form.
- **Diagrams woven through.** ASCII for static architecture and topology
  (matching the main app's `.arch-diagram` blocks); Mermaid for flows,
  sequences and decision trees.
- **Four callout types** — *Why This Matters*, *Agency Tip*, *Common
  Pitfall*, *Before / After*. No fifth.

:::note[Agency Tip]

If you are onboarding, read **System architecture** end to end, then skim each
section's scan box. That is roughly fifteen minutes and leaves you able to
place any file in the repository on the map. Come back for the prose when you
need to change something in that area.

:::

The authoring policy for this site lives in the repository at
`docs/architecture/v2/08-docs-plan.md`.
