---
id: intro
title: System architecture
sidebar_position: 1
---

# System architecture

> **Phase 0 stub.** Phase 5a expands this into the page set listed below.

## Scan box

- v2 is a **modular monolith**: one FastAPI backend internally split into
  `core/` (db, auth, config, encryption, security, cache) and `modules/`
  (`quiz`, `content`, `feed`, `media`, `cms`). One buildless front-end.
  One primary deploy unit plus the Directus service.
- **Two auth planes** by design: learner-plane (FastAPI + Google SSO with
  PKCE) carries `Learner` / `Feed Contributor`; staff-plane (Directus)
  carries `Content Author`, `Quiz Admin`, `Feed Moderator`,
  `Platform Admin`. The old `pm`/`ba`/`architect` persona becomes a
  *profile attribute*, not an authZ role.
- **Directus + shared Postgres** is the CMS topology. Directus introspects
  the existing tables and exposes a staff editing UI; FastAPI remains the
  learner-facing runtime API. Cross-service writes are routed through
  webhooks to invalidate the FastAPI cache.
- **Caching** lives in three layers — Apache (`mod_cache`, `mod_deflate`,
  `mod_expires`), a small in-process app cache (`core/cache.py`, Redis-
  ready seam), and Postgres tuning. The current vhost has none of these
  yet; Phase 3b adds them.
- **Security baseline** lifts every finding in `v2/07-security-baseline.md`
  to a concrete remediation across Phases 2e, 3c and 5b.

## What lives here

This section is the architect's overview of v2 — the boundaries between
the planes, the data flow between FastAPI and Directus, the cache
hierarchy, the security posture and the observability hooks.

Source contracts:
- `docs/architecture/v2-plan.md` — the shared contract.
- `docs/architecture/v2/01-blueprint.md` — module boundaries.
- `docs/architecture/v2/04-authz-model.md` — two-plane model.
- `docs/architecture/v2/05-config-cms.md` — Directus collection map.
- `docs/architecture/v2/06-caching-performance.md` — cache hierarchy.
- `docs/architecture/v2/07-security-baseline.md` — security posture.

## Planned pages (Phase 5a)

1. **Modular monolith** — the `core/` + `modules/` shape, how modules
   talk to each other.
2. **Directus topology** — service layout, shared Postgres, webhook
   contract.
3. **Auth planes** — Google SSO + PKCE for learners, Directus auth for
   staff, the permission matrix.
4. **Caching and performance** — Apache layer, app-cache seam, Postgres
   tuning, cache-busting for the SPA.
5. **Security baseline** — header hardening, CSP, HSTS, secret
   management, signing-key rotation.
6. **Observability** — uvicorn logs, Postgres slow queries, Directus
   audit trail, what to alert on.

:::tip Why This Matters

A "modular monolith" is a real architectural commitment — not "we
didn't get round to splitting it." The boundaries between
`backend/app/modules/{quiz,content,feed,media,cms}/` are enforced by
file layout, by the per-module `storage.py` slice, and by the parity
harness. The day a module needs to leave the monolith, it can — but
that day is not Phase 1.

:::

## Cross-references

- `docs/architecture/v2-plan.md` — the locked decisions and the phase
  plan.
- Every other section in this site rolls up here for the architectural
  view.
