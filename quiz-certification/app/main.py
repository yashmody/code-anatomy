"""FastAPI app — Q0 Quiz Module for The Anatomy of Code.

Routes:
  GET  /                       Home (or redirect to login / onboarding)
  GET  /login                  Login page (dev form or Google button)
  POST /login/dev              Dev-mode email login
  GET  /auth/google            Start Google OAuth
  GET  /auth/google/callback   OAuth callback
  GET  /logout                 Clear session
  GET  /onboarding/role        Pick role (required for new users)
  POST /onboarding/role        Save role → home
  GET  /profile/role           Change role
  POST /profile/role           Save updated role → home
  POST /quiz/start             Begin a new quiz
  POST /quiz/submit            Submit answers (graded server-side)
  GET  /quiz/take              The quiz page itself
  GET  /certificate/{cert_id}  Download a certificate PDF
  GET  /history                Past attempts for the current user
  GET  /admin/attempts         Admin view (DEV_MODE only)

Anti-cheat: questions and correct answers live in server memory (and the DB
at submit time). The client receives question text + options only.
Submissions are graded server-side; the client cannot send a "score".
"""
import uuid
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import auth, certificate, config, email_service, quiz_generator, roles, storage

app = FastAPI(title="Q0 · The Anatomy of Code · Quiz Module")
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))

# In-memory active quizzes: quiz_id -> dict
_active_quizzes: Dict[str, Dict] = {}


@app.on_event("startup")
def _startup() -> None:
    storage.init_db()


# ---------- helpers ----------

def _require_user(request: Request) -> Dict:
    """Return the session user, or raise a 302 to /login."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


def _require_user_with_role(request: Request) -> Dict:
    """Like _require_user, but also redirect to onboarding if role is unset."""
    user = _require_user(request)
    if not user.get("role"):
        raise HTTPException(status_code=302, headers={"Location": "/onboarding/role"})
    return user


def _template(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx["user"] = request.session.get("user")
    ctx["dev_mode"] = config.DEV_MODE
    ctx["roles"] = roles.ROLES
    return templates.TemplateResponse(request, name, ctx)


def _refresh_session_user(request: Request, email: str) -> Dict:
    """Pull fresh user data (incl. role) from the DB into the session."""
    db_user = storage.get_user(email) or {}
    session_user = request.session.get("user", {})
    session_user.update({
        "email": db_user.get("email", session_user.get("email")),
        "name": db_user.get("name") or session_user.get("name"),
        "picture": db_user.get("picture") or session_user.get("picture"),
        "role": db_user.get("role"),
        "provider": db_user.get("provider") or session_user.get("provider"),
    })
    request.session["user"] = session_user
    return session_user


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")
    if not user.get("role"):
        return RedirectResponse("/onboarding/role")

    cooldown = storage.cooldown_remaining_days(user["email"])
    last = storage.last_attempt(user["email"])
    passed_ever = storage.has_passed(user["email"])
    topics = quiz_generator.topic_summary()
    recommended = roles.recommended_level(user["role"])

    return _template(
        request,
        "home.html",
        cooldown=cooldown,
        last=last,
        passed_ever=passed_ever,
        topics=topics,
        recommended=recommended,
        role_label=roles.label_for(user["role"]),
        questions_per_quiz=config.QUESTIONS_PER_QUIZ,
        pass_threshold=int(config.PASS_THRESHOLD * 100),
        duration_minutes=config.QUIZ_DURATION_MIN,
        cooldown_days=config.COOLDOWN_DAYS,
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/")
    return _template(request, "login.html", allowed_domain=config.ALLOWED_DOMAIN)


@app.post("/login/dev")
async def login_dev(request: Request, email: str = Form(...)):
    """Dev-only email login. Disabled when DEV_MODE=false."""
    if not config.DEV_MODE:
        raise HTTPException(403, "Dev login disabled in production")
    email = email.strip().lower()
    if not auth.is_allowed_email(email):
        return _template(
            request,
            "login.html",
            error=f"Only @{config.ALLOWED_DOMAIN} emails allowed.",
            allowed_domain=config.ALLOWED_DOMAIN,
        )
    storage.upsert_user(email=email, name=auth.derive_name(email), provider="dev")
    _refresh_session_user(request, email)
    user = request.session["user"]
    if not user.get("role"):
        return RedirectResponse("/onboarding/role", status_code=302)
    return RedirectResponse("/", status_code=302)


@app.get("/auth/google")
async def auth_google_start(request: Request):
    if config.DEV_MODE:
        return RedirectResponse("/login")
    state = auth.make_state()
    request.session["oauth_state"] = state
    return RedirectResponse(auth.google_authorize_url(state))


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request, code: str = "", state: str = ""):
    if config.DEV_MODE:
        return RedirectResponse("/login")
    if not code or state != request.session.get("oauth_state"):
        return RedirectResponse("/login?error=invalid_state")
    profile = auth.exchange_code_for_user(code)
    if not profile:
        return RedirectResponse("/login?error=unauthorized")
    storage.upsert_user(
        email=profile["email"],
        name=profile.get("name"),
        picture=profile.get("picture"),
        provider="google",
    )
    _refresh_session_user(request, profile["email"])
    user = request.session["user"]
    if not user.get("role"):
        return RedirectResponse("/onboarding/role")
    return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


# ---------- onboarding / profile ----------

@app.get("/onboarding/role", response_class=HTMLResponse)
async def onboarding_role_page(request: Request):
    user = _require_user(request)
    return _template(
        request,
        "onboarding_role.html",
        current_role=user.get("role"),
        is_change=False,
    )


@app.post("/onboarding/role")
async def onboarding_role_save(request: Request, role: str = Form(...)):
    user = _require_user(request)
    role = role.strip().lower()
    if not roles.is_valid(role):
        return _template(
            request,
            "onboarding_role.html",
            current_role=user.get("role"),
            error="Pick one of the roles below.",
            is_change=False,
        )
    storage.set_user_role(user["email"], role)
    _refresh_session_user(request, user["email"])
    return RedirectResponse("/", status_code=302)


@app.get("/profile/role", response_class=HTMLResponse)
async def profile_role_page(request: Request):
    user = _require_user(request)
    return _template(
        request,
        "onboarding_role.html",
        current_role=user.get("role"),
        is_change=True,
    )


@app.post("/profile/role")
async def profile_role_save(request: Request, role: str = Form(...)):
    return await onboarding_role_save(request, role)


# ---------- quiz ----------

class StartQuizPayload(BaseModel):
    difficulty: str


@app.post("/quiz/start")
async def quiz_start(request: Request, payload: StartQuizPayload):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not user.get("role"):
        return JSONResponse({"error": "role_required"}, status_code=412)

    cooldown = storage.cooldown_remaining_days(user["email"])
    if cooldown > 0:
        return JSONResponse(
            {"error": "cooldown", "remaining_days": cooldown},
            status_code=429,
        )

    try:
        quiz = quiz_generator.generate(payload.difficulty)
    except ValueError as e:
        return JSONResponse({"error": "generation_failed", "detail": str(e)}, status_code=400)

    _active_quizzes[quiz["quiz_id"]] = {
        "user_email": user["email"],
        "started_at": quiz["started_at"],
        "difficulty": quiz["difficulty"],
        "server_answers": quiz["server_answers"],
        "full_questions": quiz["full_questions"],
    }

    return JSONResponse(
        {
            "quiz_id": quiz["quiz_id"],
            "started_at": quiz["started_at"],
            "difficulty": quiz["difficulty"],
            "duration_minutes": quiz["duration_minutes"],
            "questions": quiz["questions"],
        }
    )


class SubmitPayload(BaseModel):
    quiz_id: str
    answers: Dict[str, int]


@app.post("/quiz/submit")
async def quiz_submit(request: Request, payload: SubmitPayload):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if payload.quiz_id not in _active_quizzes:
        return JSONResponse({"error": "quiz_not_found"}, status_code=404)

    active = _active_quizzes[payload.quiz_id]
    if active["user_email"] != user["email"]:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    grading = quiz_generator.grade(active["server_answers"], payload.answers)

    cert_id = None
    if grading["passed"]:
        cert_id = (
            "CCA-F-"
            + datetime.utcnow().strftime("%Y%m%d")
            + "-"
            + str(uuid.uuid4())[:8].upper()
        )

    submitted_at = datetime.utcnow().isoformat() + "Z"
    record = {
        "cert_id": cert_id,
        "quiz_id": payload.quiz_id,
        "user": user,
        "difficulty": active["difficulty"],
        "started_at": active["started_at"],
        "submitted_at": submitted_at,
        "score": grading["score"],
        "correct": grading["correct"],
        "total": grading["total"],
        "passed": grading["passed"],
        "questions": active["full_questions"],
        "user_answers": payload.answers,
        "grading": grading["per_question"],
    }
    test_code = storage.save_attempt(record)
    record["test_code"] = test_code

    if grading["passed"]:
        try:
            cert_path = certificate.generate(record)
            email_service.send_certificate(
                user["email"], user.get("name") or user["email"], record, cert_path
            )
            record["certificate_path"] = str(cert_path)
            storage.save_attempt(record)  # update with cert path
        except Exception as e:
            print(f"[warn] certificate/email failed: {e}")

    del _active_quizzes[payload.quiz_id]

    review = []
    for q in active["full_questions"]:
        user_idx = payload.answers.get(q["id"])
        review.append(
            {
                "id": q["id"],
                "question": q["question"],
                "options": q["options"],
                "correct_index": q["correct_index"],
                "user_index": user_idx,
                "is_correct": user_idx == q["correct_index"],
                "explanation": q["explanation"],
                "topic": q["topic"],
            }
        )

    return JSONResponse(
        {
            "passed": grading["passed"],
            "score": grading["score"],
            "correct": grading["correct"],
            "total": grading["total"],
            "cert_id": cert_id,
            "test_code": test_code,
            "review": review,
            "cooldown_days": config.COOLDOWN_DAYS if not grading["passed"] else 0,
        }
    )


@app.get("/quiz/take", response_class=HTMLResponse)
async def quiz_take(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")
    if not user.get("role"):
        return RedirectResponse("/onboarding/role")
    return _template(request, "quiz.html", duration_minutes=config.QUIZ_DURATION_MIN)


# ---------- certificate ----------

@app.get("/certificate/{cert_id}")
async def serve_certificate(request: Request, cert_id: str):
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Login required")
    for a in storage.attempts_for(user["email"]):
        if a.get("cert_id") == cert_id:
            path = config.CERTIFICATES_DIR / f"{cert_id}.pdf"
            if not path.exists():
                path = certificate.generate(a)
            return FileResponse(str(path), media_type="application/pdf", filename=f"{cert_id}.pdf")
    raise HTTPException(404, "Certificate not found")


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    user = _require_user_with_role(request)
    attempts = storage.attempts_for(user["email"])
    return _template(request, "history.html", attempts=attempts, role_label=roles.label_for(user["role"]))


# ---------- admin (dev only) ----------

@app.get("/admin/attempts", response_class=HTMLResponse)
async def admin_attempts(request: Request):
    if not config.DEV_MODE:
        raise HTTPException(403, "Admin disabled in production")
    _require_user(request)
    return _template(request, "admin.html", attempts=storage.all_attempts())
