"""Auth routes — sign-in, OAuth, session-key, /auth/me, /logout.

Profile/onboarding role pages live in the quiz module (they're part of the
quiz flow). Everything that touches credentials lives here.
"""
import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core import auth, config, users
from app.core.deps import refresh_session_user


router = APIRouter()

# Filled by main.py during composition — keeps the quiz module the owner of
# the Jinja2Templates instance while letting the login page reuse it.
_templates = None


def bind_templates(templates) -> None:
    """Allow main.py to inject the shared Jinja2Templates instance."""
    global _templates
    _templates = templates


def _login_template(request: Request, **ctx) -> HTMLResponse:
    """Render the login page with the small ctx surface it needs."""
    ctx["user"] = request.session.get("user")
    ctx["dev_mode"] = config.DEV_MODE
    return _templates.TemplateResponse(request, "login.html", ctx)


# ── Session ──────────────────────────────────────────────────────────────────

@router.get("/auth/session-key")
async def get_session_key(request: Request):
    """Retrieve or generate the transient symmetric key used for network encryption."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if "payload_key" not in request.session:
        request.session["payload_key"] = secrets.token_urlsafe(32)
    return {"session_key": request.session["payload_key"]}


# ── Sign-in (dev + Google) ───────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/")
    return _login_template(request, allowed_domain=config.ALLOWED_DOMAIN)


@router.post("/login/dev")
async def login_dev(request: Request, email: str = Form(...)):
    """Dev-only email login. Disabled when DEV_MODE=false."""
    if not config.DEV_MODE:
        raise HTTPException(403, "Dev login disabled in production")
    email = email.strip().lower()
    if not auth.is_allowed_email(email):
        return _login_template(
            request,
            error=f"Only @{config.ALLOWED_DOMAIN} emails allowed.",
            allowed_domain=config.ALLOWED_DOMAIN,
        )
    users.upsert_user(email=email, name=auth.derive_name(email), provider="dev")
    refresh_session_user(request, email)

    # Initialize transient key
    request.session["payload_key"] = secrets.token_urlsafe(32)

    user = request.session["user"]
    if not user.get("role"):
        return RedirectResponse("/onboarding/role", status_code=302)
    return RedirectResponse("/", status_code=302)


@router.get("/auth/google")
async def auth_google_start(request: Request):
    if config.DEV_MODE:
        return RedirectResponse("/login")
    state = auth.make_state()
    request.session["oauth_state"] = state
    return RedirectResponse(auth.google_authorize_url(state))


@router.get("/auth/google/callback")
async def auth_google_callback(request: Request, code: str = "", state: str = ""):
    if config.DEV_MODE:
        return RedirectResponse("/login")
    if not code or state != request.session.get("oauth_state"):
        return RedirectResponse("/login?error=invalid_state")
    profile = auth.exchange_code_for_user(code)
    if not profile:
        return RedirectResponse("/login?error=unauthorized")
    users.upsert_user(
        email=profile["email"],
        name=profile.get("name"),
        picture=profile.get("picture"),
        provider="google",
    )
    refresh_session_user(request, profile["email"])

    # Initialize transient key
    request.session["payload_key"] = secrets.token_urlsafe(32)

    user = request.session["user"]
    if not user.get("role"):
        return RedirectResponse("/onboarding/role")
    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


# ── Current user profile ─────────────────────────────────────────────────────

@router.get("/auth/me")
async def get_current_user_profile(request: Request):
    """Retrieve details of the currently authenticated session user."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Refresh user from database to ensure up-to-date role/preferences
    db_user = users.get_user(user["email"])
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found in database")

    # Calculate initials
    name = db_user.get("name") or db_user.get("email")
    initials = "".join(w[0] for w in name.split()[:2]).upper() if name else "??"
    userId = f"u.{db_user['email'].split('@')[0]}"

    return {
        "userId": userId,
        "email": db_user["email"],
        "name": db_user["name"],
        "picture": db_user["picture"],
        "role": db_user["role"],
        "provider": db_user["provider"],
        "preferences": db_user["preferences"],
        "initials": initials,
    }
