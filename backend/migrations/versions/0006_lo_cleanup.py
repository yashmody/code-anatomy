"""phase-2a large-object cleanup trigger (Postgres-only)

Revision ID: 0006_lo_cleanup
Revises: 0005_seed_data
Create Date: 2026-06-06

Adds a BEFORE DELETE trigger on media_assets that calls lo_unlink on the
referenced pg_largeobject OID, eliminating the orphan-bytes risk
(03 §7.2). The trigger handles the happy-path delete; failed-upload
orphans are caught by the nightly `vacuumlo` cron documented in
migrations/README.md.

sqlite has no large objects, so this migration is a no-op on sqlite.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006_lo_cleanup"
down_revision: Union[str, Sequence[str], None] = "0005_seed_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION media_assets_unlink_lo() RETURNS trigger AS $$
BEGIN
    PERFORM lo_unlink(OLD.large_object_oid);
    RETURN OLD;
EXCEPTION WHEN undefined_object THEN
    -- LO was already unlinked elsewhere; don't block the metadata delete.
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""

_TRIGGER_SQL = """
CREATE TRIGGER trg_media_assets_unlink
    BEFORE DELETE ON media_assets
    FOR EACH ROW EXECUTE FUNCTION media_assets_unlink_lo();
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # sqlite has no LOs; nothing to clean up.

    op.execute(_FUNCTION_SQL)
    # CREATE TRIGGER doesn't have IF NOT EXISTS in older PG; guard manually.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_trigger "
        "WHERE tgname = 'trg_media_assets_unlink') THEN "
        + _TRIGGER_SQL.strip() +
        " END IF; END $$;"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS trg_media_assets_unlink ON media_assets")
    op.execute("DROP FUNCTION IF EXISTS media_assets_unlink_lo()")
