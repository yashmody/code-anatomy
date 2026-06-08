"""File-based content loaders for ARCH-2 (COURSE_SOURCE=files).

Reads the four course artefacts straight from the versioned JSON tree at
``content/source/course/`` instead of going to Postgres. The public surface
mirrors ``storage.py`` exactly so ``routes.py`` can call either without
branching outside the router entry-point.

Public API
----------
``get_framework()``          → dict | None
``get_framework_explainer()`` → dict | None
``get_chapter(filename)``    → {"filename", "ring", "title", "content"} | None
``get_all_chapters()``       → list[{"filename", "ring", "title", "content"}]
                               Only published chapters are returned (status filter).

Status filter
-------------
The ``status`` field in a chapter JSON may be "draft", "review", "published", or
"archived" (per course.schema.json). When the field is absent we treat it as
"published" (every existing chapter on disk carries an explicit status of
"published" per the Phase-0 reconciliation). Only chapters with status
"published" are served via ``get_all_chapters`` and ``get_chapter`` — drafts and
archived chapters are invisible to anonymous callers.

DEVOPS NOTE: the Apache static-file alias that allows content/source/course/ to
be served as static files has NOT been hardened against direct HTTP access in
this phase. That hardening (restricting the alias so only the FastAPI process
can read those files, not a direct HTTP request) is a separate devops ticket
(ARCH-2 follow-on). Until that ticket lands, a caller who knows the file path
could bypass this status filter by fetching the JSON directly. The filter here
governs what the /api/course/* endpoints expose; it does not govern the static
alias.

Ring derivation
---------------
``ring_from_address(addr)`` reuses the same one-liner as validate.py (AC1 in
ARCH-1): the ring is the first dot-segment of the ``frameworkAddress`` field
inside each chapter JSON.  Examples:
  "anatomy.m00"  → "anatomy"
  "code.c"       → "code"
  "adobe.aa"     → "adobe"

Ordering
--------
``get_all_chapters`` returns chapters sorted by filename (ASCII order). The SPA's
``fetchSectionFiles`` maps over filenames only; ``manual.js`` then re-sorts by the
framework.json order, so the on-wire order is irrelevant for rendering. Sorting
by filename gives a deterministic, reproducible order that matches what
``sorted(glob(...))`` produces in the validate.py CI gate.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import BASE_DIR

logger = logging.getLogger("app.modules.content.file_loaders")

# The repo root is BASE_DIR.parent (backend/ → repo/).
# All content files live under content/source/course/ relative to the repo root.
_COURSE_DIR: Path = BASE_DIR.parent / "content" / "source" / "course"
_SECTIONS_DIR: Path = _COURSE_DIR / "sections"
_FRAMEWORK_PATH: Path = _COURSE_DIR / "framework.json"
_EXPLAINER_PATH: Path = _COURSE_DIR / "framework-explainer.json"

# The only status value that is visible to anonymous callers.
_PUBLISHED_STATUS = "published"


# ── Helpers ───────────────────────────────────────────────────────────────────


def ring_from_address(addr: str) -> str:
    """Return the ring prefix from a frameworkAddress.

    Reuses the identical one-liner defined in validate.py (ARCH-1 AC1) so the
    derivation is consistent across the whole content pipeline.

    >>> ring_from_address("anatomy.m00")
    'anatomy'
    >>> ring_from_address("code.c")
    'code'
    """
    return addr.split(".")[0] if addr else ""


def _is_published(doc: dict) -> bool:
    """True iff the chapter should be visible to anonymous callers.

    Missing status is treated as published (per Phase-0 evidence: every chapter
    on disk has an explicit ``"status": "published"``; the absent-→-published
    rule is a defensive forward-compat measure for any future chapter that is
    written without a status field before the schema gate catches it).
    """
    status = doc.get("status")
    return status is None or status == _PUBLISHED_STATUS


def _read_json(path: Path) -> Optional[dict]:
    """Read and parse a JSON file; return None on any IO or parse error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # ValueError covers json.JSONDecodeError (a subclass) AND the
        # "embedded null byte" ValueError that path.read_text() raises for a
        # %00-laced filename — so an anonymous null-byte request 404s, not 500s
        # (rv RV finding, ARCH-2). The route maps None -> 404.
        logger.warning("file_loaders: failed to read %s: %s", path, exc)
        return None


def _chapter_from_doc(filename: str, doc: dict) -> Dict:
    """Convert a chapter JSON dict to the storage-compatible envelope.

    Matches the dict shape that storage.get_chapter returns:
      {"filename": str, "ring": str, "title": str, "content": dict}
    """
    addr = doc.get("frameworkAddress", "")
    return {
        "filename": filename,
        "ring": ring_from_address(addr),
        "title": doc.get("title", ""),
        "content": doc,
    }


# ── Framework ─────────────────────────────────────────────────────────────────


def get_framework() -> Optional[Dict]:
    """Read framework.json from disk and return its parsed content.

    Returns None if the file is missing or unparseable (the caller raises 404).
    """
    return _read_json(_FRAMEWORK_PATH)


# ── Framework-explainer ───────────────────────────────────────────────────────


def get_framework_explainer() -> Optional[Dict]:
    """Read framework-explainer.json from disk.

    Returns None if the file is missing or unparseable (the caller raises 404).
    """
    return _read_json(_EXPLAINER_PATH)


# ── Chapters ──────────────────────────────────────────────────────────────────


def get_chapter(filename: str) -> Optional[Dict]:
    """Return the storage-compatible chapter envelope for a single chapter.

    ``filename`` must be a bare filename like "anatomy-m00.json" — no path
    component is allowed (the loader sanitises the input by restricting to the
    sections/ directory, preventing directory traversal).

    Returns None if the file does not exist, fails to parse, or its status is
    not "published".
    """
    # Sanitise: accept bare filenames only. Strip any path component the caller
    # might have injected (e.g. "../secrets") so we never escape _SECTIONS_DIR.
    safe_name = Path(filename).name
    path = _SECTIONS_DIR / safe_name

    doc = _read_json(path)
    if doc is None:
        return None
    if not _is_published(doc):
        # Treat as not-found; the caller raises 404. Avoid leaking status in
        # the 404 detail — the route's generic "Chapter not found" message is
        # sufficient.
        logger.debug(
            "file_loaders: chapter %s has status=%r; returning None (not published)",
            filename,
            doc.get("status"),
        )
        return None
    return _chapter_from_doc(safe_name, doc)


def get_all_chapters() -> List[Dict]:
    """Return the storage-compatible envelope list for all published chapters.

    Only files whose status is "published" (or missing) are included.
    Sorted by filename (ASCII order) for a deterministic, reproducible response.

    This is the load-bearing loader for /api/course/chapters (the chapter list
    that ARCH-1's fetchSectionFiles depends on). The SPA reads
    ``data.chapters[].filename`` from that response; manual.js re-sorts the
    list by framework order on the client side, so the on-wire order only needs
    to be stable.
    """
    if not _SECTIONS_DIR.exists():
        logger.error(
            "file_loaders: sections directory missing: %s", _SECTIONS_DIR
        )
        return []

    chapters: List[Dict] = []
    for path in sorted(_SECTIONS_DIR.glob("*.json")):
        doc = _read_json(path)
        if doc is None:
            continue
        if not _is_published(doc):
            logger.debug(
                "file_loaders: skipping %s (status=%r)",
                path.name,
                doc.get("status"),
            )
            continue
        chapters.append(_chapter_from_doc(path.name, doc))
    return chapters
