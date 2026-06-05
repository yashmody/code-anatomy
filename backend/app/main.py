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
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core import config, db, security, users as core_users
from app.modules.auth import routes as auth_routes
from app.modules.cms import routes as cms_routes
from app.modules.content import routes as content_routes
from app.modules.feed import routes as feed_routes
from app.modules.media import routes as media_routes
from app.modules.quiz import routes as quiz_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
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


app = FastAPI(title="DEPT® Anatomy of Code · Backend", lifespan=lifespan)

# --- middleware (order matters: outermost first) ---
# Phase 2e/3c harden this with CSP/HSTS + a real CORS allowlist.
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
app.include_router(auth_routes.router, tags=["auth"])
app.include_router(quiz_routes.router, tags=["quiz"])
app.include_router(content_routes.router, prefix="/api/course", tags=["content"])
app.include_router(feed_routes.router, prefix="/api", tags=["feed"])
app.include_router(media_routes.router, tags=["media"])
app.include_router(cms_routes.router, prefix="/api/cms", tags=["cms"])
