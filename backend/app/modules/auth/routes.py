"""Auth routes — sign-in, OAuth, session-key, /auth/me, /logout.

v2 Phase 2b: the Google flow uses PKCE + nonce, with the verifier/state/
nonce carried in a short-lived signed pre-auth cookie (`aoc_preauth`) —
separate from the long-lived session cookie. See `core/auth.py` and
`docs/architecture/v2/04-authz-model.md §6.1`.

Onboarding now writes `users.persona` (job family), not the dead capability
column. Capability is read per-request via `core.users.roles_for(email)`.
"""
import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core import auth, config, users
from app.core.deps import refresh_session_user
from app.modules.auth import storage as auth_storage


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
    """Dev-only email login. Disabled when DEV_MODE=false.

    v2: NO auto-elevation. The user lands with `learner` only — same as
    prod. Use `scripts/seed_roles.py` + `ADMIN_EMAILS` (or the
    `DEV_SEED_ADMINS` env var when it ships) to grant elevated roles
    locally.
    """
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
    auth_storage.write_audit(
        actor=email,
        action="auth.login.dev",
        target=email,
        after={"provider": "dev"},
    )

    # Initialize transient key
    request.session["payload_key"] = secrets.token_urlsafe(32)

    user = request.session["user"]
    if not user.get("persona"):
        return RedirectResponse("/onboarding/role", status_code=302)
    return RedirectResponse("/", status_code=302)


@router.get("/auth/google")
async def auth_google_start(request: Request):
    """Begin the Google flow: mint state+nonce+verifier, set pre-auth cookie,
    redirect to Google with the PKCE challenge.
    """
    if config.DEV_MODE:
        return RedirectResponse("/login")

    state = auth.make_state()
    nonce = auth.make_nonce()
    code_verifier, code_challenge = auth.make_pkce_pair()

    redirect = RedirectResponse(auth.google_authorize_url(state, code_challenge, nonce))
    redirect.set_cookie(
        auth.PREAUTH_COOKIE,
        auth.pack_preauth(state, nonce, code_verifier),
        max_age=auth.PREAUTH_MAX_AGE,
        httponly=True,
        secure=not config.DEV_MODE,
        samesite="lax",
        path=auth.PREAUTH_PATH,
    )
    return redirect


@router.get("/auth/google/callback")
async def auth_google_callback(request: Request, code: str = "", state: str = ""):
    """Finish the Google flow: verify state, exchange code with the PKCE
    verifier, verify the id_token and nonce, upsert user, set session,
    clear the pre-auth cookie.
    """
    if config.DEV_MODE:
        return RedirectResponse("/login")
    if not code:
        return RedirectResponse("/login?error=invalid_state")

    preauth = auth.unpack_preauth(request.cookies.get(auth.PREAUTH_COOKIE))
    if not preauth:
        return RedirectResponse("/login?error=preauth_expired")
    if state != preauth["state"]:
        return RedirectResponse("/login?error=state_mismatch")

    profile = auth.exchange_code_for_user(
        code,
        code_verifier=preauth["code_verifier"],
        nonce=preauth["nonce"],
    )
    if not profile:
        return RedirectResponse("/login?error=unauthorized")

    users.upsert_user(
        email=profile["email"],
        name=profile.get("name"),
        picture=profile.get("picture"),
        provider="google",
    )
    refresh_session_user(request, profile["email"])
    auth_storage.write_audit(
        actor=profile["email"],
        action="auth.login.google",
        target=profile["email"],
        after={"provider": "google"},
    )

    # Initialize transient key
    request.session["payload_key"] = secrets.token_urlsafe(32)

    user = request.session["user"]
    redirect_to = "/" if user.get("persona") else "/onboarding/role"
    response = RedirectResponse(redirect_to)
    # Drop the now-used pre-auth cookie. Path MUST match the set_cookie call.
    response.delete_cookie(auth.PREAUTH_COOKIE, path=auth.PREAUTH_PATH)
    return response


@router.get("/logout")
async def logout(request: Request):
    user = request.session.get("user") or {}
    actor = user.get("email")
    request.session.clear()
    if actor:
        auth_storage.write_audit(actor=actor, action="auth.logout", target=actor)
    return RedirectResponse("/login")


# ── Current user profile ─────────────────────────────────────────────────────

@router.get("/auth/me")
async def get_current_user_profile(request: Request):
    """Retrieve details of the currently authenticated session user."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user = users.get_user(user["email"])
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found in database")

    name = db_user.get("name") or db_user.get("email")
    initials = "".join(w[0] for w in name.split()[:2]).upper() if name else "??"
    userId = f"u.{db_user['email'].split('@')[0]}"

    return {
        "userId": userId,
        "email": db_user["email"],
        "name": db_user["name"],
        "picture": db_user["picture"],
        "persona": db_user["persona"],
        "roles": sorted(users.roles_for(db_user["email"])),
        "provider": db_user["provider"],
        "preferences": db_user["preferences"],
        "initials": initials,
    }
