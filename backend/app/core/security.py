"""Security middleware seam.

Phase 2e fills this in. Three middlewares stack here, in this order (outermost
last per Starlette semantics):

  1. SessionMiddleware — named cookie, 8h max_age, SameSite=Lax, HttpOnly,
     Secure in prod. Closes F-SES-01 / F-COO-01.
  2. CORSMiddleware — explicit origins, methods, headers. No `["*"]`. Closes
     F-COR-01. Production with empty `CORS_ORIGINS` env = no CORS middleware
     attached at all (same-origin only via Apache `Alias /app`).
  3. SecurityHeadersMiddleware — adds the always-on app-side headers per
     v2/07 §3.1 (X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
     Permissions-Policy, COOP, CORP). HSTS + CSP are deliberately NOT set
     here; Apache (Phase 3c) is the single owner of those because they
     interact with vhost-level Alias mounts and SRI hashes.

Cross-slice contract:
  - 2d (config) exposes module-level constants today and is expected to
    add an `APP_ENV` env mirror plus `CORS_ORIGINS` env. We read both
    eagerly via `_load_settings()` so this seam keeps working whether 2d
    has landed yet or not.
  - 2c (cert dev-mode) wants `APP_ENV` to default to "development" when
    `DEV_MODE=true`. We compute the same fallback here.
"""
from __future__ import annotations

import os
from typing import Iterable, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import config
from app.core.observability import RequestIdMiddleware


# ---------------------------------------------------------------------------
# Settings resolution — backward-compatible with module-level constants.
# ---------------------------------------------------------------------------

_SECURITY_HEADERS: List[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
]


def _resolve_app_env() -> str:
    """Return one of {'development','staging','production'}.

    Reads APP_ENV env directly so we don't depend on 2d's settings object.
    Falls back to DEV_MODE — DEV_MODE=true => development, else production.
    """
    raw = os.getenv("APP_ENV", "").strip().lower()
    if raw in ("development", "staging", "production"):
        return raw
    return "development" if getattr(config, "DEV_MODE", True) else "production"


def _resolve_cors_origins(app_env: str) -> List[str]:
    """Parse CORS_ORIGINS env (comma-separated). Non-prod empty falls back
    to the localhost:8080 dev set so the buildless frontend keeps working;
    prod empty = no CORS middleware (same-origin only via Apache)."""
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if app_env != "production":
        return ["http://localhost:8080", "http://127.0.0.1:8080"]
    return []


# ---------------------------------------------------------------------------
# Security headers — ASGI middleware so it runs on every response, including
# StreamingResponse media bytes and exceptions translated to 4xx/5xx.
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware:
    """Append v2/07 §3.1 app-side headers to every HTTP response.

    Skips HSTS + CSP on purpose — Apache (Phase 3c) owns those. Skips
    websockets (scope['type']=='websocket') since they have no header phase.
    """

    def __init__(self, app: ASGIApp, headers: Iterable[tuple[bytes, bytes]] = _SECURITY_HEADERS) -> None:
        self.app = app
        # snapshot so the iterable can be a generator
        self._extra = list(headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                headers = list(message.get("headers", []))
                for name, value in self._extra:
                    if name not in existing:
                        headers.append((name, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def install_middleware(app: FastAPI) -> None:
    """Attach session, CORS, and security-headers middleware.

    Order: SessionMiddleware first (innermost), then CORS, then security
    headers outermost — Starlette wraps in reverse, so security headers run
    last (response phase) and stamp the outgoing response regardless of
    whether CORS short-circuited the preflight.
    """
    app_env = _resolve_app_env()
    is_prod = app_env == "production"

    # 0. GZip — innermost layer (wraps the handler directly). Compresses any
    #    response body ≥1 KB where the client sends Accept-Encoding: gzip.
    #    Course chapter JSONs are 20–80 KB raw; gzip typically shrinks them
    #    60–75%. minimum_size=1000 skips tiny API responses (health probes,
    #    short auth replies) where compression overhead isn't worth it.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # 1. SessionMiddleware — F-SES-01, F-COO-01, Q-1 (8h max_age)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie="aoc_session",
        max_age=8 * 3600,
        same_site="lax",
        https_only=is_prod,
        path="/",
    )

    # 2. CORSMiddleware — F-COR-01. Production with no explicit origins
    # means: do not attach CORS at all (same-origin only via Apache).
    origins = _resolve_cors_origins(app_env)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Encrypt-Payload", "Accept"],
        )

    # 3. Security headers — F-HDR-01 (HSTS + CSP owned by Apache, Phase 3c)
    app.add_middleware(SecurityHeadersMiddleware)

    # 4. Request-id — Phase 3 observability. Added LAST so it is the OUTERMOST
    #    middleware: it binds the request-id contextvar before any inner
    #    middleware or handler runs (so their logs carry the id) and stamps
    #    X-Request-ID on the way out regardless of what the inner stack did.
    #    Logging *configuration* (the structured formatter) is wired separately
    #    via observability.configure_logging() at lifespan start.
    app.add_middleware(RequestIdMiddleware)
