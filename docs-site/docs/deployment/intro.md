---
id: intro
title: Deployment
sidebar_position: 1
---

# Deployment

## Scan box

- v2 runs the application plane on **one virtual machine**. Apache terminates
  TLS and is the only process listening on the public network; behind it sit two
  co-resident application processes — **uvicorn** (FastAPI, the application
  plane) and **Directus** (Node, the editorial write plane). The **PostgreSQL**
  database is a **separate remote instance** they both connect out to over TLS —
  it is no longer on the VM.
- **`deploy.sh`** is the single, idempotent installer. In `DB_MODE=external`
  (the production mode) it provisions the service users, the Python virtualenv,
  the `.env` (with the remote `DATABASE_URL`), the two systemd units, the Apache
  vhost, the firewall, and the nightly large-object sweep — but it does **not**
  install or provision a local Postgres. The remote databases, extensions, and
  per-env login roles are pre-created by the DBA; Alembic owns the schema and the
  ETL seed runs against the remote. Re-running the installer is always safe.
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
   ┌──────────────────────────────── app VM ─────────────────────────────────┐
   │                      ┌─────────────────────────────────────────────┐     │
   │ Browser ─HTTPS:443─▶ │  Apache httpd  (TLS · HSTS · CSP · cache)    │     │
   │                      └───┬───────────────┬──────────────┬──────────┘     │
   │                          │ Alias         │ Alias        │ ProxyPass       │
   │                          ▼               ▼              ▼                 │
   │                 /anatomy → frozen   /app → SPA     / → uvicorn :8000      │
   │                 content/frozen/     frontend/      /cms/ → Directus :8055 │
   │                                                    │              │       │
   └────────────────────────────────────────────────────┼──────────────┼──────┘
                                                         │ TLS egress :5432    │
                                                         ▼              ▼
                              ┌──────────────────────────────────────────────┐
                              │  remote PostgreSQL instance (REMOTE_DB_HOST)  │
                              │  codecoder (prod): app_prod + directus_app    │
                              │  codecoder_dev (dev): app_dev + directus_app_dev│
                              │  media bytes in pg_largeobject · TLS required │
                              └──────────────────────────────────────────────┘
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
