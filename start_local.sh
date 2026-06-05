#!/bin/bash

# DEPT® Anatomy of Code - Local Environment Startup Script
#
# v2 layout (see docs/architecture/v2/01-blueprint.md §7):
#   backend/    (was quiz-certification/) — FastAPI app, served by uvicorn
#   frontend/   (was app/) — buildless ES modules, served by python http.server
#   content/    (was content-architecture/ + content-system/) — JSON + frozen HTML
#
# Multiplexes the FastAPI quiz backend, Python HTTP static server, and
# optional PostgreSQL db. Ensures all spawned background servers are cleanly
# killed upon exit (Ctrl+C).
#
# Usage:
#   ./start_local.sh                       # development (default)
#   ./start_local.sh --env staging         # boot as staging
#   ./start_local.sh --env=production --db # production env + start local PG
#
# --env {development|staging|production} (05 §5 · environment management):
#   selects which backend/.env.<env>.example seeds backend/.env when no .env
#   exists, exports APP_ENV so the app's validate_for_env() agrees, and prints
#   the booted environment. An existing backend/.env is never overwritten.
#
# Note on /anatomy/ in local dev:
#   In production Apache aliases /anatomy/ → content/frozen/, but the
#   stdlib http.server cannot mount an alias. Resource clicks that go to
#   /anatomy/* will 404 locally — open content/frozen/anatomy-of-code-course.html
#   directly via http://127.0.0.1:8080/content/frozen/... if you need to test
#   them in dev. Phase 2 will add a tiny dev proxy script to close this gap.

# Terminate all background processes spawned by this script on exit
trap "kill 0" EXIT

# Parse options
START_DB=false
APP_ENV_SEL="development"   # --env: development (default) | staging | production
for arg in "$@"; do
    case $arg in
        --db)
            START_DB=true
            shift
            ;;
        --env=*)
            APP_ENV_SEL="${arg#--env=}"
            shift
            ;;
        --env)
            # `--env staging` form: the value is the next positional arg.
            # Marker; the value is consumed in the second pass below.
            shift
            ;;
        development|staging|production)
            # Bare value that follows a `--env` flag (the space-separated form).
            APP_ENV_SEL="$arg"
            shift
            ;;
        *)
            # Unknown option
            ;;
    esac
done

# Validate the selected environment.
case "$APP_ENV_SEL" in
    development|staging|production) ;;
    *)
        echo "🔴 [Error] Unknown --env '$APP_ENV_SEL'. Use: development | staging | production"
        exit 1
        ;;
esac

echo "====================================================="
echo "  Starting DEPT® Anatomy of Code Local Dev Servers   "
echo "====================================================="

# Resolve absolute paths
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
VENV_UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"

# 0a. Environment selection (05 §5 · environment management).
#     --env picks which backend/.env.<env>.example seeds backend/.env when no
#     .env exists yet. An existing backend/.env is NEVER overwritten — your
#     local edits and secrets are respected. APP_ENV is exported so the
#     FastAPI app's validate_for_env() sees the same environment we booted.
ENV_FILE="$BACKEND_DIR/.env"
ENV_EXAMPLE="$BACKEND_DIR/.env.${APP_ENV_SEL}.example"

if [ -f "$ENV_FILE" ]; then
    echo "🌱 Env: using existing $ENV_FILE (selected --env=$APP_ENV_SEL)"
elif [ -f "$ENV_EXAMPLE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "🌱 Env: no .env found — seeded from $ENV_EXAMPLE"
    echo "   Edit $ENV_FILE before any non-development run (secrets are placeholders)."
else
    echo "⚠️  Env: neither $ENV_FILE nor $ENV_EXAMPLE exists — booting with process env only."
fi

# Export APP_ENV for the backend process (overrides whatever .env carries so the
# flag you passed wins).
export APP_ENV="$APP_ENV_SEL"
echo "🌍 APP_ENV=$APP_ENV"

# 0. Optionally start PostgreSQL Database
if [ "$START_DB" = true ]; then
    echo "🐘 Attempting to start PostgreSQL database..."

    # Try pg_ctl (common for standard installations & Postgres.app)
    if command -v pg_ctl &> /dev/null; then
        echo "   - Starting PostgreSQL via pg_ctl..."
        if [ -d "/opt/homebrew/var/postgres" ]; then
            pg_ctl -D /opt/homebrew/var/postgres start > /dev/null 2>&1
        elif [ -d "/usr/local/var/postgres" ]; then
            pg_ctl -D /usr/local/var/postgres start > /dev/null 2>&1
        else
            pg_ctl start > /dev/null 2>&1
        fi

    # Try Homebrew Services
    elif command -v brew &> /dev/null && brew services list | grep -q "postgresql"; then
        echo "   - Starting PostgreSQL via Homebrew Services..."
        # Detect postgresql formula suffix (e.g. postgresql@14)
        PG_FORMULA=$(brew services list | grep "postgresql" | awk '{print $1}')
        brew services start "$PG_FORMULA" > /dev/null 2>&1

    # Try Docker
    elif command -v docker &> /dev/null; then
        if docker info >/dev/null 2>&1; then
            echo "   - Starting PostgreSQL via Docker container..."
            if docker ps -a | grep -q "pg-codecoder"; then
                docker start pg-codecoder > /dev/null
            else
                docker run --name pg-codecoder \
                  -e POSTGRES_DB=codecoder \
                  -e POSTGRES_PASSWORD=securepassword \
                  -p 5432:5432 \
                  -d postgres:15 > /dev/null
            fi
        else
            echo "⚠️  [Warning] Docker daemon is not running. Cannot start DB via Docker."
            echo "   Please start the Docker App or run PostgreSQL locally."
            exit 1
        fi
    else
        echo "❌ [Error] Could not find pg_ctl, brew services, or a running Docker daemon to start PostgreSQL."
        exit 1
    fi

    echo "   - Waiting for database readiness..."
    sleep 3
fi

# Check virtual environment
if [ ! -f "$VENV_UVICORN" ]; then
    echo "🔴 [Error] Virtual environment not found at $BACKEND_DIR/.venv"
    echo "   Please set up your virtualenv first in the backend folder:"
    echo "   cd backend && python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

# 1. Start the Quiz Backend Server (FastAPI)
#    Runs from backend/ so 'app.main:app' resolves against backend/app/.
echo "🚀 [1/2] Starting Quiz Backend on port 8000..."
"$VENV_PYTHON" -m uvicorn app.main:app --app-dir "$BACKEND_DIR" --reload --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
QUIZ_PID=$!

# 2. Start the Static Web App Server
#    Serves the whole repo so you can hit /frontend/index.html for the SPA
#    and /content/frozen/... for the monolith. /anatomy/* will 404 — see
#    the note at the top of this file.
echo "🚀 [2/2] Starting Static Web Server on port 8080..."
python3 -m http.server 8080 --directory "$ROOT_DIR" > /dev/null 2>&1 &
APP_PID=$!

# Wait briefly for process validation
sleep 1.5

# Check if both background tasks are still alive
if ps -p $QUIZ_PID > /dev/null && ps -p $APP_PID > /dev/null; then
    echo "====================================================="
    echo "🟢 BOTH SERVERS RUNNING SUCCESSFULLY!  (APP_ENV=$APP_ENV)"
    echo "====================================================="
    echo "👉 Main App:   http://127.0.0.1:8080/frontend/index.html"
    echo "👉 Course:     http://127.0.0.1:8080/content/frozen/anatomy-of-code-course.html"
    echo "👉 Quiz App:   http://127.0.0.1:8000/"
    echo "====================================================="
    echo "Press [Ctrl+C] to terminate all servers."

    # Keep script alive and wait on background processes
    wait
else
    echo "====================================================="
    echo "🔴 FAILED TO START DEV SERVERS!"
    echo "====================================================="
    if ! ps -p $QUIZ_PID > /dev/null; then
        echo "❌ Quiz Backend (Port 8000) failed to start. Check if port is in use."
    fi
    if ! ps -p $APP_PID > /dev/null; then
        echo "❌ Static Web Server (Port 8080) failed to start. Check if port is in use."
    fi
    exit 1
fi
