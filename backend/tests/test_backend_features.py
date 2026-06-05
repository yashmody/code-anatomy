"""Verification test suite for dynamic RBAC, encryption, media detection, and quiz flow.

Phase 1 (v2) note: imports were repointed onto the new module layout
(core.* + modules.*). The mock-by-module-binding tests target the *imported*
references inside each module, not the source module — `storage.get_user`
patches the binding inside the test scope; for the new layout we patch the
binding inside the module that actually calls it (`core.auth.users`).
"""
import pytest
from fastapi.testclient import TestClient
from fastapi import Request, HTTPException

from app.main import app
from app.core import auth, encryption, users
from app.core.models import User, Question, Attempt
from app.modules.media import service as media_service
from app.modules.quiz import service as quiz_generator
from app.modules.quiz import storage as quiz_storage
from app.modules.content import storage as content_storage

# Backwards-compat alias for tests that still use `storage` as a single namespace.
# Each call below uses the per-module storage explicitly; this binding lets the
# course-endpoint test patch shared user/content reads against the surface the
# routers actually call.
storage = type("storage", (), {
    "get_user": users.get_user,
    "get_framework": content_storage.get_framework,
    "get_all_chapters": content_storage.get_all_chapters,
    "get_chapter": content_storage.get_chapter,
})

client = TestClient(app)


# ---------- Encryption & Decryption Tests ----------

def test_payload_encryption_decryption():
    """Test that dictionary payloads can be encrypted and successfully decrypted."""
    payload = {"status": "success", "question_ids": ["q1", "q2"], "score": 83.5}

    # 1. Encrypt
    encrypted = encryption.encrypt_payload(payload)
    assert "nonce" in encrypted
    assert "ciphertext" in encrypted

    # 2. Decrypt
    decrypted = encryption.decrypt_payload(encrypted)
    assert decrypted == payload


# ---------- Magic Byte Media Type Detection Tests ----------

def test_media_type_detection():
    """Test magic bytes signatures for images and videos."""
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    webp_bytes = b"RIFF\x00\x00\x00\x00WEBPvp8"
    mp4_bytes = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
    fake_bytes = b"not_media_file_content"

    assert media_service.detect_mime_type(png_bytes) == "image/png"
    assert media_service.detect_mime_type(jpeg_bytes) == "image/jpeg"
    assert media_service.detect_mime_type(webp_bytes) == "image/webp"
    assert media_service.detect_mime_type(mp4_bytes) == "video/mp4"
    assert media_service.detect_mime_type(fake_bytes) is None


# ---------- Dynamic RBAC Endpoint Security Tests ----------

def test_rbac_require_role_dependency(monkeypatch):
    """Test that require_role dynamically queries user database role and handles auth errors."""
    mock_user_email = "test_creator@deptagency.com"

    # The RBAC dependency lives in core.auth and calls `users.get_user` via
    # the `users` binding imported at the top of core/auth.py. Patch that
    # binding so the lookup is intercepted.
    def mock_get_user(email):
        return {
            "email": mock_user_email,
            "name": "Test Creator",
            "picture": "",
            "role": "FeedCreator",
            "provider": "dev",
        }
    monkeypatch.setattr(auth.users, "get_user", mock_get_user)

    # Test validator
    feed_creator_validator = auth.require_role(["FeedCreator"])
    moderator_validator = auth.require_role(["Moderator"])

    # Mock request with session
    class MockRequest:
        def __init__(self, session_data):
            self.session = session_data
            self.url = type('url', (), {'path': '/api/feed'})()
            self.headers = {}

    # Success Case
    req_success = MockRequest({"user": {"email": mock_user_email}})
    res = feed_creator_validator(req_success)
    assert res["role"] == "FeedCreator"

    # Failure Case (Insufficent Role)
    req_fail_role = MockRequest({"user": {"email": mock_user_email}})
    with pytest.raises(HTTPException) as exc_info:
        moderator_validator(req_fail_role)
    assert exc_info.value.status_code == 403

    # Failure Case (Unauthorized/No Session)
    req_fail_auth = MockRequest({})
    with pytest.raises(HTTPException) as exc_info:
        feed_creator_validator(req_fail_auth)
    assert exc_info.value.status_code == 401


# ---------- Quiz Repeat Exclusion & Fallback Tests ----------

def test_quiz_repeat_exclusion_and_fallback(monkeypatch):
    """Test that quiz generator excludes answered questions and falls back correctly."""
    mock_email = "student@deptagency.com"

    # Mock questions database entries
    class MockQuestion:
        def __init__(self, id, topic, difficulty, options, correct_index):
            self.id = id
            self.topic = topic
            self.difficulty = difficulty
            self.question = f"Question {id} text?"
            self.options = options
            self.correct_index = correct_index
            self.explanation = "Explanation"
            self.status = "published"

    mock_questions = [
        MockQuestion("b1", "caching", "beginner", ["A", "B"], 0),
        MockQuestion("b2", "caching", "beginner", ["A", "B"], 1),
        MockQuestion("b3", "caching", "beginner", ["A", "B"], 0),
    ]

    # Mock attempts to simulate user has answered questions b1 and b2
    class MockAttempt:
        def __init__(self, payload):
            self.payload = payload
            self.user_email = mock_email

    mock_attempts = [
        MockAttempt({
            "user_answers": {"b1": 0},
            "grading": {"b1": {"is_correct": True}} # answered correct
        }),
        MockAttempt({
            "user_answers": {"b2": 0},
            "grading": {"b2": {"is_correct": False}} # answered wrong
        })
    ]

    # Mock database session query results
    class MockSession:
        def __init__(self):
            pass
        def scalars(self, query):
            # Inspect query structure to return appropriate mock data
            q_str = str(query).lower()
            if "attempts" in q_str:
                return type('Result', (), {'all': lambda *args: mock_attempts})()
            elif "questions.id in" in q_str:
                # Wrong answers fallback pool (b2)
                return type('Result', (), {'all': lambda *args: [mock_questions[1]]})()
            elif "not in" in q_str:
                # Unseen pool (b3 only, since b1 and b2 are excluded)
                return type('Result', (), {'all': lambda *args: [mock_questions[2]]})()
            else:
                # All pool
                return type('Result', (), {'all': lambda *args: mock_questions})()

        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(quiz_generator, "get_session", lambda: MockSession())
    monkeypatch.setattr(quiz_generator.config, "QUESTIONS_PER_QUIZ", 1)

    # Run dynamic generation requesting 1 question
    # Should select "b3" as it is the only unseen question
    quiz = quiz_generator.generate("beginner", mock_email, count=1)
    assert len(quiz["questions"]) == 1
    assert quiz["questions"][0]["id"] == "b3"

    # If count is 2, it exhausts unseen (1) and must pull from wrong answer fallback (b2)
    quiz_with_fallback = quiz_generator.generate("beginner", mock_email, count=2)
    assert len(quiz_with_fallback["questions"]) == 2
    ids = [q["id"] for q in quiz_with_fallback["questions"]]
    assert "b3" in ids
    assert "b2" in ids  # pulled wrong answer


# ---------- Course Content & Session Status Endpoint Tests ----------

def test_course_endpoints(monkeypatch):
    """Test that course endpoints and user profile endpoints return expected data."""
    mock_framework_data = {"rings": [{"id": "code", "name": "code letters", "letters": [{"id": "code.c", "letter": "C"}]}]}
    mock_chapter_data = {"filename": "code-c.json", "ring": "code", "title": "C · Content", "content": {"title": "C · Content", "sections": []}}

    # Mock storage methods — patch the bindings inside the route modules
    # (content/routes.py imports `content_storage as content_storage`; the
    # /auth/me handler reads via `core.users.get_user`).
    from app.modules.content import routes as content_routes
    monkeypatch.setattr(content_routes.content_storage, "get_framework", lambda: mock_framework_data)
    monkeypatch.setattr(content_routes.content_storage, "get_all_chapters", lambda: [mock_chapter_data])
    monkeypatch.setattr(content_routes.content_storage, "get_chapter", lambda filename: mock_chapter_data if filename == "code-c.json" else None)

    from app.modules.auth import routes as auth_routes
    user_record = {
        "email": "test@deptagency.com",
        "name": "Test User",
        "picture": "",
        "role": "FeedCreator",
        "provider": "dev",
        "preferences": {},
    }
    monkeypatch.setattr(auth_routes.users, "get_user", lambda email: user_record if email == "test@deptagency.com" else None)
    # The dev /login/dev handler upserts the user via users.upsert_user — stub it so we don't hit the DB.
    monkeypatch.setattr(auth_routes.users, "upsert_user", lambda **kw: user_record)
    monkeypatch.setattr(auth_routes, "refresh_session_user", lambda req, email: req.session.setdefault("user", dict(user_record)))

    # 1. Course Framework API
    res_fw = client.get("/api/course/framework")
    assert res_fw.status_code == 200
    assert res_fw.json() == mock_framework_data

    # 2. Course Chapters List API
    res_chaps = client.get("/api/course/chapters")
    assert res_chaps.status_code == 200
    assert len(res_chaps.json()["chapters"]) == 1
    assert res_chaps.json()["chapters"][0]["filename"] == "code-c.json"

    # 3. Course Chapter Detail API
    res_chap = client.get("/api/course/chapters/code-c.json")
    assert res_chap.status_code == 200
    assert res_chap.json() == mock_chapter_data["content"]

    # 4. Auth me (Not Authenticated)
    res_me_unauth = client.get("/auth/me")
    assert res_me_unauth.status_code == 401

    # 5. Auth me (Authenticated)
    # Perform dev login first to establish session cookie in TestClient
    client.post("/login/dev", data={"email": "test@deptagency.com"})
    res_me_auth = client.get("/auth/me")
    assert res_me_auth.status_code == 200
    me_data = res_me_auth.json()
    assert me_data["email"] == "test@deptagency.com"
    assert me_data["role"] == "FeedCreator"
    assert me_data["initials"] == "TU"
