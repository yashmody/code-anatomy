#!/bin/bash

# DEPT® Anatomy of Code - Local Environment Startup Script
# Multiplexes both the FastAPI quiz backend and Python HTTP static server.
# Ensures all spawned background servers are cleanly killed upon exit (Ctrl+C).

# Terminate all background processes spawned by this script on exit
trap "kill 0" EXIT

echo "====================================================="
echo "  Starting DEPT® Anatomy of Code Local Dev Servers   "
echo "====================================================="

# Resolve absolute paths
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUIZ_DIR="$ROOT_DIR/quiz-certification"
VENV_PYTHON="$QUIZ_DIR/.venv/bin/python"
VENV_UVICORN="$QUIZ_DIR/.venv/bin/uvicorn"

# Check virtual environment
if [ ! -f "$VENV_UVICORN" ]; then
    echo "🔴 [Error] Virtual environment not found at $QUIZ_DIR/.venv"
    echo "   Please set up your virtualenv first in the quiz-certification folder:"
    echo "   cd quiz-certification && python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

# 1. Start the Quiz Backend Server (FastAPI)
echo "🚀 [1/2] Starting Quiz Backend on port 8000..."
# Run uvicorn pointing to the app module directory
"$VENV_UVICORN" app.main:app --app-dir "$QUIZ_DIR" --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
QUIZ_PID=$!

# 2. Start the Static Web App Server
echo "🚀 [2/2] Starting Static Web Server on port 8080..."
# Run python http.server inside the workspace root so sibling paths resolve
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
