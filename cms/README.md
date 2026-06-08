# cms/ — RETIRED (ARCH-3)

Directus has been removed from this project as of ARCH-3 (2026-06-08).

## What happened

The course is now served from versioned JSON files via `COURSE_SOURCE=files`
(ARCH-2). Directus only ever sat as a generic admin over the same Postgres
tables; the learner app never read from it. Staff-role grants are handled by
`/api/admin/roles` directly.

The `cms/` directory contents (docker-compose.yml, bootstrap.sh,
register-collections.mjs, snapshot.yaml, extensions/, package.json,
node_modules/) have been removed.

## Reference

See ADR `content/source/docs/adr/0002-content-source-of-truth-and-authoring.md`
for the full architectural decision record.

## What is NOT removed

The `directus_app` Postgres role and the `course_chapters` / `frameworks` tables
are left intact in the database until ARCH-4's drop-tables migration runs. They
are harmless orphans and will be cleaned up in the next gated migration.
