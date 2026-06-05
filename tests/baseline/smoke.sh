#!/usr/bin/env bash
#
# smoke.sh — wrapper around smoke.py for shell-callers / CI.
#
# Examples:
#   bash tests/baseline/smoke.sh                         # spawn + run + tear down
#   QUIZ_BASE_URL=http://localhost:8000 \
#     bash tests/baseline/smoke.sh --no-spawn            # attach to existing server
#
# All args after the script name are forwarded to smoke.py.
#
# Exit codes match smoke.py: 0 ok, 1 failed checks, 2 inconclusive.
#
# Idempotent: launching a second copy on the same port will get an inconclusive
# (exit=2) rather than corrupting the running server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Prefer the project venv if present so the script always has fastapi/uvicorn.
# v2 path: backend/.venv (was quiz-certification/.venv).
VENV_PY="${REPO_ROOT}/backend/.venv/bin/python"
if [[ -x "${VENV_PY}" ]]; then
  PY="${VENV_PY}"
else
  PY="$(command -v python3)"
fi

exec "${PY}" "${SCRIPT_DIR}/smoke.py" "$@"
