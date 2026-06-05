#!/usr/bin/env bash
# ============================================================================
# DEPT Anatomy of Code — Directus operator bootstrap (idempotent).
# Phase 4a, Slice 4a-2.
#
# The SOURCE OF TRUTH for the parts a `directus schema snapshot` cannot
# capture cleanly: the directus_* tables + admin (via `directus bootstrap`),
# the collections bound over EXISTING Postgres tables, the staff roles, the
# collection permissions, and the cache-invalidation Flow.
#
# Run order:
#   1. npm install                       (once; installs the pinned directus)
#   2. bash bootstrap.sh                 (this script)
#   3. npm start  (or docker compose up) (serve)
#
# This script:
#   (a) runs `directus bootstrap` — creates directus_* tables + the admin
#       from ADMIN_EMAIL/ADMIN_PASSWORD in .env. Idempotent: Directus skips
#       if already bootstrapped.
#   (b) ensures Directus is RUNNING (the API calls in step c need a live
#       server). If it is not reachable, it starts it in the background and
#       waits for /server/health.
#   (c) runs register-collections.mjs over the Directus REST API: binds the
#       existing tables as collections (NO DDL), creates the 4 staff roles,
#       sets permissions per 05 §3, and creates the cache-invalidation Flow.
#
# Token handling: register-collections.mjs logs in as ADMIN_EMAIL/ADMIN_PASSWORD
# (read from .env) and uses the returned short-lived access_token in memory
# only. No long-lived token is written to disk. On the VM, prefer a dedicated
# bootstrap admin whose password rotates after first run.
#
# Re-runnable: every create is existence-guarded. A second run is a no-op.
# ============================================================================
set -euo pipefail

CMS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$CMS_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: cms/.env not found. Copy .env.example -> .env and fill it in." >&2
  exit 1
fi

# directus binary from local node_modules (pinned version).
DIRECTUS_BIN="$CMS_DIR/node_modules/.bin/directus"
if [[ ! -x "$DIRECTUS_BIN" ]]; then
  echo "ERROR: directus not installed. Run: npm install" >&2
  exit 1
fi

# Pull PUBLIC_URL / health endpoint from .env for the readiness check.
PUBLIC_URL="$(grep -E '^PUBLIC_URL=' .env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
PUBLIC_URL="${PUBLIC_URL:-http://localhost:8055}"
HEALTH_URL="${PUBLIC_URL%/}/server/health"

echo "== (a) directus bootstrap (directus_* tables + admin) =="
"$DIRECTUS_BIN" bootstrap

# --- (b) ensure a running server for the API-driven registration ----------
STARTED_HERE=0
DIRECTUS_PID=""
if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "== (b) Directus already running at $PUBLIC_URL =="
else
  echo "== (b) starting Directus in background for registration =="
  "$DIRECTUS_BIN" start > "$CMS_DIR/.bootstrap-directus.log" 2>&1 &
  DIRECTUS_PID=$!
  STARTED_HERE=1
  # wait up to ~60s for health
  for i in $(seq 1 60); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      echo "  Directus healthy after ${i}s"
      break
    fi
    sleep 1
    if [[ $i -eq 60 ]]; then
      echo "ERROR: Directus did not become healthy in 60s. See .bootstrap-directus.log" >&2
      [[ -n "$DIRECTUS_PID" ]] && kill "$DIRECTUS_PID" 2>/dev/null || true
      exit 1
    fi
  done
fi

cleanup() {
  if [[ "$STARTED_HERE" -eq 1 && -n "$DIRECTUS_PID" ]]; then
    echo "== stopping the bootstrap-only Directus instance (pid $DIRECTUS_PID) =="
    kill "$DIRECTUS_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# --- (c) register collections / roles / permissions / flow ----------------
echo "== (c) register collections, roles, permissions, flow =="
node "$CMS_DIR/register-collections.mjs"

echo ""
echo "Bootstrap complete."
echo "Next: paste the content_author role id (printed above) into"
echo "      AUTH_GOOGLE_DEFAULT_ROLE_ID in cms/.env, then run: npm start"
