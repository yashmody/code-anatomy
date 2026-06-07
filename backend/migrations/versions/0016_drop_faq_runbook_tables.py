"""0016_drop_faq_runbook_tables — drop the FAQ + runbook DB tables

FAQs and runbooks moved to STATIC content under resources/ (see
docs/CONTENT-AUTHORING.md). Their DB/API layers were removed pre-cutover, so the
backing tables are now unused. Idempotent — no-op if already absent.

Drops: faq_items, faq_categories, runbooks. (The runbook Excel parser is kept;
runbooks are now authored via the template + scripts/render_runbook.py → static.)

Revision ID: 0016_drop_faq_runbook_tables
Revises: 0015_drop_techflix_episodes
Create Date: 2026-06-07
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_drop_faq_runbook_tables"
down_revision: Union[str, Sequence[str], None] = "0015_drop_techflix_episodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    # faq_items first (FK → faq_categories), then faq_categories, then runbooks.
    for t in ("faq_items", "faq_categories", "runbooks"):
        if t in existing:
            op.drop_table(t)


def downgrade() -> None:
    # One-way drop. These features are static now; recreate from migrations
    # 0010 (faq) / 0012 (runbooks) if ever needed by downgrading past them.
    pass
