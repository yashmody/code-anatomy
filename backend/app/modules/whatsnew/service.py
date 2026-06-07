"""What's New service — the weekly Adobe content-refresh pipeline (Phase 1).

Flow per source:
  fetch (requests, host allow-listed, size-capped)
   → strip HTML to text
   → Claude extracts the most-recent distinct updates as JSON + DEPT-voice summary
   → dedup by synthesised source_url
   → store new items

No course writes in Phase 1. The LLM is the *extractor* as well as the
summariser, so there is no brittle HTML/CSS parsing and no extra dependency.
Everything degrades gracefully: a bad source or LLM error is logged and skipped,
never crashing the run.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from html.parser import HTMLParser
from typing import List, Optional

import requests

from app.core import config
from app.core.llm import get_provider
from app.modules.whatsnew import sources as src
from app.modules.whatsnew import storage

_FETCH_TIMEOUT = 20          # seconds
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap per page
_MAX_TEXT_CHARS = 14000       # bound LLM input
_MAX_ITEMS_PER_SOURCE = 6

_SYSTEM = (
    "You extract Adobe product release-note updates from page text and write "
    "short summaries for an audience of senior architects and engineers. "
    "Use Indian English spelling (organise, optimise, behaviour). Plain "
    "professional register — no marketing language, no hype, no AI-tells. "
    "Expand acronyms on first use. Return ONLY valid JSON, no prose around it."
)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t:
                self.parts.append(t)


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    text = " ".join(p.parts)
    return re.sub(r"\s+", " ", text)[:_MAX_TEXT_CHARS]


def _fetch_text(url: str) -> Optional[str]:
    """Fetch a page (host allow-listed, size-capped) and return stripped text."""
    if not src.host_allowed(url):
        print(f"[whatsnew] BLOCKED off-allow-list URL: {url}")
        return None
    try:
        resp = requests.get(
            url, timeout=_FETCH_TIMEOUT,
            headers={"User-Agent": "DEPT-AnatomyOfCode-ContentRefresh/1.0"},
            stream=True,
        )
        resp.raise_for_status()
        raw = resp.raw.read(_MAX_BYTES, decode_content=True) or b""
        html = raw.decode(resp.encoding or "utf-8", errors="replace")
        return _html_to_text(html)
    except Exception as e:
        print(f"[whatsnew] fetch failed for {url}: {e.__class__.__name__}: {e}")
        return None


def _parse_json_array(text: str) -> list:
    """Tolerant JSON-array parse — strips code fences, isolates the [...] span."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t).rstrip("`").strip()
    try:
        data = json.loads(t)
    except Exception:
        m = re.search(r"\[.*\]", t, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
    return data if isinstance(data, list) else []


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


def _parse_date(val) -> Optional[datetime]:
    if not val or not isinstance(val, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(val[:len(fmt) + 2], fmt)
        except Exception:
            continue
    return None


async def _extract_items(provider, source: dict, text: str) -> List[dict]:
    """Ask Claude to pull the most-recent distinct updates from page text."""
    prompt = (
        f"Source product: {source['product']}.\n"
        f"From the release-notes page text below, extract up to {_MAX_ITEMS_PER_SOURCE} "
        "of the MOST RECENT distinct updates. For each return: "
        "`title` (<=120 chars), `date` (ISO yyyy-mm-dd if shown, else null), "
        "`summary` (1-2 sentences in DEPT voice). "
        'Return a JSON array of objects with keys "title","date","summary". '
        "If nothing datable/recent is present, return [].\n\n"
        f"PAGE TEXT:\n{text}"
    )
    raw = await provider.complete(prompt, system=_SYSTEM, max_tokens=1200, temperature=0.2)
    items = _parse_json_array(raw)
    out = []
    for it in items[:_MAX_ITEMS_PER_SOURCE]:
        if isinstance(it, dict) and it.get("title"):
            out.append(it)
    return out


async def run_sync(dry_run: bool = False) -> dict:
    """Run the Phase-1 pipeline. Returns an audit report dict.

    dry_run=True does everything EXCEPT writing to the DB — used for the
    pre-enable validation run.
    """
    provider = get_provider()
    report = {
        "started_at": datetime.utcnow().isoformat() + "Z",
        "dry_run": dry_run,
        "provider": config.settings.llm_provider,
        "model": config.settings.llm_model,
        "sources": [],
        "new_items": 0,
        "errors": [],
    }
    if provider is None:
        report["errors"].append("LLM provider not configured (set LLM_PROVIDER=anthropic + LLM_API_KEY)")
        return report

    for source in src.SOURCES:
        s_rep = {"key": source["key"], "fetched": False, "extracted": 0, "new": 0, "items": []}
        text = _fetch_text(source["url"])
        if not text:
            s_rep["error"] = "fetch failed / empty"
            report["sources"].append(s_rep)
            continue
        s_rep["fetched"] = True
        try:
            items = await _extract_items(provider, source, text)
        except Exception as e:
            s_rep["error"] = f"LLM error: {e.__class__.__name__}"
            report["sources"].append(s_rep)
            continue
        s_rep["extracted"] = len(items)

        for it in items:
            title = str(it.get("title", "")).strip()[:512]
            if not title:
                continue
            source_url = f"{source['url']}#{_slug(title)}"
            if storage.source_url_exists(source_url):
                continue
            published = _parse_date(it.get("date"))
            summary = (it.get("summary") or None)
            if summary:
                summary = str(summary).strip()
            preview = {
                "title": title, "date": it.get("date"), "summary": summary,
                "chapter": source["chapter"],
            }
            s_rep["items"].append(preview)
            s_rep["new"] += 1
            if not dry_run:
                storage.insert_item(
                    id=str(uuid.uuid4()), source=source["key"], source_url=source_url,
                    product=source["product"], title=title, summary=summary,
                    related_chapter=source["chapter"], published_at=published, status="new",
                )
        report["new_items"] += s_rep["new"]
        report["sources"].append(s_rep)

    report["finished_at"] = datetime.utcnow().isoformat() + "Z"
    return report
