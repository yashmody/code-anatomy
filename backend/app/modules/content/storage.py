"""Content storage — course chapters + framework + framework-explainer.

The frameworks table stores TWO id-keyed blobs: `framework` (the hierarchy)
and `explainer` (the static framing JSON for masthead/Parts/CODE-CODER
wrappers/etc.). Keeping both in one table is intentional — they share
shape and live/die together.
"""
from typing import Dict, List, Optional

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import CourseChapter, Framework


# ── Chapters ─────────────────────────────────────────────────────────────────

def save_chapter(filename: str, ring: str, title: str, content: Dict) -> None:
    with get_session() as s:
        chapter = s.get(CourseChapter, filename)
        if chapter:
            chapter.ring = ring
            chapter.title = title
            chapter.content = content
        else:
            chapter = CourseChapter(filename=filename, ring=ring, title=title, content=content)
            s.add(chapter)
        s.commit()


def get_chapter(filename: str) -> Optional[Dict]:
    with get_session() as s:
        chapter = s.get(CourseChapter, filename)
        if chapter:
            return {
                "filename": chapter.filename,
                "ring": chapter.ring,
                "title": chapter.title,
                "content": chapter.content
            }
        return None


def get_all_chapters() -> List[Dict]:
    with get_session() as s:
        chapters = s.scalars(select(CourseChapter)).all()
        return [
            {
                "filename": c.filename,
                "ring": c.ring,
                "title": c.title,
                "content": c.content
            }
            for c in chapters
        ]


# ── Framework ────────────────────────────────────────────────────────────────

def save_framework(data: Dict) -> None:
    with get_session() as s:
        fw = s.get(Framework, "framework")
        if fw:
            fw.data = data
        else:
            fw = Framework(id="framework", data=data)
            s.add(fw)
        s.commit()


def get_framework() -> Optional[Dict]:
    with get_session() as s:
        fw = s.get(Framework, "framework")
        return fw.data if fw else None


# ── Framework-explainer ──────────────────────────────────────────────────────
# The static framing JSON (masthead, Part banners, CODE/CODER outer/inner
# wrappers, node-blocks, #nest, Review, Watch). Stored in the same
# `frameworks` table with id='explainer' so we get one canonical place for
# all framework-shaped JSON without a new table.

def save_framework_explainer(data: Dict) -> None:
    with get_session() as s:
        fw = s.get(Framework, "explainer")
        if fw:
            fw.data = data
        else:
            fw = Framework(id="explainer", data=data)
            s.add(fw)
        s.commit()


def get_framework_explainer() -> Optional[Dict]:
    with get_session() as s:
        fw = s.get(Framework, "explainer")
        return fw.data if fw else None
