"""phase-2a new tables — quiz_sessions, signing_keys, roles, user_roles, app_config, auth_audit

Revision ID: 0003_new_tables
Revises: 0002_reconcile
Create Date: 2026-06-06

Per docs/architecture/v2/03-data-model.md §2.2–§2.10. Storage-only — no
behaviour wiring (2b/2c/2d own that). All tables are dialect-portable so
they work against the live sqlite DB *and* the eventual Postgres target.

Each create_table call is guarded by an inspector lookup. Reason: during
Phase 2a's transition the app's `init_db()` still calls `create_all()` for
first-boot safety, which may create some of these tables before alembic
runs. Skipping pre-existing tables keeps the migration idempotent so a
local dev DB and a fresh-from-alembic DB both arrive at the same state.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_new_tables"
down_revision: Union[str, Sequence[str], None] = "0002_reconcile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb(dialect_name: str):
    """Return JSONB on Postgres, JSON on sqlite — matches the model shim."""
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB
        return JSONB
    return sa.JSON


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    JSONB = _jsonb(dialect)
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. signing_keys — referenced by attempts.signing_key_id (added in 0004).
    if "signing_keys" not in existing_tables:
        op.create_table(
            "signing_keys",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("environment", sa.String(32), nullable=False),
            sa.Column("env_var_name", sa.String(128), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("can_verify", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("verify_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.UniqueConstraint("name", name="uq_signing_keys_name"),
            sa.CheckConstraint(
                "environment IN ('production','staging','development')",
                name="ck_signing_keys_environment",
            ),
        )

    # 2. roles — capability reference table (seeded in 0005).
    if "roles" not in existing_tables:
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("key", sa.String(32), nullable=False),
            sa.Column("plane", sa.String(16), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("key", name="uq_roles_key"),
            sa.CheckConstraint("plane IN ('learner','staff')", name="ck_roles_plane"),
        )

    # 3. user_roles — many-to-many grants. Composite PK.
    if "user_roles" not in existing_tables:
        op.create_table(
            "user_roles",
            sa.Column("user_email", sa.String(255), nullable=False),
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("granted_by", sa.String(255), nullable=True),
            sa.ForeignKeyConstraint(["user_email"], ["users.email"], ondelete="CASCADE",
                                    name="fk_user_roles_user"),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT",
                                    name="fk_user_roles_role"),
            sa.PrimaryKeyConstraint("user_email", "role_id", name="pk_user_roles"),
        )
        op.create_index("idx_user_roles_user", "user_roles", ["user_email"])

    # 4. quiz_sessions — replaces _active_quizzes dict. Wired in 2b.
    if "quiz_sessions" not in existing_tables:
        op.create_table(
            "quiz_sessions",
            sa.Column("quiz_id", sa.String(64), primary_key=True),
            sa.Column("user_email", sa.String(255), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("difficulty", sa.String(32), nullable=False),
            sa.Column("server_answers", JSONB, nullable=False),
            sa.Column("full_questions", JSONB, nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_quiz_sessions_user_expires", "quiz_sessions",
                        ["user_email", "expires_at"])

    # 5. app_config — Directus-editable runtime tunables (no `is_secret`, per C-20).
    if "app_config" not in existing_tables:
        op.create_table(
            "app_config",
            sa.Column("key", sa.String(128), primary_key=True),
            sa.Column("value", JSONB, nullable=False),
            sa.Column("value_type", sa.String(16), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.CheckConstraint(
                "value_type IN ('string','int','float','bool','json')",
                name="ck_app_config_value_type",
            ),
        )

    # 6. auth_audit — append-only. Created BEFORE the authz split (2b/0006) so
    #    the split can write `role.grant` rows for its backfill.
    if "auth_audit" not in existing_tables:
        op.create_table(
            "auth_audit",
            sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                      primary_key=True, autoincrement=True),
            sa.Column("actor_email", sa.String(255), nullable=True),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("target_email", sa.String(255), nullable=True),
            sa.Column("target_role", sa.String(32), nullable=True),
            sa.Column("before", JSONB, nullable=True),
            sa.Column("after", JSONB, nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
        )
        op.create_index("idx_auth_audit_actor", "auth_audit", ["actor_email", "occurred_at"])
        op.create_index("idx_auth_audit_action", "auth_audit", ["action", "occurred_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "auth_audit" in existing_tables:
        op.drop_index("idx_auth_audit_action", table_name="auth_audit")
        op.drop_index("idx_auth_audit_actor", table_name="auth_audit")
        op.drop_table("auth_audit")
    if "app_config" in existing_tables:
        op.drop_table("app_config")
    if "quiz_sessions" in existing_tables:
        op.drop_index("idx_quiz_sessions_user_expires", table_name="quiz_sessions")
        op.drop_table("quiz_sessions")
    if "user_roles" in existing_tables:
        op.drop_index("idx_user_roles_user", table_name="user_roles")
        op.drop_table("user_roles")
    if "roles" in existing_tables:
        op.drop_table("roles")
    if "signing_keys" in existing_tables:
        op.drop_table("signing_keys")
