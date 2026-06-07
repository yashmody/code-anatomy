"""FastAPI composition root.

This file contains NO business logic. It builds the app, attaches middleware,
mounts static + templates, registers lifespan, and includes each module's
router. Every endpoint lives in `app/modules/<name>/routes.py`.

Route map (preserved exactly from the legacy monolith — issued certificates
keep verifying, the buildless SPA keeps fetching the same paths):

  auth/      /auth/session-key, /login (GET/POST dev), /auth/google,
             /auth/google/callback, /logout, /auth/me
  quiz/      /, /onboarding/role (GET+POST), /profile/role (GET+POST),
             /quiz/start, /quiz/submit, /quiz/take,
             /certificate/{cert_id}, /history, /verify, /verify/{cert_id},
             /admin/attempts, /api/admin/questions
  content/   /api/course/framework, /api/course/chapters,
             /api/course/chapters/{filename}, /api/course/framework-explainer
  feed/      /api/feed (GET+POST), /api/feed/flag,
             /api/moderate/queue, /api/moderate/action
  media/     /api/media/upload, /media/video/{asset_id}, /media/image/{asset_id}
  cms/       (placeholder — Phase 4 fills)
  runbooks/  /api/runbooks (GET list), /api/runbooks/{slug} (GET detail),
             /api/runbooks/upload (POST xlsx), /api/runbooks/json (POST),
             /api/runbooks/{slug} (DELETE)
"""
import shutil
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.core import config, db, observability, security, users as core_users
from app.core.cache import cache as app_cache
from app.modules.admin import routes as admin_routes
from app.modules.auth import routes as auth_routes
from app.modules.cms import routes as cms_routes
from app.modules.content import routes as content_routes
from app.modules.feed import routes as feed_routes
from app.modules.faq import routes as faq_routes
from app.modules.media import routes as media_routes
from app.modules.quiz import routes as quiz_routes
from app.modules.runbooks import routes as runbook_routes
from app.modules.superadmin import routes as superadmin_routes
from app.modules.whatsnew import routes as whatsnew_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Structured logging + request-id correlation must be configured before any
    # other startup log line so they all carry the (startup) request_id="-".
    observability.configure_logging(config.settings.log_level)
    # Phase 2a will replace this with an Alembic-migrated startup check.
    db.init_db()
    # Phase 2b owns the real ensure_first_admin() — call defensively so 2e
    # ships without depending on the 2b landing order. Once 2b lands, this
    # will resolve and seed the first platform_admin from ADMIN_EMAILS.
    _ensure_first_admin = getattr(core_users, "ensure_first_admin", None)
    if callable(_ensure_first_admin):
        try:
            _ensure_first_admin()
        except Exception as exc:  # noqa: BLE001 — lifespan must not fail closed on seeding
            import logging
            logging.getLogger("app.lifespan").warning(
                "ensure_first_admin() raised %s; continuing startup", exc
            )
    yield


# ---------------------------------------------------------------------------
# Health / readiness probes (Phase 3 observability).
#
# Both are UNAUTHENTICATED and must never 307/302 to /login — they are
# liveness/readiness probes for systemd, Apache, and uptime checks. They live
# inline (no module) so they have zero dependency on any auth surface and can
# answer even if a module fails to import in a future change.
#   GET /healthz  → 200 {status, version, env}                (liveness)
#   GET /readyz   → 200 if DB reachable (+ redis if selected); 503 otherwise
# ---------------------------------------------------------------------------
health_router = APIRouter()

_APP_VERSION = "v2"


@health_router.get("/healthz")
async def healthz():
    """Liveness: the process is up and serving. No dependency checks."""
    return {
        "status": "ok",
        "version": _APP_VERSION,
        "env": config.settings.app_env,
    }


@health_router.get("/readyz")
async def readyz():
    """Readiness: dependencies are reachable.

    - DB: `SELECT 1` must succeed.
    - Cache: only checked when CACHE_BACKEND=redis — the active backend must be
      redis (i.e. it didn't silently degrade to memory). In the default memory
      configuration the cache is always ready.

    Returns 200 with per-check detail when ready, 503 otherwise.
    """
    checks: dict[str, str] = {}
    ready = True

    # DB check
    try:
        with db.get_session() as session:
            session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:  # noqa: BLE001 — readiness reports, never raises
        checks["db"] = f"error: {exc.__class__.__name__}"
        ready = False

    # Cache check — only meaningful when redis was requested.
    if config.settings.cache_backend == "redis":
        if app_cache.backend_name == "redis":
            checks["cache"] = "ok"
        else:
            # Redis was requested but the cache degraded to memory — not ready.
            checks["cache"] = "error: redis requested but backend is memory"
            ready = False
    else:
        checks["cache"] = "skip (memory backend)"

    # Disk space — warn (not fail) on low free space so the probe doesn't
    # flap under transient load; an operator should be paged before it's "ok".
    try:
        usage = shutil.disk_usage(config.settings.log_dir)
        free_ratio = usage.free / usage.total
        free_gb = usage.free / (1024**3)
        if free_gb < 1 or free_ratio < 0.10:
            checks["disk"] = f"warn: {free_gb:.1f}GB free ({free_ratio:.0%})"
        else:
            checks["disk"] = f"ok: {free_gb:.1f}GB free ({free_ratio:.0%})"
    except OSError as exc:
        checks["disk"] = f"error: {exc.__class__.__name__}"

    # DB pool saturation — warn when checked-out connections approach the
    # configured ceiling. Production uses QueuePool, whose checkedout() is the
    # live leased count; the ceiling is db_pool_size + db_max_overflow (the same
    # values db.py hands the engine — note pool.overflow() is a *current* count,
    # not the max, so we read the ceiling from config). Dev/SQLite uses NullPool,
    # which exposes no checkedout()/size() — report skip there.
    try:
        pool = db.engine.pool
        if hasattr(pool, "checkedout"):
            checked_out = pool.checkedout()
            ceiling = config.settings.db_pool_size + max(config.settings.db_max_overflow, 0)
            if ceiling > 0:
                utilisation = checked_out / ceiling
                detail = f"{checked_out}/{ceiling} ({utilisation:.0%})"
                checks["db_pool"] = f"warn: {detail}" if utilisation >= 0.80 else f"ok: {detail}"
            else:
                checks["db_pool"] = "skip (no fixed pool)"
        else:
            checks["db_pool"] = "skip (no pooling)"
    except Exception as exc:  # noqa: BLE001 — readiness reports, never raises
        checks["db_pool"] = f"error: {exc.__class__.__name__}"

    body = {"status": "ok" if ready else "not_ready", "checks": checks}
    return JSONResponse(body, status_code=200 if ready else 503)


@health_router.post("/csp/report")
async def csp_report(request: Request):
    """Sink for CSP violation reports — the Report-To `csp-endpoint` target.

    Unauthenticated by design: browsers POST CSP reports with no credentials
    and must never be redirected. Accepts any content-type
    (application/csp-report or application/reports+json), logs a compact line so
    the CSP Report-Only soak (deploy.sh) has somewhere to land, and returns 204.
    No DB, no auth, no redirect — it lives on the inline health_router for
    exactly that reason. Closes V2-F-02 (the Report-To header previously
    dangled at a 404).
    """
    import logging
    try:
        raw = (await request.body()).decode("utf-8", "replace")[:2000]
    except Exception:  # noqa: BLE001 — a report sink must never error
        raw = "<unreadable>"
    logging.getLogger("app.csp").warning("csp-report %s", raw)
    return Response(status_code=204)


app = FastAPI(title="DEPT® Anatomy of Code · Backend", lifespan=lifespan)

# --- middleware (order matters: outermost first) ---
# Phase 2e/3c harden this with CSP/HSTS + a real CORS allowlist.
# install_middleware also wires the request-id middleware (observability) as
# the outermost layer; configure_logging() runs at lifespan start.
security.install_middleware(app)

# --- static + templates ---
# /static stays FastAPI-served (so Jinja `url_for('static', ...)` references
# remain stable and FastAPI owns cache headers for templated pages).
# The /app SPA mount that the legacy monolith carried is REMOVED — Apache
# serves the SPA at /app/ in v2; FastAPI no longer needs it.
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

# Templates are owned by the quiz module (every HTML page is its page).
# Auth's /login page shares the same instance via bind_templates so we
# don't ship two Jinja loaders.
quiz_routes.bind_templates(templates)
auth_routes.bind_templates(templates)

# --- routers ---
# Health probes first — unauthenticated, no prefix (so /healthz, /readyz).
app.include_router(health_router, tags=["health"])
app.include_router(auth_routes.router, tags=["auth"])
app.include_router(quiz_routes.router, tags=["quiz"])
app.include_router(content_routes.router, prefix="/api/course", tags=["content"])
app.include_router(feed_routes.router, prefix="/api", tags=["feed"])
app.include_router(media_routes.router, tags=["media"])
app.include_router(cms_routes.router, prefix="/api/cms", tags=["cms"])
app.include_router(superadmin_routes.router, tags=["superadmin"])
app.include_router(faq_routes.router, prefix="/api/faqs", tags=["faq"])
app.include_router(runbook_routes.router, prefix="/api/runbooks", tags=["runbooks"])
app.include_router(whatsnew_routes.router, tags=["whatsnew"])  # GET /api/whatsnew
# Admin role-assignment REST (04 §7.2). Decorators are "/roles"; the prefix
# carries "/api/admin" → /api/admin/roles. All endpoints require role.assign.
app.include_router(admin_routes.router, prefix="/api/admin", tags=["admin"])
