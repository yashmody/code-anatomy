"""Quiz routes — home, onboarding, profile, quiz runtime, certificates, history,
public verification, admin attempts, admin question CRUD.

The quiz module owns every Jinja-templated HTML page (home/login redirect target,
quiz, history, verify, admin, onboarding_role) — `bind_templates(...)` injects
the shared Jinja2Templates from main.py so the `_template()` helper has it.

The in-process `_active_quizzes` dict is kept as a module-level seam (parity
with the legacy main.py:69). It's NOT multi-worker safe; Phase 1 acceptance
(01-blueprint §9 Slice A item 12) pins QUIZ_WORKERS=1 until Phase 2b moves
the active-quiz state into Postgres.
"""
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from app.core import config, roles
from app.core.deps import (
    decrypt_request_payload,
    encrypt_response_payload,
    refresh_session_user,
    require_role,
    require_user,
    require_user_with_role,
)
from app.modules.quiz import certificate, email as email_service, service as quiz_generator
from app.modules.quiz import storage as quiz_storage
from app.modules.quiz.schemas import QuestionPayload, StartQuizPayload, SubmitPayload


router = APIRouter()

# Injected by main.py — kept module-private so other routers can't reach in.
_templates = None

# In-process quiz state — quiz_id → {user_email, started_at, difficulty,
# server_answers, full_questions}. Parity-preserved from legacy main.py:69.
# Not multi-worker safe (see Phase 1 acceptance gate in 01-blueprint §9).
_active_quizzes: Dict[str, Dict] = {}


def bind_templates(templates) -> None:
    """main.py calls this to hand the Jinja2Templates instance to the quiz module."""
    global _templates
    _templates = templates


def _template(request: Request, name: str, **ctx) -> HTMLResponse:
    """Render with the shared context every page needs (user, roles, dev_mode)."""
    ctx["user"] = request.session.get("user")
    ctx["dev_mode"] = config.DEV_MODE
    ctx["roles"] = roles.ROLES
    return _templates.TemplateResponse(request, name, ctx)


# ── Home + onboarding/profile ────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")
    if not user.get("role"):
        return RedirectResponse("/onboarding/role")

    cooldown = quiz_storage.cooldown_remaining_days(user["email"])
    last = quiz_storage.last_attempt(user["email"])
    passed_ever = quiz_storage.has_passed(user["email"])
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
        pass_threshold=int(round(config.PASS_THRESHOLD * 100)),
        pass_mark_correct=config.PASS_MARK_CORRECT,
        duration_minutes=config.QUIZ_DURATION_MIN,
        cooldown_days=config.COOLDOWN_DAYS,
    )


@router.get("/onboarding/role", response_class=HTMLResponse)
async def onboarding_role_page(request: Request):
    user = require_user(request)
    return _template(
        request,
        "onboarding_role.html",
        current_role=user.get("role"),
        is_change=False,
    )


@router.post("/onboarding/role")
async def onboarding_role_save(request: Request, role: str = Form(...)):
    user = require_user(request)
    role = role.strip().lower()
    if not roles.is_valid(role):
        return _template(
            request,
            "onboarding_role.html",
            current_role=user.get("role"),
            error="Pick one of the roles below.",
            is_change=False,
        )
    # Lazy import to keep the route file free of direct user-helper coupling
    # (users live in core/users.py; only auth + admin pages need to set roles).
    from app.core import users as core_users
    core_users.set_user_role(user["email"], role)
    refresh_session_user(request, user["email"])
    return RedirectResponse("/", status_code=302)


@router.get("/profile/role", response_class=HTMLResponse)
async def profile_role_page(request: Request):
    user = require_user(request)
    return _template(
        request,
        "onboarding_role.html",
        current_role=user.get("role"),
        is_change=True,
    )


@router.post("/profile/role")
async def profile_role_save(request: Request, role: str = Form(...)):
    return await onboarding_role_save(request, role)


# ── Quiz runtime (network encrypted) ─────────────────────────────────────────

@router.post("/quiz/start")
async def quiz_start(request: Request, payload: StartQuizPayload):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not user.get("role"):
        return JSONResponse({"error": "role_required"}, status_code=412)

    cooldown = quiz_storage.cooldown_remaining_days(user["email"])
    if cooldown > 0:
        return JSONResponse(
            {"error": "cooldown", "remaining_days": cooldown},
            status_code=429,
        )

    try:
        # Filters out repeat questions using user_email.
        quiz = quiz_generator.generate(payload.difficulty, user["email"])
    except ValueError as e:
        return JSONResponse({"error": "generation_failed", "detail": str(e)}, status_code=400)

    _active_quizzes[quiz["quiz_id"]] = {
        "user_email": user["email"],
        "started_at": quiz["started_at"],
        "difficulty": quiz["difficulty"],
        "server_answers": quiz["server_answers"],
        "full_questions": quiz["full_questions"],
    }

    response_data = {
        "quiz_id": quiz["quiz_id"],
        "started_at": quiz["started_at"],
        "difficulty": quiz["difficulty"],
        "duration_minutes": quiz["duration_minutes"],
        "questions": quiz["questions"],
    }

    return encrypt_response_payload(response_data, request)


@router.post("/quiz/submit")
async def quiz_submit(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    # Decode payload if encrypted
    body = await request.json()
    session_key = request.session.get("payload_key")
    body = decrypt_request_payload(body, session_key)

    try:
        payload = SubmitPayload(**body)
    except Exception as e:
        return JSONResponse({"error": "invalid_payload", "detail": str(e)}, status_code=400)

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
    test_code = quiz_storage.save_attempt(record)
    record["test_code"] = test_code

    if grading["passed"]:
        try:
            cert_path = certificate.generate(record)
            email_service.send_certificate(
                user["email"], user.get("name") or user["email"], record, cert_path
            )
            record["certificate_path"] = str(cert_path)
            quiz_storage.save_attempt(record)
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

    response_data = {
        "passed": grading["passed"],
        "score": grading["score"],
        "correct": grading["correct"],
        "total": grading["total"],
        "cert_id": cert_id,
        "test_code": test_code,
        "review": review,
        "cooldown_days": config.COOLDOWN_DAYS if not grading["passed"] else 0,
    }

    return encrypt_response_payload(response_data, request)


@router.get("/quiz/take", response_class=HTMLResponse)
async def quiz_take(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")
    if not user.get("role"):
        return RedirectResponse("/onboarding/role")
    return _template(
        request,
        "quiz.html",
        duration_minutes=config.QUIZ_DURATION_MIN,
        pass_mark_correct=config.PASS_MARK_CORRECT,
        questions_per_quiz=config.QUESTIONS_PER_QUIZ,
    )


# ── Certificate ──────────────────────────────────────────────────────────────

@router.get("/certificate/{cert_id}")
async def serve_certificate(request: Request, cert_id: str):
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Login required")
    for a in quiz_storage.attempts_for(user["email"]):
        if a.get("cert_id") == cert_id:
            path = config.CERTIFICATES_DIR / f"{cert_id}.pdf"
            if not path.exists():
                path = certificate.generate(a)
            return FileResponse(str(path), media_type="application/pdf", filename=f"{cert_id}.pdf")
    raise HTTPException(404, "Certificate not found")


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    user = require_user_with_role(request)
    attempts = quiz_storage.attempts_for(user["email"])
    return _template(request, "history.html", attempts=attempts, role_label=roles.label_for(user["role"]))


# ── Public verification ──────────────────────────────────────────────────────

@router.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, cert_id: str = ""):
    result = None
    cert_id = cert_id.strip().upper()
    if cert_id:
        attempt = quiz_storage.attempt_by_cert_id_public(cert_id)
        if attempt and attempt.get("passed") and attempt.get("cert_id"):
            valid_sig = quiz_storage.verify_signature(attempt)
            result = {
                "found": True,
                "valid": valid_sig,
                "legacy": not attempt.get("signature"),
                "attempt": attempt,
            }
        else:
            result = {"found": False, "valid": False, "legacy": False, "attempt": None}
    return _template(request, "verify.html", cert_id=cert_id, result=result)


@router.get("/verify/{cert_id}", response_class=HTMLResponse)
async def verify_direct(request: Request, cert_id: str):
    return await verify_page(request, cert_id=cert_id)


# ── Admin (RBAC restricted) ──────────────────────────────────────────────────

@router.get("/admin/attempts", response_class=HTMLResponse)
async def admin_attempts(request: Request, user=Depends(require_role(["QuizManager"]))):
    return _template(request, "admin.html", attempts=quiz_storage.all_attempts())


@router.post("/api/admin/questions")
async def admin_save_question(payload: QuestionPayload, user=Depends(require_role(["QuizManager"]))):
    """Add or update a question in the bank, auto-versioning under the hood."""
    q_dict = payload.dict()
    q_dict["author_id"] = user["email"]
    q_dict["is_user_submitted"] = False
    quiz_storage.save_question(q_dict)
    return {"status": "success", "id": payload.id}
