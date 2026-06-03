"""Roles + recommended quiz level.

A user picks one role at onboarding. The home page highlights the matching
level but never blocks the other one.
"""
from typing import Dict, List

# Ordered for display in the role picker
ROLES: List[Dict] = [
    {"key": "pm",        "label": "Project Manager",   "level": "beginner", "blurb": "Plans, runs, ships work. Cares about scope, risk, dates."},
    {"key": "ba",        "label": "Business Analyst",  "level": "beginner", "blurb": "Translates the ask into requirements. Owns clarity."},
    {"key": "qa",        "label": "QA / Test",         "level": "beginner", "blurb": "Test plans, regression, the safety net. Coverage > speed."},
    {"key": "sales",     "label": "Sales / Pre-sales", "level": "beginner", "blurb": "Pitches the work. Needs the vocabulary, not the implementation."},
    {"key": "design",    "label": "Designer",          "level": "beginner", "blurb": "Owns the user experience and the visual system."},
    {"key": "devops",    "label": "DevOps / Platform", "level": "advanced",     "blurb": "Owns the pipeline, the infra, and the delivery loop. Lives between code and production."},
    {"key": "coder",     "label": "Engineer / Coder",  "level": "advanced", "blurb": "Writes the code. Lives in the CODER inner ring."},
    {"key": "architect", "label": "Architect",         "level": "advanced", "blurb": "Owns the system. Trades off the cross-cutting concerns."},
    {"key": "other",     "label": "Other",             "level": "beginner", "blurb": "Pick this if nothing else fits. You can change it later."},
]

VALID_KEYS = {r["key"] for r in ROLES}


def is_valid(key: str) -> bool:
    return key in VALID_KEYS


def recommended_level(role_key: str) -> str:
    for r in ROLES:
        if r["key"] == role_key:
            return r["level"]
    return "beginner"


def label_for(role_key: str) -> str:
    for r in ROLES:
        if r["key"] == role_key:
            return r["label"]
    return role_key or "—"
