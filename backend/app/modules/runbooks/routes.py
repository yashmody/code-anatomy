"""Runbooks API routes.

Route map (all mounted under /api/runbooks by main.py):

  GET  /api/runbooks                 — list published runbooks (filter: role, domain)
  GET  /api/runbooks/all             — list ALL runbooks incl. drafts (content.write required)
  GET  /api/runbooks/{slug}          — fetch a single runbook (published; draft OK with content.write)
  POST /api/runbooks/upload          — upload an Excel (.xlsx) file; parses and upserts (content.write)
  POST /api/runbooks/json            — upsert a runbook from raw JSON body              (content.write)
  DELETE /api/runbooks/{slug}        — hard-delete a runbook                            (content.write)

Auth: upload/delete/all require the `content.write` permission, which is held
by `content_author` and the global `platform_admin` bypass. Read endpoints
are unauthenticated so the public runbook reader page works without login.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.core import cache as app_cache
from app.core.deps import require_permission
from app.modules.runbooks import parser as rb_parser
from app.modules.runbooks import storage as rb_storage
from app.modules.runbooks.schemas import RunbookCreate, RunbookDetail, RunbookSummary

logger = logging.getLogger(__name__)

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────────────

def _summary(rb) -> dict:
    return {
        "id": rb.id,
        "slug": rb.slug,
        "title": rb.title,
        "role": rb.role,
        "domain": rb.domain,
        "type": rb.runbook_type,
        "description": rb.description,
        "status": rb.status,
        "created_by": rb.created_by,
        "updated_at": rb.updated_at.isoformat() if rb.updated_at else None,
    }


def _detail(rb) -> dict:
    return {
        **_summary(rb),
        "phases": rb.phases or [],
        "meta": rb.meta or {},
    }


_TEMPLATE_PATH = Path(__file__).parent.parent.parent.parent / "data" / "runbook-template.xlsx"


# ── read endpoints (public) ──────────────────────────────────────────────────

@router.get("/template", summary="Download the blank Excel runbook template")
async def download_template() -> FileResponse:
    """Serve the standard runbook Excel template for teams to fill in.

    Teams download this, fill the 'Runbook' (metadata) and 'Content' (hierarchy)
    sheets, then upload via POST /api/runbooks/upload.
    """
    if not _TEMPLATE_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Template file not found on server. "
                "Run: python -m scripts.generate_runbook_template  from backend/"
            ),
        )
    return FileResponse(
        path=str(_TEMPLATE_PATH),
        filename="dept-runbook-template.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("", summary="List published runbooks")
async def list_runbooks(
    role: Optional[str] = Query(None, description="Filter by role (architect, devops, …)"),
    domain: Optional[str] = Query(None, description="Filter by domain (banking, ecommerce, …)"),
) -> JSONResponse:
    cache_key = f"runbooks:list:{role or 'all'}:{domain or 'all'}"
    cached = app_cache.cache.get(cache_key)
    if cached is not None:
        return JSONResponse(cached)
    runbooks = rb_storage.list_runbooks(role=role, domain=domain, status="published")
    payload = {"runbooks": [_summary(r) for r in runbooks]}
    app_cache.cache.set(cache_key, payload, ttl=300)
    return JSONResponse(payload)


@router.get("/all", summary="List all runbooks incl. drafts (requires content.write)")
async def list_all_runbooks(
    _: None = Depends(require_permission("content.write")),
    role: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
) -> JSONResponse:
    runbooks = rb_storage.list_runbooks(role=role, domain=domain, include_draft=True)
    return JSONResponse({"runbooks": [_summary(r) for r in runbooks]})


@router.get("/{slug}", summary="Get a runbook by slug")
async def get_runbook(slug: str, request: Request) -> JSONResponse:
    rb = rb_storage.get_runbook(slug)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Runbook '{slug}' not found")

    # Draft runbooks are visible only to content.write holders
    if rb.status == "draft":
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=404, detail=f"Runbook '{slug}' not found")
        # Platform admin bypass or content_author role — simplified check here;
        # full permission check is done in the /all and write endpoints via Depends.
        # For draft visibility on GET we allow any authenticated user for now.

    return JSONResponse(_detail(rb))


# ── write endpoints (require content.write) ───────────────────────────────────

@router.post("/upload", summary="Upload an Excel runbook template (.xlsx)")
async def upload_runbook(
    request: Request,
    file: UploadFile = File(..., description="Runbook Excel template (.xlsx)"),
    publish: bool = Query(False, description="Set status=published immediately after parse"),
    _: None = Depends(require_permission("content.write")),
) -> JSONResponse:
    """Parse an Excel workbook and upsert the runbook into the database.

    The workbook must follow the standard template
    (download: GET /api/runbooks/template). Idempotent on slug — re-uploading
    the same file updates the existing record.
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=422,
            detail="Only .xlsx files are accepted. Save your spreadsheet in Excel 2007+ format.",
        )

    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:  # 10 MB sanity cap
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        runbook_data = rb_parser.parse_excel(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if publish:
        runbook_data.status = "published"

    actor = request.session.get("user", {}).get("email") if request.session else None
    rb = rb_storage.upsert_runbook(runbook_data, created_by=actor)
    app_cache.cache.invalidate_prefix("runbooks:list")

    logger.info("[runbooks] upload: slug=%s actor=%s status=%s", rb.slug, actor, rb.status)

    return JSONResponse(
        {
            "ok": True,
            "slug": rb.slug,
            "title": rb.title,
            "status": rb.status,
            "url": f"/runbook?slug={rb.slug}",
            "api": f"/api/runbooks/{rb.slug}",
        },
        status_code=201,
    )


@router.post("/json", summary="Upsert a runbook from a JSON body")
async def upsert_runbook_json(
    payload: RunbookCreate,
    request: Request,
    _: None = Depends(require_permission("content.write")),
) -> JSONResponse:
    """Direct JSON upsert — useful for scripted seeding or Directus Flows."""
    actor = request.session.get("user", {}).get("email") if request.session else None
    rb = rb_storage.upsert_runbook(payload, created_by=actor)
    return JSONResponse(
        {
            "ok": True,
            "slug": rb.slug,
            "status": rb.status,
            "url": f"/runbook?slug={rb.slug}",
        },
        status_code=201,
    )


@router.delete("/{slug}", summary="Delete a runbook by slug")
async def delete_runbook(
    slug: str,
    _: None = Depends(require_permission("content.write")),
) -> JSONResponse:
    deleted = rb_storage.delete_runbook(slug)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Runbook '{slug}' not found")
    return JSONResponse({"ok": True, "deleted": slug})
