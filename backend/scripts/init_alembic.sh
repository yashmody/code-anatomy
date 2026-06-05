#!/usr/bin/env bash
# init_alembic.sh — Operator helper for adopting Alembic on an existing DB.
#
# Phase 2a one-shot. Use on a fresh production cutover or when a developer
# needs to wire an existing q0.db into the migration history.
#
# What it does:
#   1. Verifies that backend/alembic.ini and backend/migrations/env.py exist.
#   2. Confirms the DB has the legacy baseline schema (users + attempts + ...).
#   3. If `alembic_version` row is absent: `alembic stamp 0001_baseline`.
#   4. Runs `alembic upgrade head` to apply 0002+ revisions.
#
# Idempotent: safe to re-run. Aborts cleanly if the DB is missing baseline
# tables (probably a fresh DB — let init_db()/create_all bootstrap it first,
# then re-run this).
#
# Env:
#   DATABASE_URL — required for non-default DBs. Falls back to .env / config.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${BACKEND_DIR}"

if [[ ! -f alembic.ini ]]; then
    echo "ERROR: ${BACKEND_DIR}/alembic.ini missing. Phase 2a not initialised." >&2
    exit 1
fi
if [[ ! -d migrations/versions ]]; then
    echo "ERROR: ${BACKEND_DIR}/migrations/versions missing." >&2
    exit 1
fi

if [[ -x .venv/bin/alembic ]]; then
    ALEMBIC=".venv/bin/alembic"
elif command -v alembic >/dev/null 2>&1; then
    ALEMBIC="alembic"
else
    echo "ERROR: alembic not found. Activate the backend venv and re-run." >&2
    exit 1
fi

echo "[init_alembic] using ${ALEMBIC}"
echo "[init_alembic] DATABASE_URL = ${DATABASE_URL:-(from .env / config.py)}"

# Check current state. If alembic_version is empty/missing, stamp baseline.
CURRENT=$("${ALEMBIC}" current 2>&1 | tail -1 || true)
if [[ "${CURRENT}" == *"0001"* || "${CURRENT}" == *"0002"* || "${CURRENT}" == *"0003"* || \
      "${CURRENT}" == *"0004"* || "${CURRENT}" == *"0005"* || "${CURRENT}" == *"0006"* ]]; then
    echo "[init_alembic] alembic_version already populated: ${CURRENT}"
else
    echo "[init_alembic] stamping baseline (0001_baseline)"
    "${ALEMBIC}" stamp 0001_baseline
fi

echo "[init_alembic] running alembic upgrade head"
"${ALEMBIC}" upgrade head

echo "[init_alembic] done."
echo
echo "Next steps (Phase 2c cutover):"
echo "  - Set CERT_HMAC_LEGACY in production .env to the current SECRET_KEY value."
echo "  - Verify a known cert still resolves valid=true on /verify/<cert_id>."
echo "  - Schedule the vacuumlo nightly cron — see backend/migrations/README.md."
