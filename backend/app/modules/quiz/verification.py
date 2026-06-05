"""Cert verification service — dev-mode aware, per-environment HMAC keys.

Owns the HMAC signing/verification rules for `attempts`. Storage code calls
into here; `storage.sign_attempt` and `storage.verify_signature` are thin
wrappers that delegate to `sign_record` / `verify_attempt` below.

Design contract: `docs/architecture/v2/07-security-baseline.md` §8 (cert
dev-mode) and `03-data-model.md` §2.5 (`signing_keys` table).

Key rules:

- The HMAC input string is unchanged from Phase 1
  (`cert_id|email_lower|score:.6f|submitted_at`), so every cert issued before
  Phase 2c verifies byte-identical so long as the key material is unchanged.
- Key material lives in environment variables. The `signing_keys` row stores
  the env-var *name* (`env_var_name`); this module reads `os.getenv(name)` at
  sign and verify time. Missing material is a hard fail.
- Per-environment isolation: a DEV cert cannot verify against the production
  key and vice versa. The verifier resolves the row by
  `attempts.signing_key_id`, falling back to the seeded `legacy-prod` row for
  rows that pre-date Phase 2a (defence in depth — the 0005 migration already
  backfilled every historical row, so this branch should never fire in
  practice).
- Rotation rules from §8.4 are enforced here: `can_verify=false` or
  `verify_until < now()` causes the verifier to refuse, with a `reason` field
  so the caller can render the correct badge.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime
from typing import Dict, Optional, Tuple

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import SigningKey


# Cert-ID prefix policy (07-security-baseline.md §8.2 + gate decision Q-2).
# Production keeps the bare `CCA-F-…` prefix forever so existing PDFs and
# every URL ever printed continue to verify. Non-prod environments stamp the
# environment tag onto the cert ID at generation time.
_ENV_TO_PREFIX = {
    "production": "",
    "staging": "STG-",
    "development": "DEV-",
}


# ── Key lookup + material ────────────────────────────────────────────────────


def _signing_key_to_dict(row: SigningKey) -> Dict:
    """Detach a SigningKey row into a plain dict so callers don't hold a session."""
    return {
        "id": row.id,
        "name": row.name,
        "environment": row.environment,
        "env_var_name": row.env_var_name,
        "is_active": bool(row.is_active),
        "can_verify": bool(row.can_verify),
        "verify_until": row.verify_until,
    }


def get_active_signing_key(environment: str) -> Optional[Dict]:
    """Return the currently-active signing-key row for `environment`, or None.

    Active = `is_active=TRUE`. Schema enforces one active row per environment
    via the partial unique index (`03 §2.5`).
    """
    with get_session() as s:
        row = s.scalar(
            select(SigningKey).where(
                SigningKey.environment == environment,
                SigningKey.is_active.is_(True),
            ).limit(1)
        )
        return _signing_key_to_dict(row) if row else None


def _get_signing_key_by_id(signing_key_id: int) -> Optional[Dict]:
    with get_session() as s:
        row = s.scalar(select(SigningKey).where(SigningKey.id == signing_key_id))
        return _signing_key_to_dict(row) if row else None


def _get_legacy_prod_key() -> Optional[Dict]:
    """Fallback for attempts whose `signing_key_id` is NULL — pre-2a rows."""
    with get_session() as s:
        row = s.scalar(select(SigningKey).where(SigningKey.name == "legacy-prod"))
        return _signing_key_to_dict(row) if row else None


def load_key_material(signing_key_row: Dict) -> bytes:
    """Read the HMAC secret from the env var named in the signing_keys row.

    Raises RuntimeError if the env var is unset/empty — we never silently fall
    back to `SECRET_KEY` (that would re-introduce F-CER-01).
    """
    name = signing_key_row["env_var_name"]
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Signing-key material missing: env var {name!r} is unset or empty. "
            f"Set it in the service's .env (see backend/.env.example)."
        )
    return value.encode("utf-8")


# ── HMAC formula ─────────────────────────────────────────────────────────────


def hmac_score_payload(attempt: Dict, key: bytes) -> str:
    """HMAC-SHA256 over the existing formula `cert_id|email|score|submitted_at`.

    Formula is UNCHANGED from Phase 1 (`storage._sign_payload`) — that's the
    no-loss constraint. Changing it would break every previously-issued cert.
    """
    email = (attempt.get("user") or {}).get("email") or attempt.get("user_email") or ""
    payload = "{cert_id}|{email}|{score:.6f}|{submitted_at}".format(
        cert_id=attempt["cert_id"],
        email=email.lower(),
        score=float(attempt["score"]),
        submitted_at=attempt["submitted_at"],
    )
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


# ── Sign + verify ────────────────────────────────────────────────────────────


def sign_record(record: Dict, environment: str) -> Tuple[str, int]:
    """Sign a fresh attempt with the active key for `environment`.

    Returns `(signature_hex, signing_key_id)`. The caller persists both on the
    `attempts` row. Raises if no active key exists for the environment or if
    its env-var material is missing.
    """
    key_row = get_active_signing_key(environment)
    if not key_row:
        raise RuntimeError(
            f"No active signing key for environment={environment!r}. "
            f"Seed one via the 0005_seed_data migration or insert a row in signing_keys."
        )
    key_bytes = load_key_material(key_row)
    signature = hmac_score_payload(record, key_bytes)
    return signature, key_row["id"]


def verify_attempt(attempt: Optional[Dict]) -> Dict:
    """Verify a stored attempt's HMAC. Returns a structured result.

    Result shape::

        {
            "valid": bool,
            "environment": "production" | "staging" | "development" | None,
            "key_active": bool,         # is the row still the current signer?
            "key_can_verify": bool,     # is verification still allowed?
            "reason": str,              # machine-readable code; "" on success
            "signing_key_id": int | None,
            "signing_key_name": str | None,
        }

    `reason` is one of: `""` (valid), `"no_attempt"`, `"no_signature"` (legacy
    cert), `"key_missing"` (signing_keys row gone), `"key_retired"`,
    `"key_expired"`, `"key_material_missing"`, `"signature_mismatch"`.
    """
    base = {
        "valid": False,
        "environment": None,
        "key_active": False,
        "key_can_verify": False,
        "reason": "",
        "signing_key_id": None,
        "signing_key_name": None,
    }

    if not attempt:
        base["reason"] = "no_attempt"
        return base

    stored_sig = attempt.get("signature")
    if not stored_sig:
        # Pre-signature legacy certs — verify_signature() historically returned
        # False here and the verify page rendered the "legacy" badge.
        base["environment"] = attempt.get("environment") or "production"
        base["reason"] = "no_signature"
        return base

    # Resolve the signing key. Prefer the FK; fall back to legacy-prod for
    # belt-and-braces against any row the backfill might have missed.
    sk_id = attempt.get("signing_key_id")
    key_row = _get_signing_key_by_id(sk_id) if sk_id else _get_legacy_prod_key()

    if not key_row:
        base["environment"] = attempt.get("environment") or "production"
        base["reason"] = "key_missing"
        return base

    base["signing_key_id"] = key_row["id"]
    base["signing_key_name"] = key_row["name"]
    base["environment"] = attempt.get("environment") or key_row["environment"]
    base["key_active"] = key_row["is_active"]
    base["key_can_verify"] = key_row["can_verify"]

    if not key_row["can_verify"]:
        base["reason"] = "key_retired"
        return base

    if key_row["verify_until"] is not None and key_row["verify_until"] < datetime.utcnow():
        base["reason"] = "key_expired"
        return base

    try:
        key_bytes = load_key_material(key_row)
    except RuntimeError:
        base["reason"] = "key_material_missing"
        return base

    expected = hmac_score_payload(attempt, key_bytes)
    if hmac.compare_digest(expected, stored_sig):
        base["valid"] = True
        return base

    base["reason"] = "signature_mismatch"
    return base


# ── Cert-ID prefix helper ────────────────────────────────────────────────────


def apply_env_prefix(cert_id: str, environment: str) -> str:
    """Stamp `DEV-`/`STG-` onto a freshly-minted cert ID when env != production.

    Idempotent — if the prefix is already present, returns the input unchanged.
    Legacy production certs (`CCA-F-…`) keep their prefix forever.
    """
    if not cert_id:
        return cert_id
    prefix = _ENV_TO_PREFIX.get(environment, "")
    if not prefix:
        return cert_id
    if cert_id.startswith(prefix):
        return cert_id
    # Only stamp the env tag onto the production-format ID; never double-stamp
    # nor mutate an unrecognised shape.
    if cert_id.startswith("CCA-F-"):
        return f"{prefix}{cert_id}"
    return cert_id


def current_environment() -> str:
    """Return the current process's APP_ENV, defaulting to 'production'.

    Phase 2d will move this into `core.config.Settings`; until then storage
    reads it via this helper so the dependency on `os.getenv` is in one place.
    """
    raw = os.getenv("APP_ENV", "production").strip().lower()
    if raw in _ENV_TO_PREFIX:
        return raw
    # Unknown values default to production rather than silently downgrading
    # security (a typo in APP_ENV must not turn off the watermark).
    return "production"
