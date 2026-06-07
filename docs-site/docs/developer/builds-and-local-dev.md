---
id: builds-and-local-dev
title: Builds & local dev
sidebar_position: 7
---

# Builds & local dev

How to run Tenet on your machine and how the front-end ships without a build
step. The short version: there is no bundler, and local dev mirrors production
through one script.

## Scan box

- **The SPA is buildless.** Plain ES modules loaded by the browser — no webpack,
  no Vite, no transpile. Filenames are stable (`main.js`, not
  `main.ab12cd34.js`), which is why Apache serves `/app/` with
  `must-revalidate`, never `immutable`.
- **Third-party deps come from CDNs, pinned.** mermaid from jsdelivr, Ajv from
  esm.sh — referenced directly in the import map / module URLs, not installed.
- **One script runs everything locally.** `start_local.sh` boots the app, and
  optionally Directus (`--with-cms`) and a local Postgres (`--db`), seeding the
  right `.env` template per `--env`.
- **Deploys are `deploy.sh`.** Full install or `--update` (re-sync code +
  restart). Content-only changes need only the ETL + a restart, not a full
  deploy.
- **Tests run on SQLite locally**, but anything touching search, media or
  role-isolation must be exercised on Postgres — the SQLite shim cannot
  reproduce them.

## The buildless front-end

The SPA in `frontend/` is loaded as native ES modules. `core/main.js` is the app
shell and hash router; it lazy-`import()`s each heavy mode module (manual, read,
feed, techflix) on first navigation, caching the import promise. There is no
compile step — what is on disk is what the browser runs.

Consequences worth internalising:

- **No content hash in filenames**, so a deploy is picked up on the next load
  because `/app/` is served `max-age=0, must-revalidate`. Marking it `immutable`
  would pin a stale bundle for a year — a documented pitfall in the
  [deployment](../admin/deployment) vhost.
- **CDN allow-list is the CSP.** Because deps load from jsdelivr and esm.sh, the
  CSP `script-src`/`connect-src` lists exactly those origins. Adding a dependency
  means widening the CSP, not running `npm install`.
- **Visual parity with the frozen monolith is the gate.** The components mirror
  the original `content/frozen/` monolith; equivalence is the acceptance test.

For the component architecture itself, see
[Components (front-end)](./components/intro).

## Running locally

`start_local.sh` is the multiplexer:

```bash
./start_local.sh                         # development (default)
./start_local.sh --env staging           # boot as staging
./start_local.sh --env=production --db    # production env + local Postgres
./start_local.sh --with-cms              # also boot Directus on :8055
```

- `--env {development|staging|production}` seeds `backend/.env.<env>.example` when
  no `.env` exists and exports `APP_ENV`.
- `--db` starts a local Postgres (via `pg_ctl`, Homebrew services or Docker) —
  local dev only; production points `DATABASE_URL` at the remote instance.
- `--with-cms` boots Directus (needs `cms/`, `cms/node_modules`, reachable
  Postgres, and **Node 22** — see [Managing the CMS](../admin/managing-the-cms)).

:::caution[Common Pitfall]

In local dev the `/resources/*` and `/anatomy/*` resource links can 404. In
production Apache aliases those paths to disk; the stdlib dev server cannot mount
an alias. Open the static page directly (e.g.
`http://127.0.0.1:8080/content/frozen/anatomy-of-code-course.html`) to test
frozen content locally.

:::

## The database engine matters

Production is **Postgres-only** — the schema leans on JSONB, generated `tsvector`
columns, GIN indexes, `ARRAY`, `hstore` and large objects, none of which SQLite
has. A SQLite shim (`models.py` branches on the DB URL) keeps the local smoke
suite fast, but it runs a materially different schema.

:::caution[Common Pitfall]

A green SQLite test run proves nothing about search, media or role isolation —
those features are simply not exercised on SQLite. When you need confidence in
any of them, run against Postgres (a throwaway container is the right local DB —
same engine as production, zero shim). See
[Postgres-only features](./data-model/postgres-only-features).

:::

## Deploying a change

| Change | What to run |
|---|---|
| Code (backend or front-end) | `sudo ./deploy.sh --update` (re-sync + restart) |
| Content only (chapters, questions) | re-run the ETL + restart, no full deploy |
| Full first install | `sudo ./deploy.sh` |

Content-only fast path:

```bash
cd /opt/dept-anatomy/backend
sudo -u cca .venv/bin/python -m scripts.migrate_to_postgres   # idempotent
sudo systemctl restart cca-quiz
```

The ETL is idempotent — it inserts only new rows. The full installer and the
vhost are documented in [Deployment](../admin/deployment).

:::note[Agency Tip]

Treat the buildless SPA as a feature, not a limitation. There is no build cache
to bust, no transpile step to debug, and no lockfile drift — the cost is that
every dependency is a CDN origin you must add to the CSP and pin. For an internal
tool with a small, stable dependency set, that trade is firmly worth it.

:::
