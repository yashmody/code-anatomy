#!/bin/bash

# DEPT® Anatomy of Code - Local Environment Startup Script
# Multiplexes the FastAPI quiz backend, Python HTTP static server, and optional PostgreSQL db.
# Ensures all spawned background servers are cleanly killed upon exit (Ctrl+C).

# Terminate all background processes spawned by this script on exit
trap "kill 0" EXIT

# Parse options
START_DB=false
for arg in "$@"; do
    case $arg in
        --db)
            START_DB=true
            shift
            ;;
        *)
            # Unknown option
            ;;
    esac
done

echo "====================================================="
echo "  Starting DEPT® Anatomy of Code Local Dev Servers   "
echo "====================================================="

# Resolve absolute paths
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUIZ_DIR="$ROOT_DIR/quiz-certification"
VENV_PYTHON="$QUIZ_DIR/.venv/bin/python"
VENV_UVICORN="$QUIZ_DIR/.venv/bin/uvicorn"

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
    echo "🔴 [Error] Virtual environment not found at $QUIZ_DIR/.venv"
    echo "   Please set up your virtualenv first in the quiz-certification folder:"
    echo "   cd quiz-certification && python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

# 1. Start the Quiz Backend Server (FastAPI)
echo "🚀 [1/2] Starting Quiz Backend on port 8000..."
"$VENV_UVICORN" app.main:app --app-dir "$QUIZ_DIR" --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
QUIZ_PID=$!

# 2. Start the Static Web App Server
echo "🚀 [2/2] Starting Static Web Server on port 8080..."
python3 -m http.server 8080 --directory "$ROOT_DIR" > /dev/null 2>&1 &
APP_PID=$!

# Wait briefly for process validation
sleep 1.5

# Check if both background tasks are still alive
if ps -p $QUIZ_PID > /dev/null && ps -p $APP_PID > /dev/null; then
    echo "====================================================="
    echo "🟢 BOTH SERVERS RUNNING SUCCESSFULLY!"
    echo "====================================================="
    echo "👉 Main App:   http://localhost:8080/app/"
    echo "👉 Quiz App:   http://localhost:8000/"
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
