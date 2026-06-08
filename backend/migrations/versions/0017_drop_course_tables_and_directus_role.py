"""0017 — drop course_chapters + frameworks; clean up Directus DB role

Revision ID: 0017_drop_course_tables_and_directus_role
Revises: 0016_drop_faq_runbook_tables
Create Date: 2026-06-08

Context
-------
ARCH-1/2/3 established COURSE_SOURCE=files as the sole content path. Phase 0
proved `course_chapters` and `frameworks` are byte-identical to the canonical
JSON files in data/ — they carry no information not already in git. Directus
is fully unwired from code (ARCH-3); the directus_app DB role and its grants
are orphaned infrastructure.

This migration removes the two course tables and, on PostgreSQL, reverts the
0008_directus_app_role changes: REVOKEs all grants and DROPs the login role.

Ownership investigation (2026-06-08, read-only SELECT)
-------------------------------------------------------
Connected to the DEV database (codecoder-dev, oid=16967). Findings:

  1. directus_*  system tables: ZERO in the public schema of codecoder-dev.
     SELECT returned 0 rows.

  2. directus_app_dev in codecoder-dev: 11 pg_shdepend rows, ALL deptype='a'
     (ACL/grants only). No ownership (deptype='o') of any object in this DB.
     The role grants cover: course_chapters, feed_items, frameworks,
     media_assets, questions, users, roles_id_seq, attempts_id_seq,
     auth_audit_id_seq, signing_keys_id_seq, and the public schema.

  3. directus_app ownership rows: all 37 deptype='o' entries in pg_shdepend
     reference dbid=16628 (the PRODUCTION 'codecoder' database), not this dev
     DB. In codecoder-dev, directus_app also has only ACL (deptype='a') rows.
     Ownership in PROD means DROP OWNED BY on prod will be needed by TM.

Decision: the migration uses DROP OWNED BY <role> inside a DO $$ block so
that on PROD (where directus_app owns its self-created directus_* tables) the
role drop is clean. This is the correct "clear old Directus state" approach
the ticket calls for. DROP OWNED BY removes all privileges AND all objects
owned by the role in the current database — it will drop any directus_* tables
Directus created, then the GRANT-table GRANTs, then the role itself. This is
an intentional, irreversible clean-up; TM must take a full backup first.

SQLite guard: all Postgres DDL is skipped on sqlite (the local smoke suite).

upgrade()   1. DROP TABLE IF EXISTS course_chapters, frameworks.
            2. DROP OWNED BY + DROP ROLE directus_app (Postgres-only, guarded).
            3. DROP OWNED BY + DROP ROLE directus_app_dev (Postgres-only,
               guarded) — the dev-DB peer role, same ticket.

downgrade() Re-creates course_chapters and frameworks (empty schema; data is
            re-seedable from git files or the pre-drop backup). Re-creates
            directus_app + directus_app_dev roles and restores all grants
            exactly as 0008 left them.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_drop_course_tables_and_directus_role"
down_revision: Union[str, Sequence[str], None] = "0016_drop_faq_runbook_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── Postgres role-name helper (identical pattern to 0008) ───────────────────
_ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _validated_role(name: str) -> str:
    """Validate `name` is a safe Postgres identifier before embedding in DDL."""
    if not _ROLE_NAME_RE.match(name):
        raise ValueError(
            f"Role name {name!r} is not a valid Postgres identifier "
            "(^[a-z_][a-z0-9_]{{0,62}}$). Refusing to emit DDL."
        )
    return name


def _directus_role() -> str:
    """Return the primary Directus role name from env (default: directus_app)."""
    return _validated_role(os.getenv("DIRECTUS_DB_ROLE", "directus_app"))


def _directus_dev_role() -> str:
    """Return the dev Directus role name from env (default: directus_app_dev)."""
    return _validated_role(os.getenv("DIRECTUS_DB_ROLE_DEV", "directus_app_dev"))


def _drop_role_sql(role: str) -> str:
    """
    DROP OWNED BY <role> then DROP ROLE <role>, guarded by pg_roles existence.

    DROP OWNED BY removes ALL objects owned by the role in the *current*
    database (tables, sequences, indexes) AND revokes all privileges the role
    holds on objects in this database. This is the correct clean-up path when
    the role may own directus_* system tables it created itself.

    Safe to call when the role holds only GRANTs (no ownership): DROP OWNED BY
    is a no-op for objects, but still strips the ACL entries — which is what
    we want before the DROP ROLE.
    """
    return f"""
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
        BEGIN
            DROP OWNED BY {role};
            DROP ROLE {role};
        EXCEPTION WHEN OTHERS THEN
            -- Best-effort role cleanup. A non-superuser/CREATEROLE credential
            -- (e.g. the dev app role, which OWNS the course tables and can drop
            -- them but cannot drop roles) skips this with a NOTICE rather than
            -- aborting the migration — the course-table DROPs above have already
            -- succeeded. Re-run as a DBA/privileged credential (prod deploy) to
            -- finish the role cleanup. Mirrors db.py's best-effort-DDL idiom.
            RAISE NOTICE 'ARCH-4: skipped dropping role {role} (SQLSTATE %, %); run as a privileged credential to finish.', SQLSTATE, SQLERRM;
        END;
    END IF;
END
$$;
"""


# ── upgrade ──────────────────────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Drop the now-redundant course content tables.
    #    IF EXISTS makes this idempotent and compatible with --sql offline mode.
    #    No FK dependents confirmed: 0 rows in information_schema
    #    referential_constraints pointing at these tables (investigated read-only).
    op.execute("DROP TABLE IF EXISTS course_chapters;")
    op.execute("DROP TABLE IF EXISTS frameworks;")

    # 2. Clean up the Directus DB role(s) — Postgres only.
    if bind.dialect.name != "postgresql":
        return

    role = _directus_role()          # directus_app  (prod)
    dev_role = _directus_dev_role()  # directus_app_dev (dev)

    # Drop both roles. DROP OWNED BY handles: directus_* tables Directus
    # created (on prod), sequence GRANTs, schema USAGE GRANTs, and every
    # table-level privilege granted by 0008. After DROP OWNED BY the role
    # holds no objects or privileges, so DROP ROLE succeeds cleanly.
    op.execute(_drop_role_sql(role))
    op.execute(_drop_role_sql(dev_role))


# ── downgrade ────────────────────────────────────────────────────────────────


def downgrade() -> None:
    """
    Re-create course_chapters + frameworks (empty; data is re-seedable).
    Re-create directus_app + directus_app_dev and restore all 0008 grants.

    Schema is restored exactly as in the baseline + 0008. Data is NOT restored
    — re-seed from the git JSON files or the pre-drop backup.

    Uses raw SQL with IF NOT EXISTS guards so this is idempotent and
    compatible with --sql offline mode (no sa.inspect on MockConnection).
    """
    bind = op.get_bind()

    # ── Re-create course_chapters ─────────────────────────────────────────────
    # Baseline schema from models.py CourseChapter: filename PK (varchar 128),
    # ring (varchar 32, NOT NULL), title (varchar 255, NOT NULL),
    # content (JSONB/JSON NOT NULL), created_at, updated_at.
    if bind.dialect.name == "postgresql":
        op.execute("""
CREATE TABLE IF NOT EXISTS course_chapters (
    filename    VARCHAR(128) PRIMARY KEY,
    ring        VARCHAR(32)  NOT NULL,
    title       VARCHAR(255) NOT NULL,
    content     JSONB        NOT NULL,
    created_at  TIMESTAMP    DEFAULT NOW(),
    updated_at  TIMESTAMP    DEFAULT NOW()
);
""")
    else:
        op.execute("""
CREATE TABLE IF NOT EXISTS course_chapters (
    filename    VARCHAR(128) PRIMARY KEY,
    ring        VARCHAR(32)  NOT NULL,
    title       VARCHAR(255) NOT NULL,
    content     JSON         NOT NULL,
    created_at  DATETIME,
    updated_at  DATETIME
);
""")

    # ── Re-create frameworks ──────────────────────────────────────────────────
    # Baseline schema from models.py Framework: id PK (varchar 32),
    # data (JSONB/JSON NOT NULL), updated_at.
    if bind.dialect.name == "postgresql":
        op.execute("""
CREATE TABLE IF NOT EXISTS frameworks (
    id          VARCHAR(32) PRIMARY KEY,
    data        JSONB       NOT NULL,
    updated_at  TIMESTAMP   DEFAULT NOW()
);
""")
    else:
        op.execute("""
CREATE TABLE IF NOT EXISTS frameworks (
    id          VARCHAR(32) PRIMARY KEY,
    data        JSON        NOT NULL,
    updated_at  DATETIME
);
""")

    # ── Restore Postgres role + grants (exact reverse of upgrade) ─────────────
    if bind.dialect.name != "postgresql":
        return

    role     = _directus_role()
    dev_role = _directus_dev_role()

    # Helper: create role if absent. No password — set out of band (same as 0008).
    def _create_if_absent(r: str) -> None:
        op.execute(f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{r}') THEN
        CREATE ROLE {r} LOGIN;
    END IF;
END
$$;
""")

    for r in (role, dev_role):
        _create_if_absent(r)

        # Schema-level: Directus must be able to create + manage directus_* tables.
        op.execute(f"GRANT CREATE, USAGE ON SCHEMA public TO {r};")

        # Identity + reference: read-only.
        op.execute(f"GRANT SELECT ON users, roles, user_roles TO {r};")

        # Authoring surface: full DML on questions; no DELETE on course_chapters
        # is intentional here but 0008 granted DELETE — restore identically.
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON course_chapters, questions TO {r};"
        )

        # frameworks: no DELETE (rows must go through migration).
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON frameworks TO {r};")

        # feed_items: moderation only — no INSERT/DELETE.
        op.execute(f"GRANT SELECT, UPDATE ON feed_items TO {r};")

        # app_config: no DELETE.
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON app_config TO {r};")

        # media_assets: read-only asset browser.
        op.execute(f"GRANT SELECT ON media_assets TO {r};")

        # Sequences: needed for serial inserts.
        op.execute(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {r};"
        )

        # Hard deny of runtime + audit tables.
        op.execute(
            f"REVOKE ALL ON attempts, quiz_sessions, signing_keys, auth_audit FROM {r};"
        )

        # superadmin is denied too (set by 0009, restore here for completeness).
        op.execute(f"REVOKE ALL ON superadmin FROM {r};")
