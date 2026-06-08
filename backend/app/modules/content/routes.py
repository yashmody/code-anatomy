"""Content routes — course framework + chapters + framework-explainer.

Mounted under ``/api/course`` by main.py so paths register as
``/api/course/framework``, ``/api/course/chapters/{filename}``, etc.

Each GET read is memoised in the process-wide ``AppCache`` (core/cache.py) so a
repeat request is served from memory instead of a fresh IO round-trip. The cache
keys live under the same collection prefixes used elsewhere in the codebase:
``frameworks:`` for the framework and its explainer, and ``course_chapters:``
for the chapter list and per-chapter detail. Missing content raises 404 *inside*
the loader so the not-found state is never cached.

Feature flag — COURSE_SOURCE
-----------------------------
Set the ``COURSE_SOURCE`` environment variable (or ``course_source`` in .env) to
control the data source:

  ``files``  (default, ARCH-2 target): serve from the versioned JSON tree at
             ``content/source/course/``. The file-based loaders are in
             ``file_loaders.py``.
  ``db``     : retain the Postgres path via ``storage.py``. Keep this path alive
             for instant rollback until ARCH-4 drops the tables.

The cache-key namespace is identical for both sources so a flag flip + process
restart flushes the cache cleanly (the process-wide MemoryBackend is discarded on
restart; a Redis backend's existing keys expire on their normal TTL).

Cache-key correctness under the flag
-------------------------------------
Both paths use the same keys (``frameworks:framework``, ``course_chapters:__list__``,
etc.).  Changing COURSE_SOURCE without restarting the process would serve stale
data from the old source until the TTL expires.  The recommended flip procedure
is: set the flag, restart the app (uvicorn workers=1 so the cache flushes
atomically).  There is no cross-source cache poisoning risk in the steady state
because the app reads one source per lifetime.

Draft/archived chapters
-----------------------
The file-based path filters chapters by ``status``; only ``"published"`` chapters
(or chapters with no status field — treated as published) are visible to anonymous
callers via this API.  The DB path does NOT currently filter by status because the
``course_chapters`` table has no status column — that column was never added to the
DB model because status lives in the file JSON.  The DB path is the legacy path
kept only for rollback; the file path is the designed, correct path.
"""
import json

from fastapi import APIRouter, HTTPException, Response

from app.core import config
from app.core.cache import cache
from app.modules.content import storage as content_storage
from app.modules.content import file_loaders


router = APIRouter()

# Course content is editor-driven and changes rarely; a 5-minute browser cache
# with a 1-minute stale-while-revalidate grace pairs with the server-side cache
# below. Declared once so every content route stays consistent.
_CONTENT_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=60"


def _using_files() -> bool:
    """True iff COURSE_SOURCE=files (the ARCH-2 default)."""
    return config.settings.course_source == "files"


# ── /framework ────────────────────────────────────────────────────────────────


@router.get("/framework")
async def get_course_framework(response: Response):
    """Retrieve the overall framework hierarchy.

    Source: content/source/course/framework.json (COURSE_SOURCE=files, default)
            or PostgreSQL frameworks table (COURSE_SOURCE=db).
    """

    def _load():
        if _using_files():
            fw = file_loaders.get_framework()
        else:
            fw = content_storage.get_framework()
        if not fw:
            # Raised inside the loader → get_or_compute never caches the 404,
            # so a later file update or ETL re-seed is picked up on the next request.
            raise HTTPException(status_code=404, detail="Framework not found")
        return fw

    fw = cache.get_or_compute(
        "frameworks:framework",
        ttl=config.settings.cache_ttl_framework,
        loader=_load,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return fw


# ── /chapters (list) ──────────────────────────────────────────────────────────


@router.get("/chapters")
async def get_course_chapters(response: Response):
    """Retrieve the ordered list of all published course chapters.

    Response shape: ``{"chapters": [{"filename": str, "ring": str, "title": str}]}``

    This is the load-bearing endpoint for the SPA's ``fetchSectionFiles`` (ARCH-1).
    The SPA reads ``data.chapters[].filename``; the ring and title are used by
    manual.js when building the contents panel.

    Draft/archived chapters are excluded when COURSE_SOURCE=files. When
    COURSE_SOURCE=db, no status filter is applied (the DB row has no status
    column; all rows are returned as-is for rollback compatibility).
    """
    def _load():
        if _using_files():
            return file_loaders.get_all_chapters()
        return content_storage.get_all_chapters()

    # Cached under the ``course_chapters:`` prefix so invalidation drops the
    # list on any bulk chapter change (the Directus webhook uses this prefix;
    # with COURSE_SOURCE=files the webhook is inert but the key still works).
    chapters = cache.get_or_compute(
        "course_chapters:__list__",
        ttl=config.settings.cache_ttl_framework,
        loader=_load,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return {
        "chapters": [
            {"filename": c["filename"], "ring": c["ring"], "title": c["title"]}
            for c in chapters
        ]
    }


# ── /chapters/{filename} ──────────────────────────────────────────────────────


@router.get("/chapters/{filename}")
async def get_course_chapter(filename: str, response: Response):
    """Retrieve the full content JSON for a single published chapter.

    Returns the raw chapter dict (the ``content`` key of the storage envelope)
    to match the pre-ARCH-2 response shape: the SPA receives the full chapter
    JSON directly, not wrapped in an envelope.

    Draft/archived chapters return 404 (same as missing chapters).
    """

    def _load():
        if _using_files():
            chapter = file_loaders.get_chapter(filename)
        else:
            chapter = content_storage.get_chapter(filename)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found")
        return chapter

    # Per-filename key matches the cache invalidation pattern used by the
    # Directus webhook (``course_chapters:<id>`` where id == filename).
    chapter = cache.get_or_compute(
        f"course_chapters:{filename}",
        ttl=config.settings.cache_ttl_framework,
        loader=_load,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return chapter["content"]


# ── /framework-explainer ──────────────────────────────────────────────────────


@router.get("/framework-explainer")
async def get_framework_explainer(response: Response):
    """Serve the static framing JSON (masthead, Part banners, CODE/CODER
    outer/inner wrappers, node-blocks, #nest, Review, Watch).

    Source order when COURSE_SOURCE=files (default):
      1. Filesystem  (content/source/course/framework-explainer.json)

    Source order when COURSE_SOURCE=db (rollback path):
      1. PostgreSQL  (frameworks table, id='explainer')  — seeded by the ETL
      2. Filesystem  (framework-explainer.json)          — fallback for partial
         deploys where the ETL has not run yet.
    """

    def _load():
        if _using_files():
            expl = file_loaders.get_framework_explainer()
            if expl:
                return expl
            raise HTTPException(
                status_code=404,
                detail="framework-explainer.json not found on disk.",
            )

        # DB path (rollback) — retains the original two-step fallback.
        expl = content_storage.get_framework_explainer()
        if expl:
            return expl

        # Fallback to on-disk JSON. BASE_DIR is the backend root, so
        # BASE_DIR.parent is the repo root.
        explainer_path = (
            config.BASE_DIR.parent
            / "content"
            / "source"
            / "course"
            / "framework-explainer.json"
        )
        if explainer_path.exists():
            try:
                with open(explainer_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read framework-explainer.json: {exc}",
                ) from exc

        raise HTTPException(
            status_code=404,
            detail="framework-explainer not found in DB or filesystem. Run the ETL migration.",
        )

    # Same ``frameworks:`` namespace as the framework itself (id='explainer' in
    # the same table) — one webhook event clears both.
    expl = cache.get_or_compute(
        "frameworks:explainer",
        ttl=config.settings.cache_ttl_framework,
        loader=_load,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return expl
