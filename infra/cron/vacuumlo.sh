#!/usr/bin/env bash
#
# ============================================================================
# DEPT(R) Anatomy of Code - large-object orphan sweep (vacuumlo)
# ----------------------------------------------------------------------------
# Owner docs: 03-data-model.md section 7.2 (LO lifecycle), 06 section 6.4.
#
# WHAT: runs the standard Postgres contrib tool `vacuumlo` over the codecoder
# database. vacuumlo walks every oid-typed column (here:
# media_assets.large_object_oid) and unlinks any large object in
# pg_largeobject that is not referenced anywhere. This reclaims bytes leaked
# by FAILED uploads - store_media_asset creates the LO and commits before the
# metadata insert, so a failed insert orphans the LO, and only a sweep (not
# the BEFORE DELETE trigger from migration 0006) can reclaim it.
#
# WHY a cron AND a trigger: the trigger (migration 0006_lo_cleanup) is the
# authoritative happy-path reclaim on row DELETE. This sweep is the
# belt-and-braces safety net for the crash / partial-failure path. Run both.
#
# SAFETY: idempotent and safe to run daily. With no orphans it is empty-cost
# (it only unlinks LOs proven unreferenced across the whole DB). It never
# touches referenced bytes. deploy.sh installs this (or the equivalent
# systemd timer in 06 section 6.4) to run nightly as the postgres user.
#
# In production prefer the systemd timer (dept-vacuumlo.timer, 06 section 6.4)
# for journald integration; this script is the portable cron-friendly form and
# the thing an operator runs by hand during a drill.
# ============================================================================

set -euo pipefail

# -- Config (override via env) ----------------------------------------------
# Database to sweep. The app DB is "codecoder" (see deploy.sh / .env
# DATABASE_URL).
DB_NAME="${VACUUMLO_DB:-codecoder}"

# Connect as a role allowed to unlink large objects. On the VM this script
# runs as the OS "postgres" superuser via peer auth, so no password is needed.
DB_USER="${VACUUMLO_USER:-postgres}"

# Log destination. Created if missing; one line per run with a timestamp.
LOG_DIR="${VACUUMLO_LOG_DIR:-/var/log/dept-anatomy}"
LOG_FILE="${VACUUMLO_LOG_FILE:-${LOG_DIR}/vacuumlo.log}"

# -- Logging helper ---------------------------------------------------------
log() {
    # ISO-8601 UTC timestamp + message, appended to the log and echoed to stdout
    # (so cron mails it / journald captures it).
    printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" | tee -a "$LOG_FILE"
}

# Best-effort log dir. If we cannot create it (e.g. unprivileged dry-run on a
# dev box), fall back to a temp file so the script still completes.
if ! mkdir -p "$LOG_DIR" 2>/dev/null || [[ ! -w "$LOG_DIR" ]]; then
    LOG_FILE="$(mktemp -t dept-vacuumlo.XXXXXX.log)"
fi

# -- Preconditions ----------------------------------------------------------
if ! command -v vacuumlo >/dev/null 2>&1; then
    log "ERROR: vacuumlo not found on PATH. Install the postgresql-contrib package."
    exit 1
fi

# -- Run --------------------------------------------------------------------
# -v: verbose, so the log records how many orphans were removed.
# Exit non-zero from vacuumlo (e.g. cannot connect) propagates via set -e and
# is captured below so cron surfaces the failure.
log "vacuumlo start  db=${DB_NAME} user=${DB_USER}"

if vacuumlo -v -U "$DB_USER" "$DB_NAME" >>"$LOG_FILE" 2>&1; then
    log "vacuumlo done   db=${DB_NAME} (orphans reclaimed are listed above)"
else
    rc=$?
    log "ERROR: vacuumlo exited ${rc} for db=${DB_NAME}. See ${LOG_FILE}."
    exit "$rc"
fi
