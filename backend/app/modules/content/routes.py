"""Content routes — course framework + chapters + framework-explainer.

Mounted under `/api/course` by main.py so paths register as
`/api/course/framework`, `/api/course/chapters/{filename}`, etc.

Each GET read is memoised in the process-wide `AppCache` (core/cache.py) so a
repeat request is served from memory instead of a fresh Postgres round-trip.
The cache keys live under the same collection prefixes the Directus webhook
invalidates (`modules/cms/routes.py`): `frameworks:` for the framework and its
explainer (stored in the `frameworks` table with ids 'framework'/'explainer'),
and `course_chapters:` for the chapter list and per-chapter detail. An editor
publish therefore drops exactly the affected entries; absent any event the
`cache_ttl_framework` window (default 15 min) bounds staleness. Missing rows
raise 404 *inside* the loader so the not-found state is never cached.

The framework-explainer endpoint retains the filesystem fallback that the
legacy main.py shipped: DB first, then `content/source/course/framework-
explainer.json` on disk.
"""
import json

from fastapi import APIRouter, HTTPException, Response

from app.core import config
from app.core.cache import cache
from app.modules.content import storage as content_storage


router = APIRouter()

# Course content is editor-driven and changes rarely; a 5-minute browser cache
# with a 1-minute stale-while-revalidate grace pairs with the server-side cache
# below. Declared once so every content route stays consistent.
_CONTENT_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=60"


@router.get("/framework")
async def get_course_framework(response: Response):
    """Retrieve the overall framework hierarchy from PostgreSQL."""

    def _load():
        fw = content_storage.get_framework()
        if not fw:
            # Raised inside the loader → get_or_compute never caches the 404,
            # so a later ETL re-seed is picked up on the next request.
            raise HTTPException(status_code=404, detail="Framework not found")
        return fw

    fw = cache.get_or_compute(
        "frameworks:framework",
        ttl=config.settings.cache_ttl_framework,
        loader=_load,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return fw


@router.get("/chapters")
async def get_course_chapters(response: Response):
    """Retrieve list of all course chapters from PostgreSQL."""
    # Cached under the `course_chapters:` prefix so the webhook's collection-wide
    # invalidation drops the list on any bulk chapter change.
    chapters = cache.get_or_compute(
        "course_chapters:__list__",
        ttl=config.settings.cache_ttl_framework,
        loader=content_storage.get_all_chapters,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return {
        "chapters": [
            {"filename": c["filename"], "ring": c["ring"], "title": c["title"]}
            for c in chapters
        ]
    }


@router.get("/chapters/{filename}")
async def get_course_chapter(filename: str, response: Response):
    """Retrieve content of a specific course chapter by filename from PostgreSQL."""

    def _load():
        chapter = content_storage.get_chapter(filename)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found")
        return chapter

    # Per-id key matches the webhook's `course_chapters:<id>` invalidation
    # (id == filename), so editing one chapter drops exactly that entry.
    chapter = cache.get_or_compute(
        f"course_chapters:{filename}",
        ttl=config.settings.cache_ttl_framework,
        loader=_load,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return chapter["content"]


@router.get("/framework-explainer")
async def get_framework_explainer(response: Response):
    """Serve the static framing JSON (masthead, Part banners, CODE/CODER
    outer/inner wrappers, node-blocks, #nest, Review, Watch).

    Source order:
      1. PostgreSQL  (frameworks table, id='explainer')  — seeded by the ETL
      2. Filesystem  (content/source/course/framework-explainer.json)
         — fallback for partial deploys where the ETL hasn't run yet.
    """

    def _load():
        # 1. Try the DB
        expl = content_storage.get_framework_explainer()
        if expl:
            return expl

        # 2. Fallback to the on-disk JSON. BASE_DIR is the backend root, so
        # BASE_DIR.parent is the repo root and the seed lives at
        # content/source/course/framework-explainer.json.
        explainer_path = (
            config.BASE_DIR.parent / "content" / "source" / "course" / "framework-explainer.json"
        )
        if explainer_path.exists():
            try:
                with open(explainer_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                # 500 raised inside the loader → not cached; a transient read
                # error won't poison the next request.
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read framework-explainer.json: {e}",
                )

        raise HTTPException(
            status_code=404,
            detail="framework-explainer not found in DB or filesystem. Run the ETL migration.",
        )

    # Same `frameworks:` namespace as the framework itself (id='explainer' in
    # the same table) — one webhook event clears both.
    expl = cache.get_or_compute(
        "frameworks:explainer",
        ttl=config.settings.cache_ttl_framework,
        loader=_load,
    )
    response.headers["Cache-Control"] = _CONTENT_CACHE_CONTROL
    return expl
