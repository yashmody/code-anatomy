#!/usr/bin/env python3
"""db-inventory.py — emit a per-table row-count report for q0.db.

Used by the v2 parity gate (`docs/architecture/v2/02-parity-method.md` §2.1
step 3). Idempotent and read-only.

Run from anywhere:

    cd quiz-certification && .venv/bin/python \
        ../tests/baseline/scripts/db-inventory.py

Output (deterministic, diffable):

    table=attempts          rows=4
    table=course_chapters   rows=0
    ...
    cert=CCA-F-20260605-E79E74AB  user=yash@deptagency.com  signed=1
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def find_db() -> Path:
    """Resolve q0.db whether we were invoked from the repo root or from
    quiz-certification/."""
    candidates = [
        Path.cwd() / "q0.db",
        Path.cwd() / "quiz-certification" / "q0.db",
        Path(__file__).resolve().parent.parent.parent.parent
        / "quiz-certification"
        / "q0.db",
    ]
    for c in candidates:
        if c.is_file():
            return c
    print("ERROR: could not find quiz-certification/q0.db", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    db = find_db()
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()

    tables = [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    for t in tables:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        # Pad the name so the report stays tidy regardless of table name length.
        print(f"table={t:20s} rows={n}")

    print()
    # Cert sentinel: every signed cert must keep verifying after migrations.
    rows = list(
        cur.execute(
            "SELECT cert_id, user_email, signature IS NOT NULL "
            "FROM attempts "
            "WHERE cert_id IS NOT NULL "
            "ORDER BY submitted_at"
        )
    )
    if not rows:
        print("# no certificates issued yet")
    else:
        for cert_id, email, signed in rows:
            print(f"cert={cert_id}  user={email}  signed={int(bool(signed))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
