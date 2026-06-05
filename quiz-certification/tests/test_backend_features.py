"""Verification test suite for dynamic RBAC, encryption, media detection, and quiz flow.
"""
import pytest
from fastapi.testclient import TestClient
from fastapi import Request, HTTPException

from app.main import app
from app import encryption, media_service, quiz_generator, storage, auth
from app.models import User, Question, Attempt

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
    
    # Mock storage.get_user to return user with FeedCreator role
    def mock_get_user(email):
        return {
            "email": mock_user_email,
            "name": "Test Creator",
            "picture": "",
            "role": "FeedCreator",
            "provider": "dev"
        }
    monkeypatch.setattr(storage, "get_user", mock_get_user)
    
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
            elif "not_in" in q_str:
                # Unseen pool (b3 only, since b1 and b2 are excluded)
                return type('Result', (), {'all': lambda *args: [mock_questions[2]]})()
            elif "in_" in q_str:
                # Wrong answers fallback pool (b2)
                return type('Result', (), {'all': lambda *args: [mock_questions[1]]})()
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
