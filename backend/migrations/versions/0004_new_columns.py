"""phase-2a new columns — users.persona, attempts.environment, attempts.signing_key_id

Revision ID: 0004_new_columns
Revises: 0003_new_tables
Create Date: 2026-06-06

Adds non-breaking columns. No backfill here — the legacy-prod signing_keys
row and the attempts.signing_key_id backfill happen in 0005_seed_data so the
schema change and the data change can be reverted independently.

Uses batch operations for sqlite compatibility — sqlite cannot ALTER TABLE
ADD CONSTRAINT, so the FK on signing_key_id is created via batch mode.

Each column add is guarded by an inspector lookup so the migration is
idempotent (Phase 2a's `init_db().create_all()` may have already added the
attempts.environment column on a fresh boot via the updated ORM).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_new_columns"
down_revision: Union[str, Sequence[str], None] = "0003_new_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _fk_names(inspector, table: str) -> set[str]:
    return {fk.get("name") for fk in inspector.get_foreign_keys(table) if fk.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    users_cols = _column_names(inspector, "users")
    attempts_cols = _column_names(inspector, "attempts")
    attempts_fks = _fk_names(inspector, "attempts")

    # users.persona — the demoted job-family attribute (pm, ba, qa, ...).
    if "persona" not in users_cols:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("persona", sa.String(32), nullable=True))

    # attempts: add environment + signing_key_id together so the batch ALTER
    # only rebuilds the table once on sqlite.
    needs_env = "environment" not in attempts_cols
    needs_skid = "signing_key_id" not in attempts_cols
    needs_fk = "fk_attempts_signing_key" not in attempts_fks

    if needs_env or needs_skid or needs_fk:
        with op.batch_alter_table("attempts") as batch:
            if needs_env:
                batch.add_column(
                    sa.Column(
                        "environment",
                        sa.String(32),
                        nullable=False,
                        server_default="production",
                    )
                )
            if needs_skid:
                batch.add_column(sa.Column("signing_key_id", sa.Integer(), nullable=True))
            if needs_fk:
                batch.create_foreign_key(
                    "fk_attempts_signing_key",
                    "signing_keys",
                    ["signing_key_id"],
                    ["id"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    attempts_cols = _column_names(inspector, "attempts")
    attempts_fks = _fk_names(inspector, "attempts")

    if attempts_fks or "signing_key_id" in attempts_cols or "environment" in attempts_cols:
        with op.batch_alter_table("attempts") as batch:
            if "fk_attempts_signing_key" in attempts_fks:
                batch.drop_constraint("fk_attempts_signing_key", type_="foreignkey")
            if "signing_key_id" in attempts_cols:
                batch.drop_column("signing_key_id")
            if "environment" in attempts_cols:
                batch.drop_column("environment")

    if "persona" in _column_names(inspector, "users"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("persona")
