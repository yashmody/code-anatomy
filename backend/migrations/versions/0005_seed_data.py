"""phase-2a seed data — roles, legacy-prod signing key, attempts backfill

Revision ID: 0005_seed_data
Revises: 0004_new_columns
Create Date: 2026-06-06

CRITICAL: the attempts.signing_key_id backfill is what keeps the
already-issued real cert (CCA-F-20260605-E79E74AB) verifying after Phase 2c
flips verify to read by signing_key_id. The legacy-prod row's env_var_name
is CERT_HMAC_LEGACY; the operator seeds that env var with the current
SECRET_KEY value at cutover (documented in migrations/README.md).

users.role is NOT migrated here. Per the locked decision in 03 §3 step 5,
the authz split owns that backfill and the QuizManager → {learner} rule is
enforced in 2b (C-01) — never auto-grant admin via migration.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_seed_data"
down_revision: Union[str, Sequence[str], None] = "0004_new_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Six capability roles per 04-authz-model.md / open decision 1.
ROLES = [
    ("learner",          "learner", "Default plane; every authenticated user."),
    ("feed_contributor", "learner", "May post UGC feed items and propose UGC questions."),
    ("content_author",   "staff",   "Authors official course content and questions via Directus."),
    ("quiz_admin",       "staff",   "Manages quiz bank, scoring, and pass-mark configuration."),
    ("feed_moderator",   "staff",   "Reviews flagged feed items and enforces moderation policy."),
    ("platform_admin",   "staff",   "Grants/revokes roles and edits platform configuration."),
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Seed roles. Skip rows that already exist (idempotent re-run).
    roles_t = sa.table(
        "roles",
        sa.column("key", sa.String),
        sa.column("plane", sa.String),
        sa.column("description", sa.Text),
    )
    existing = {r[0] for r in bind.execute(sa.text("SELECT key FROM roles")).fetchall()}
    to_insert = [
        {"key": k, "plane": p, "description": d}
        for (k, p, d) in ROLES
        if k not in existing
    ]
    if to_insert:
        op.bulk_insert(roles_t, to_insert)

    # 2. Seed the legacy-prod signing_keys row. Idempotent.
    existing_keys = bind.execute(
        sa.text("SELECT name FROM signing_keys WHERE name = 'legacy-prod'")
    ).fetchone()
    if not existing_keys:
        op.execute(
            sa.text(
                "INSERT INTO signing_keys "
                "(name, environment, env_var_name, is_active, can_verify, "
                " verify_until, notes) "
                "VALUES ('legacy-prod', 'production', 'CERT_HMAC_LEGACY', "
                "        :is_active, :can_verify, NULL, :notes)"
            ).bindparams(
                is_active=True,
                can_verify=True,
                notes="Pre-v2 signing key. Material lives in env var CERT_HMAC_LEGACY "
                      "(operator seeds with the existing SECRET_KEY value at cutover).",
            )
        )

    # 3. Backfill attempts.signing_key_id for every row that doesn't have one.
    #    Every existing cert points at legacy-prod after this runs.
    legacy_id = bind.execute(
        sa.text("SELECT id FROM signing_keys WHERE name = 'legacy-prod'")
    ).scalar()
    if legacy_id is None:
        raise RuntimeError(
            "0005_seed_data: legacy-prod signing key not found after insert — "
            "cannot backfill attempts.signing_key_id."
        )
    op.execute(
        sa.text(
            "UPDATE attempts SET signing_key_id = :kid "
            "WHERE signing_key_id IS NULL"
        ).bindparams(kid=legacy_id)
    )


def downgrade() -> None:
    # Reverse the backfill, then remove the seed rows.
    op.execute(sa.text("UPDATE attempts SET signing_key_id = NULL"))
    op.execute(sa.text("DELETE FROM signing_keys WHERE name = 'legacy-prod'"))
    op.execute(sa.text("DELETE FROM roles WHERE key IN "
                       "('learner','feed_contributor','content_author',"
                       "'quiz_admin','feed_moderator','platform_admin')"))
