# Migrations

This directory is the Alembic root for the backend. It is currently a
placeholder — Phase 2a of the v2 restructure will initialise Alembic here
(`alembic init .` produces `alembic.ini`, `env.py`, and the `versions/`
directory).

Until Phase 2a lands, the canonical schema is still
`backend/deploy_schema.sql` (idempotent, hand-rolled, applied by
`deploy.sh`). A snapshot of that DDL is kept at `legacy/reference.sql` so
the first Alembic autogenerate can be diffed against what production
actually has.

## Phase 2a checklist (not yet done)

- [ ] `alembic init .` and pin the Alembic version in `backend/requirements.txt`.
- [ ] Wire `alembic.ini` to read `DATABASE_URL` from the app's settings.
- [ ] Generate the first migration that matches `legacy/reference.sql`
      byte-for-byte (`alembic revision --autogenerate -m "baseline schema"`).
- [ ] Replace `deploy.sh`'s `psql -f deploy_schema.sql` step with
      `alembic upgrade head`.
- [ ] Add the `quiz_sessions` table — closes C-12 and unblocks
      `QUIZ_WORKERS > 1` in `deploy.sh`.
- [ ] Delete `legacy/` once `alembic upgrade head` from an empty database
      produces the same schema as production.

See `docs/architecture/v2/01-blueprint.md` Open Issues C-12 and the Phase 2a
plan for the full sequencing.
