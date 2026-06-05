"""Configuration loaded from environment variables (Phase 2d).

This module is the Tier-1 (secret) + structural-config seam for the v2
backend. Per `docs/architecture/v2/05-config-cms.md §7.1`, it exposes a single
typed `Settings` singleton built from environment variables (with optional
`.env` support via pydantic-settings) — Tier-2 runtime tunables come from
`app.core.cms_client.cfg(...)` instead.

Backward-compat: every module-level constant the v1 layout exposed
(`SECRET_KEY`, `ALLOWED_DOMAIN`, `GOOGLE_CLIENT_*`, `SMTP_*`, `BASE_DIR`, …)
is still re-exported here so 2b/2c/2e callers do not have to be touched in
this slice. They are computed once at module import from the `settings`
singleton.

In dev mode (default), Google OAuth and SMTP are stubbed — sign in with any
email and emails are written to ./outbox/ instead of being sent.

For production, set `APP_ENV=production` and provide all credentials. The
`Settings.validate_for_env()` model-validator refuses to construct the
singleton if a non-dev environment still carries dev-default secrets.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file lives at backend/app/core/config.py. Walking up three parents
# (config.py → core/ → app/ → backend/) lands on the backend root, so all
# BASE_DIR-derived paths (data/, certificates/, .env) stay correct across
# Phase 1 + Phase 2.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables from .env if it exists. We do this at module
# load (before Settings() is constructed) so that os.getenv-based fallback
# paths still see the file even if pydantic-settings is given a different
# env_file path.
load_dotenv(BASE_DIR / ".env")


# ─────────────────────────────────────────────────────────────────────────────
# Settings class
# ─────────────────────────────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Typed, env-driven settings for the v2 backend.

    Field names are the v2 canonical lower_snake form; Pydantic Settings is
    case-insensitive when reading env vars so existing UPPER_CASE entries in
    `.env` (e.g. `SECRET_KEY`) bind correctly.
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Run mode ────────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_base_url: str = "http://localhost:8000"

    # Legacy alias. The v1 codebase keyed branching on QUIZ_DEV_MODE; we keep
    # it as an explicit field so an operator that still sets it gets the
    # expected behaviour (DEV_MODE = quiz_dev_mode if explicitly false).
    quiz_dev_mode: bool = True

    # ── Tier-1 secrets ──────────────────────────────────────────────────────
    secret_key: SecretStr = SecretStr("dev-secret-CHANGE-IN-PROD-7f8a9b0c1d2e3f4a")
    app_payload_secret: SecretStr = SecretStr("dev-payload-secret-32bytes-long!")

    google_client_id: SecretStr = SecretStr("")
    google_client_secret: SecretStr = SecretStr("")
    # Optional override (per 05 §4.1 / C-26). Empty string = derive from
    # app_base_url.
    google_redirect_uri: str = ""

    smtp_user: SecretStr = SecretStr("")
    smtp_pass: SecretStr = SecretStr("")

    # Allowlist for first-admin bootstrap; not a key (re-tiered Tier-2 in 05
    # §1.5 / C-53). SecretStr would obscure logging — keep as plain string.
    admin_emails: str = ""
    dev_seed_admins: str = ""

    # Per-environment certificate HMAC keys. The runtime row is selected by
    # `signing_keys.environment = app_env`; the secret material is loaded
    # from the env var named in `env_var_name` (e.g. CERT_HMAC_PROD) — these
    # fields just hold the values so Phase 2c can read them through a single
    # typed seam.
    cert_hmac_legacy: Optional[SecretStr] = None
    cert_hmac_dev: Optional[SecretStr] = None
    cert_hmac_stg: Optional[SecretStr] = None
    cert_hmac_prod: Optional[SecretStr] = None

    # Rotation pre-stage slots (07 baseline). Optional.
    secret_key_next: Optional[SecretStr] = None
    google_client_secret_next: Optional[SecretStr] = None

    # ── Non-secret env config ───────────────────────────────────────────────
    allowed_domain: str = "deptagency.com"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_use_tls: bool = True
    from_email: str = "no-reply@deptagency.com"
    from_name: str = "DEPT® Academy"

    # ── Paths ───────────────────────────────────────────────────────────────
    quiz_results_dir: Path = BASE_DIR / "quiz_results"
    certificates_dir: Path = BASE_DIR / "certificates"
    outbox_dir: Path = BASE_DIR / "outbox"
    static_dir: Path = BASE_DIR / "static"
    templates_dir: Path = BASE_DIR / "templates"

    # ── Database ────────────────────────────────────────────────────────────
    # Kept as a plain string (not SecretStr) for backward-compat: v1 callers
    # in core/db.py and core/models.py do `config.DATABASE_URL.startswith(...)`
    # and `"postgresql" in config.DATABASE_URL`. Switching to SecretStr would
    # break those two read-sites without serving Phase 2d's contract.
    database_url: str = f"sqlite:///{BASE_DIR / 'q0.db'}"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # ── Quiz behaviour ──────────────────────────────────────────────────────
    cooldown_days: int = 7
    quiz_duration_min: int = 45
    questions_per_quiz: int = 30
    pass_mark_correct: int = 25

    # ── Media limits (currently hardcoded; 05 §6 migrates these to
    # app_config in a later phase). Kept as fields so .env can override them
    # for ops experiments today. ─────────────────────────────────────────────
    max_video_size_mb: float = 30
    max_image_size_mb: float = 2.5
    max_video_duration_sec: int = 60

    # ── Cache TTLs (Phase 2d / 06 cross-ref) ────────────────────────────────
    cache_ttl_framework: int = 900
    cache_ttl_feed: int = 30
    cache_ttl_app_config: int = 60

    # ── Cache backend (Phase 3 / 06 §4.2 — pluggable backing store) ──────────
    # `memory` is the default per the 2-worker topology decision (06 §4.2 /
    # gate §10 #1). `redis` swaps the backing store behind the same AppCache
    # interface for 4+ workers or multi-VM; it degrades gracefully back to
    # `memory` if the redis client is absent or the server is unreachable.
    cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"

    # ── LLM seam (no provider clients in 2d) ────────────────────────────────
    llm_provider: Literal["none", "anthropic", "openai"] = "none"
    llm_api_key: SecretStr = SecretStr("")

    # ── Directus seam (Phase 4a; receivers built in 2d) ─────────────────────
    directus_url: str = "http://localhost:8055"
    directus_admin_token: SecretStr = SecretStr("")

    # ── Ops ─────────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    csp_report_only: bool = True

    # ── Dev escape hatch (07 baseline) — never set outside development. ──
    keep_dev_secret: bool = False

    # ── Computed fields ─────────────────────────────────────────────────────

    def resolved_google_redirect_uri(self) -> str:
        """Return the Google OAuth redirect URI.

        Honour the explicit override if set (per 05 §4.1 / C-26 — protects
        already-registered Google Console redirects). Otherwise derive from
        APP_BASE_URL.
        """
        if self.google_redirect_uri:
            return self.google_redirect_uri
        return self.app_base_url.rstrip("/") + "/auth/google/callback"

    # ── Validators ──────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def validate_for_env(self) -> "Settings":
        """Refuse to construct a Settings whose env is non-dev but secrets are dev defaults.

        Format errors are RuntimeError-style ValueErrors (Pydantic wraps them
        into ValidationError). The messages identify the offending key so an
        operator can fix it without re-reading source.
        """
        if self.app_env == "development":
            return self

        if self.keep_dev_secret:
            # Explicit ops opt-out for dev-only environments that still want
            # to lie about being staging (e.g. local integration tests).
            # Never set in real deployments.
            return self

        errors: list[str] = []

        sk = self.secret_key.get_secret_value() if self.secret_key else ""
        if sk.startswith("dev-secret-"):
            errors.append(
                f"SECRET_KEY still carries the dev default while APP_ENV={self.app_env}"
            )

        aps = (
            self.app_payload_secret.get_secret_value() if self.app_payload_secret else ""
        )
        if aps.startswith("dev-payload-"):
            errors.append(
                f"APP_PAYLOAD_SECRET still carries the dev default while APP_ENV={self.app_env}"
            )

        if not self.allowed_domain:
            errors.append(
                f"ALLOWED_DOMAIN must be set when APP_ENV={self.app_env}"
            )

        if errors:
            joined = "; ".join(errors)
            raise ValueError(
                f"Refusing to start with dev defaults in APP_ENV={self.app_env}: {joined}"
            )

        return self


# ─────────────────────────────────────────────────────────────────────────────
# Singleton + backward-compat re-exports
# ─────────────────────────────────────────────────────────────────────────────

# Constructing the Settings runs validate_for_env(). In normal use it picks
# up `.env` from BASE_DIR. The constructor is the right place to fail-fast on
# misconfiguration — if it raises, the app does not start.
settings = Settings()


# Mode -----------------------------------------------------------------------
# DEV_MODE preserves the v1 boolean. The canonical truth in v2 is
# `settings.app_env == "development"`, but a number of 2b/2c/2e callers still
# read `config.DEV_MODE`; we honour both inputs:
#   - if APP_ENV is set, derive from it
#   - else fall back to QUIZ_DEV_MODE (the v1 env var)
_app_env_was_explicit = (
    os.getenv("APP_ENV") is not None or os.getenv("app_env") is not None
)
if _app_env_was_explicit:
    DEV_MODE: bool = settings.app_env == "development"
else:
    DEV_MODE = settings.quiz_dev_mode

# Tier-1 secrets — exported as plain strings for the legacy call-sites
# (`config.SECRET_KEY.encode(...)`, `config.APP_PAYLOAD_SECRET.encode(...)`,
# `config.GOOGLE_CLIENT_SECRET`). Phase 2b/2c/2e are free to migrate those
# call-sites to `settings.secret_key.get_secret_value()` at their leisure.
SECRET_KEY: str = settings.secret_key.get_secret_value()
APP_PAYLOAD_SECRET: str = settings.app_payload_secret.get_secret_value()

GOOGLE_CLIENT_ID: str = settings.google_client_id.get_secret_value()
GOOGLE_CLIENT_SECRET: str = settings.google_client_secret.get_secret_value()
GOOGLE_REDIRECT_URI: str = settings.resolved_google_redirect_uri()

# Non-secret env config ------------------------------------------------------
ALLOWED_DOMAIN: str = settings.allowed_domain
SMTP_HOST: str = settings.smtp_host
SMTP_PORT: int = settings.smtp_port
SMTP_USER: str = settings.smtp_user.get_secret_value()
SMTP_PASS: str = settings.smtp_pass.get_secret_value()
SMTP_USE_TLS: bool = settings.smtp_use_tls
FROM_EMAIL: str = settings.from_email
FROM_NAME: str = settings.from_name

# Paths ----------------------------------------------------------------------
QUIZ_RESULTS_DIR: Path = settings.quiz_results_dir
CERTIFICATES_DIR: Path = settings.certificates_dir
OUTBOX_DIR: Path = settings.outbox_dir
STATIC_DIR: Path = settings.static_dir
TEMPLATES_DIR: Path = settings.templates_dir
QUESTION_BANK: Path = BASE_DIR / "data" / "question_bank.json"

# DB -------------------------------------------------------------------------
DATABASE_URL: str = settings.database_url

# Quiz behaviour -------------------------------------------------------------
COOLDOWN_DAYS: int = settings.cooldown_days
QUIZ_DURATION_MIN: int = settings.quiz_duration_min
QUESTIONS_PER_QUIZ: int = settings.questions_per_quiz
PASS_MARK_CORRECT: int = settings.pass_mark_correct

# Media limits ---------------------------------------------------------------
MAX_VIDEO_SIZE_MB: float = settings.max_video_size_mb
MAX_IMAGE_SIZE_MB: float = settings.max_image_size_mb
MAX_VIDEO_DURATION_SEC: int = settings.max_video_duration_sec

# Derived percentage, used only for display (e.g. "Pass mark 83%").
PASS_THRESHOLD: float = (
    PASS_MARK_CORRECT / QUESTIONS_PER_QUIZ if QUESTIONS_PER_QUIZ else 0.0
)

# Ensure on-disk dirs exist so v1 call-sites that write into them keep
# working without an explicit init step.
for d in (QUIZ_RESULTS_DIR, CERTIFICATES_DIR, OUTBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)
