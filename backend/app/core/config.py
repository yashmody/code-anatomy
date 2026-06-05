"""Configuration loaded from environment variables.

In dev mode (default), Google OAuth and SMTP are stubbed — sign in with any email
and emails are written to ./outbox/ instead of being sent.

For production, set DEV_MODE=false and provide all credentials.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# This file moved from app/config.py → app/core/config.py in v2 Phase 1.
# Walking up three parents (config.py → core/ → app/ → backend/) lands on the
# backend root, so all BASE_DIR-derived paths (data/, certificates/, .env)
# stay correct.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables from .env if it exists
load_dotenv(BASE_DIR / ".env")


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

# DB — Postgres required for production. Falls back to sqlite locally if not configured, but features like large objects require Postgres.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'q0.db'}")

COOLDOWN_DAYS = int(os.getenv("COOLDOWN_DAYS", "7"))
QUIZ_DURATION_MIN = int(os.getenv("QUIZ_DURATION_MIN", "45"))   # 45 min for 30-question quiz
QUESTIONS_PER_QUIZ = int(os.getenv("QUESTIONS_PER_QUIZ", "30"))

# Pass mark — absolute number of correct answers required to pass.
# Default: 25 of 30. This is the single source of truth for passing.
PASS_MARK_CORRECT = int(os.getenv("PASS_MARK_CORRECT", "25"))

# Encryption key for API responses (network tab protection) - must be 32 bytes (base64 encoded or raw string)
APP_PAYLOAD_SECRET = os.getenv("APP_PAYLOAD_SECRET", "dev-payload-secret-32bytes-long!")

# Media limits
MAX_VIDEO_SIZE_MB = 30
MAX_IMAGE_SIZE_MB = 2.5
MAX_VIDEO_DURATION_SEC = 60

# Derived percentage, used only for display (e.g. "Pass mark 83%").
PASS_THRESHOLD = (
    PASS_MARK_CORRECT / QUESTIONS_PER_QUIZ if QUESTIONS_PER_QUIZ else 0.0
)

# Static + templates — pointed at by main.py's StaticFiles / Jinja2Templates
# mounts. Kept at the backend root (not under app/) to match the legacy
# layout — moving them would silently change `url_for('static', ...)`
# resolution in the Jinja templates. Phase 2 (if it wants to relocate
# them under app/) does so as a deliberate move with template updates.
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure dirs exist
for d in (QUIZ_RESULTS_DIR, CERTIFICATES_DIR, OUTBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)
