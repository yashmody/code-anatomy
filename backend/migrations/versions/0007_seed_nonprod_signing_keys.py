"""phase-3 seed non-prod signing keys (Q-4)

Revision ID: 0007_seed_nonprod_signing_keys
Revises: 0006_lo_cleanup
Create Date: 2026-06-06

Seeds the development and staging signing_keys rows so non-production
environments sign and verify certificates with their OWN keys instead of
borrowing the legacy-prod material. Gate decision Q-4.

Two rows, both idempotent (guarded on the unique `name`):

  - dev-default  / development / env var CERT_HMAC_DEV
  - stg-default  / staging     / env var CERT_HMAC_STG

Both are is_active=true and can_verify=true with verify_until left NULL
(no hard expiry on a non-prod signer). The operator seeds the matching
env vars (CERT_HMAC_DEV, CERT_HMAC_STG) with freshly generated material
per environment - this migration only creates the metadata rows, never
key material.

The legacy-prod row (seeded in 0005) is the production signer and is NOT
touched here: production cert verification is unaffected, so the real-cert
canary (CCA-F-20260605-E79E74AB) continues to verify.

downgrade() removes ONLY the two rows added here, by name.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_seed_nonprod_signing_keys"
down_revision: Union[str, Sequence[str], None] = "0006_lo_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, environment, env_var_name) for the two non-prod signers.
_NONPROD_KEYS = [
    ("dev-default", "development", "CERT_HMAC_DEV"),
    ("stg-default", "staging", "CERT_HMAC_STG"),
]

_NOTES = (
    "Non-prod signer (Q-4). Material lives in env var {env_var}; the operator "
    "generates a per-environment value - never reuse the legacy-prod material."
)


def upgrade() -> None:
    bind = op.get_bind()

    for name, environment, env_var in _NONPROD_KEYS:
        # Guard on the unique name so a re-run is a clean no-op.
        exists = bind.execute(
            sa.text("SELECT 1 FROM signing_keys WHERE name = :name"),
            {"name": name},
        ).fetchone()
        if exists:
            continue

        # 03 section 2.5 declares a partial UNIQUE index on
        # signing_keys (environment) WHERE is_active - one active signer per
        # environment. On a fresh deploy these are the FIRST non-prod signers,
        # so they come up active. But if an active signer already exists for
        # this environment (e.g. a hand-seeded fixture), inserting a second
        # active row would violate that index and abort the migration. Guard
        # against it: claim the active slot only when it is empty, else insert
        # the row inactive (the operator activates it later if they want it to
        # take over). can_verify stays true either way so already-issued
        # non-prod certs keep verifying.
        active_exists = bind.execute(
            sa.text(
                "SELECT 1 FROM signing_keys "
                "WHERE environment = :environment AND is_active = true"
            ),
            {"environment": environment},
        ).fetchone()
        is_active = active_exists is None

        op.execute(
            sa.text(
                "INSERT INTO signing_keys "
                "(name, environment, env_var_name, is_active, can_verify, "
                " verify_until, notes) "
                "VALUES (:name, :environment, :env_var, :is_active, :can_verify, "
                "        NULL, :notes)"
            ).bindparams(
                name=name,
                environment=environment,
                env_var=env_var,
                is_active=is_active,
                can_verify=True,
                notes=_NOTES.format(env_var=env_var),
            )
        )


def downgrade() -> None:
    # Remove ONLY the two rows this migration added. legacy-prod is untouched.
    op.execute(
        sa.text("DELETE FROM signing_keys WHERE name IN ('dev-default', 'stg-default')")
    )
