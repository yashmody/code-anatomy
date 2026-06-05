"""Seed `app_config` with the Phase 2d defaults.

Idempotent — every row is INSERTed `ON CONFLICT DO NOTHING` (or its dialect
equivalent), so re-running this script is safe. Existing operator edits in
`app_config` are preserved untouched.

Per `docs/architecture/v2/05-config-cms.md §2.1`. The values mirror today's
hardcoded constants so a fresh DB seeded with these rows renders byte-
identically to the v1 build.

Run from `backend/`::

    .venv/bin/python -m scripts.seed_app_config

Output: a one-line summary per row (`+` inserted, `=` already present) and a
totals footer.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from sqlalchemy import insert, select

from app.core import db
from app.core.cms_client import DEFAULTS
from app.core.models import AppConfig


# ─────────────────────────────────────────────────────────────────────────────
# Per-row metadata: declared value type + the description Directus shows
# beside the field. The Tier-2 inventory in 05 §2.1 is the source of truth;
# this mapping is the wire-format for getting it into the DB.
# ─────────────────────────────────────────────────────────────────────────────


_TYPE_OF_VALUE: dict[type, str] = {
    bool: "bool",   # check bool BEFORE int because bool is a subclass of int
    int: "int",
    float: "float",
    str: "string",
}


def _value_type(value: Any) -> str:
    """Pick the value_type column for an arbitrary Python default."""
    for py_type, label in _TYPE_OF_VALUE.items():
        if isinstance(value, py_type):
            return label
    return "json"


DESCRIPTIONS: dict[str, str] = {
    "quiz.cooldown_days":
        "Days a candidate must wait between failed attempts.",
    "quiz.duration_min":
        "Time limit per quiz attempt, in minutes.",
    "quiz.questions_per_quiz":
        "Number of questions sampled per attempt.",
    "quiz.pass_mark_correct":
        ("Correct answers required to pass. "
         "Changing this affects new attempts only. Certificate verification "
         "reads the HMAC-signed score and never reads this row, so existing "
         "certificates are unaffected."),
    "media.max_video_size_mb":
        "Maximum size of a single uploaded video, in megabytes.",
    "media.max_image_size_mb":
        "Maximum size of a single uploaded image, in megabytes.",
    "media.max_video_duration_sec":
        "Maximum duration of an uploaded video, in seconds.",
    "feed.flag_threshold":
        "Number of flags before a feed item is auto-flipped to 'flagged'.",
    "feed.require_review_on_post":
        "If true, new feed items start in 'pending_review'; if false, they publish immediately.",
    "auth.allowed_domain":
        ("Email domain accepted for sign-in. Empty disables the check. "
         "Runtime authority — env ALLOWED_DOMAIN is the fallback only."),
    "mail.from_email":
        "From-address used for outbound mail.",
    "mail.from_name":
        "Display name used for outbound mail.",
    "features.llm.enabled":
        "Master switch for the LLM seam. Required-true for any per-feature flag below to fire.",
    "features.llm.quiz_explainer":
        "If true, attach an LLM-generated explanation to quiz feedback.",
    "features.llm.feed_summary":
        "If true, summarise long feed items inline.",
    "llm.provider":
        "Active LLM provider ('none', 'anthropic', 'openai'). Mirror only — env LLM_PROVIDER is authoritative.",
    "llm.model":
        "Model identifier the active provider should use (e.g. 'claude-opus-4-7').",
    "llm.temperature":
        "Sampling temperature passed to the provider.",
    "env.label":
        "Display-only environment label. Read-only — mirror of APP_ENV.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    session = db.get_session()
    inserted = 0
    existing = 0
    try:
        # Build a set of keys already present so we can present a useful
        # row-by-row report; the actual write is still individual inserts so
        # the DESCRIPTIONS column lands correctly.
        present_keys = {
            k for (k,) in session.execute(select(AppConfig.key)).all()
        }

        for key, default in DEFAULTS.items():
            if key in present_keys:
                existing += 1
                print(f"  =  {key}")
                continue

            value_type = _value_type(default)
            description = DESCRIPTIONS.get(key, "")
            session.execute(
                insert(AppConfig).values(
                    key=key,
                    value=default,
                    value_type=value_type,
                    description=description,
                )
            )
            inserted += 1
            print(f"  +  {key}  ({value_type}) = {json.dumps(default)}")

        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()

    print()
    print(f"seed_app_config: inserted={inserted}, already_present={existing}, "
          f"total_known={len(DEFAULTS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
