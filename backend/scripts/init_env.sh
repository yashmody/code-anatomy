#!/usr/bin/env bash
# init_env.sh — pick the right .env template for APP_ENV and copy it into place.
#
# Operator helper for first-time setup on a fresh host. Reads APP_ENV from
# the environment (default: development) and copies the matching
# .env.<env>.example to backend/.env iff backend/.env does not already exist.
#
# Idempotent: never overwrites an existing .env. The operator deletes it by
# hand if they want a clean slate.
#
# Usage:
#   APP_ENV=development bash backend/scripts/init_env.sh
#   APP_ENV=staging      bash backend/scripts/init_env.sh
#   APP_ENV=production   bash backend/scripts/init_env.sh
#
# Exit codes: 0 ok (copied or already present); 2 invalid APP_ENV; 3 template
# missing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_ENV="${APP_ENV:-development}"

case "${APP_ENV}" in
  development|staging|production) ;;
  *)
    echo "init_env.sh: invalid APP_ENV='${APP_ENV}' — expected development|staging|production" >&2
    exit 2
    ;;
esac

TEMPLATE="${BACKEND_DIR}/.env.${APP_ENV}.example"
TARGET="${BACKEND_DIR}/.env"

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "init_env.sh: template not found: ${TEMPLATE}" >&2
  exit 3
fi

if [[ -f "${TARGET}" ]]; then
  echo "init_env.sh: ${TARGET} already exists — leaving untouched."
  echo "             (delete it to re-initialise from ${TEMPLATE})"
  exit 0
fi

cp "${TEMPLATE}" "${TARGET}"
chmod 0600 "${TARGET}"
echo "init_env.sh: copied ${TEMPLATE} → ${TARGET} (mode 0600)"
echo "             review and fill in real secrets before starting the app."
