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


@pytest.fixture(autouse=True)
def _clean_cache():
    """Reset the process-wide AppCache around every test.

    The content + feed read routes now memoise their DB reads in the shared
    cache singleton. Clearing before and after each test keeps the
    monkeypatched-loader assertions (e.g. test_course_endpoints) deterministic
    regardless of test order. Mirrors the autouse fixture in test_faq.py.
    """
    from app.core import cache as _cache
    _cache.clear()
    yield
    _cache.clear()


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

def test_rbac_require_permission_dependency(monkeypatch):
    """v2 RBAC: require_permission checks the session user's capability roles
    (read via users.roles_for) against PERMISSION_GRANTS, with platform_admin as
    the single global bypass.

    Replaces the v1 single-role require_role test. In v2 `require_role` is a
    deprecated shim that no route uses; every route enforces require_permission,
    and a user's capability lives in the `user_roles` join (not `users.role`).
    """
    from app.core import deps

    email = "test_creator@deptagency.com"
    # _session_user_or_401 reads users.get_user(email); the capability set comes
    # from users.roles_for(email). Patch both on the shared users module.
    monkeypatch.setattr(users, "get_user", lambda e: {"email": email} if e == email else None)
    held = {"value": set()}
    monkeypatch.setattr(users, "roles_for", lambda e: held["value"])

    class MockRequest:
        def __init__(self, session_data):
            self.session = session_data
            self.url = type("url", (), {"path": "/api/feed"})()
            self.headers = {}

    create_dep = deps.require_permission("feed.create")        # granted to feed_contributor
    moderate_dep = deps.require_permission("moderate.view")    # granted to feed_moderator

    # Success — a feed_contributor holds feed.create.
    held["value"] = {"learner", "feed_contributor"}
    res = create_dep(MockRequest({"user": {"email": email}}))
    assert res["email"] == email

    # 403 — a plain learner does not hold feed.create.
    held["value"] = {"learner"}
    with pytest.raises(HTTPException) as exc_info:
        create_dep(MockRequest({"user": {"email": email}}))
    assert exc_info.value.status_code == 403

    # platform_admin is the single global bypass — holds every permission.
    held["value"] = {"platform_admin"}
    assert moderate_dep(MockRequest({"user": {"email": email}}))["email"] == email

    # 401 — no session (path starts /api/ → JSON 401, not a redirect).
    with pytest.raises(HTTPException) as exc_info:
        create_dep(MockRequest({}))
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
    """Test course endpoints via the DB path (COURSE_SOURCE=db) with mocked storage.

    Forces COURSE_SOURCE=db so the route delegates to content_storage, which this
    test patches with deterministic mocks. This keeps the DB-rollback path fully
    exercised by the test suite regardless of the ARCH-2 default.
    """
    # Force COURSE_SOURCE=db so content_storage mocks are used (not file_loaders).
    from app.core import config as app_config
    monkeypatch.setattr(app_config.settings, "course_source", "db")

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
    # v2 user shape: persona (job family) replaces the v1 single `role`; capability
    # roles live in user_roles and are read via users.roles_for, which /auth/me
    # surfaces as `roles` + derived `permissions`.
    user_record = {
        "email": "test@deptagency.com",
        "name": "Test User",
        "picture": "",
        "persona": "architect",
        "provider": "dev",
        "preferences": {},
    }
    monkeypatch.setattr(auth_routes.users, "get_user", lambda email: user_record if email == "test@deptagency.com" else None)
    monkeypatch.setattr(auth_routes.users, "roles_for", lambda email: {"learner"})
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
    assert me_data["persona"] == "architect"           # v2: persona, not the v1 `role`
    assert me_data["roles"] == ["learner"]             # capability roles from roles_for
    assert "permissions" in me_data                     # derived from roles via PERMISSION_GRANTS
    assert me_data["initials"] == "TU"


# ---------- ARCH-2: file-served course content tests ----------

def test_course_endpoints_files_path(monkeypatch):
    """Test course endpoints via the file path (COURSE_SOURCE=files, the ARCH-2 default).

    Reads from the real on-disk content/source/course/ tree (no mocks for
    file_loaders) to prove the routes work end-to-end with actual files.
    Verifies:
      - /api/course/framework returns a dict with a "rings" list
      - /api/course/chapters returns all 31 published chapters with the
        correct response shape expected by fetchSectionFiles (ARCH-1)
      - /api/course/chapters/{filename} returns the full chapter dict for a
        real chapter, with the content key unwrapped (same shape as before ARCH-2)
      - /api/course/framework-explainer returns a non-empty dict
      - A non-existent chapter filename returns 404
    """
    # Ensure COURSE_SOURCE=files (the default, but be explicit for clarity).
    from app.core import config as app_config
    monkeypatch.setattr(app_config.settings, "course_source", "files")

    # 1. Framework
    res_fw = client.get("/api/course/framework")
    assert res_fw.status_code == 200
    fw_data = res_fw.json()
    assert "rings" in fw_data
    assert isinstance(fw_data["rings"], list)
    assert len(fw_data["rings"]) > 0

    # 2. Chapter list — the load-bearing fetchSectionFiles contract
    res_chaps = client.get("/api/course/chapters")
    assert res_chaps.status_code == 200
    chaps_data = res_chaps.json()
    # Top-level key must be "chapters"
    assert "chapters" in chaps_data
    chapters = chaps_data["chapters"]
    # All 31 currently-published chapters must be returned
    assert len(chapters) == 31, f"expected 31 chapters, got {len(chapters)}"
    # Every chapter entry must carry the three fields the SPA reads
    for ch in chapters:
        assert "filename" in ch, f"missing 'filename' key in {ch}"
        assert "ring" in ch,     f"missing 'ring' key in {ch}"
        assert "title" in ch,    f"missing 'title' key in {ch}"
    # filenames must be bare .json names (no path component)
    filenames = {ch["filename"] for ch in chapters}
    assert "anatomy-m00.json" in filenames
    assert "code-c.json" in filenames
    assert "adobe-aa.json" in filenames

    # 3. Single chapter — response is the raw chapter dict (content unwrapped)
    res_ch = client.get("/api/course/chapters/anatomy-m00.json")
    assert res_ch.status_code == 200
    ch_data = res_ch.json()
    # The chapter JSON itself is returned directly (not wrapped in an envelope)
    assert ch_data.get("frameworkAddress") == "anatomy.m00"
    assert ch_data.get("title") == "The Mental Model"
    assert "sections" in ch_data

    # 4. Framework-explainer
    res_expl = client.get("/api/course/framework-explainer")
    assert res_expl.status_code == 200
    expl_data = res_expl.json()
    assert isinstance(expl_data, (dict, list))  # it is a large dict; just check non-empty
    assert expl_data  # truthy — not null/empty

    # 5. Missing chapter → 404
    res_missing = client.get("/api/course/chapters/does-not-exist.json")
    assert res_missing.status_code == 404

    # 6. Ring derivation is correct for a sample of chapters
    ring_map = {ch["filename"]: ch["ring"] for ch in chapters}
    assert ring_map["anatomy-m00.json"] == "anatomy"
    assert ring_map["code-c.json"] == "code"
    assert ring_map["coder-r.json"] == "coder"
    assert ring_map["adobe-aa.json"] == "adobe"
    assert ring_map["ai-bmad.json"] == "ai"


def test_status_filter_excludes_draft_and_archived(monkeypatch, tmp_path):
    """Draft and archived chapters are invisible to the API (COURSE_SOURCE=files).

    Writes two synthetic chapter files — one draft, one archived — into a
    temporary sections directory, then patches the file_loaders._SECTIONS_DIR
    constant so the loaders read from that tmp dir.  Asserts that neither
    chapter appears in the list or is fetchable by name.
    """
    import json as _json
    from app.core import config as app_config
    from app.modules.content import file_loaders

    monkeypatch.setattr(app_config.settings, "course_source", "files")

    # Build a minimal tmp sections directory with three chapters:
    #   published_ch.json   — should be visible
    #   draft_ch.json       — must be hidden
    #   archived_ch.json    — must be hidden
    published = {
        "frameworkAddress": "code.c",
        "title": "Published Chapter",
        "status": "published",
        "sections": [{"id": "code.c.test", "blocks": [{"type": "prose", "html": "hi"}]}],
    }
    draft = {
        "frameworkAddress": "code.o",
        "title": "Draft Chapter",
        "status": "draft",
        "sections": [{"id": "code.o.test", "blocks": [{"type": "prose", "html": "hi"}]}],
    }
    archived = {
        "frameworkAddress": "code.d",
        "title": "Archived Chapter",
        "status": "archived",
        "sections": [{"id": "code.d.test", "blocks": [{"type": "prose", "html": "hi"}]}],
    }
    (tmp_path / "published_ch.json").write_text(_json.dumps(published), encoding="utf-8")
    (tmp_path / "draft_ch.json").write_text(_json.dumps(draft), encoding="utf-8")
    (tmp_path / "archived_ch.json").write_text(_json.dumps(archived), encoding="utf-8")

    # Redirect the file_loaders to the tmp directory.
    monkeypatch.setattr(file_loaders, "_SECTIONS_DIR", tmp_path)

    # Chapter list: only the published chapter appears.
    res_list = client.get("/api/course/chapters")
    assert res_list.status_code == 200
    filenames = [ch["filename"] for ch in res_list.json()["chapters"]]
    assert "published_ch.json" in filenames
    assert "draft_ch.json" not in filenames,    "draft chapter must not be in the public list"
    assert "archived_ch.json" not in filenames, "archived chapter must not be in the public list"
    assert len(filenames) == 1

    # Per-chapter fetch: published chapter is accessible.
    res_pub = client.get("/api/course/chapters/published_ch.json")
    assert res_pub.status_code == 200
    assert res_pub.json()["title"] == "Published Chapter"

    # Per-chapter fetch: draft and archived chapters return 404.
    res_draft = client.get("/api/course/chapters/draft_ch.json")
    assert res_draft.status_code == 404, "draft chapter must return 404"

    res_archived = client.get("/api/course/chapters/archived_ch.json")
    assert res_archived.status_code == 404, "archived chapter must return 404"
