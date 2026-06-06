"""Break-glass superadmin routes — local username/password + TOTP 2FA.

Completely independent of Google OAuth. One account maximum, provisioned via
scripts/create_superadmin.py.

Auth state machine
──────────────────
  POST /superadmin/login
    password OK + totp_enabled=False  →  set superadmin_pending  →  302 /superadmin/setup
    password OK + totp_enabled=True   →  set superadmin_pending  →  302 /superadmin/totp
    password FAIL                     →  re-render login form (400)

  GET  /superadmin/setup              →  provisioning URI + raw secret (requires pending)
  POST /superadmin/setup              →  verify first TOTP code → enable 2FA → authenticated

  GET  /superadmin/totp               →  TOTP entry form (requires pending)
  POST /superadmin/totp               →  verify TOTP → authenticated → 302 /

  POST /superadmin/logout             →  clear session → 302 /superadmin/login

Session keys
────────────
  session["superadmin_pending"]  =  {"email": ...}          # password OK, TOTP pending
  session["superadmin"]          =  {"email": ..., "authenticated": True}  # fully authed

Rate limiting: 5 password failures per IP per 5-minute window → 429.
"""
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

import pyotp
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.db import get_session
from app.core.models import SuperAdmin

log = logging.getLogger("app.superadmin")

router = APIRouter(tags=["superadmin"])

# ── In-memory rate limiter (IP → list of failure timestamps) ─────────────────
_failures: dict = defaultdict(list)
_MAX_FAILURES = 5
_WINDOW = 300  # seconds


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is currently blocked."""
    now = time.time()
    _failures[ip] = [t for t in _failures[ip] if now - t < _WINDOW]
    return len(_failures[ip]) >= _MAX_FAILURES


def _record_failure(ip: str) -> None:
    _failures[ip].append(time.time())


def _clear_failures(ip: str) -> None:
    _failures.pop(ip, None)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_superadmin(email: str) -> Optional[SuperAdmin]:
    with get_session() as s:
        return s.get(SuperAdmin, email)


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        import bcrypt as _bcrypt
        return _bcrypt.checkpw(plain.encode(), hashed.encode() if isinstance(hashed, str) else hashed)
    except Exception:
        return False


def _verify_totp(secret: str, code: str) -> bool:
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code.strip(), valid_window=1)
    except Exception:
        return False


# ── HTML page factory (minimal, branded) ─────────────────────────────────────

_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f0f; color: #e8e8e8; font-family: 'DM Sans', system-ui, sans-serif;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px;
          padding: 2.5rem; width: 100%; max-width: 400px; }
  .logo { color: #FF4900; font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em;
          margin-bottom: 1.5rem; }
  h1 { font-size: 1.25rem; font-weight: 600; margin-bottom: 0.4rem; }
  p.sub { color: #888; font-size: 0.85rem; margin-bottom: 1.75rem; line-height: 1.5; }
  label { display: block; font-size: 0.8rem; color: #aaa; margin-bottom: 0.35rem; }
  input { display: block; width: 100%; background: #111; border: 1px solid #333;
          border-radius: 5px; color: #e8e8e8; font-size: 0.95rem; padding: 0.65rem 0.85rem;
          margin-bottom: 1.1rem; outline: none; }
  input:focus { border-color: #FF4900; }
  button { width: 100%; background: #FF4900; color: #fff; border: none; border-radius: 5px;
           font-size: 0.95rem; font-weight: 600; padding: 0.7rem; cursor: pointer; }
  button:hover { background: #e03e00; }
  .err { background: #2a1010; border: 1px solid #5a1a1a; border-radius: 5px;
         color: #f88; font-size: 0.85rem; padding: 0.6rem 0.85rem; margin-bottom: 1.1rem; }
  .mono { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; background: #111;
          border: 1px solid #333; border-radius: 4px; padding: 0.5rem 0.75rem;
          word-break: break-all; margin-bottom: 1rem; color: #aaa; }
  .note { font-size: 0.8rem; color: #777; line-height: 1.5; margin-bottom: 1rem; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · DEPT® Superadmin</title>
<style>{_CSS}</style></head><body><div class="card">
<div class="logo">DEPT® Academy</div>
{body}
</div></body></html>""")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/superadmin/login", response_class=HTMLResponse)
async def login_get(request: Request, error: str = ""):
    # 404 if no superadmin account has been provisioned
    with get_session() as s:
        count = s.query(SuperAdmin).count()
    if count == 0:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)
    err_html = f'<div class="err">{error}</div>' if error else ""
    return _page("Login", f"""
<h1>Superadmin login</h1>
<p class="sub">Break-glass access. Password + authenticator code required.</p>
{err_html}
<form method="post" action="/superadmin/login">
  <label>Email</label>
  <input name="email" type="email" autocomplete="username" required autofocus>
  <label>Password</label>
  <input name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Continue</button>
</form>""")


@router.post("/superadmin/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    ip = _get_client_ip(request)
    if _check_rate_limit(ip):
        log.warning("superadmin login rate-limited ip=%s", ip)
        return _page("Blocked", """
<h1>Too many attempts</h1>
<p class="sub">Login is blocked for 5 minutes after 5 failures. Try again later.</p>
"""), 429

    sa_user = _get_superadmin(email)
    if not sa_user or not _verify_password(password, sa_user.password_hash):
        _record_failure(ip)
        log.warning("superadmin login failed email=%s ip=%s", email, ip)
        return RedirectResponse(
            "/superadmin/login?error=Invalid+email+or+password", status_code=302
        )

    _clear_failures(ip)
    log.info("superadmin password verified email=%s ip=%s", email, ip)

    # Mark password step complete — TOTP still required
    request.session["superadmin_pending"] = {"email": email}
    request.session.pop("superadmin", None)

    if not sa_user.totp_enabled:
        return RedirectResponse("/superadmin/setup", status_code=302)
    return RedirectResponse("/superadmin/totp", status_code=302)


# ── First-time TOTP setup ─────────────────────────────────────────────────────

@router.get("/superadmin/setup", response_class=HTMLResponse)
async def setup_get(request: Request):
    pending = request.session.get("superadmin_pending")
    if not pending:
        return RedirectResponse("/superadmin/login", status_code=302)

    email = pending["email"]
    sa_user = _get_superadmin(email)
    if not sa_user:
        return RedirectResponse("/superadmin/login", status_code=302)
    if sa_user.totp_enabled:
        # Already set up — go to TOTP entry
        return RedirectResponse("/superadmin/totp", status_code=302)

    # Generate or reuse a pending secret
    secret = sa_user.totp_secret
    if not secret:
        secret = pyotp.random_base32()
        with get_session() as s:
            row = s.get(SuperAdmin, email)
            row.totp_secret = secret
            s.commit()

    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=email, issuer_name="DEPT Academy Superadmin"
    )

    return _page("Set up 2FA", f"""
<h1>Set up two-factor authentication</h1>
<p class="sub">Scan the provisioning URI in Google Authenticator, Authy, or any TOTP app.
Then enter the 6-digit code below to confirm.</p>
<label>Provisioning URI (paste into your authenticator app)</label>
<div class="mono">{uri}</div>
<label>Raw secret (for manual entry)</label>
<div class="mono">{secret}</div>
<p class="note">After scanning, enter the 6-digit code your app shows to activate 2FA.
You will need your authenticator app on every future login.</p>
<form method="post" action="/superadmin/setup">
  <label>Authenticator code</label>
  <input name="code" type="text" inputmode="numeric" pattern="[0-9]{{6}}"
         maxlength="6" autocomplete="one-time-code" required autofocus placeholder="123456">
  <button type="submit">Activate 2FA and sign in</button>
</form>""")


@router.post("/superadmin/setup")
async def setup_post(request: Request, code: str = Form(...)):
    pending = request.session.get("superadmin_pending")
    if not pending:
        return RedirectResponse("/superadmin/login", status_code=302)

    email = pending["email"]
    sa_user = _get_superadmin(email)
    if not sa_user or not sa_user.totp_secret:
        return RedirectResponse("/superadmin/login", status_code=302)

    if not _verify_totp(sa_user.totp_secret, code):
        return _page("Set up 2FA", """
<h1>Set up two-factor authentication</h1>
<p class="sub">That code was incorrect. Go back and try again.</p>
<a href="/superadmin/setup" style="color:#FF4900">← Try again</a>""")

    # Enable 2FA and mark as authenticated
    with get_session() as s:
        row = s.get(SuperAdmin, email)
        row.totp_enabled = True
        row.last_login_at = datetime.utcnow()
        s.commit()

    request.session.pop("superadmin_pending", None)
    request.session["superadmin"] = {"email": email, "authenticated": True}
    log.info("superadmin 2FA enabled and authenticated email=%s", email)

    return RedirectResponse("/", status_code=302)


# ── TOTP verification (subsequent logins) ─────────────────────────────────────

@router.get("/superadmin/totp", response_class=HTMLResponse)
async def totp_get(request: Request, error: str = ""):
    if not request.session.get("superadmin_pending"):
        return RedirectResponse("/superadmin/login", status_code=302)
    err_html = f'<div class="err">{error}</div>' if error else ""
    return _page("Two-factor authentication", f"""
<h1>Two-factor authentication</h1>
<p class="sub">Enter the 6-digit code from your authenticator app.</p>
{err_html}
<form method="post" action="/superadmin/totp">
  <label>Authenticator code</label>
  <input name="code" type="text" inputmode="numeric" pattern="[0-9]{{6}}"
         maxlength="6" autocomplete="one-time-code" required autofocus placeholder="123456">
  <button type="submit">Sign in</button>
</form>""")


@router.post("/superadmin/totp")
async def totp_post(request: Request, code: str = Form(...)):
    pending = request.session.get("superadmin_pending")
    if not pending:
        return RedirectResponse("/superadmin/login", status_code=302)

    email = pending["email"]
    sa_user = _get_superadmin(email)
    if not sa_user or not sa_user.totp_secret:
        return RedirectResponse("/superadmin/login", status_code=302)

    if not _verify_totp(sa_user.totp_secret, code):
        log.warning("superadmin TOTP failed email=%s", email)
        return RedirectResponse(
            "/superadmin/totp?error=Invalid+code.+Try+again.", status_code=302
        )

    with get_session() as s:
        row = s.get(SuperAdmin, email)
        row.last_login_at = datetime.utcnow()
        s.commit()

    request.session.pop("superadmin_pending", None)
    request.session["superadmin"] = {"email": email, "authenticated": True}
    log.info("superadmin authenticated email=%s", email)

    return RedirectResponse("/", status_code=302)


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/superadmin/logout")
async def logout(request: Request):
    request.session.pop("superadmin", None)
    request.session.pop("superadmin_pending", None)
    log.info("superadmin logout")
    return RedirectResponse("/superadmin/login", status_code=302)
