"""phase-4a directus_app DB role + scoped GRANT/REVOKE (Postgres-only)

Revision ID: 0008_directus_app_role
Revises: 0007_seed_nonprod_signing_keys
Create Date: 2026-06-06

Stands up the dedicated Postgres login role Directus connects as
(`directus_app` by default) and pins its reach to exactly the tables it
edits/reads as collections, while explicitly denying the runtime-only and audit
tables. This is the DB-level half of the Phase 4a Directus coexistence; it is
ADDITIVE and REVERSIBLE and does NOT move any content.

Remote-shared-Postgres note (dev/prod isolation): a Postgres ROLE is
cluster-global, but GRANTs are per-database-object. With one remote server
hosting several databases (prod=codecoder, dev=codecoder_dev), granting a single
`directus_app` on BOTH databases would let one credential reach both — breaking
isolation. So the role NAME is parameterised via DIRECTUS_DB_ROLE: the dev DB is
migrated with DIRECTUS_DB_ROLE=directus_app_dev (a distinct role granted only on
codecoder_dev) while prod keeps the default directus_app (granted only on
codecoder). The default is unchanged, so existing local + prod behaviour is
identical when the env var is unset.

The authority comes from 03-data-model.md §5 — the "Directus DB-role GRANT
table". The shape:

  - SCHEMA public: CREATE + USAGE  — Directus needs to create and manage its
    own `directus_*` system tables in the same database.
  - app tables: scoped per the GRANT table (read-only on identity/reference,
    DML on the authoring/moderation surface, INSERT/UPDATE-only where row
    deletion must go through a migration).
  - explicit REVOKE ALL on the denied set (attempts, quiz_sessions,
    signing_keys, auth_audit) — runtime + HMAC-sealed + append-only audit;
    never editor-mutable, not even SELECT.

No password is set here: this migration is environment-agnostic. The operator
(deploy.sh) and the local 4a-2 setup set/rotate the role's password out of
band. CREATE ROLE without a password leaves it unable to log in until a
password (or other auth method) is configured, which is the intended posture.

sqlite has no roles, so this migration is a no-op on sqlite (the local smoke
suite runs against sqlite). Everything is idempotent: CREATE ROLE is guarded
by a pg_roles check, GRANT/REVOKE are themselves idempotent.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

from alembic import op

revision: str = "0008_directus_app_role"
down_revision: Union[str, Sequence[str], None] = "0007_seed_nonprod_signing_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The Directus login-role name. Default `directus_app` keeps existing local +
# prod behaviour identical; the dev DB is migrated with
# DIRECTUS_DB_ROLE=directus_app_dev so the dev credential cannot reach prod.
#
# SECURITY: the role name is interpolated directly into DDL (no bind params for
# identifiers in Postgres DDL), so it MUST be a plain SQL identifier. We refuse
# anything outside ^[a-z_][a-z0-9_]{0,62}$ — this rejects quotes, semicolons,
# whitespace and every other SQL-injection vector an attacker could try to
# smuggle through the env var, before any SQL is emitted.
_ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _directus_role() -> str:
    role = os.getenv("DIRECTUS_DB_ROLE", "directus_app")
    if not _ROLE_NAME_RE.match(role):
        raise ValueError(
            f"DIRECTUS_DB_ROLE={role!r} is not a valid Postgres identifier. "
            "It is interpolated into DDL, so it must match "
            "^[a-z_][a-z0-9_]{0,62}$ (lower-case letters, digits, underscore; "
            "starting with a letter or underscore). Refusing to emit SQL."
        )
    return role


# Idempotent role creation: CREATE ROLE has no IF NOT EXISTS, so guard on
# pg_roles. LOGIN (so Directus can connect) but NO password — set out of band.
# `role` is validated by _directus_role() before reaching this template.
def _create_role_sql(role: str) -> str:
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
        CREATE ROLE {role} LOGIN;
    END IF;
END
$$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # sqlite has no roles; nothing to do.

    role = _directus_role()

    # 1. The role itself — login-capable, password set out of band.
    op.execute(_create_role_sql(role))

    # 2. Schema-level: Directus must create + manage its own directus_* tables.
    op.execute(f"GRANT CREATE, USAGE ON SCHEMA public TO {role};")

    # 3. Scoped table grants (03 §5 GRANT table).

    # Identity + reference: read-only view inside Directus. user_roles is
    # SELECT-only by default; the optional grant UI (INSERT/UPDATE/DELETE) is
    # gated behind a decision in 05-config-cms.md, so we do not grant it here.
    op.execute(f"GRANT SELECT ON users, roles, user_roles TO {role};")

    # Authoring + UGC surface: official authoring of questions, and the
    # Content Author surface over course_chapters. Full DML — rows here are
    # editor-managed content.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON course_chapters, questions TO {role};"
    )

    # frameworks: 2-row reference content, authored in Directus but rows must
    # never be DROPPED (the runtime resolves against exactly these rows), so no
    # DELETE.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON frameworks TO {role};")

    # feed_items: moderation surface only — Directus flips the status field on
    # existing posts. It must never create or remove posts (those come from the
    # learner runtime), so no INSERT and no DELETE.
    op.execute(f"GRANT SELECT, UPDATE ON feed_items TO {role};")

    # app_config: Platform Admin config UI. Deletion of config keys must go
    # through a migration, so no DELETE.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON app_config TO {role};")

    # media_assets: metadata read only, for the asset browser. The bytes live
    # in pg_largeobject and are served exclusively by FastAPI; Directus never
    # writes here.
    op.execute(f"GRANT SELECT ON media_assets TO {role};")

    # Sequences: serial/identity-backed inserts (questions, course_chapters,
    # app_config, frameworks) need USAGE+SELECT on the owning sequences.
    op.execute(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};"
    )

    # 4. Explicit hard denial of the runtime + audit tables. A blanket REVOKE
    # ALL after the GRANT block — a future migration creating a table won't
    # auto-include the role, but these four must NEVER be reachable:
    #   attempts       — runtime, HMAC-sealed; never editor-mutable
    #   quiz_sessions  — ephemeral runtime state
    #   signing_keys   — key metadata; Platform-Admin infra path only
    #   auth_audit     — append-only audit; not even SELECT for Directus
    op.execute(
        f"REVOKE ALL ON attempts, quiz_sessions, signing_keys, auth_audit "
        f"FROM {role};"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # sqlite no-op.

    role = _directus_role()

    # Drop the role cleanly. DROP ROLE fails if the role still owns objects or
    # holds grants, so DROP OWNED BY first (this also removes every GRANT made
    # to the role across the database), then DROP ROLE. Guard on existence so a
    # re-run is a clean no-op.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                DROP OWNED BY {role};
                DROP ROLE {role};
            END IF;
        END
        $$;
        """
    )
