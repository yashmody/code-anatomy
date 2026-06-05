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
  POST /quiz/start             Begin a new quiz (Excludes repeat questions, JWE Encrypted)
  POST /quiz/submit            Submit answers (graded server-side, JWE Encrypted)
  GET  /quiz/take              The quiz page itself
  GET  /certificate/{cert_id}  Download a certificate PDF
  GET  /history                Past attempts for the current user
  GET  /admin/attempts         Admin view (RBAC restricted)

New API routes:
  GET  /auth/session-key       Retrieve transient GCM session encryption key
  GET  /api/feed               Retrieve published feed items
  POST /api/feed               Create a feed item (RBAC: FeedCreator, inserts scenario UGC questions)
  GET  /api/moderate/queue     Moderate queue items (RBAC: Moderator)
  POST /api/moderate/action    Moderator approve/reject (RBAC: Moderator)
  POST /api/admin/questions    Add/Update question (RBAC: QuizManager)
  POST /api/media/upload       Upload media (RBAC: FeedCreator, checks duration, resolution, size)
  GET  /media/video/{asset_id} Chunked video streaming from Postgres using range headers
  GET  /media/image/{asset_id} Image rendering from Postgres large object
"""
import uuid
import secrets
import tempfile
import os
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import auth, certificate, config, email_service, quiz_generator, roles, storage, encryption, media_service
from .models import MediaAsset

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


def _decrypt_request_payload(request_data: dict, session_key: str = None) -> dict:
    """Decrypt the incoming payload if encrypted using AES-GCM."""
    if "nonce" in request_data and "ciphertext" in request_data:
        try:
            return encryption.decrypt_payload(request_data, session_key)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Payload decryption failed: {e}")
    return request_data


def _encrypt_response_payload(response_data: dict, request: Request) -> JSONResponse:
    """Encrypt the outgoing response payload if encryption is requested or active."""
    session_key = request.session.get("payload_key")
    # In prod, we force payload encryption, or if client explicitly sets X-Encrypt-Payload
    if session_key and (request.headers.get("X-Encrypt-Payload") == "true" or not config.DEV_MODE):
        encrypted = encryption.encrypt_payload(response_data, session_key)
        return JSONResponse(encrypted)
    return JSONResponse(response_data)


# ---------- session & auth routes ----------

@app.get("/auth/session-key")
async def get_session_key(request: Request):
    """Retrieve or generate the transient symmetric key used for network encryption."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if "payload_key" not in request.session:
        request.session["payload_key"] = secrets.token_urlsafe(32)
    return {"session_key": request.session["payload_key"]}


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
        pass_threshold=int(round(config.PASS_THRESHOLD * 100)),
        pass_mark_correct=config.PASS_MARK_CORRECT,
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
    
    # Initialize transient key
    request.session["payload_key"] = secrets.token_urlsafe(32)
    
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
    
    # Initialize transient key
    request.session["payload_key"] = secrets.token_urlsafe(32)
    
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


# ---------- quiz runtime (network encrypted) ----------

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
        # Upgraded to filter out repeat questions using user_email!
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
    
    return _encrypt_response_payload(response_data, request)


class SubmitPayload(BaseModel):
    quiz_id: str
    answers: Dict[str, int]


@app.post("/quiz/submit")
async def quiz_submit(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    # Decode payload if encrypted
    body = await request.json()
    session_key = request.session.get("payload_key")
    body = _decrypt_request_payload(body, session_key)

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
    test_code = storage.save_attempt(record)
    record["test_code"] = test_code

    if grading["passed"]:
        try:
            cert_path = certificate.generate(record)
            email_service.send_certificate(
                user["email"], user.get("name") or user["email"], record, cert_path
            )
            record["certificate_path"] = str(cert_path)
            storage.save_attempt(record)
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
    
    return _encrypt_response_payload(response_data, request)


@app.get("/quiz/take", response_class=HTMLResponse)
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


# ---------- public verification ----------

@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, cert_id: str = ""):
    result = None
    cert_id = cert_id.strip().upper()
    if cert_id:
        attempt = storage.attempt_by_cert_id_public(cert_id)
        if attempt and attempt.get("passed") and attempt.get("cert_id"):
            valid_sig = storage.verify_signature(attempt)
            result = {
                "found": True,
                "valid": valid_sig,
                "legacy": not attempt.get("signature"),
                "attempt": attempt,
            }
        else:
            result = {"found": False, "valid": False, "legacy": False, "attempt": None}
    return _template(request, "verify.html", cert_id=cert_id, result=result)


@app.get("/verify/{cert_id}", response_class=HTMLResponse)
async def verify_direct(request: Request, cert_id: str):
    return await verify_page(request, cert_id=cert_id)


# ---------- admin (RBAC restricted) ----------

@app.get("/admin/attempts", response_class=HTMLResponse)
async def admin_attempts(request: Request, user=Depends(auth.require_role(["QuizManager"]))):
    return _template(request, "admin.html", attempts=storage.all_attempts())


# ---------- RBAC Feed APIs ----------

@app.get("/api/feed")
async def get_feed(request: Request, user=Depends(auth.require_role(["User", "FeedCreator", "Moderator"]))):
    """Retrieve all published feed items."""
    return {"feed": storage.get_feed_items()}


@app.post("/api/feed")
async def post_feed(request: Request, item: dict, user=Depends(auth.require_role(["FeedCreator"]))):
    """Create a new feed item. If type is 'scenario', registers it as a pending quiz question."""
    if "id" not in item:
        item["id"] = f"post.{secrets.token_hex(4)}"
    item["createdAt"] = datetime.utcnow().isoformat() + "Z"
    item["status"] = "published" # defaults to published for FeedCreators
    
    # Check if scenario is submitted and map to questions table
    if item.get("type") == "scenario":
        payload = item.get("scenario", {})
        question_data = {
            "id": f"q.ugc.{item['id']}",
            "topic": item.get("topics", ["general"])[0],
            "difficulty": "intermediate", # Default for UGC scenarios
            "question": payload.get("prompt", "Scenario prompt missing"),
            "options": payload.get("options", []),
            "correct_index": payload.get("correct", 0),
            "explanation": payload.get("reveal", ""),
            "status": "pending_review", # Needs Moderator approval before pool injection
            "author_id": user["email"],
            "is_user_submitted": True
        }
        storage.save_question(question_data)
        item["status"] = "pending-review" # Force post state if containing quiz question
        
    storage.save_feed_item(item)
    return {"status": "success", "id": item["id"]}


# ---------- RBAC Moderation APIs ----------

@app.get("/api/moderate/queue")
async def get_moderation_queue(user=Depends(auth.require_role(["Moderator"]))):
    """View all items pending review or flagged for removal."""
    return storage.get_moderation_queue()


class ModActionPayload(BaseModel):
    item_id: str
    item_type: str # 'feed' or 'question'
    action: str # 'approve', 'flag', 'remove'


@app.post("/api/moderate/action")
async def moderate_action(payload: ModActionPayload, user=Depends(auth.require_role(["Moderator"]))):
    """Approve or reject/flag content."""
    action = payload.action.lower()
    
    if payload.item_type == "feed":
        with storage.get_session() as s:
            item = s.get(storage.FeedItem, payload.item_id)
            if not item:
                raise HTTPException(status_code=404, detail="Feed item not found")
            if action == "approve":
                item.status = "published"
            elif action == "flag":
                item.status = "flagged"
            elif action == "remove":
                item.status = "removed"
            s.commit()
            
    elif payload.item_type == "question":
        with storage.get_session() as s:
            q = s.get(storage.Question, payload.item_id)
            if not q:
                raise HTTPException(status_code=404, detail="Question not found")
            if action == "approve":
                q.status = "published"
            elif action == "flag":
                q.status = "draft"
            elif action == "remove":
                q.status = "archived"
            s.commit()
            
    return {"status": "success"}


# ---------- RBAC Quiz Management APIs ----------

class QuestionPayload(BaseModel):
    id: str
    topic: str
    difficulty: str
    question: str
    options: List[str]
    correct_index: int
    explanation: Optional[str] = ""
    status: Optional[str] = "published"


@app.post("/api/admin/questions")
async def admin_save_question(payload: QuestionPayload, user=Depends(auth.require_role(["QuizManager"]))):
    """Add or update a question in the bank, auto-versioning under the hood."""
    q_dict = payload.dict()
    q_dict["author_id"] = user["email"]
    q_dict["is_user_submitted"] = False
    storage.save_question(q_dict)
    return {"status": "success", "id": payload.id}


# ---------- Native Media Uploads & Streaming ----------

@app.post("/api/media/upload")
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(auth.require_role(["FeedCreator"]))
):
    """Upload a file to PostgreSQL Large Objects with strict type/size/FFmpeg resolution validation."""
    # 1. Read headers for type spoofing protection
    head_bytes = await file.read(2048) # Read signature block
    await file.seek(0) # Reset pointer
    
    mime_type = media_service.detect_mime_type(head_bytes)
    if not mime_type:
        raise HTTPException(status_code=400, detail="Unsupported file format or header mismatch")
        
    # Check limit boundaries
    is_video = mime_type.startswith("video/")
    max_size = config.MAX_VIDEO_SIZE_MB * 1024 * 1024 if is_video else config.MAX_IMAGE_SIZE_MB * 1024 * 1024
    
    # 2. Enforce Stream-Level Size Caps
    temp_fd, temp_path = tempfile.mkstemp()
    bytes_written = 0
    try:
        with os.fdopen(temp_fd, 'wb') as tmp:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_size:
                    raise HTTPException(
                        status_code=413, 
                        detail=f"Upload exceeds size boundary (Max: {max_size / (1024*1024):.1f}MB)"
                    )
                tmp.write(chunk)
                
        # 3. Perform specific quality and metadata checks locally
        if is_video:
            valid, err = media_service.validate_video(temp_path)
            if not valid:
                raise HTTPException(status_code=400, detail=err)
        else:
            valid, err = media_service.validate_image(temp_path)
            if not valid:
                raise HTTPException(status_code=400, detail=err)
                
        # 4. Ingest into PostgreSQL Large Objects
        asset_id, oid = media_service.store_media_asset(
            temp_path, file.filename, mime_type, user["email"]
        )
        
        # Generate the access endpoints
        endpoint = f"/media/video/{asset_id}" if is_video else f"/media/image/{asset_id}"
        return {"status": "success", "asset_id": asset_id, "url": endpoint}
        
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.get("/media/video/{asset_id}")
async def stream_video(request: Request, asset_id: str):
    """Stream videos from PostgreSQL large objects supporting HTTP Range requests (scrubbing)."""
    with storage.get_session() as session:
        asset = session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        oid = asset.large_object_oid
        size = asset.size_bytes
        mime = asset.mime_type
        
    range_header = request.headers.get("Range")
    if not range_header:
        # Request full file
        generator = media_service.stream_video_chunks(oid, 0, size - 1)
        return StreamingResponse(generator, media_type=mime)
        
    try:
        range_str = range_header.replace("bytes=", "")
        start_str, end_str = range_str.split("-")
        start = int(start_str)
        end = int(end_str) if end_str else size - 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Range header")
        
    if start >= size or end >= size or start > end:
        raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")
        
    headers = {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    }
    
    generator = media_service.stream_video_chunks(oid, start, end)
    return StreamingResponse(generator, status_code=206, headers=headers, media_type=mime)


@app.get("/media/image/{asset_id}")
async def serve_image(asset_id: str):
    """Serve images stored inside PostgreSQL Large Objects."""
    with storage.get_session() as session:
        asset = session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        oid = asset.large_object_oid
        size = asset.size_bytes
        mime = asset.mime_type
        
    generator = media_service.stream_video_chunks(oid, 0, size - 1)
    return StreamingResponse(generator, media_type=mime)
