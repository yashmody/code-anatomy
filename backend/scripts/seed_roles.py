"""seed_roles — idempotent role seed + first-admin bootstrap (Phase 2b).

Run AFTER `alembic upgrade head` lands the schema:

    cd backend && .venv/bin/python -m scripts.seed_roles

What it does:
  1. Confirms the six capability roles are present in `roles` (the Alembic
     0005_seed_data revision is the canonical seeder; this is a belt-and-
     braces re-assert so the script is safe to run on a freshly stamped DB).
  2. Calls `core.users.ensure_first_admin()` which reads the
     `ADMIN_EMAILS` env (comma-separated) and grants `platform_admin` to
     every listed email that already has a `users` row. Idempotent: re-runs
     are no-ops.

NOT a migration. Owned by Phase 2b for operator convenience. The Alembic
revisions remain the source of truth for schema + seed.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import select

from app.core import users as core_users
from app.core.db import get_session
from app.core.models import Role


# Mirror of the canonical set seeded by Alembic 0005. Re-asserted here so
# this script can self-heal a DB where someone deleted a role row.
ROLE_SEED = [
    ("learner",          "learner", "Default plane; every authenticated user."),
    ("feed_contributor", "learner", "May post UGC feed items and propose UGC questions."),
    ("content_author",   "staff",   "Authors official course content and questions via Directus."),
    ("quiz_admin",       "staff",   "Manages quiz bank, scoring, and pass-mark configuration."),
    ("feed_moderator",   "staff",   "Reviews flagged feed items and enforces moderation policy."),
    ("platform_admin",   "staff",   "Grants/revokes roles and edits platform configuration."),
]


def seed_roles() -> int:
    """Insert any missing role rows. Returns the count added."""
    added = 0
    with get_session() as s:
        existing = {k for (k,) in s.execute(select(Role.key)).all()}
        for key, plane, desc in ROLE_SEED:
            if key in existing:
                continue
            s.add(Role(key=key, plane=plane, description=desc))
            added += 1
        if added:
            s.commit()
    return added


def main() -> int:
    print("[seed_roles] reasserting role catalogue …")
    added = seed_roles()
    if added:
        print(f"[seed_roles] inserted {added} missing role row(s).")
    else:
        print("[seed_roles] all six roles present — nothing to insert.")

    print("[seed_roles] ensuring first admin(s) from ADMIN_EMAILS env …")
    raw = (os.getenv("ADMIN_EMAILS") or "").strip()
    if not raw:
        print("[seed_roles] ADMIN_EMAILS unset — skipping admin bootstrap.")
        print("           Set it (comma-separated) and re-run to grant platform_admin:")
        print("             ADMIN_EMAILS=you@deptagency.com,ops@deptagency.com")
        return 0

    granted = core_users.ensure_first_admin()
    if not granted:
        print(
            "[seed_roles] no admin grants applied — every listed email needs a "
            "users row first. Have the operator sign in once, then re-run."
        )
        return 0
    print(f"[seed_roles] platform_admin ensured for: {', '.join(granted)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
