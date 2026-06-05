"""Security middleware seam.

Today this wraps the same `CORSMiddleware` + `SessionMiddleware` pair that
the legacy `main.py` installed inline. The seam exists so Phase 2e (auth
hardening) and Phase 3c (CSP/HSTS headers, real CORS allowlist) can add
new middleware in one place without touching every router.

Order matters: middleware added later wraps earlier ones, so the LAST
`add_middleware` call is the OUTERMOST in the request path. We add CORS
first and SessionMiddleware second — same order the legacy app used.

Filled in further by Phase 2e/3c per v2/07.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core import config


def install_middleware(app: FastAPI) -> None:
    """Attach CORS + session middleware. Composition-only.

    Keeps the legacy localhost:8080 dev CORS rule so the buildless frontend
    served by `python -m http.server 8080` keeps working under the new
    layout. Phase 3c tightens this with a real allowlist + CSP/HSTS.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)
