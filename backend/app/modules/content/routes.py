"""Content routes — course framework + chapters + framework-explainer.

Mounted under `/api/course` by main.py so paths register as
`/api/course/framework`, `/api/course/chapters/{filename}`, etc.

The framework-explainer endpoint retains the filesystem fallback that the
legacy main.py shipped: DB first, then `content-architecture/.../framework-
explainer.json` on disk. Slice C may move the fallback path to
`content/source/...` later — for now the legacy location is preserved so
this slice doesn't depend on Slice C landing.
"""
import json

from fastapi import APIRouter, HTTPException

from app.core import config
from app.modules.content import storage as content_storage


router = APIRouter()


@router.get("/framework")
async def get_course_framework():
    """Retrieve the overall framework hierarchy from PostgreSQL."""
    fw = content_storage.get_framework()
    if not fw:
        raise HTTPException(status_code=404, detail="Framework not found")
    return fw


@router.get("/chapters")
async def get_course_chapters():
    """Retrieve list of all course chapters from PostgreSQL."""
    chapters = content_storage.get_all_chapters()
    return {
        "chapters": [
            {"filename": c["filename"], "ring": c["ring"], "title": c["title"]}
            for c in chapters
        ]
    }


@router.get("/chapters/{filename}")
async def get_course_chapter(filename: str):
    """Retrieve content of a specific course chapter by filename from PostgreSQL."""
    chapter = content_storage.get_chapter(filename)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter["content"]


@router.get("/framework-explainer")
async def get_framework_explainer():
    """Serve the static framing JSON (masthead, Part banners, CODE/CODER
    outer/inner wrappers, node-blocks, #nest, Review, Watch).

    Source order:
      1. PostgreSQL  (frameworks table, id='explainer')  — seeded by the ETL
      2. Filesystem  (content/source/course/framework-explainer.json)
         — fallback for partial deploys where the ETL hasn't run yet.
    """
    # 1. Try the DB
    expl = content_storage.get_framework_explainer()
    if expl:
        return expl

    # 2. Fallback to the on-disk JSON. BASE_DIR is the backend root, so
    # BASE_DIR.parent is the repo root and the seed lives at
    # content/source/course/framework-explainer.json (Slice C moved it
    # here from the v1 content-architecture/ tree).
    explainer_path = (
        config.BASE_DIR.parent / "content" / "source" / "course" / "framework-explainer.json"
    )
    if explainer_path.exists():
        try:
            with open(explainer_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read framework-explainer.json: {e}",
            )

    raise HTTPException(
        status_code=404,
        detail="framework-explainer not found in DB or filesystem. Run the ETL migration.",
    )
