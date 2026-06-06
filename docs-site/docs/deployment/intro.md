---
id: intro
title: Deployment
sidebar_position: 1
---

# Deployment

## Scan box

- v2 runs on **one virtual machine**. Apache terminates TLS and is the only
  process listening on the public network; behind it sit two co-resident
  application processes — **uvicorn** (FastAPI, the application plane) and
  **Directus** (Node, the editorial write plane) — and one **PostgreSQL**
  cluster they both share.
- **`deploy.sh`** is the single, idempotent installer. It provisions the
  service users, the Python virtualenv, the `.env`, the database (role, schema,
  ETL seed), the two systemd units, the Apache vhost, the firewall, and the
  nightly large-object sweep. Re-running it is always safe.
- The **Apache vhost** is the security and performance surface: TLS 1.2/1.3 with
  HSTS, two Content-Security-Policy profiles (one for the app, one for the frozen
  course), gzip and HTTP/2, per-location cache rules, the `/cms/` reverse proxy,
  and a loopback-only guard on the cache-invalidation webhook.
- **Directus is additive and gated.** Set `DEPLOY_DIRECTUS=false` and you get a
  pure application-plane box; the default brings the CMS up over the *same*
  Postgres as the scoped `directus_app` role. Nothing about the runtime read
  path depends on Directus being present.
- **Media is final and Postgres-only.** All media bytes live in `pg_largeobject`
  and stream from FastAPI. There is no S3, no object store, no filesystem media
  store. This shapes the backup story: the nightly dump must carry large objects,
  or it silently drops every video and image.

## What lives here

This section is the deployment reference for operators and architects. It is the
*why* behind each step `deploy.sh` takes — what every systemd unit, Apache
directive, and environment variable is for, and how to run the box from day two:
backups, key rotation, the large-object sweep, and the Directus stand-up.

It is written against the **final v2 state**, not the design-era plan. Where a
design document (06, 07) described an option that was later settled differently —
worker count, the media storage adapter, HSTS preload — this section documents
what actually ships.

Source material: `DEPLOY.md` (the operator walkthrough), `deploy.sh` (the
installer), `docs/RUNBOOK.md` (day-two operations), `cms/README.md` (the Directus
as-code), and the design contracts `docs/architecture/v2/06-caching-performance.md`
and `07-security-baseline.md`.

## The shape of the deploy

```
                          ┌─────────────────────────────────────────────┐
   Browser ──HTTPS:443──▶ │  Apache httpd  (TLS · HSTS · CSP · cache)    │
                          └───┬───────────────┬──────────────┬──────────┘
                              │ Alias         │ Alias        │ ProxyPass
                              ▼               ▼              ▼
                     /anatomy → frozen   /app → SPA     / → uvicorn 127.0.0.1:8000
                     content/frozen/     frontend/      (FastAPI application plane)
                                                        /cms/ → Directus 127.0.0.1:8055
                                                              (editorial write plane)
                              │               │              │
                              └───────────────┴──────────────┘
                                              ▼
                              ┌─────────────────────────────────┐
                              │  PostgreSQL  ·  codecoder DB     │
                              │  app role + scoped directus_app  │
                              │  media bytes in pg_largeobject   │
                              └─────────────────────────────────┘
```

## Section map

1. **[Single-VM topology](./topology)** — the one-host model: who listens on what
   port, why both planes share one Postgres, and the trust boundaries the
   topology buys.
2. **[The deploy.sh installer](./deploy-script)** — every step the script runs,
   the full-install vs `--update` modes, and why it is safe to re-run.
3. **[The Apache vhost](./apache-vhost)** — TLS, HSTS, the two CSP profiles, gzip
   and HTTP/2, the per-location cache matrix, the `/cms/` proxy, and the webhook
   `Require ip`.
4. **[Environments and secrets](./environments)** — `APP_ENV`, the `.env.*.example`
   templates, `start_local.sh`, fail-closed secret validation, and where each
   secret lives.
5. **[The Directus stand-up](./directus-cms)** — systemd-plus-npm vs Docker
   Compose, the strict bootstrap order, Google SSO, the Node 22 requirement.
6. **[Day-two operations](./operations)** — backup (including large objects),
   `vacuumlo`, signing-key rotation, the cache backend switch, and reading the
   slow-query log.

:::tip[Agency Tip]
For a multi-tenant engagement, run `deploy.sh` against a non-production host
first and run the parity harness from `tests/baseline/` *before* pointing DNS.
The harness is the contract that says nothing was lost in the move — the cert
canary in particular proves every already-issued certificate still verifies.
:::
