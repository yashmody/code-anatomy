"""0009_superadmin — break-glass superadmin account with TOTP 2FA

Revision ID: 0009_superadmin
Revises: 0008_directus_app_role
Create Date: 2026-06-06

Creates the `superadmin` table — a completely separate credential store from
the learner-plane `users` table and Google OAuth. One account maximum.
Provisioned via scripts/create_superadmin.py; credentials never come from git.

SECURITY: REVOKE ALL on this table from directus_app_dev (and directus_app)
so the editorial plane can never read or write superadmin credentials.

Idempotent: guarded by inspector lookup.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_superadmin"
down_revision: Union[str, Sequence[str], None] = "0008_directus_app_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "superadmin" not in existing:
        op.create_table(
            "superadmin",
            sa.Column("email",         sa.String(255), primary_key=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("totp_secret",   sa.String(64),  nullable=True),
            sa.Column("totp_enabled",  sa.Boolean(),   nullable=False, server_default="false"),
            sa.Column("created_at",    sa.DateTime(),  server_default=sa.text("NOW()")),
            sa.Column("last_login_at", sa.DateTime(),  nullable=True),
        )

    # REVOKE on both Directus roles — superadmin credentials must never be
    # reachable from the editorial plane. Guard with pg_roles existence check
    # so this is a no-op on sqlite and on clusters without these roles.
    if bind.dialect.name == "postgresql":
        for role in ("directus_app", "directus_app_dev"):
            exists = bind.execute(
                sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
                {"r": role},
            ).scalar()
            if exists:
                op.execute(f"REVOKE ALL ON superadmin FROM {role};")


def downgrade() -> None:
    op.drop_table("superadmin")
