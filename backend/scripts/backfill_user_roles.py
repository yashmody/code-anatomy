"""backfill_user_roles — split legacy users.role into persona + user_roles.

Phase 2b one-shot. Run AFTER `alembic upgrade head` and after
`seed_roles.py` so the six role rows exist.

    cd backend && .venv/bin/python -m scripts.backfill_user_roles

Mapping per 04-authz-model §5.2 — the hard rules are LOCKED, do not relax:

    | legacy users.role                                | persona   | user_roles set                  |
    |--------------------------------------------------|-----------|---------------------------------|
    | pm/ba/qa/sales/design/devops/coder/architect/other | <same>    | {learner}                       |
    | QuizManager                                      | (untouched) | {learner}  — NEVER admin       |
    | Moderator                                        | (untouched) | {learner}  — NEVER moderator   |
    | FeedCreator                                      | (untouched) | {learner}  — NEVER contributor |
    | User                                             | (untouched) | {learner}                       |
    | NULL / empty                                     | (untouched) | {learner}                       |

Why the stricter rule for `QuizManager` / `Moderator` / `FeedCreator`:
the 04 doc proves these are dev-mode artefacts (every dev login wrote
`QuizManager`; the other two were never written by any code path). Auto-
promoting them re-introduces over-privilege. Real admins are granted
deliberately via `ADMIN_EMAILS` (`seed_roles.py`).

Idempotent: re-running against rows already split is a no-op.

Audit: every demote writes an `auth_audit` row with
`action='migration.role.demote'`.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from typing import Dict, List, Optional

from sqlalchemy import select

from app.core import users as core_users
from app.core.db import get_session
from app.core.models import AuthAudit, Role, User, UserRole


PERSONAS = {"pm", "ba", "qa", "sales", "design", "devops", "coder", "architect", "other"}
LEGACY_CAPABILITIES = {"QuizManager", "Moderator", "FeedCreator", "User"}


def _role_id(s, key: str) -> int:
    rid = s.execute(select(Role.id).where(Role.key == key)).scalar_one_or_none()
    if rid is None:
        raise RuntimeError(
            f"Role '{key}' missing from roles table. Run scripts/seed_roles.py first."
        )
    return rid


def _has_user_role(s, email: str, role_id: int) -> bool:
    return s.execute(
        select(UserRole.role_id)
        .where(UserRole.user_email == email)
        .where(UserRole.role_id == role_id)
    ).first() is not None


def backfill() -> Dict[str, object]:
    counts = Counter()
    report_rows: List[Dict[str, Optional[str]]] = []

    with get_session() as s:
        learner_id = _role_id(s, "learner")

        for u in s.query(User).all():
            email = u.email
            legacy = u.role
            persona_before = u.persona
            persona_after = persona_before

            # 1. Persona split — only mutate when legacy holds a known persona
            #    AND persona is unset. Don't clobber a deliberately-set persona.
            if legacy in PERSONAS and not persona_before:
                u.persona = legacy
                persona_after = legacy
                counts["persona_set"] += 1

            # 2. Ensure learner floor for everyone.
            if not _has_user_role(s, email, learner_id):
                s.add(UserRole(user_email=email, role_id=learner_id,
                               granted_by="system:backfill_user_roles"))
                counts["learner_added"] += 1

            # 3. Track demotes for the report (action='migration.role.demote').
            if legacy in LEGACY_CAPABILITIES:
                s.add(AuthAudit(
                    actor_email="system:backfill_user_roles",
                    action="migration.role.demote",
                    target_email=email,
                    target_role=legacy,
                    before={"role": legacy},
                    after={"roles": ["learner"]},
                ))
                counts[f"demote_{legacy}"] += 1
                report_rows.append({
                    "email": email,
                    "legacy_role": legacy,
                    "persona_before": persona_before,
                    "persona_after": persona_after,
                    "roles_after": "learner",
                })
            elif legacy in PERSONAS:
                report_rows.append({
                    "email": email,
                    "legacy_role": legacy,
                    "persona_before": persona_before,
                    "persona_after": persona_after,
                    "roles_after": "learner",
                })
            else:
                report_rows.append({
                    "email": email,
                    "legacy_role": legacy or "",
                    "persona_before": persona_before,
                    "persona_after": persona_after,
                    "roles_after": "learner",
                })

            counts["users_touched"] += 1

        s.commit()

    return {"counts": dict(counts), "report_rows": report_rows}


def write_csv(report_rows: List[Dict[str, Optional[str]]], path: str) -> None:
    if not report_rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["email", "legacy_role", "persona_before", "persona_after", "roles_after"],
        )
        w.writeheader()
        for row in report_rows:
            w.writerow({k: ("" if v is None else v) for k, v in row.items()})


def main() -> int:
    result = backfill()
    counts: Dict[str, int] = result["counts"]  # type: ignore[assignment]
    rows: List[Dict[str, Optional[str]]] = result["report_rows"]  # type: ignore[assignment]

    print("[backfill_user_roles] done.")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")

    out = "backfill_user_roles.csv"
    write_csv(rows, out)
    print(f"[backfill_user_roles] wrote report -> {out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
