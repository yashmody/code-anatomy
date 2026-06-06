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
#   ./start_local.sh --env=production --db # production env + start local PG (legacy)
#   ./start_local.sh --with-cms            # also boot Directus on :8055
#
# REMOTE dev database (2026-06 cutover):
#   Local development now connects to the REMOTE shared instance's dev database
#   (codecoder_dev) over TLS — there is NO local Postgres any more (it took too
#   much disk). On FIRST run (no backend/.env yet, development env, interactive
#   terminal) the script PROMPTS for the DB connection — paste the DATABASE_URL
#   the maintainer emailed, or type host/port/db/user/password and it assembles
#   + URL-encodes the connection string into backend/.env (mode 600). A non-TTY
#   run, or leaving the host blank, keeps the .env.development.example placeholder.
#   --db (start a local Postgres) is now a LEGACY escape hatch — you do NOT need
#   it for normal dev. The OFFLINE smoke harness (scripts/smoke.sh) is separate:
#   it forces sqlite and never touches the network, so it stays self-contained.
#
# --with-cms (Phase 4a · 05-config-cms.md §5.5):
#   After the FastAPI + static server, boots Directus locally
#   (cd cms && npx directus start) and prints http://localhost:8055.
#   Without the flag, behaviour is unchanged. Requires cms/ (slice 4a-2),
#   cms/node_modules, and a reachable Postgres (use --db or a running PG).
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
WITH_CMS=false             # --with-cms: also boot Directus locally on :8055
APP_ENV_SEL="development"   # --env: development (default) | staging | production
for arg in "$@"; do
    case $arg in
        --db)
            START_DB=true
            shift
            ;;
        --with-cms)
            WITH_CMS=true
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

# First-run DB bootstrap: prompt for the connection and write DATABASE_URL into a
# freshly-seeded backend/.env. The maintainer emails the creds; the dev pastes
# them here once instead of hand-editing the template. Interactive TTY only —
# a non-interactive shell (CI) keeps the template placeholder untouched. The
# password is read WITHOUT echo and URL-encoded before it enters the connection
# string (real passwords carry @ # ! * which would otherwise break the URL).
prompt_db_into_env() {
    local env_file="$1"
    if [ ! -t 0 ]; then
        echo "   (non-interactive shell — left DATABASE_URL as the template placeholder; edit $env_file)"
        return 0
    fi
    echo ""
    echo "🔑 First run: configure the database connection (creds from the maintainer)."
    echo "   Paste the full DATABASE_URL if you were emailed one, or press Enter to type the parts."
    local full url=""
    read -r -p "   DATABASE_URL (blank = enter parts): " full
    if [ -n "$full" ]; then
        url="$full"
    else
        local host port db user pass ssl enc
        read -r -p "   DB host (e.g. 20.228.243.225): " host
        if [ -z "$host" ]; then
            echo "   ↪ Skipped — left the template placeholder. Edit $env_file before first run."
            return 0
        fi
        read -r -p "   DB port [5432]: " port;            port="${port:-5432}"
        read -r -p "   DB name [codecoder_dev]: " db;     db="${db:-codecoder_dev}"
        read -r -p "   DB username: " user
        read -r -s -p "   DB password (hidden): " pass;   echo ""
        read -r -p "   SSL mode [require]: " ssl;         ssl="${ssl:-require}"
        # URL-encode the password via stdin so it never appears in the process list.
        enc="$(printf '%s' "$pass" | python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))')"
        url="postgresql://${user}:${enc}@${host}:${port}/${db}?sslmode=${ssl}"
    fi
    # Replace any existing DATABASE_URL line, then append the new one. Done via
    # grep+append (not sed) to avoid escaping % & / in the connection string.
    grep -v '^DATABASE_URL=' "$env_file" > "$env_file.tmp" && mv "$env_file.tmp" "$env_file"
    printf 'DATABASE_URL=%s\n' "$url" >> "$env_file"
    chmod 600 "$env_file" 2>/dev/null || true
    # Masked confirmation — never print the password.
    local masked
    masked="$(printf '%s' "$url" | sed -E 's#://([^:]+):[^@]*@#://\1:****@#')"
    echo "   ✅ Wrote DATABASE_URL=$masked to $env_file (mode 600)."
}

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
    if [ "$APP_ENV_SEL" = "development" ]; then
        # First run: ask for the DB connection and write it into the new .env.
        prompt_db_into_env "$ENV_FILE"
    else
        echo "   Edit $ENV_FILE before any non-development run (secrets are placeholders;"
        echo "   staging/production DATABASE_URL is filled from the secret store, not here)."
    fi
else
    echo "⚠️  Env: neither $ENV_FILE nor $ENV_EXAMPLE exists — booting with process env only."
fi

# Database posture note (2026-06 cutover). Local dev no longer runs a local
# Postgres: the development env connects to the remote shared dev database over
# TLS. The offline smoke harness is the one exception (it forces sqlite).
if [ "$APP_ENV_SEL" = "development" ] && [ "$START_DB" != true ]; then
    echo "🛢️  DB: local dev connects to the REMOTE dev database (codecoder_dev) over TLS;"
    echo "        no local Postgres required. (Offline smoke uses sqlite via scripts/smoke.sh.)"
fi

# Export APP_ENV for the backend process (overrides whatever .env carries so the
# flag you passed wins).
export APP_ENV="$APP_ENV_SEL"
echo "🌍 APP_ENV=$APP_ENV"

# 0. Optionally start PostgreSQL Database
# LEGACY escape hatch: normal dev uses the REMOTE dev database (see the note
# above), so --db is only for an offline/local Postgres by choice. If you pass
# it, also point DATABASE_URL in backend/.env at the local server, otherwise the
# app still dials the remote host from the .env.development template.
if [ "$START_DB" = true ]; then
    echo "🐘 --db (legacy): starting a LOCAL PostgreSQL. Normal dev uses the remote dev DB."
    echo "   Make sure backend/.env DATABASE_URL points at localhost if you want to use it."
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

# 3. (Optional) Start Directus CMS  (--with-cms · Phase 4a · 05 §5.5)
#    Boots Directus on :8055 over the same Postgres the backend uses. Best-effort:
#    a CMS failure does NOT bring down the FastAPI/static pair — the flag is for
#    editorial work, not the runtime read path. Requires cms/ + cms/node_modules.
CMS_PID=""
CMS_DIR="$ROOT_DIR/cms"
if [ "$WITH_CMS" = true ]; then
    if [ ! -d "$CMS_DIR" ]; then
        echo "⚠️  --with-cms: no cms/ directory at $CMS_DIR (slice 4a-2 not present). Skipping CMS."
    elif ! command -v npx > /dev/null 2>&1; then
        echo "⚠️  --with-cms: npx not found on PATH. Install Node 18/20/22 LTS. Skipping CMS."
    elif [ ! -d "$CMS_DIR/node_modules" ]; then
        echo "⚠️  --with-cms: cms/node_modules missing. Run 'cd cms && npm install' first. Skipping CMS."
    else
        echo "🚀 [3/3] Starting Directus CMS on port 8055..."
        ( cd "$CMS_DIR" && npx directus start ) > /dev/null 2>&1 &
        CMS_PID=$!
    fi
fi

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
    if [ "$WITH_CMS" = true ] && [ -n "$CMS_PID" ] && ps -p "$CMS_PID" > /dev/null; then
        echo "👉 CMS Admin:  http://localhost:8055"
    elif [ "$WITH_CMS" = true ]; then
        echo "⚠️  CMS:        not running (see warnings above; check 'cd cms && npx directus start')"
    fi
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
