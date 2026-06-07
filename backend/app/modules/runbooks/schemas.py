"""Pydantic schemas for the runbooks module.

The nested structure mirrors the Excel template layout:
  Phases → Sections → Tasks (each task has steps, checklist items, links).

All fields are optional at the individual item level so partial runbooks
(e.g. a skeleton with only phase headings) are valid during drafting.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, field_validator


# ── Task-level primitives ───────────────────────────────────────────────────

class RunbookLink(BaseModel):
    label: str
    url: str


class RunbookTask(BaseModel):
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    tools: List[str] = []
    timing: Optional[str] = None
    steps: List[str] = []
    checklist: List[str] = []
    links: List[RunbookLink] = []
    notes: Optional[str] = None


# ── Hierarchy ───────────────────────────────────────────────────────────────

class RunbookSection(BaseModel):
    title: str
    description: Optional[str] = None
    timing: Optional[str] = None
    tasks: List[RunbookTask] = []


class RunbookPhase(BaseModel):
    title: str
    description: Optional[str] = None
    timing: Optional[str] = None
    sections: List[RunbookSection] = []


# ── Top-level ───────────────────────────────────────────────────────────────

VALID_ROLES = {"architect", "devops", "developer", "qa", "pm", "ba"}
VALID_DOMAINS = {"banking", "ecommerce", "manufacturing", "healthcare", "generic"}
VALID_TYPES = {"greenfield", "brownfield"}
VALID_STATUSES = {"draft", "published"}


class RunbookCreate(BaseModel):
    slug: str
    title: str
    role: str
    domain: str = "generic"
    type: str = "greenfield"
    description: Optional[str] = None
    status: str = "draft"
    phases: List[RunbookPhase] = []
    meta: Dict[str, Any] = {}

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        import re
        v = v.strip().lower()
        if not re.match(r"^[a-z0-9][a-z0-9\-]{1,126}$", v):
            raise ValueError("slug must be lowercase alphanumeric with hyphens, 2-127 chars")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return v

    @field_validator("domain")
    @classmethod
    def domain_valid(cls, v: str) -> str:
        v = v.strip().lower()
        # Allow any domain — VALID_DOMAINS is advisory; new domains should not break the upload.
        return v

    @field_validator("type")
    @classmethod
    def type_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_TYPES:
            raise ValueError(f"type must be one of {sorted(VALID_TYPES)}")
        return v


class RunbookSummary(BaseModel):
    """Lightweight listing — no phases tree."""
    id: int
    slug: str
    title: str
    role: str
    domain: str
    type: str
    description: Optional[str]
    status: str
    created_by: Optional[str]
    updated_at: str  # ISO-8601

    model_config = {"from_attributes": True}


class RunbookDetail(RunbookSummary):
    """Full runbook including the phases tree."""
    phases: List[RunbookPhase]
    meta: Dict[str, Any]
