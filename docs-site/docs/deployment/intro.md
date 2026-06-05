---
id: intro
title: Deployment
sidebar_position: 1
---

# Deployment

> **Phase 0 stub.** Phase 5a expands this into the page set listed below.

## Scan box

- v2 keeps the one-VM deployment model: **CentOS 8 + Apache + uvicorn +
  Postgres**. The orchestrator script moves from `./deploy.sh` to
  `infra/deploy.sh` with every path repointed for the new tree.
- Apache continues to terminate TLS, serve the SPA and the frozen monolith
  via Aliases, and proxy `/` to uvicorn on `127.0.0.1`. New in v2: an
  Alias for `/docs/` to this Docusaurus build (proposed default — see the
  open gate in `v2/08-docs-plan.md`).
- A second service joins the host in **Phase 4**: **Directus** (Node) for
  the staff content/quiz/feed editor plane, against the same Postgres.
- Environment and secrets move to a clean registry (`v2/05-config-cms.md`).
  The dev-default `SECRET_KEY` and `APP_PAYLOAD_SECRET` no longer leak
  into production; deploys fail loudly if real secrets are missing.
- The current `DEPLOY.md` walkthrough remains the operator-facing
  reference; this section is the *architecture* of the deploy — the why
  behind each rsync, alias, ProxyPass, systemd unit.

## What lives here

This section is the deployment reference for operators and architects:
what `infra/deploy.sh` does at each step, how the Apache vhost is shaped
(cache rules, deflate, HSTS, the new docs alias), how the uvicorn systemd
unit is wired, how environment variables and secrets are sourced, and how
to upgrade or roll back.

Source contracts:
- `DEPLOY.md` — the operator-facing walkthrough (kept).
- `docs/architecture/v2/01-blueprint.md` §7 — the path-reference migration
  map for `deploy.sh`.
- Phase 3a infra refactor — environment management; Phase 3b — caching.

## Planned pages (Phase 5a)

1. **Prerequisites** — VM specs, OS, OS packages, Postgres provisioning.
2. **`infra/deploy.sh` walk-through** — every rsync, every systemd write,
   every Apache touch.
3. **Apache vhost** — TLS, Aliases (`/anatomy/`, `/app/`, `/docs/`),
   ProxyPass, cache/deflate/HTTP2 (Phase 3b).
4. **systemd and uvicorn** — the unit file, log rotation, worker count.
5. **Env and secrets** — what is required, what defaults are fatal in
   prod, how Directus shares the Postgres credentials.
6. **Upgrade and rollback** — the parity harness before each deploy, the
   rollback recipe.

:::tip Agency Tip

For multi-tenant agency engagements, run `infra/deploy.sh` against a
non-production host first and run the parity harness from
`tests/baseline/` *before* pointing DNS. The harness is the contract
that says nothing was lost in the move.

:::

## Cross-references

- `DEPLOY.md` — operator walk-through (kept after v2 cutover).
- `docs/architecture/v2/06-caching-performance.md` — Apache cache,
  deflate, expires, HTTP/2.
- `docs/architecture/v2/07-security-baseline.md` — TLS configuration,
  HSTS preload, header hardening.
