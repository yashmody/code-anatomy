"""Configuration loaded from environment variables.

In dev mode (default), Google OAuth and SMTP are stubbed — sign in with any email
and emails are written to ./outbox/ instead of being sent.

For production, set DEV_MODE=false and provide all credentials.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Mode
DEV_MODE = os.getenv("QUIZ_DEV_MODE", "true").lower() == "true"

# Session
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-CHANGE-IN-PROD-7f8a9b0c1d2e3f4a")

# Domain restriction (only emails ending in this domain can sign in)
ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "deptagency.com")

# Google OAuth (used when DEV_MODE=false)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

# SMTP (used when DEV_MODE=false)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@deptagency.com")
FROM_NAME = os.getenv("FROM_NAME", "DEPT® Academy")

# Quiz behaviour
QUIZ_RESULTS_DIR = Path(os.getenv("QUIZ_RESULTS_DIR", BASE_DIR / "quiz_results"))
CERTIFICATES_DIR = Path(os.getenv("CERTIFICATES_DIR", BASE_DIR / "certificates"))
OUTBOX_DIR = Path(os.getenv("OUTBOX_DIR", BASE_DIR / "outbox"))
QUESTION_BANK = BASE_DIR / "data" / "question_bank.json"

# DB — SQLite for local, set DATABASE_URL=postgresql://... for production
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'q0.db'}")

COOLDOWN_DAYS = int(os.getenv("COOLDOWN_DAYS", "7"))
PASS_THRESHOLD = float(os.getenv("PASS_THRESHOLD", "0.7"))  # 70%
QUIZ_DURATION_MIN = int(os.getenv("QUIZ_DURATION_MIN", "45"))   # 45 min for 30-question quiz
QUESTIONS_PER_QUIZ = int(os.getenv("QUESTIONS_PER_QUIZ", "30"))

# Ensure dirs exist
for d in (QUIZ_RESULTS_DIR, CERTIFICATES_DIR, OUTBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)
