#!/usr/bin/env bash
# ============================================================================
# DEPT® · Anatomy of Code — single-VM deployment script
#   Targets: Ubuntu 20.04/22.04 (Azure default) · CentOS/RHEL 8
#
# Assumes the following are pre-installed on the VM:
#   • Apache httpd (apache2 on Ubuntu / httpd on RHEL)
#   • Python 3.9+ (python3 on Ubuntu / python39 on RHEL)
#   • PostgreSQL (postgresql on Ubuntu / postgresql-server on RHEL)
#
# What this script does:
#   • Syncs the bundle into $APP_HOME
#   • Creates a Python venv and installs pip dependencies
#   • Writes a .env if one does not exist
#   • Creates the PostgreSQL role + database (idempotent)
#   • Applies deploy_schema.sql (idempotent — IF NOT EXISTS throughout)
#   • Runs the ETL migration to seed questions, feed items, and course content
#   • Writes a systemd unit for the FastAPI/uvicorn process
#   • Writes an Apache vhost config (HTTP → HTTPS redirect + reverse proxy)
#   • Opens ports 80 and 443 in the firewall
#
# Layout produced on the VM (v2 paths — see docs/architecture/v2/01-blueprint.md §7):
#   https://<vm>/             → quiz + certification app (FastAPI, via proxy)
#   https://<vm>/app/         → static SPA (Feed / Manual / Read) — served from frontend/
#   https://<vm>/anatomy/     → frozen content monolith (course, checklist, runbooks, FAQs)
#                               served from content/frozen/
#
# Usage:
#   sudo ./deploy.sh                    # full first-time install
#   sudo ./deploy.sh --update           # pull new code + restart services only
#
#   # Production with OAuth:
#   sudo GOOGLE_CLIENT_ID=xxx GOOGLE_CLIENT_SECRET=yyy ./deploy.sh
#
# All steps are idempotent — safe to re-run.
# ============================================================================
set -euo pipefail

# ── Tunables (override via environment) ─────────────────────────────────────
APP_USER="${APP_USER:-cca}"
APP_HOME="${APP_HOME:-/opt/dept-anatomy}"
QUIZ_PORT="${QUIZ_PORT:-8000}"
# C-12 mitigation — quiz_sessions persistence lands in Phase 2a; until then keep
# workers=1 so the in-memory session map stays consistent across requests. See
# docs/architecture/v2/01-blueprint.md "Open issues / C-12".
QUIZ_WORKERS="${QUIZ_WORKERS:-1}"
DOMAIN="${DOMAIN:-internal.in.deptagency.com}"
SERVER_NAME="${SERVER_NAME:-$DOMAIN}"

# Application environment (05 §5 · environment management).
#   development | staging | production
# A real deploy defaults to production: the app's validate_for_env() then
# refuses to boot on dev-default SECRET_KEY / APP_PAYLOAD_SECRET, so the .env
# step below generates fresh secrets. Override for a staging box:
#   sudo APP_ENV=staging ./deploy.sh
APP_ENV="${APP_ENV:-production}"

# CSP rollout gate (07 §3 · safe-rollout path). 0 = Report-Only (observe
# violations without breaking the page); 1 = enforced Content-Security-Policy.
# Ship Report-Only first, watch the browser console / report-to sink, then
# re-run with CSP_ENFORCE=1 once the allowlist is proven clean.
CSP_ENFORCE="${CSP_ENFORCE:-0}"

DB_NAME="${DB_NAME:-codecoder}"
DB_USER="${DB_USER:-codecoder}"
DB_PASS="${DB_PASS:-}"

# ── Database connection mode (2026-06 cutover · remote shared Postgres) ──────
# DB_MODE selects HOW the database is provisioned and reached:
#   local    — legacy single-VM path: deploy.sh installs/preflights a LOCAL
#              Postgres, edits pg_hba.conf / listen_addresses, talks to it over
#              the /var/run/postgresql Unix socket. This is the DEFAULT so an
#              unset environment behaves exactly as before.
#   external — the database lives on a REMOTE shared Postgres server. deploy.sh
#              does NO local server install, NO socket detection, NO pg_hba /
#              listen_addresses edits. It connects over TCP+TLS to DB_HOST and
#              builds DATABASE_URL with ?sslmode=$DB_SSLMODE.
# Convenience: if DB_HOST is set to a non-local host, external is implied even
# when DB_MODE is left at its default.
DB_MODE="${DB_MODE:-local}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
# TLS posture for the remote connection. require = encrypt (no server-identity
# check); verify-full = encrypt AND validate the server cert against a CA
# (provide the CA via PGSSLROOTCERT / sslrootcert). require is the floor.
DB_SSLMODE="${DB_SSLMODE:-require}"
# PROVISION_DB controls whether deploy.sh creates databases/roles/extensions on
# the remote instance (needs a remote superuser password) or assumes a DBA has
# pre-created them:
#   auto  — provision IF a superuser password is available, else assume pre-made
#   true  — force provisioning (requires POSTGRES_SUPERUSER_PASSWORD)
#   false — never provision; the DBA pre-created everything (DML-only app role)
PROVISION_DB="${PROVISION_DB:-auto}"
# A non-local DB_HOST implies external mode (so an operator only has to set the
# host). Covers IPs and FQDNs; the loopback/socket forms stay local.
case "$DB_HOST" in
  localhost|127.0.0.1|::1|/*|"") : ;;   # local socket / loopback → keep DB_MODE
  *) DB_MODE="external" ;;
esac

# ── Directus CMS (Phase 4a · 05-config-cms.md §5.5, §8.2) ───────────────────
# Directus is the editorial write plane: a separate Node service over the SAME
# Postgres, reverse-proxied under /cms/. It is ADDITIVE and gated — set
# DEPLOY_DIRECTUS=false to skip the whole block and deploy only the FastAPI
# application plane (an operator who hasn't stood the CMS up yet, or a box that
# only serves traffic).
DEPLOY_DIRECTUS="${DEPLOY_DIRECTUS:-true}"
CMS_PORT="${CMS_PORT:-8055}"
CMS_SERVICE_NAME="cms-directus"
# Directus runs as its own OS user so its file/socket surface is isolated from
# the FastAPI app user. Falls back to the app user if you'd rather not add one.
CMS_USER="${CMS_USER:-directus}"
# Scoped DB role Directus connects as (07 baseline / 03 §5). The matching role
# is created/granted by Alembic migration 0008 (slice 4a-1); deploy.sh only sets
# its password. This role is PER-ENVIRONMENT so a dev Directus credential can
# never reach prod (the role is GRANTed only on its own database). Canonical
# name is DIRECTUS_DB_ROLE; CMS_DB_USER is kept as a back-compat alias.
#   prod=directus_app · staging=directus_app_stg · dev=directus_app_dev
DIRECTUS_DB_ROLE="${DIRECTUS_DB_ROLE:-${CMS_DB_USER:-directus_app}}"
CMS_DB_USER="$DIRECTUS_DB_ROLE"
# Leave CMS_DB_PASS empty to auto-generate on first run.
CMS_DB_PASS="${CMS_DB_PASS:-}"
# Directus admin bootstrap account (the break-glass local admin from §8.2 step
# 4). The first SSO Platform Admin from ADMIN_EMAILS is mirrored in later, but
# this account always exists so a misconfigured SSO can't lock everyone out.
CMS_ADMIN_EMAIL="${CMS_ADMIN_EMAIL:-${ADMIN_EMAIL:-admin@${DOMAIN}}}"
CMS_ADMIN_PASSWORD="${CMS_ADMIN_PASSWORD:-}"

# PostgreSQL superuser password (the password for the 'postgres' PG role).
# When set, all admin psql calls run as root with PGPASSWORD and -U postgres,
# so the script never depends on peer/ident auth or pg_hba.conf changes.
# Supply it on the command line:
#   sudo POSTGRES_SUPERUSER_PASSWORD='yourpw' ./deploy.sh
POSTGRES_SUPERUSER_PASSWORD="${POSTGRES_SUPERUSER_PASSWORD:-${PGPASSWORD:-}}"

# TLS — override if your certs live elsewhere.
# Defaults are set after OS detection below.
CERT_FILE="${CERT_FILE:-}"
KEY_FILE="${KEY_FILE:-}"
CHAIN_FILE="${CHAIN_FILE:-}"

GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"

SERVICE_NAME="cca-quiz"
TOTAL_STEPS=11
# Directus (Phase 4a) adds one step when DEPLOY_DIRECTUS=true. Resolved after
# the deploy.env auto-load below so an operator override counts.
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_START=$SECONDS
STEP_NUM=0

# ── Auto-load deploy.env if present ─────────────────────────────────────────
# Optional file next to this script. Any of the tunables above can be set
# here so you don't have to pass them on the command line every run.
# Example deploy.env:
#   POSTGRES_SUPERUSER_PASSWORD='your-postgres-password'
#   GOOGLE_CLIENT_ID='...'
#   GOOGLE_CLIENT_SECRET='...'
#   DOMAIN='internal.in.deptagency.com'
# This file is gitignored — see .gitignore.
if [[ -f "$SRC_DIR/deploy.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SRC_DIR/deploy.env"
  set +a
  # Re-resolve the env-var-backed tunables in case deploy.env set them
  POSTGRES_SUPERUSER_PASSWORD="${POSTGRES_SUPERUSER_PASSWORD:-${PGPASSWORD:-}}"
  DOMAIN="${DOMAIN:-internal.in.deptagency.com}"
  SERVER_NAME="${SERVER_NAME:-$DOMAIN}"
  APP_ENV="${APP_ENV:-production}"
  CSP_ENFORCE="${CSP_ENFORCE:-0}"
  # Directus (Phase 4a) — re-resolve in case deploy.env set them.
  DEPLOY_DIRECTUS="${DEPLOY_DIRECTUS:-true}"
  CMS_PORT="${CMS_PORT:-8055}"
  CMS_USER="${CMS_USER:-directus}"
  CMS_ADMIN_EMAIL="${CMS_ADMIN_EMAIL:-${ADMIN_EMAIL:-admin@${DOMAIN}}}"
  # Database mode (2026-06 cutover) — re-resolve in case deploy.env set them.
  DB_MODE="${DB_MODE:-local}"
  DB_HOST="${DB_HOST:-localhost}"
  DB_PORT="${DB_PORT:-5432}"
  DB_SSLMODE="${DB_SSLMODE:-require}"
  PROVISION_DB="${PROVISION_DB:-auto}"
  case "$DB_HOST" in
    localhost|127.0.0.1|::1|/*|"") : ;;
    *) DB_MODE="external" ;;
  esac
  # Per-env Directus role (canonical DIRECTUS_DB_ROLE; CMS_DB_USER is the alias).
  DIRECTUS_DB_ROLE="${DIRECTUS_DB_ROLE:-${CMS_DB_USER:-directus_app}}"
  CMS_DB_USER="$DIRECTUS_DB_ROLE"
fi

# Directus adds one numbered step to the run when enabled.
[[ "$DEPLOY_DIRECTUS" == "true" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))

# ── Console helpers ──────────────────────────────────────────────────────────
# Colours
C_CYAN='\033[1;36m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[1;31m'
C_DIM='\033[2m'
C_BOLD='\033[1m'
C_RESET='\033[0m'

# step N "title" — prints a numbered section header with elapsed time
step() {
  STEP_NUM=$((STEP_NUM + 1))
  local elapsed=$(( SECONDS - DEPLOY_START ))
  printf '\n%b%s%b\n' "$C_CYAN" \
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "$C_RESET"
  printf '%b[%d/%d]%b %b%s%b  %b+%ds%b\n' \
    "$C_CYAN" "$STEP_NUM" "$TOTAL_STEPS" "$C_RESET" \
    "$C_BOLD" "$*" "$C_RESET" \
    "$C_DIM" "$elapsed" "$C_RESET"
  printf '%b%s%b\n' "$C_CYAN" \
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "$C_RESET"
}

ok()   { printf '  %b✓%b  %s\n'  "$C_GREEN"  "$C_RESET" "$*"; }
info() { printf '  %b·%b  %s\n'  "$C_CYAN"   "$C_RESET" "$*"; }
warn() { printf '  %b!!%b %s\n'  "$C_YELLOW" "$C_RESET" "$*"; }
die()  { printf '%bERR%b %s\n'   "$C_RED"    "$C_RESET" "$*" >&2; exit 1; }

# wait_dot — prints a dot on the same line while waiting
wait_dot() { printf '.'; }

[[ $EUID -eq 0 ]] || die "Run as root:  sudo ./deploy.sh"

UPDATE_ONLY=false
[[ "${1:-}" == "--update" ]] && UPDATE_ONLY=true

# ── Startup banner ───────────────────────────────────────────────────────────
printf '\n%b' "$C_CYAN"
printf '╔══════════════════════════════════════════════════════════╗\n'
printf '║   DEPT®  ·  Anatomy of Code  ·  Deployment Script       ║\n'
printf '║   Domain : %-46s║\n' "$DOMAIN"
printf '║   Target : %-46s║\n' "$APP_HOME"
printf '║   Env    : %-46s║\n' "$APP_ENV"
printf '║   Mode   : %-46s║\n' "$( $UPDATE_ONLY && echo '--update (code + restart only)' || echo 'full install')"
[[ -f "$SRC_DIR/deploy.env" ]] && \
printf '║   Config : %-46s║\n' "deploy.env loaded ✓"
printf '╚══════════════════════════════════════════════════════════╝\n'
printf '%b\n' "$C_RESET"

# ── OS detection ─────────────────────────────────────────────────────────────
if grep -qi 'ubuntu\|debian' /etc/os-release 2>/dev/null; then
  OS_FAMILY="debian"
  APACHE_SERVICE="apache2"
  APACHE_CONF_DIR="/etc/apache2"
  APACHE_SITE_FILE="/etc/apache2/sites-available/${SERVICE_NAME}.conf"
  APACHE_LOG_DIR="/var/log/apache2"
  APACHE_TEST="apache2ctl -t"
  CERT_FILE="${CERT_FILE:-/etc/ssl/certs/${DOMAIN}.crt}"
  KEY_FILE="${KEY_FILE:-/etc/ssl/private/${DOMAIN}.key}"
  info "OS family : Ubuntu / Debian"
else
  OS_FAMILY="rhel"
  APACHE_SERVICE="httpd"
  APACHE_CONF_DIR="/etc/httpd"
  APACHE_SITE_FILE="/etc/httpd/conf.d/${SERVICE_NAME}.conf"
  APACHE_LOG_DIR="/var/log/httpd"
  APACHE_TEST="httpd -t"
  CERT_FILE="${CERT_FILE:-/etc/pki/tls/certs/${DOMAIN}.crt}"
  KEY_FILE="${KEY_FILE:-/etc/pki/tls/private/${DOMAIN}.key}"
  info "OS family : RHEL / CentOS"
fi

# ── pg_exec helper ───────────────────────────────────────────────────────────
# Run a psql command as the PostgreSQL superuser.
#
# EXTERNAL mode (remote shared Postgres):
#   • Requires POSTGRES_SUPERUSER_PASSWORD. Connects over TCP to the REMOTE host:
#     PGPASSWORD=… psql -U postgres -h $DB_HOST -p $DB_PORT, with SSL forced via
#     PGSSLMODE=$DB_SSLMODE. No Unix socket, no peer auth — those don't exist on
#     a managed remote instance. Callers must NOT depend on this when there is no
#     superuser password (the caller guards with the DB_PROVISION flag instead).
#
# LOCAL mode (legacy single-VM path):
#   • If POSTGRES_SUPERUSER_PASSWORD is set: run psql directly as root with
#     PGPASSWORD + `-U postgres` over the Unix socket. No pg_hba edits.
#   • Otherwise: fall back to `runuser -l postgres` (peer auth path), wrapped
#     in `timeout` so any hang surfaces within 10 seconds.
#
# The caller passes the psql command string (e.g. "psql -c 'SELECT 1'").
# This helper transparently adds -U postgres plus the right host/port.
pg_exec() {
  local raw_cmd="$*"
  if [[ "$DB_MODE" == "external" ]]; then
    # Remote instance: TCP + TLS, superuser password is mandatory here.
    local injected="${raw_cmd/#psql/psql -U postgres -h ${DB_HOST} -p ${DB_PORT}}"
    PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
    PGSSLMODE="${DB_SSLMODE}" \
    PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-5}" \
      timeout 15 bash -c "$injected"
  elif [[ -n "$POSTGRES_SUPERUSER_PASSWORD" ]]; then
    # Insert -U postgres -h $PGHOST after the leading "psql" token so callers
    # don't have to remember to add them. e.g. "psql -c '...'" becomes
    # "psql -U postgres -h /var/run/postgresql -c '...'".
    local injected="${raw_cmd/#psql/psql -U postgres -h ${PGHOST:-/var/run/postgresql}}"
    PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
    PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-3}" \
      timeout 10 bash -c "$injected"
  else
    local cmd="PGCONNECT_TIMEOUT=${PGCONNECT_TIMEOUT:-3} ${PGHOST:+PGHOST=$PGHOST} $raw_cmd"
    if command -v runuser &>/dev/null; then
      timeout 10 runuser -l postgres -c "$cmd"
    else
      timeout 10 su - postgres -c "$cmd"
    fi
  fi
}

# ── db_provision_enabled ─────────────────────────────────────────────────────
# Resolve PROVISION_DB (auto|true|false) into a yes/no decision for whether
# deploy.sh should create databases / roles / extensions on the (remote) server.
#   auto  → yes IFF a superuser password is available
#   true  → yes (the caller dies later if no password is set)
#   false → no  (DBA pre-created everything)
# Echoes "yes" or "no".
db_provision_enabled() {
  case "$PROVISION_DB" in
    true)  echo "yes" ;;
    false) echo "no" ;;
    auto|*)
      if [[ -n "$POSTGRES_SUPERUSER_PASSWORD" ]]; then echo "yes"; else echo "no"; fi
      ;;
  esac
}

# ── build_database_url ───────────────────────────────────────────────────────
# Compose the DATABASE_URL the FastAPI app reads, branching on DB_MODE:
#   local    → postgresql://USER:PASS@localhost:5432/DBNAME   (no sslmode — the
#              app talks to the co-resident server over loopback/socket).
#   external → postgresql://USER:PASS@DB_HOST:DB_PORT/DBNAME?sslmode=DB_SSLMODE
#              (TLS enforced via the URL query; psycopg2/SQLAlchemy honour it).
# Args: <user> <pass>. The password is passed verbatim — callers redact it when
# echoing. Note: a password containing URL-reserved characters would need
# percent-encoding; the generated passwords (token_urlsafe) are URL-safe.
build_database_url() {
  local u="$1" p="$2"
  if [[ "$DB_MODE" == "external" ]]; then
    printf 'postgresql://%s:%s@%s:%s/%s?sslmode=%s' \
      "$u" "$p" "$DB_HOST" "$DB_PORT" "$DB_NAME" "$DB_SSLMODE"
  else
    printf 'postgresql://%s:%s@localhost:5432/%s' "$u" "$p" "$DB_NAME"
  fi
}

# Redacted host:port/db?sslmode suffix for log lines (never prints the password).
db_url_display() {
  if [[ "$DB_MODE" == "external" ]]; then
    printf 'postgresql://%s:***@%s:%s/%s?sslmode=%s' \
      "$DB_USER" "$DB_HOST" "$DB_PORT" "$DB_NAME" "$DB_SSLMODE"
  else
    printf 'postgresql://%s:***@localhost:5432/%s' "$DB_USER" "$DB_NAME"
  fi
}

# ── pg_socket_dir ────────────────────────────────────────────────────────────
# Find where the PostgreSQL server is actually creating its Unix socket.
# Checks the two standard locations: /var/run/postgresql (Debian/RHEL PGDG)
# and /tmp (some source builds). Returns the first one that has the socket.
pg_socket_dir() {
  for d in /var/run/postgresql /tmp; do
    if [[ -S "$d/.s.PGSQL.5432" ]]; then
      echo "$d"; return 0
    fi
  done
  return 1
}

# ── env_set ──────────────────────────────────────────────────────────────────
# Set or update a KEY=VALUE line in an env file safely.
# Uses Python so values with special chars (|, &, /, \, etc.) don't break sed.
#
#   env_set <file> <KEY> <VALUE>
env_set() {
  local file="$1" key="$2" value="$3"
  python3 - "$file" "$key" "$value" <<'PY'
import sys, pathlib
path = pathlib.Path(sys.argv[1])
key  = sys.argv[2]
val  = sys.argv[3]
new_line = f"{key}={val}"
if not path.exists():
    path.write_text(new_line + "\n"); raise SystemExit
lines = path.read_text().splitlines()
out, found = [], False
for ln in lines:
    stripped = ln.lstrip()
    if stripped.startswith(f"{key}=") or stripped.startswith(f"#{key}="):
        out.append(new_line); found = True
    else:
        out.append(ln)
if not found:
    out.append(new_line)
path.write_text("\n".join(out) + "\n")
PY
}

# ── pg_hba_path ──────────────────────────────────────────────────────────────
# Locate pg_hba.conf by filesystem inspection (no psql call required).
# Covers PGDG (/var/lib/pgsql/<ver>/data) and Debian (/etc/postgresql/<ver>/main).
pg_hba_path() {
  for f in \
      /var/lib/pgsql/16/data/pg_hba.conf \
      /var/lib/pgsql/15/data/pg_hba.conf \
      /var/lib/pgsql/14/data/pg_hba.conf \
      /var/lib/pgsql/13/data/pg_hba.conf \
      /var/lib/pgsql/12/data/pg_hba.conf \
      /var/lib/pgsql/data/pg_hba.conf \
      /etc/postgresql/16/main/pg_hba.conf \
      /etc/postgresql/15/main/pg_hba.conf \
      /etc/postgresql/14/main/pg_hba.conf \
      /etc/postgresql/13/main/pg_hba.conf \
      /etc/postgresql/12/main/pg_hba.conf; do
    [[ -f "$f" ]] && { echo "$f"; return 0; }
  done
  return 1
}

# ── ensure_postgres_peer_auth ────────────────────────────────────────────────
# Make sure the postgres OS user can connect to the postgres PG role via the
# Unix socket without a password. Prepends `local all postgres peer` to
# pg_hba.conf if not already there, then reloads PostgreSQL.
# Idempotent — safe to re-run.
ensure_postgres_peer_auth() {
  local hba="$1"
  local svc="$2"
  [[ -f "$hba" ]] || return 1

  # Already has a working rule for the postgres user via local socket?
  if grep -qE "^\s*local\s+all\s+postgres\s+(peer|trust)" "$hba"; then
    return 0
  fi
  info "Adding 'local all postgres peer' to $hba …"
  # Backup once
  [[ -f "${hba}.deploy-backup" ]] || cp -p "$hba" "${hba}.deploy-backup"
  # Prepend the rule before any other 'local' rule
  if grep -qE "^\s*local\s+" "$hba"; then
    sed -i "0,/^\s*local\s\+/{s||local   all   postgres   peer\nlocal   |}" "$hba"
  else
    # No existing local rules — add at top of file
    sed -i "1i local   all   postgres   peer" "$hba"
  fi
  info "Reloading $svc to apply auth change…"
  systemctl reload "$svc" 2>/dev/null || systemctl restart "$svc" || true
  # Give the reload a moment
  sleep 1
  ok "Peer auth enabled for postgres user"
  return 0
}

# ── pg_service_name ──────────────────────────────────────────────────────────
# Resolve the active (or installed) PostgreSQL systemd unit name.
pg_service_name() {
  for candidate in \
      postgresql \
      postgresql-16 postgresql-15 postgresql-14 postgresql-13 postgresql-12 \
      "postgresql@16-main" "postgresql@15-main" "postgresql@14-main" \
      "postgresql@13-main" "postgresql@12-main"; do
    if systemctl is-active --quiet "$candidate" 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  for candidate in \
      postgresql \
      postgresql-16 postgresql-15 postgresql-14 postgresql-13 postgresql-12; do
    if systemctl list-unit-files --type=service 2>/dev/null \
        | grep -q "^${candidate}\.service"; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

# SELinux check (RHEL only)
SELINUX_ON=false
if [[ "$OS_FAMILY" == "rhel" ]] \
   && command -v getenforce &>/dev/null \
   && [[ "$(getenforce 2>/dev/null)" == "Enforcing" ]]; then
  SELINUX_ON=true
  info "SELinux   : Enforcing — will apply httpd policies"
fi

# ── Database mode banner ─────────────────────────────────────────────────────
# Surface the chosen DB mode (and, when external, the remote host + DBA
# prerequisites) before any DB work runs. The password is never printed.
DB_PROVISION="$(db_provision_enabled)"
if [[ "$DB_MODE" == "external" ]]; then
  printf '\n  %b▣ Database mode : EXTERNAL (remote shared Postgres)%b\n' "$C_BOLD" "$C_RESET"
  info "Remote host : ${DB_HOST}:${DB_PORT}  (TLS sslmode=${DB_SSLMODE})"
  info "Database    : ${DB_NAME}   App role: ${DB_USER}   Directus role: ${DIRECTUS_DB_ROLE}"
  if [[ "$DB_PROVISION" == "yes" ]]; then
    info "Provisioning: ON — will create db/roles/extensions on the remote (superuser password supplied)"
  else
    warn "Provisioning: OFF — assuming the DBA pre-created the following on ${DB_HOST}:"
    warn "  • database '${DB_NAME}'"
    warn "  • extensions pgcrypto + hstore inside '${DB_NAME}'"
    warn "  • login role '${DB_USER}' (app, DML-only) with a password + GRANTs on '${DB_NAME}'"
    warn "  • login role '${DIRECTUS_DB_ROLE}' (Directus) with a password + GRANTs on '${DB_NAME}'"
    warn "  • TLS enabled on the server (connections use sslmode=${DB_SSLMODE})"
    warn "  Set PROVISION_DB=true + POSTGRES_SUPERUSER_PASSWORD to have deploy.sh do this instead."
  fi
  # The whole local-Postgres preflight assumes a local server — there is none.
  warn "Local Postgres install/preflight, socket detection, pg_hba and"
  warn "listen_addresses edits are SKIPPED in external mode (DB_MODE=local to restore)."
else
  printf '\n  %b▣ Database mode : LOCAL (single-VM Postgres on this host)%b\n' "$C_BOLD" "$C_RESET"
  info "Local Postgres will be preflighted/provisioned over the Unix socket as today."
fi

# ── STEP 1 · Pre-flight checks ───────────────────────────────────────────────
step "Pre-flight checks"

if ! $UPDATE_ONLY; then
  # Python — prefer 3.9+ explicitly. The pinned versions in
  # requirements.txt (jinja2==3.1.4 etc.) require Python ≥3.7, so we
  # refuse 3.6 with a clear install hint.
  PYBIN=""
  for candidate in python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$candidate" &>/dev/null; then
      PYBIN="$(command -v "$candidate")"; break
    fi
  done

  # If no 3.8+ found, offer to install python39 on RHEL automatically
  if [[ -z "$PYBIN" && "$OS_FAMILY" == "rhel" ]]; then
    warn "No Python ≥3.8 found. Trying to install python39 from RHEL AppStream…"
    if dnf install -y python39 python39-devel python39-pip 2>&1 | tail -3 \
        | while read -r l; do info "  $l"; done; then
      PYBIN="$(command -v python3.9)"
      ok "python39 installed: $PYBIN"
    fi
  fi

  # Last-resort fallback (Ubuntu apt)
  if [[ -z "$PYBIN" ]] && command -v python3 &>/dev/null; then
    PY_FALLBACK="$(command -v python3)"
    FALLBACK_VER="$("$PY_FALLBACK" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    # Only accept if ≥3.7
    if "$PY_FALLBACK" -c 'import sys; sys.exit(0 if sys.version_info >= (3,7) else 1)'; then
      PYBIN="$PY_FALLBACK"
    fi
  fi

  if [[ -z "$PYBIN" ]]; then
    if [[ "$OS_FAMILY" == "rhel" ]]; then
      die "Python ≥3.8 required. Install with:  sudo dnf install python39 python39-devel python39-pip"
    else
      die "Python ≥3.8 required. Install with:  sudo apt install python3.10 python3.10-venv python3.10-dev"
    fi
  fi

  PY_VER="$("$PYBIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  ok "Python      : $PYBIN  ($PY_VER)"

  # python3-venv / build tools (Ubuntu)
  if [[ "$OS_FAMILY" == "debian" ]]; then
    if ! "$PYBIN" -c "import venv" &>/dev/null; then
      info "Installing python3-venv…"
      apt-get install -y -q python3-venv python3-pip
      ok "python3-venv installed"
    fi
    for pkg in build-essential libpq-dev python3-dev; do
      if ! dpkg -s "$pkg" &>/dev/null; then
        info "Installing $pkg…"
        apt-get install -y -q "$pkg"
        ok "$pkg installed"
      else
        ok "$pkg          : already present"
      fi
    done
  fi

  # Apache
  if [[ "$OS_FAMILY" == "debian" ]]; then
    command -v apache2 &>/dev/null \
      || die "apache2 not found. Install: sudo apt install apache2 libapache2-mod-proxy"
    ok "Apache      : $(apache2 -v 2>&1 | head -1)"
  else
    command -v httpd &>/dev/null \
      || die "httpd not found. Install: sudo dnf install httpd mod_ssl"
    ok "Apache      : $(httpd -v 2>&1 | head -1)"
  fi

  # PostgreSQL client
  command -v psql &>/dev/null \
    || die "psql not found. Install the PostgreSQL client package."
  ok "psql        : $(psql --version)"

  # PostgreSQL connectivity
  if [[ "$DB_MODE" == "external" ]]; then
    # ── EXTERNAL: remote shared Postgres ──────────────────────────────────────
    # No local server: skip socket detection, service check, pg_hba/peer auth.
    # We only verify the psql CLIENT exists, then (when provisioning) confirm we
    # can reach the REMOTE instance over TCP+TLS as the superuser. When NOT
    # provisioning, the runtime app role connects later from .env — we don't need
    # superuser reachability and skip the trial entirely.
    info "PG mode     : external — local server preflight skipped"
    if [[ "$DB_PROVISION" == "yes" ]]; then
      if [[ -z "$POSTGRES_SUPERUSER_PASSWORD" ]]; then
        die "PROVISION_DB requires POSTGRES_SUPERUSER_PASSWORD to reach ${DB_HOST}. Set it, or use PROVISION_DB=false (DBA pre-creates)."
      fi
      info "Verifying remote superuser reachability ${DB_HOST}:${DB_PORT} (sslmode=${DB_SSLMODE}) …"
      if pg_exec "psql -c 'SELECT 1'" >/dev/null 2>&1; then
        ok "PostgreSQL  : reachable over TLS at ${DB_HOST}:${DB_PORT}"
      else
        info "Captured psql error:"
        pg_exec "psql -c 'SELECT 1'" 2>&1 | head -5 | while read -r l; do warn "  $l"; done
        die "Cannot reach the remote Postgres as superuser. Check DB_HOST/DB_PORT, the superuser password, TLS, and that the server allows your IP."
      fi
    else
      ok "Provisioning off — assuming DBA pre-created db/roles/extensions on ${DB_HOST} (see banner above)"
    fi
  else
    # ── LOCAL: single-VM Postgres (legacy path, unchanged) ────────────────────
    PG_SVC="$(pg_service_name || echo 'postgresql-14')"
    info "PG service  : $PG_SVC"

    if ! systemctl is-active --quiet "$PG_SVC"; then
      die "$PG_SVC is not running. Start it: systemctl start $PG_SVC"
    fi
    ok "PG service  : active"

    # Find the actual socket location BEFORE attempting any psql call.
    # This avoids the silent TCP-fallback hang.
    PG_SOCK="$(pg_socket_dir || echo '')"
    if [[ -z "$PG_SOCK" ]]; then
      warn "No PostgreSQL Unix socket found in /var/run/postgresql or /tmp"
      info "Diagnostics:"
      info "  ls -la /var/run/postgresql/ :"
      ls -la /var/run/postgresql/ 2>&1 | head -5 | while read -r l; do info "    $l"; done
      info "  ls -la /tmp/.s.PGSQL.5432   :"
      ls -la /tmp/.s.PGSQL.5432 2>&1 | head -3 | while read -r l; do info "    $l"; done
      info "  Listening TCP ports        :"
      ss -tlnp 2>/dev/null | grep -E ':(5432|postgres)' \
        | while read -r l; do info "    $l"; done || true
      die "Cannot locate the Postgres socket. The server is running but unreachable. Check: journalctl -u $PG_SVC -n 30"
    fi
    ok "Socket dir  : $PG_SOCK"
    export PGHOST="$PG_SOCK"
    export PGCONNECT_TIMEOUT=3

    # Two auth paths:
    #   1. POSTGRES_SUPERUSER_PASSWORD supplied → use it directly (no pg_hba edits).
    #   2. No password → fall back to peer auth, adding the rule to pg_hba.conf
    #      if it's missing.
    if [[ -n "$POSTGRES_SUPERUSER_PASSWORD" ]]; then
      ok "Auth mode   : password (POSTGRES_SUPERUSER_PASSWORD env var)"
    else
      PG_HBA_PATH="$(pg_hba_path || echo '')"
      if [[ -n "$PG_HBA_PATH" ]]; then
        ok "pg_hba.conf : $PG_HBA_PATH"
        ensure_postgres_peer_auth "$PG_HBA_PATH" "$PG_SVC"
        ok "Auth mode   : peer (postgres OS user → postgres PG role)"
      else
        warn "Could not locate pg_hba.conf — no auth fallback available"
        die  "Set POSTGRES_SUPERUSER_PASSWORD and re-run: sudo POSTGRES_SUPERUSER_PASSWORD='...' ./deploy.sh"
      fi
    fi

    # Trial connection
    if pg_exec "psql -c 'SELECT 1'" >/dev/null 2>&1; then
      ok "PostgreSQL  : reachable via socket ($PG_SOCK)"
    else
      info "Captured psql error:"
      pg_exec "psql -c 'SELECT 1'" 2>&1 | head -5 | while read -r l; do warn "  $l"; done
      if [[ -n "$POSTGRES_SUPERUSER_PASSWORD" ]]; then
        die "psql rejected the supplied POSTGRES_SUPERUSER_PASSWORD — check the password is correct."
      else
        die "psql failed. Either set POSTGRES_SUPERUSER_PASSWORD=... or fix $PG_HBA_PATH auth."
      fi
    fi
  fi

  ok "All pre-flight checks passed"
else
  PYBIN="$APP_HOME/backend/.venv/bin/python"
  PG_SVC="$(pg_service_name || echo 'postgresql-14')"
  info "Update mode — skipping pre-flight checks"
  info "Using venv  : $PYBIN"
fi

# ── STEP 2 · Service user ────────────────────────────────────────────────────
step "Service user"

if ! id "$APP_USER" &>/dev/null; then
  useradd --system --create-home --home-dir "/home/$APP_USER" --shell /sbin/nologin "$APP_USER"
  ok "Created user '$APP_USER'  (system, nologin)"
else
  ok "User '$APP_USER' already exists — skipping"
fi

# ── STEP 3 · Sync bundle ─────────────────────────────────────────────────────
step "Sync bundle → $APP_HOME"

# Guard: refuse to ship frontend JavaScript that does not parse. A single
# syntax error — e.g. an editor silently swapping a straight ' for a smart
# quote ‘ ’ — would otherwise break the WHOLE SPA in production (one bad module
# fails to load and the router dies). We validate the SOURCE tree before rsync,
# so a broken file never reaches $APP_HOME. This runs in --update mode too
# (where the pre-flight step is skipped), since that is the common path for
# shipping new SPA code.
JS_CHECK_NODE="${NODE_BIN:-$(command -v node || true)}"
if [[ -n "$JS_CHECK_NODE" ]]; then
  info "Validating frontend JS (node --check) …"
  js_bad=0
  while IFS= read -r -d '' jsf; do
    if ! "$JS_CHECK_NODE" --check "$jsf" 2>/tmp/cca-jscheck.err; then
      warn "  syntax error: ${jsf#"$SRC_DIR"/}"
      sed 's/^/      /' /tmp/cca-jscheck.err >&2 || true
      js_bad=$((js_bad + 1))
    fi
  done < <(find "$SRC_DIR/frontend" -name '*.js' -not -path '*/node_modules/*' -print0)
  if [[ "$js_bad" -gt 0 ]]; then
    die "$js_bad frontend JS file(s) failed syntax check — refusing to deploy. Fix the file(s) above and re-run."
  fi
  ok "Frontend JS syntax OK"
else
  warn "node not found — skipping frontend JS syntax guard (install Node LTS to enable it)."
fi

mkdir -p "$APP_HOME"
info "Running rsync from $SRC_DIR …"

# v2 path layout (see docs/architecture/v2/01-blueprint.md §7):
#   $APP_HOME/backend/         (was quiz-certification/)
#   $APP_HOME/frontend/        (was app/)
#   $APP_HOME/content/source/  (was content-architecture/)
#   $APP_HOME/content/frozen/  (was content-system/)
RSYNC_OUT="$(rsync -a --delete --stats \
  --exclude '.venv/' \
  --exclude 'backend/quiz_results/' \
  --exclude 'backend/certificates/' \
  --exclude 'backend/outbox/' \
  --exclude 'backend/.env' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "$SRC_DIR/backend" \
  "$SRC_DIR/frontend" \
  "$SRC_DIR/content" \
  "$APP_HOME/" 2>&1)"

# Print key rsync stats
echo "$RSYNC_OUT" | grep -E 'Number of files:|transferred|speedup' | while read -r line; do
  info "$line"
done

QUIZ_DIR="$APP_HOME/backend"
mkdir -p "$QUIZ_DIR"/{quiz_results,certificates,outbox}
ok "Bundle synced to $APP_HOME"

# ── STEP 4 · Python venv + dependencies ─────────────────────────────────────
step "Python virtualenv + pip dependencies"

if [[ ! -d "$QUIZ_DIR/.venv" ]]; then
  info "Creating virtualenv at $QUIZ_DIR/.venv …"
  "$PYBIN" -m venv "$QUIZ_DIR/.venv"
  ok "Virtualenv created"
else
  ok "Virtualenv exists — reusing"
fi

info "Upgrading pip…"
"$QUIZ_DIR/.venv/bin/pip" install --upgrade pip --quiet

info "Installing requirements from requirements.txt…"
"$QUIZ_DIR/.venv/bin/pip" install -r "$QUIZ_DIR/requirements.txt" \
  | grep -E '^(Collecting|Successfully installed|Already satisfied)' \
  | while read -r line; do info "$line"; done || true

ok "pip dependencies up to date"

# ── STEP 5 · Environment file (.env) ─────────────────────────────────────────
step "Environment file (.env)"

if [[ ! -f "$QUIZ_DIR/.env" ]]; then
  info "Creating from .env.example …"
  cp "$QUIZ_DIR/.env.example" "$QUIZ_DIR/.env"

  SECRET="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  env_set "$QUIZ_DIR/.env" SECRET_KEY "$SECRET"
  ok "Generated SECRET_KEY"

  # ── Environment management (05 §5) ─────────────────────────────────────────
  # Stamp APP_ENV so the app's validate_for_env() boots in the right mode.
  # The .env.example shipped here is the dev template (APP_ENV=development,
  # QUIZ_DEV_MODE=true). For staging/production we overwrite both and provide
  # the secrets validate_for_env() insists on (SECRET_KEY + APP_PAYLOAD_SECRET
  # must not carry their dev defaults). The per-env .env.*.example templates
  # (.env.development.example / .env.staging.example / .env.production.example,
  # authored in Phase 2d) document the full key set for hand-tuning.
  env_set "$QUIZ_DIR/.env" APP_ENV "$APP_ENV"
  ok "APP_ENV              → $APP_ENV"

  # APP_PAYLOAD_SECRET — required non-dev in staging/production (the app rejects
  # the 'dev-payload-' default). Generate it unconditionally so a dev box also
  # gets a real value.
  PAYLOAD_SECRET="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  env_set "$QUIZ_DIR/.env" APP_PAYLOAD_SECRET "$PAYLOAD_SECRET"
  ok "Generated APP_PAYLOAD_SECRET"

  # Certificate-signing continuity (03 §7 / cert HMAC chain):
  #   • CERT_HMAC_LEGACY mirrors the SECRET_KEY that signed certs at v2 cutover,
  #     so every previously issued certificate keeps verifying. We seed it from
  #     the SECRET_KEY just generated for this fresh install.
  #   • CERT_HMAC_PROD is the active production signing key — generated fresh.
  # Only set these if the template left them blank (don't clobber an operator
  # who pre-populated CERT_HMAC_LEGACY with the real cutover key).
  if ! grep -qE '^CERT_HMAC_LEGACY=.+' "$QUIZ_DIR/.env"; then
    env_set "$QUIZ_DIR/.env" CERT_HMAC_LEGACY "$SECRET"
    ok "CERT_HMAC_LEGACY     → mirrored from SECRET_KEY (cert continuity)"
  else
    ok "CERT_HMAC_LEGACY     → preserved from template (operator-supplied)"
  fi
  if ! grep -qE '^CERT_HMAC_PROD=.+' "$QUIZ_DIR/.env"; then
    CERT_PROD="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
    env_set "$QUIZ_DIR/.env" CERT_HMAC_PROD "$CERT_PROD"
    ok "Generated CERT_HMAC_PROD"
  fi

  # In a non-development env, the v1 dev-login path must be off so the OAuth
  # flow is the only way in. QUIZ_DEV_MODE=false also aligns DEV_MODE with
  # APP_ENV in config.py for the handful of legacy call-sites that read it.
  if [[ "$APP_ENV" != "development" ]]; then
    env_set "$QUIZ_DIR/.env" QUIZ_DEV_MODE "false"
  fi

  if [[ -z "$DB_PASS" ]]; then
    DB_PASS="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(24))')"
    ok "Generated DB password"
  fi
  # DATABASE_URL: local (loopback) or external (remote host + ?sslmode=) per DB_MODE.
  DB_URL="$(build_database_url "$DB_USER" "$DB_PASS")"

  # Q-14: GOOGLE_REDIRECT_URI is set on first create only — never overwritten on
  # subsequent deploys. Operators who customise this (e.g. /oauth/google/callback
  # for a non-default OAuth flow, or a CDN-fronted host) keep their value across
  # `./deploy.sh --update` runs. See docs/architecture/v2/01-blueprint.md Q-14.
  if ! grep -qE '^GOOGLE_REDIRECT_URI=' "$QUIZ_DIR/.env"; then
    env_set "$QUIZ_DIR/.env" GOOGLE_REDIRECT_URI "https://${DOMAIN}/auth/google/callback"
    ok "OAuth redirect URI   → https://${DOMAIN}/auth/google/callback (Q-14: set only if missing)"
  else
    ok "OAuth redirect URI   → preserved from existing .env (Q-14)"
  fi

  env_set "$QUIZ_DIR/.env" DATABASE_URL "$DB_URL"
  ok "DATABASE_URL         → $(db_url_display)"

  if [[ -n "$GOOGLE_CLIENT_ID" && -n "$GOOGLE_CLIENT_SECRET" ]]; then
    env_set "$QUIZ_DIR/.env" QUIZ_DEV_MODE        "false"
    env_set "$QUIZ_DIR/.env" GOOGLE_CLIENT_ID     "$GOOGLE_CLIENT_ID"
    env_set "$QUIZ_DIR/.env" GOOGLE_CLIENT_SECRET "$GOOGLE_CLIENT_SECRET"
    ok "Mode                 → PRODUCTION (OAuth enabled, APP_ENV=$APP_ENV)"
    warn "Remember to set SMTP_HOST/USER/PASS in $QUIZ_DIR/.env"
  elif [[ "$APP_ENV" != "development" ]]; then
    # APP_ENV is staging/production but no OAuth creds were supplied. The app
    # will boot (secrets are real), but the OAuth login flow is not wired yet.
    ok "Mode                 → $APP_ENV (QUIZ_DEV_MODE=false — OAuth not yet configured)"
    warn "Supply GOOGLE_CLIENT_ID/SECRET + SMTP_* to enable real sign-in:"
    warn "  sudo GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... APP_ENV=$APP_ENV ./deploy.sh"
  else
    ok "Mode                 → DEV (email login, no OAuth required)"
    warn "To enable production auth: set APP_ENV=production + GOOGLE_CLIENT_ID/SECRET + SMTP"
    warn "  then re-run: sudo GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... ./deploy.sh"
  fi
else
  ok ".env already exists — leaving untouched"
  if [[ -z "$DB_PASS" ]]; then
    DB_PASS="$(grep '^DATABASE_URL=' "$QUIZ_DIR/.env" \
               | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')" || DB_PASS=""
  fi
  info "DB user              : $DB_USER"
  info "Database             : $DB_NAME"
fi

chown -R "$APP_USER:$APP_USER" "$APP_HOME"
chmod 600 "$QUIZ_DIR/.env"
ok "Permissions set (owner: $APP_USER, .env: 600)"

# ── STEP 6 · PostgreSQL ──────────────────────────────────────────────────────
step "PostgreSQL — role, database, schema, ETL seed"

# Make sure DB_PASS is set before we build any URL (covers --update where STEP 5
# left it from the existing .env, and a fresh provision where it was generated).
if [[ -z "$DB_PASS" ]]; then
  DB_PASS="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(24))')"
fi

if [[ "$DB_MODE" == "local" ]]; then
  # ── LOCAL provisioning (legacy single-VM path — unchanged behaviour) ────────
  # Everything here assumes a LOCAL server on this host: the systemd unit, the
  # Unix socket, listen_addresses and pg_hba.conf edits. None of it applies to a
  # remote managed instance, so the whole block is guarded by DB_MODE=local.

  # Resolve unit name
  PG_SVC="$(pg_service_name)" \
    || die "No PostgreSQL systemd unit found. Ensure postgresql (or postgresql-14) is installed."
  info "Service unit         : $PG_SVC"

  # Ensure running
  if ! systemctl is-active --quiet "$PG_SVC"; then
    info "Starting $PG_SVC …"
    systemctl start "$PG_SVC" \
      || die "Could not start $PG_SVC. Run: systemctl status $PG_SVC"
  fi

  # Wait for socket readiness. Uses the explicit socket path discovered in
  # pre-flight (PGHOST is already exported above) plus PGCONNECT_TIMEOUT,
  # so every psql call returns in ≤3 s instead of hanging on TCP fallback.
  # Re-discover the socket here in case step 6 ran without preflight (--update).
  if [[ -z "${PGHOST:-}" ]]; then
    PG_SOCK="$(pg_socket_dir || echo '/var/run/postgresql')"
    export PGHOST="$PG_SOCK"
    export PGCONNECT_TIMEOUT=3
  fi
  info "Waiting for PostgreSQL to accept connections "
  for i in {1..20}; do
    if pg_exec "psql -c 'SELECT 1'" >/dev/null 2>&1; then
      echo; ok "PostgreSQL is up and accepting connections"; break
    fi
    wait_dot; sleep 1
    [[ $i -eq 20 ]] && { echo; die "PostgreSQL did not become ready after 20 s."; }
  done

  # Now ensure Postgres is also listening on TCP/127.0.0.1 so the FastAPI app
  # (which uses psycopg2's TCP driver via DATABASE_URL) can connect.
  # Check by parsing postgresql.conf's listen_addresses setting.
  PG_CONF="$(pg_exec "psql -tAc 'SHOW config_file'" 2>/dev/null | tr -d '[:space:]')"
  info "postgresql.conf      : $PG_CONF"
  if [[ -n "$PG_CONF" && -f "$PG_CONF" ]]; then
    LISTEN_NOW="$(pg_exec "psql -tAc 'SHOW listen_addresses'" 2>/dev/null | tr -d '[:space:]')"
    if [[ "$LISTEN_NOW" != "*" && "$LISTEN_NOW" != *"localhost"* && "$LISTEN_NOW" != *"127.0.0.1"* ]]; then
      info "listen_addresses = '$LISTEN_NOW' — enabling localhost…"
      # Replace existing line or append
      if grep -qE "^\s*#?\s*listen_addresses" "$PG_CONF"; then
        sed -i "s|^\s*#\?\s*listen_addresses.*|listen_addresses = 'localhost'|" "$PG_CONF"
      else
        echo "listen_addresses = 'localhost'" >> "$PG_CONF"
      fi
      info "Restarting $PG_SVC to apply listen_addresses…"
      systemctl restart "$PG_SVC"
      # Wait again briefly for it to come back
      for i in {1..15}; do
        pg_exec "psql -c 'SELECT 1'" >/dev/null 2>&1 && break
        sleep 1
      done
      ok "PostgreSQL now listens on localhost (TCP)"
    else
      ok "PostgreSQL already listens on TCP (listen_addresses='$LISTEN_NOW')"
    fi
  fi

  # Role
  # Always pull the .env password and ALTER ROLE to match — this prevents the
  # "password in .env" ↔ "password the role was created with" desync that
  # happens after re-runs with regenerated passwords or partial failures.
  if ! pg_exec "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" \
      2>/dev/null | grep -q 1; then
    pg_exec "psql -c \"CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}'\""
    ok "Role '${DB_USER}' created"
  else
    # Role exists — sync the password to what's in .env so the app/ETL can connect
    pg_exec "psql -c \"ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}'\"" >/dev/null
    ok "Role '${DB_USER}' exists — password synced to .env"
  fi

  # Persist the (possibly newly generated) password into .env using env_set
  # to avoid sed delimiter clashes with any character in DB_PASS.
  env_set "$QUIZ_DIR/.env" DATABASE_URL "$(build_database_url "$DB_USER" "$DB_PASS")"

  # Database
  if ! pg_exec "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" \
      2>/dev/null | grep -q 1; then
    pg_exec "psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}\""
    ok "Database '${DB_NAME}' created"
  else
    ok "Database '${DB_NAME}' already exists"
  fi

  # Privileges
  pg_exec "psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER}\"" \
    >/dev/null 2>&1
  ok "Privileges granted to '${DB_USER}'"

  # pg_hba.conf
  PG_HBA="$(pg_exec "psql -tAc 'SHOW hba_file'" 2>/dev/null | tr -d '[:space:]')"
  info "pg_hba.conf          : $PG_HBA"

  if [[ -n "$PG_HBA" && -f "$PG_HBA" ]]; then
    HBA_CHANGED=false
    if ! grep -qE "^local\s+${DB_NAME}\s+${DB_USER}" "$PG_HBA"; then
      sed -i "/^local\s\+all/i local   ${DB_NAME}   ${DB_USER}   md5" "$PG_HBA"
      HBA_CHANGED=true; info "Added local md5 rule"
    fi
    if ! grep -qE "^host\s+${DB_NAME}\s+${DB_USER}\s+127\.0\.0\.1" "$PG_HBA"; then
      sed -i "/^host\s\+all/i host   ${DB_NAME}   ${DB_USER}   127.0.0.1/32   md5" "$PG_HBA"
      HBA_CHANGED=true; info "Added host md5 rule (127.0.0.1)"
    fi
    if $HBA_CHANGED; then
      systemctl reload "$PG_SVC" 2>/dev/null || systemctl restart "$PG_SVC" || true
      ok "pg_hba.conf updated and PostgreSQL reloaded"
    else
      ok "pg_hba.conf already has correct entries"
    fi
  fi

  # Schema (DDL)
  # Apply as the postgres superuser via pg_exec (auth path we already verified).
  # This is more robust than connecting as codecoder over TCP — no password
  # mismatch is possible, and pgcrypto/hstore extensions require superuser.
  info "Applying deploy_schema.sql …"
  SCHEMA_TMP="/tmp/deploy_schema_$$.sql"
  # Copy schema to a path the postgres user can read (runuser drops privs)
  cp "$QUIZ_DIR/deploy_schema.sql" "$SCHEMA_TMP"
  chmod 644 "$SCHEMA_TMP"
  pg_exec "psql -d ${DB_NAME} -f ${SCHEMA_TMP}" \
    2>&1 | grep -v '^$' | while read -r line; do info "  pg: $line"; done
  rm -f "$SCHEMA_TMP"

  # Grant table privileges to the application role so the app can read/write
  # everything created by the postgres superuser.
  pg_exec "psql -d ${DB_NAME} -c \"GRANT ALL ON ALL TABLES IN SCHEMA public TO ${DB_USER}\"" \
    >/dev/null 2>&1
  pg_exec "psql -d ${DB_NAME} -c \"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER}\"" \
    >/dev/null 2>&1
  pg_exec "psql -d ${DB_NAME} -c \"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER}\"" \
    >/dev/null 2>&1
  ok "Schema applied (tables/indexes created or already exist)"
  ok "Table & sequence privileges granted to '${DB_USER}'"

  # Verify the app role can connect over TCP using the password in .env.
  # This is the same connection the ETL and FastAPI app will use, so catching
  # auth failures here is much clearer than failing mid-migration.
  info "Verifying app role can connect over TCP with .env password …"
  if PGPASSWORD="$DB_PASS" PGCONNECT_TIMEOUT=3 \
     timeout 5 psql -U "$DB_USER" -d "$DB_NAME" -h 127.0.0.1 -c 'SELECT 1' >/dev/null 2>&1; then
    ok "App role '${DB_USER}' authenticates over TCP"
  else
    warn "App role TCP auth failed. Capturing error:"
    PGPASSWORD="$DB_PASS" PGCONNECT_TIMEOUT=3 \
      timeout 5 psql -U "$DB_USER" -d "$DB_NAME" -h 127.0.0.1 -c 'SELECT 1' 2>&1 \
      | head -5 | while read -r l; do warn "  $l"; done
    die "App role cannot connect. Check pg_hba.conf has an md5 host rule for ${DB_USER}."
  fi

else
  # ── EXTERNAL provisioning (remote shared Postgres) ──────────────────────────
  # No local server: no systemd unit, no socket, no listen_addresses, no
  # pg_hba.conf edits — those don't exist on a managed remote instance. The DBA
  # owns server-level config + TLS. We either (a) provision db/roles/extensions
  # remotely when a superuser password is available, or (b) assume the DBA did.
  # In BOTH cases the schema is owned by Alembic (run below), NOT by
  # deploy_schema.sql + create_all, because the runtime app role has DML only.
  info "External Postgres    : ${DB_HOST}:${DB_PORT}/${DB_NAME}  (TLS sslmode=${DB_SSLMODE})"

  # Persist the remote DATABASE_URL into .env (used by Alembic + seeds + the app).
  env_set "$QUIZ_DIR/.env" DATABASE_URL "$(build_database_url "$DB_USER" "$DB_PASS")"
  ok "DATABASE_URL         → $(db_url_display)"

  if [[ "$DB_PROVISION" == "yes" ]]; then
    # Remote provisioning as the superuser (reachability verified in preflight).
    # CREATE DATABASE cannot run inside a transaction block and must target the
    # maintenance DB, so each statement is its own psql call.
    info "Provisioning remote database + login roles + extensions …"

    # App login role (DML-only; schema privileges are granted post-Alembic).
    if ! pg_exec "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" \
        2>/dev/null | grep -q 1; then
      pg_exec "psql -c \"CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}'\""
      ok "Role '${DB_USER}' created (app, login)"
    else
      pg_exec "psql -c \"ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}'\"" >/dev/null
      ok "Role '${DB_USER}' exists — password synced to .env"
    fi

    # Database, owned by the app role.
    if ! pg_exec "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" \
        2>/dev/null | grep -q 1; then
      pg_exec "psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}\""
      ok "Database '${DB_NAME}' created on remote"
    else
      ok "Database '${DB_NAME}' already exists on remote"
    fi
    pg_exec "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER}\"" \
      >/dev/null 2>&1
    ok "Database-level privileges granted to '${DB_USER}'"

    # Extensions — must be created by a superuser INSIDE the target database.
    # The app's init_db() no longer creates these (the runtime role lacks the
    # privilege on a managed instance); we do it here while we hold superuser.
    pg_exec "psql -d ${DB_NAME} -c \"CREATE EXTENSION IF NOT EXISTS pgcrypto\"" \
      >/dev/null 2>&1 && ok "Extension pgcrypto present in '${DB_NAME}'" \
      || warn "Could not create pgcrypto in '${DB_NAME}' — ask the DBA to add it"
    pg_exec "psql -d ${DB_NAME} -c \"CREATE EXTENSION IF NOT EXISTS hstore\"" \
      >/dev/null 2>&1 && ok "Extension hstore present in '${DB_NAME}'" \
      || warn "Could not create hstore in '${DB_NAME}' — ask the DBA to add it"
  else
    # DBA pre-created everything. We do NOT touch roles/db/extensions; we only
    # rely on the DATABASE_URL written above. Alembic (run below) needs a
    # privileged migration credential — see the note printed in the banner.
    warn "PROVISION_DB=off — not creating remote db/roles/extensions (DBA owns them)."
    warn "Alembic below needs a privileged migration credential for DDL + the 0008"
    warn "directus-role GRANTs. If DATABASE_URL's role is DML-only, run migrations"
    warn "separately with a migration role, or set PROVISION_DB=true + a superuser pw."
  fi
fi

# Schema + seeds
# Note: we do NOT `source .env` here. app/config.py uses python-dotenv to
# load it directly, which correctly handles values with spaces or special
# characters like "FROM_NAME=DEPT® Academy" that break bash source. The schema
# migration reads DATABASE_URL from .env (local loopback or remote+TLS), so it
# targets whichever instance STEP 6 pointed .env at — no change needed here.
#
# DIRECTUS_DB_ROLE is exported into the migration environment so the 0008
# migration creates/grants the PER-ENV Directus role (prod=directus_app,
# staging=directus_app_stg, dev=directus_app_dev) — one credential cannot reach
# two databases, preserving dev/prod isolation on the shared instance.
if [[ "$DB_MODE" == "external" ]]; then
  info "Running schema migration + seeds against remote ${DB_HOST}:${DB_PORT}/${DB_NAME} …"
else
  info "Running ETL migration: question bank + feed + course chapters + framework …"
fi
cd "$QUIZ_DIR"
DIRECTUS_DB_ROLE="$DIRECTUS_DB_ROLE" \
"$QUIZ_DIR/.venv/bin/python" -m scripts.migrate_to_postgres \
  2>&1 | while read -r line; do info "  etl: $line"; done
ok "Schema migration + seeds complete"

# Generate the runbook Excel template so GET /api/runbooks/template works.
# Idempotent — safe to re-run; overwrites only if the script succeeds.
info "Generating runbook Excel template (data/runbook-template.xlsx) …"
"$QUIZ_DIR/.venv/bin/python" -m scripts.generate_runbook_template \
  "$QUIZ_DIR/data/runbook-template.xlsx" \
  2>&1 | while read -r line; do info "  template: $line"; done || \
  warn "Runbook template generation failed — GET /api/runbooks/template will 404 until fixed"

# ── STEP 7 · systemd service ─────────────────────────────────────────────────
step "systemd service  ($SERVICE_NAME)"

# Ordering dependency for the units. In LOCAL mode the app must start after the
# co-resident Postgres unit. In EXTERNAL mode the database is remote, so there is
# no local PG unit to order against — depend on the network being up instead.
if [[ "$DB_MODE" == "local" ]]; then
  PG_AFTER="${PG_SVC}.service"
  PG_WANTS="${PG_SVC}.service"
else
  PG_AFTER="network-online.target"
  PG_WANTS="network-online.target"
fi

info "Writing /etc/systemd/system/${SERVICE_NAME}.service …"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=DEPT CCA Quiz (FastAPI / uvicorn)
After=network.target ${PG_AFTER}

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${QUIZ_DIR}
# APP_ENV is also in .env, but set it here so the unit's mode is visible in
# 'systemctl show' and survives an operator hand-editing .env (05 §5).
Environment=APP_ENV=${APP_ENV}
EnvironmentFile=${QUIZ_DIR}/.env
ExecStart=${QUIZ_DIR}/.venv/bin/uvicorn app.main:app \\
    --host 127.0.0.1 \\
    --port ${QUIZ_PORT} \\
    --workers ${QUIZ_WORKERS} \\
    --proxy-headers \\
    --forwarded-allow-ips='127.0.0.1'
Restart=on-failure
RestartSec=5
# ── Security hardening (07 §9, softened per C-64) ───────────────────────────
# Phase-1 baseline:
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${QUIZ_DIR}
# Phase-3 additions — kernel / cgroup / namespace surface reduction:
ProtectKernelTunables=true
ProtectControlGroups=true
ProtectKernelModules=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
# Allow the broad service syscall set. Deliberately NOT MemoryDenyWriteExecute
# (Pillow/ffprobe need W^X off) and NOT the aggressive ~@resources deny-list —
# both are deferred to a Phase 3c 24h soak to avoid media-pipeline regressions
# (C-64).
SystemCallFilter=@system-service

[Install]
WantedBy=multi-user.target
EOF

info "Reloading systemd daemon …"
systemctl daemon-reload

info "Enabling and (re)starting ${SERVICE_NAME} …"
systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1
systemctl restart "${SERVICE_NAME}"

# Brief pause then check
sleep 2
SVC_STATUS="$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || echo 'unknown')"
if [[ "$SVC_STATUS" == "active" ]]; then
  ok "${SERVICE_NAME} is running  (active)"
else
  warn "${SERVICE_NAME} status: $SVC_STATUS"
  warn "Check logs: journalctl -u ${SERVICE_NAME} -n 30 --no-pager"
fi

# ── STEP 7b · Directus CMS (Phase 4a · 05 §5.5, §8.2) ────────────────────────
# ADDITIVE + REVERSIBLE. Stands Directus up over the EXISTING Postgres by
# introspection — no content is moved, no table is decomposed, media stays in
# Postgres large objects. Gated behind DEPLOY_DIRECTUS so an operator can skip
# the whole CMS (set DEPLOY_DIRECTUS=false). Runs in BOTH full-install and
# --update modes: a fresh install bootstraps (npm ci + directus bootstrap +
# bootstrap.sh + snapshot apply); --update restarts the service and re-applies
# the schema snapshot. The cms/ as-code layout (package.json, docker-compose.yml,
# .env.example, bootstrap.sh, snapshot.yaml) is delivered by slice 4a-2; the
# scoped DB role directus_app is created by Alembic migration 0008 (slice 4a-1).
if [[ "$DEPLOY_DIRECTUS" == "true" ]]; then
  step "Directus CMS  (${CMS_SERVICE_NAME})"

  CMS_DIR="$APP_HOME/cms"

  if [[ ! -d "$CMS_DIR" ]]; then
    warn "No cms/ directory at $CMS_DIR (slice 4a-2 not in bundle)."
    warn "Skipping Directus stand-up. Re-run after cms/ lands, or set DEPLOY_DIRECTUS=false."
  else
    # ── (a) Directus service user ─────────────────────────────────────────────
    # Its own system user so the CMS file/socket surface is isolated from the
    # FastAPI app user. Falls back silently if CMS_USER == APP_USER.
    if [[ "$CMS_USER" != "$APP_USER" ]] && ! id "$CMS_USER" &>/dev/null; then
      useradd --system --create-home --home-dir "/home/$CMS_USER" \
        --shell /sbin/nologin "$CMS_USER"
      ok "Created user '$CMS_USER'  (system, nologin)"
    else
      ok "User '$CMS_USER' present (or shared with app user)"
    fi

    # ── (b) Node runtime check ────────────────────────────────────────────────
    # Directus officially supports Node 18/20/22 LTS. We warn (not die) on an
    # unsupported major so the as-code path still installs; the operator can
    # point ExecStart at an LTS node via the override documented in RUNBOOK §7.2.
    NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
    if [[ -z "$NODE_BIN" ]]; then
      warn "node not found on PATH — install Node 20 LTS (RUNBOOK §7.2) then re-run."
      warn "Skipping Directus stand-up for this run."
    else
      NODE_MAJOR="$("$NODE_BIN" -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
      info "Node        : $("$NODE_BIN" --version)  (major $NODE_MAJOR)"
      case "$NODE_MAJOR" in
        18|20|22) ok "Node major $NODE_MAJOR is a Directus-supported LTS" ;;
        *) warn "Node major $NODE_MAJOR is OUTSIDE Directus's supported set (18/20/22 LTS)."
           warn "Directus may refuse to boot. Pin an LTS (nvm / nodesource) per RUNBOOK §7.2." ;;
      esac

      # ── (c) Directus DB role password ───────────────────────────────────────
      # CMS_DB_USER is the PER-ENV Directus role (DIRECTUS_DB_ROLE): prod
      # directus_app, staging directus_app_stg, dev directus_app_dev. The role +
      # its per-database GRANTs are created by Alembic 0008 (slice 4a-1). Here we
      # only set its password (idempotent ALTER ROLE) and persist it into
      # cms/.env. If 0008 has not run, the role is absent — warn and continue.
      if [[ -z "$CMS_DB_PASS" ]]; then
        if [[ -f "$CMS_DIR/.env" ]] && grep -q '^DB_PASSWORD=' "$CMS_DIR/.env"; then
          CMS_DB_PASS="$(grep '^DB_PASSWORD=' "$CMS_DIR/.env" | head -1 | cut -d= -f2-)"
          info "Reusing DB_PASSWORD from existing cms/.env"
        else
          CMS_DB_PASS="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(24))')"
          ok "Generated Directus DB password"
        fi
      fi
      # Setting the role password needs superuser/role-admin. In local mode (or
      # external mode WITH provisioning) we have it; in external+no-provision the
      # DBA owns the role's password, so we skip the ALTER and just write cms/.env.
      if [[ "$DB_MODE" == "local" || "$DB_PROVISION" == "yes" ]]; then
        if pg_exec "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${CMS_DB_USER}'\"" \
            2>/dev/null | grep -q 1; then
          pg_exec "psql -c \"ALTER ROLE ${CMS_DB_USER} WITH LOGIN PASSWORD '${CMS_DB_PASS}'\"" >/dev/null
          ok "Role '${CMS_DB_USER}' password synced"
        else
          warn "Role '${CMS_DB_USER}' not found — run Alembic 0008 (slice 4a-1) first."
          warn "  cd $QUIZ_DIR && .venv/bin/alembic upgrade head"
        fi
      else
        warn "External + PROVISION_DB=off: not altering '${CMS_DB_USER}' (DBA owns its password)."
        warn "  Ensure cms/.env DB_PASSWORD matches the password the DBA set for '${CMS_DB_USER}'."
      fi

      # ── (d) cms/.env ─────────────────────────────────────────────────────────
      # Seeded from cms/.env.example (slice 4a-2) on first deploy; an existing
      # cms/.env is never clobbered. KEY/SECRET generated once. PUBLIC_URL is the
      # /cms/ subpath on the HTTPS vhost so the Google SSO redirect resolves.
      if [[ ! -f "$CMS_DIR/.env" ]]; then
        if [[ -f "$CMS_DIR/.env.example" ]]; then
          cp "$CMS_DIR/.env.example" "$CMS_DIR/.env"
          ok "cms/.env created from cms/.env.example"
        else
          : > "$CMS_DIR/.env"
          warn "cms/.env.example missing — wrote an empty cms/.env (fill from RUNBOOK §7.1)"
        fi
        env_set "$CMS_DIR/.env" KEY    "$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
        env_set "$CMS_DIR/.env" SECRET "$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
        ok "Generated Directus KEY + SECRET"
        if [[ -z "$CMS_ADMIN_PASSWORD" ]]; then
          CMS_ADMIN_PASSWORD="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(18))')"
          ok "Generated Directus admin password (printed in the summary)"
        fi
        env_set "$CMS_DIR/.env" ADMIN_EMAIL    "$CMS_ADMIN_EMAIL"
        env_set "$CMS_DIR/.env" ADMIN_PASSWORD "$CMS_ADMIN_PASSWORD"
      else
        ok "cms/.env already exists — leaving secrets untouched"
      fi

      # Always (re)write the connection + URL keys so a DB password rotation, a
      # DOMAIN change, or a DB-mode change is picked up. Directus connects to the
      # SAME Postgres as the app and at the SAME host/port — loopback in local
      # mode, the remote host over TLS in external mode (matches DATABASE_URL).
      env_set "$CMS_DIR/.env" DB_CLIENT   "pg"
      if [[ "$DB_MODE" == "external" ]]; then
        env_set "$CMS_DIR/.env" DB_HOST   "$DB_HOST"
        env_set "$CMS_DIR/.env" DB_PORT   "$DB_PORT"
        # TLS to the remote instance (matches the app's sslmode). For
        # sslmode=require WITHOUT a provisioned CA, node-postgres cannot verify
        # the chain, so reject-unauthorized must be false (documented in
        # cms/.env.example). For verify-full, set DB_SSL__CA + reject=true by hand.
        env_set "$CMS_DIR/.env" DB_SSL    "true"
        if [[ "$DB_SSLMODE" == "verify-full" || "$DB_SSLMODE" == "verify-ca" ]]; then
          info "Directus DB_SSL=true (sslmode=${DB_SSLMODE}) — set DB_SSL__CA + DB_SSL__REJECT_UNAUTHORIZED=true in cms/.env to validate the server cert."
        else
          env_set "$CMS_DIR/.env" DB_SSL__REJECT_UNAUTHORIZED "false"
          info "Directus DB_SSL=true with DB_SSL__REJECT_UNAUTHORIZED=false (sslmode=${DB_SSLMODE}: encrypt without CA verification)."
        fi
      else
        env_set "$CMS_DIR/.env" DB_HOST   "127.0.0.1"
        env_set "$CMS_DIR/.env" DB_PORT   "5432"
      fi
      env_set "$CMS_DIR/.env" DB_DATABASE "$DB_NAME"
      env_set "$CMS_DIR/.env" DB_USER     "$CMS_DB_USER"
      env_set "$CMS_DIR/.env" DB_PASSWORD "$CMS_DB_PASS"
      env_set "$CMS_DIR/.env" HOST        "127.0.0.1"
      env_set "$CMS_DIR/.env" PORT        "$CMS_PORT"
      env_set "$CMS_DIR/.env" PUBLIC_URL  "https://${DOMAIN}/cms"
      # Directus-INTERNAL files only (e.g. avatars) under cms/uploads. App media
      # is NEVER stored here: all media bytes live in Postgres large objects and
      # are streamed by FastAPI /media/* (no S3, no object store, no filesystem
      # media store — Postgres is the only database). App-media uploads into
      # Directus Files are disabled by permission. Do not configure S3.
      env_set "$CMS_DIR/.env" STORAGE_LOCATIONS "local"
      env_set "$CMS_DIR/.env" STORAGE_LOCAL_DRIVER "local"
      env_set "$CMS_DIR/.env" STORAGE_LOCAL_ROOT   "${CMS_DIR}/uploads"
      # Google SSO for staff (04 §4.2 / §8.2 step 4) — a SEPARATE OAuth client
      # from the FastAPI one; redirect URI <PUBLIC_URL>/auth/login/google/callback.
      # Reuse the FastAPI Google creds only if no dedicated CMS creds were given.
      CMS_GOOGLE_ID="${AUTH_GOOGLE_CLIENT_ID:-$GOOGLE_CLIENT_ID}"
      CMS_GOOGLE_SECRET="${AUTH_GOOGLE_CLIENT_SECRET:-$GOOGLE_CLIENT_SECRET}"
      # SSO posture (4a F2 reconcile — must match cms/.env.example):
      #   - PUBLIC_REGISTRATION=false: admins PRE-CREATE each staff Directus
      #     user, matched to their @deptagency.com Google email. SSO then only
      #     LOGS IN an existing user; it never self-provisions one. This is the
      #     secure default.
      #   - ALLOW_LIST=deptagency.com: defence-in-depth — Directus rejects any
      #     Google account whose verified email host is not on this list, even
      #     if public registration were ever turned on.
      #   - DEFAULT_ROLE_ID: the role a newly self-registered user would land in.
      #     It is USED ONLY IF public registration is enabled; with it false the
      #     value is inert, but we still set it (least-privilege content_author)
      #     so the contract is explicit and a future flip is safe. The role id is
      #     minted at runtime by cms/bootstrap.sh — set CMS_DEFAULT_ROLE_ID in the
      #     deploy environment to that id, or leave the placeholder and paste the
      #     id printed by bootstrap.sh into cms/.env afterwards (RUNBOOK §7.3).
      CMS_DEFAULT_ROLE_ID="${CMS_DEFAULT_ROLE_ID:-replace-with-content_author-role-id}"
      if [[ -n "$CMS_GOOGLE_ID" && -n "$CMS_GOOGLE_SECRET" ]]; then
        env_set "$CMS_DIR/.env" AUTH_PROVIDERS              "google"
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_DRIVER          "openid"
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_CLIENT_ID       "$CMS_GOOGLE_ID"
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_CLIENT_SECRET   "$CMS_GOOGLE_SECRET"
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_ISSUER_URL      "https://accounts.google.com"
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_IDENTIFIER_KEY  "email"
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_ALLOW_PUBLIC_REGISTRATION "false"
        # Domain restriction (defence-in-depth) + least-privilege default role.
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_ALLOW_LIST       "deptagency.com"
        env_set "$CMS_DIR/.env" AUTH_GOOGLE_DEFAULT_ROLE_ID  "$CMS_DEFAULT_ROLE_ID"
        ok "Directus Google SSO configured (redirect: https://${DOMAIN}/cms/auth/login/google/callback)"
        warn "Register that redirect URI in the Directus OAuth client (Google Console)."
        if [[ "$CMS_DEFAULT_ROLE_ID" == replace-with-* ]]; then
          warn "AUTH_GOOGLE_DEFAULT_ROLE_ID is a placeholder — paste the content_author role id from bootstrap.sh into cms/.env (RUNBOOK §7.3)."
        fi
      else
        info "No Google creds for Directus — staff use the break-glass admin until SSO is set (RUNBOOK §7.3)"
      fi

      mkdir -p "$CMS_DIR/uploads" "$CMS_DIR/.directus"
      chown -R "$CMS_USER:$CMS_USER" "$CMS_DIR/uploads" "$CMS_DIR/.directus" "$CMS_DIR/.env"
      chmod 600 "$CMS_DIR/.env"

      # ── (e) npm install + Directus bootstrap (first deploy only) ────────────
      NPM_BIN="${NPM_BIN:-$(command -v npm || true)}"
      NPX_BIN="${NPX_BIN:-$(command -v npx || true)}"
      if [[ ! -d "$CMS_DIR/node_modules" ]]; then
        if [[ -n "$NPM_BIN" ]]; then
          info "Installing CMS Node dependencies (npm ci) …"
          ( cd "$CMS_DIR" && sudo -u "$CMS_USER" "$NPM_BIN" ci --omit=dev 2>&1 ) \
            | tail -3 | while read -r l; do info "  npm: $l"; done \
            || warn "npm ci failed — install Node deps by hand (RUNBOOK §7.1)"
        else
          warn "npm not found — install CMS deps by hand (RUNBOOK §7.1)"
        fi
      else
        ok "cms/node_modules present — skipping npm install"
      fi

      # directus bootstrap creates the directus_* tables + the admin account.
      # Idempotent: re-running is a no-op once the core tables exist.
      if [[ -x "$CMS_DIR/node_modules/.bin/directus" || -n "$NPX_BIN" ]]; then
        info "Running directus bootstrap (creates directus_* tables + admin) …"
        ( cd "$CMS_DIR" && sudo -u "$CMS_USER" env $(grep -v '^#' .env | xargs) \
            "$NPX_BIN" directus bootstrap 2>&1 ) \
          | tail -4 | while read -r l; do info "  directus: $l"; done \
          || warn "directus bootstrap reported an error — see journal / RUNBOOK §7.1"
      fi

      # ── (f) bootstrap.sh (roles/permissions/webhooks) + snapshot apply ──────
      # bootstrap.sh (slice 4a-2) wires the 6 roles, collection permissions, and
      # the loopback webhooks. snapshot.yaml is the introspected collection
      # schema. Both are idempotent and re-applied on every run (incl. --update).
      if [[ -f "$CMS_DIR/bootstrap.sh" ]]; then
        info "Applying cms/bootstrap.sh (roles · permissions · webhooks) …"
        ( cd "$CMS_DIR" && sudo -u "$CMS_USER" bash bootstrap.sh 2>&1 ) \
          | tail -4 | while read -r l; do info "  bootstrap: $l"; done \
          || warn "bootstrap.sh reported an error — re-run by hand (RUNBOOK §7.4)"
      else
        info "cms/bootstrap.sh absent — skipping role/permission/webhook wiring"
      fi
      if [[ -f "$CMS_DIR/snapshot.yaml" && -n "$NPX_BIN" ]]; then
        info "Applying Directus schema snapshot (cms/snapshot.yaml) …"
        ( cd "$CMS_DIR" && sudo -u "$CMS_USER" env $(grep -v '^#' .env | xargs) \
            "$NPX_BIN" directus schema apply --yes ./snapshot.yaml 2>&1 ) \
          | tail -4 | while read -r l; do info "  schema: $l"; done \
          || warn "schema apply reported an error — re-apply by hand (RUNBOOK §7.4)"
      else
        info "cms/snapshot.yaml absent — skipping schema apply"
      fi

      # ── (g) systemd unit (mirrors the cca-quiz hardening; no MemoryDenyWriteExecute) ──
      info "Writing /etc/systemd/system/${CMS_SERVICE_NAME}.service …"
      cat > "/etc/systemd/system/${CMS_SERVICE_NAME}.service" <<EOF
[Unit]
Description=DEPT CCA Directus CMS (editorial write plane over Postgres)
After=network.target ${PG_AFTER} ${SERVICE_NAME}.service
Wants=${PG_WANTS}

[Service]
Type=exec
User=${CMS_USER}
Group=${CMS_USER}
WorkingDirectory=${CMS_DIR}
EnvironmentFile=${CMS_DIR}/.env
# Boot via the project-local Directus binary; npx is the documented fallback.
ExecStart=${CMS_DIR}/node_modules/.bin/directus start
Restart=on-failure
RestartSec=5
# ── Security hardening — mirrors cca-quiz (07 §9, softened per C-64) ─────────
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
# Directus writes uploads (local storage) + its own cache/transient dir.
ReadWritePaths=${CMS_DIR}/uploads ${CMS_DIR}/.directus
ProtectKernelTunables=true
ProtectControlGroups=true
ProtectKernelModules=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
# Deliberately NOT MemoryDenyWriteExecute (the Node/V8 JIT needs W^X off),
# matching the cca-quiz unit's rationale (C-64).
SystemCallFilter=@system-service

[Install]
WantedBy=multi-user.target
EOF

      systemctl daemon-reload
      info "Enabling and (re)starting ${CMS_SERVICE_NAME} …"
      systemctl enable "${CMS_SERVICE_NAME}" >/dev/null 2>&1
      systemctl restart "${CMS_SERVICE_NAME}"
      sleep 2
      CMS_STATUS="$(systemctl is-active "${CMS_SERVICE_NAME}" 2>/dev/null || echo 'unknown')"
      if [[ "$CMS_STATUS" == "active" ]]; then
        ok "${CMS_SERVICE_NAME} is running  (active, 127.0.0.1:${CMS_PORT})"
      else
        warn "${CMS_SERVICE_NAME} status: $CMS_STATUS"
        warn "Check logs: journalctl -u ${CMS_SERVICE_NAME} -n 40 --no-pager"
        warn "Common cause: unsupported Node major (need 18/20/22 LTS) — see RUNBOOK §7.2"
      fi
    fi
  fi
fi

# ── STEP 8 · SELinux (RHEL only) ─────────────────────────────────────────────
if $SELINUX_ON && ! $UPDATE_ONLY; then
  step "SELinux policy"
  info "Allowing httpd network connections …"
  setsebool -P httpd_can_network_connect 1
  ok "httpd_can_network_connect = on"

  info "Labelling content directories …"
  semanage fcontext -a -t httpd_sys_content_t "${APP_HOME}/content/frozen(/.*)?" 2>/dev/null \
    || semanage fcontext -m -t httpd_sys_content_t "${APP_HOME}/content/frozen(/.*)?"
  semanage fcontext -a -t httpd_sys_content_t "${APP_HOME}/frontend(/.*)?" 2>/dev/null \
    || semanage fcontext -m -t httpd_sys_content_t "${APP_HOME}/frontend(/.*)?"
  restorecon -Rv "${APP_HOME}/content/frozen" "${APP_HOME}/frontend" >/dev/null
  ok "SELinux file contexts applied"
else
  # Don't consume a step number when SELinux is skipped
  TOTAL_STEPS=$((TOTAL_STEPS - 1))
fi

# ── STEP 9 · Apache vhost config ─────────────────────────────────────────────
if ! $UPDATE_ONLY; then
  step "Apache vhost config"

  # Enable required Apache modules (06 §2.1).
  #   proxy/proxy_http/ssl/rewrite — reverse proxy + TLS + HTTP→HTTPS redirect.
  #   headers   — 'Header always set' for HSTS/CSP/Cache-Control (already on).
  #   deflate   — gzip text/JSON/CSS/JS/SVG.
  #   expires   — Cache-Control / Expires per location.
  #   http2     — HTTP/2 over TLS (ALPN 'h2').
  #   ratelimit — mod_ratelimit, outbound throttle on /api/media/upload (C-29).
  #   proxy_wstunnel — WebSocket upgrade for the Directus admin (only when
  #                    DEPLOY_DIRECTUS=true · Phase 4a · 05 §8.2 step 8).
  DEB_MODS="proxy proxy_http ssl rewrite headers deflate expires http2 ratelimit"
  RHEL_MODS="proxy_module proxy_http_module ssl_module rewrite_module headers_module deflate_module expires_module http2_module ratelimit_module"
  if [[ "$DEPLOY_DIRECTUS" == "true" ]]; then
    DEB_MODS="$DEB_MODS proxy_wstunnel"
    RHEL_MODS="$RHEL_MODS proxy_wstunnel_module"
  fi
  if [[ "$OS_FAMILY" == "debian" ]]; then
    info "Enabling Apache modules …"
    for mod in $DEB_MODS; do
      if a2enmod "$mod" >/dev/null 2>&1; then
        ok "  a2enmod $mod"
      else
        info "  $mod already enabled"
      fi
    done
  else
    # RHEL/CentOS: these modules ship as separate packages but are loaded by
    # default via /etc/httpd/conf.modules.d/*.conf once installed. mod_proxy,
    # mod_proxy_http, mod_ssl, mod_rewrite, mod_headers, mod_deflate,
    # mod_expires, mod_http2 and mod_ratelimit are all in the base httpd /
    # mod_ssl / mod_http2 packages. We verify rather than LoadModule by hand so
    # we don't duplicate a directive the distro already ships.
    info "Verifying Apache modules are loaded (RHEL loads via conf.modules.d) …"
    for mod in $RHEL_MODS; do
      if httpd -M 2>/dev/null | grep -q "$mod"; then
        ok "  $mod"
      else
        warn "  $mod NOT loaded — install/enable it (e.g. dnf install mod_http2 mod_ssl)"
      fi
    done
  fi

  TLS_AVAILABLE=false
  [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]] && TLS_AVAILABLE=true

  if $TLS_AVAILABLE; then
    info "TLS certs found — configuring HTTPS vhost"
    ok "  Cert : $CERT_FILE"
    ok "  Key  : $KEY_FILE"
    HTTP_BLOCK="# Redirect plain HTTP → HTTPS
<VirtualHost *:80>
    ServerName ${SERVER_NAME}
    RewriteEngine On
    RewriteRule ^/?(.*) https://${SERVER_NAME}/\$1 [R=301,L]
</VirtualHost>"
  else
    warn "TLS certs not found at $CERT_FILE"
    warn "Serving over HTTP only. To add TLS:"
    warn "  sudo certbot --apache -d ${DOMAIN}"
    warn "  or set CERT_FILE/KEY_FILE and re-run ./deploy.sh"
    HTTP_BLOCK="<VirtualHost *:80>
    ServerName ${SERVER_NAME}

    # v2 paths — see docs/architecture/v2/01-blueprint.md §7
    Alias /anatomy \"${APP_HOME}/content/frozen\"
    <Directory \"${APP_HOME}/content/frozen\">
        Require all granted
        DirectoryIndex anatomy-of-code-course.html
        Options -Indexes +FollowSymLinks
    </Directory>

    Alias /app \"${APP_HOME}/frontend\"
    <Directory \"${APP_HOME}/frontend\">
        Require all granted
        DirectoryIndex index.html
        Options -Indexes +FollowSymLinks
        FallbackResource /app/index.html
    </Directory>

    # Q-13: NO 'Alias /static/' — FastAPI mounts /static/ itself; let it fall
    # through to ProxyPass so the app's CSS/JS bundles ship from uvicorn.

    # /runbook → content/frozen/runbook.html (dynamic reader SPA, static file)
    RewriteEngine On
    RewriteRule ^/runbook$ /anatomy/runbook.html [L]

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto \"http\"
    ProxyPass        /anatomy !
    ProxyPass        /app     !
    ProxyPass        /runbook !
    ProxyPass        /  http://127.0.0.1:${QUIZ_PORT}/
    ProxyPassReverse /  http://127.0.0.1:${QUIZ_PORT}/

    ErrorLog  ${APACHE_LOG_DIR}/${SERVICE_NAME}_error.log
    CustomLog ${APACHE_LOG_DIR}/${SERVICE_NAME}_access.log combined
</VirtualHost>"
  fi

  # ── Content-Security-Policy profiles (07 §3) ───────────────────────────────
  # CDN allowlist discovered by grepping frontend/ + content/frozen/:
  #   • https://cdn.jsdelivr.net — mermaid 11 (SPA diagram.js + course HTML)
  #   • https://esm.sh           — Ajv 2020 + ajv-formats (SPA feed/validate.js)
  #   • https://fonts.googleapis.com / https://fonts.gstatic.com — web fonts
  #   • https://www.deptagency.com — the DEPT® logo SVG
  # DEFAULT profile (/, /app/, /api): both CDNs in script-src because the SPA
  # loads mermaid (jsdelivr) AND ajv (esm.sh); esm.sh also in connect-src since
  # its ESM build pulls peer modules at import time.
  # COURSE profile (/anatomy/): only jsdelivr (mermaid) + media-src 'self' for
  # the monolith's <video> tags (C-67).
  # Single quotes here are literal — they sit inside the double-quoted
  # HTTPS_BLOCK heredoc, so Apache receives real 'self' / 'none' tokens.
  CSP_DEFAULT="default-src 'self'; script-src 'self' https://cdn.jsdelivr.net https://esm.sh; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://www.deptagency.com; connect-src 'self' https://esm.sh; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'; report-to csp-endpoint"
  CSP_COURSE="default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://www.deptagency.com; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'; report-to csp-endpoint"

  # CMS (Directus admin) profile (/cms/ · Phase 4a · 05 §8.2 step 8). Directus's
  # admin app is a Vue SPA served same-origin under /cms/; the main-vhost DEFAULT
  # CSP above (which has no 'unsafe-inline' / 'unsafe-eval' in script-src and
  # would block the admin shell) must NOT apply here. We scope a Directus-
  # appropriate policy via a <Location "/cms/"> so it never widens the policy on
  # the application paths. The widening over DEFAULT is minimal and confined:
  #   • script-src adds 'unsafe-eval' — the Directus app bundle uses it.
  #   • style-src keeps 'unsafe-inline' (already in DEFAULT) for runtime styles.
  #   • img-src / media-src add blob: + data: for upload previews of cms/uploads.
  #   • connect-src 'self' — the admin app talks to its own /cms/ API origin.
  #   • worker-src adds blob: for the Directus web-worker bundle.
  # If you instead front Directus on a SUBDOMAIN (cms.<domain>), Directus serves
  # its own CSP and this <Location> is unnecessary — see RUNBOOK §7.6.
  CSP_CMS="default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; media-src 'self' blob:; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'; report-to csp-endpoint"

  # Safe-rollout gate (C-31): default ships Report-Only so a too-tight policy
  # logs violations instead of breaking the page. Flip CSP_ENFORCE=1 to enforce
  # once the report-to sink is quiet. report-to (NOT report-uri) per C-31; the
  # named group below points at the app's /csp/report endpoint (07 §3.2).
  if [[ "$CSP_ENFORCE" == "1" ]]; then
    CSP_HEADER="Content-Security-Policy"
    info "CSP mode    : ENFORCED (Content-Security-Policy)"
  else
    CSP_HEADER="Content-Security-Policy-Report-Only"
    info "CSP mode    : Report-Only (set CSP_ENFORCE=1 to enforce)"
  fi
  # The Report-To group JSON. Doubled inner quotes survive the heredoc; the
  # endpoint is same-origin so no extra CSP allowance is needed.
  REPORT_TO_JSON='{\"group\":\"csp-endpoint\",\"max_age\":10886400,\"endpoints\":[{\"url\":\"/csp/report\"}]}'

  # ── Directus reverse-proxy block (Phase 4a · 05 §8.2 step 8) ────────────────
  # Built as two variables interpolated into the HTTPS vhost below:
  #   CMS_LOCATION_BLOCK — the <Location "/cms/"> that scopes the Directus CSP
  #                        (CSP_CMS) and sets WebSocket upgrade for live preview.
  #   CMS_PROXY_BLOCK    — the ProxyPass /cms/ pair, which MUST sit BEFORE the
  #                        catch-all ProxyPass / so it is not shadowed.
  # Both are empty when DEPLOY_DIRECTUS=false, so a CMS-less box never proxies to
  # a dead 8055. /cms/ does NOT collide with any reserved path (/, /app,
  # /anatomy, /media, /certificate, /api) — it's a fresh top-level subpath.
  # The Google SSO callback (PUBLIC_URL/auth/login/google/callback →
  # /cms/auth/login/google/callback) rides this same proxy.
  if [[ "$DEPLOY_DIRECTUS" == "true" ]]; then
    CMS_LOCATION_BLOCK="    # ── Directus admin (Phase 4a) — scoped CSP for the Vue admin SPA ─────────
    # 'always set' REPLACES the vhost DEFAULT CSP for this subpath only, so the
    # application paths keep the tighter DEFAULT profile. Directus serves its
    # API + admin shell + the Google SSO callback under /cms/.
    <Location \"/cms/\">
        Header always set ${CSP_HEADER} \"${CSP_CMS}\"
        # Directus admin uses no shared cache; revalidate the shell every load.
        Header always set Cache-Control \"no-cache\"
    </Location>
    # WebSocket upgrade for Directus live-preview / realtime (06: not cached).
    # mod_proxy_wstunnel rewrites ws:// upgrades onto the same backend port.
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule ^/cms/(.*)$ ws://127.0.0.1:${CMS_PORT}/\$1 [P,L]
"
    CMS_PROXY_BLOCK="    # Directus — MUST precede the catch-all ProxyPass / below (05 §8.2 step 8).
    ProxyPass        /cms/  http://127.0.0.1:${CMS_PORT}/
    ProxyPassReverse /cms/  http://127.0.0.1:${CMS_PORT}/
"
  else
    CMS_LOCATION_BLOCK=""
    CMS_PROXY_BLOCK=""
    info "Directus    : DEPLOY_DIRECTUS=false — /cms/ proxy omitted from vhost"
  fi

  if $TLS_AVAILABLE; then
    CHAIN_LINE=""
    [[ -n "$CHAIN_FILE" && -f "$CHAIN_FILE" ]] && \
      CHAIN_LINE="    SSLCertificateChainFile ${CHAIN_FILE}"
    HTTPS_BLOCK="<VirtualHost *:443>
    ServerName ${SERVER_NAME}

    # ── HTTP/2 (06 §2.2) ────────────────────────────────────────────────────
    # ALPN advertises h2; clients that don't speak it fall back to http/1.1.
    Protocols h2 http/1.1

    SSLEngine on
    SSLCertificateFile    ${CERT_FILE}
    SSLCertificateKeyFile ${KEY_FILE}
${CHAIN_LINE}
    SSLProtocol           -all +TLSv1.2 +TLSv1.3
    SSLCipherSuite        HIGH:!aNULL:!MD5
    SSLHonorCipherOrder   on

    # ── Security headers (07 §3) — Apache owns HSTS + CSP only ──────────────
    # The other 6 headers (X-Content-Type-Options, X-Frame-Options,
    # Referrer-Policy, Permissions-Policy, COOP, CORP) are set by the app's
    # SecurityHeadersMiddleware — do NOT duplicate them here.
    Header always set Strict-Transport-Security \"max-age=31536000; includeSubDomains\"
    # DEFAULT CSP profile (/, /app/, /api). Overridden for /anatomy/ below.
    # ${CSP_HEADER} is enforced or Report-Only per the CSP_ENFORCE gate.
    Header always set ${CSP_HEADER} \"${CSP_DEFAULT}\"
    Header always set Report-To \"${REPORT_TO_JSON}\"

    # ── Compression (06 §2.3) ───────────────────────────────────────────────
    AddOutputFilterByType DEFLATE text/html text/plain text/css application/javascript application/json image/svg+xml application/xml

    # v2 paths — see docs/architecture/v2/01-blueprint.md §7
    Alias /anatomy \"${APP_HOME}/content/frozen\"
    <Directory \"${APP_HOME}/content/frozen\">
        Require all granted
        DirectoryIndex anatomy-of-code-course.html
        Options -Indexes +FollowSymLinks
    </Directory>

    Alias /app \"${APP_HOME}/frontend\"
    <Directory \"${APP_HOME}/frontend\">
        Require all granted
        DirectoryIndex index.html
        Options -Indexes +FollowSymLinks
        FallbackResource /app/index.html
    </Directory>

    # Q-13: NO 'Alias /static/' — FastAPI mounts /static/ itself; let it fall
    # through to ProxyPass so the app's CSS/JS bundles ship from uvicorn.

    # ── Cache-Control per location (06 §2.4) ────────────────────────────────
    # Every directive uses 'Header always set' so the value rides 304s too
    # (C-09 — 'Header set' alone is dropped on Not-Modified responses). Apache
    # auto-emits ETag for static files under /app/ and /anatomy/.

    # Buildless SPA: no content-hash in the URL, so revalidate every load. Do
    # NOT use immutable here — the filenames are stable across deploys.
    <Location \"/app/\">
        Header always set Cache-Control \"public, max-age=0, must-revalidate\"
    </Location>
    # Enable when cache-bust versioning lands (06 §3): hashed URLs are
    # content-addressed and safe to cache forever.
    #<LocationMatch \"^/app/(css|js)/v=[0-9a-f]+/\">
    #    Header always set Cache-Control \"public, max-age=31536000, immutable\"
    #</LocationMatch>

    # Frozen monolith + runbooks/FAQs: changes rarely, 1-day window + ETag.
    <Location \"/anatomy/\">
        Header always set Cache-Control \"public, max-age=86400, must-revalidate\"
        # COURSE CSP profile — adds media-src 'self' for the monolith's <video>
        # tags (C-67). Overrides the vhost-level DEFAULT profile above for this
        # path; 'always set' replaces, so no duplicate header ships.
        Header always set ${CSP_HEADER} \"${CSP_COURSE}\"
    </Location>

    # Dynamic runbook reader — re-validates each load (content changes on upload).
    <Location \"/runbook\">
        Header always set Cache-Control \"no-cache\"
    </Location>
    # Runbook API: list + detail re-validate; template download is stable.
    <LocationMatch \"^/api/runbooks/\">
        Header always set Cache-Control \"public, max-age=0, must-revalidate\"
    </LocationMatch>

    # Course JSON: app emits a strong ETag; revalidate every load.
    <LocationMatch \"^/api/course/\">
        Header always set Cache-Control \"public, max-age=0, must-revalidate\"
    </LocationMatch>
    # Feed mutates (posts, flags) — never serve a cached copy without revalidating.
    <LocationMatch \"^/api/feed\">
        Header always set Cache-Control \"no-cache\"
    </LocationMatch>
    # Media: stable asset_id, but moderated/deleted media must be able to expire,
    # so NOT immutable (C-30) — a 1-day revalidating window instead.
    <LocationMatch \"^/media/\">
        Header always set Cache-Control \"public, max-age=86400, must-revalidate\"
    </LocationMatch>
    # Signed certificate PDFs are user-private and byte-stable. 'private' keeps
    # them out of shared caches; Vary: Cookie defends in depth against a
    # misconfigured proxy serving one user's PDF to another (C-10).
    <LocationMatch \"^/certificate/\">
        Header always set Cache-Control \"private, max-age=86400, must-revalidate\"
        Header always set Vary \"Cookie\"
    </LocationMatch>

    # ── Rate limiting (C-29) — throttle the media upload endpoint ────────────
    <Location \"/api/media/upload\">
        SetOutputFilter RATE_LIMIT
        SetEnv rate-limit 4096
    </Location>

    # ── CMS webhook loopback-only (Q-15 / C-52) ─────────────────────────────
    # Defense in depth — the app already rejects non-loopback callers. This
    # <Location> sits AFTER ProxyPass / below so the Require is evaluated for
    # the proxied request (mod_authz_core Require applies alongside ProxyPass).
    <Location \"/api/cms/webhook\">
        Require ip 127.0.0.1 ::1
    </Location>

    # ── CMS role-mirror loopback-only (04 §7.2) ─────────────────────────────
    # Same model as the webhook above: the Directus roles-sync hook POSTs staff
    # role changes to FastAPI over loopback only; the app also rejects
    # non-loopback callers. Co-resident by design.
    <Location \"/api/cms/roles-sync\">
        Require ip 127.0.0.1 ::1
    </Location>

${CMS_LOCATION_BLOCK}
    # /runbook → content/frozen/runbook.html (dynamic reader, served as static file)
    RewriteRule ^/runbook$ /anatomy/runbook.html [L]

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto \"https\"
    ProxyPass        /anatomy !
    ProxyPass        /app     !
    ProxyPass        /runbook !
${CMS_PROXY_BLOCK}    ProxyPass        /  http://127.0.0.1:${QUIZ_PORT}/
    ProxyPassReverse /  http://127.0.0.1:${QUIZ_PORT}/

    ErrorLog  ${APACHE_LOG_DIR}/${SERVICE_NAME}_error.log
    CustomLog ${APACHE_LOG_DIR}/${SERVICE_NAME}_access.log combined
</VirtualHost>"
  else
    HTTPS_BLOCK=""
  fi

  info "Writing $APACHE_SITE_FILE …"
  printf '%s\n\n%s\n' "$HTTP_BLOCK" "$HTTPS_BLOCK" > "$APACHE_SITE_FILE"

  if [[ "$OS_FAMILY" == "debian" ]]; then
    a2dissite 000-default.conf >/dev/null 2>&1 && info "Disabled 000-default.conf" || true
    a2ensite "${SERVICE_NAME}.conf" >/dev/null 2>&1
    ok "Site ${SERVICE_NAME}.conf enabled"
  else
    [[ -f /etc/httpd/conf.d/welcome.conf ]] && \
      mv /etc/httpd/conf.d/welcome.conf /etc/httpd/conf.d/welcome.conf.disabled 2>/dev/null \
      && info "Disabled welcome.conf" || true
  fi

  info "Validating Apache config ($APACHE_TEST) …"
  if "$APACHE_TEST" 2>&1 | grep -q "Syntax OK"; then
    ok "Apache config syntax OK"
  else
    "$APACHE_TEST" 2>&1 | while read -r line; do warn "  $line"; done
    die "Apache config has errors — see above."
  fi

  systemctl enable "$APACHE_SERVICE" >/dev/null 2>&1 || true
  info "(Re)starting $APACHE_SERVICE …"
  systemctl restart "$APACHE_SERVICE"
  ok "$APACHE_SERVICE running  ($(systemctl is-active $APACHE_SERVICE))"
fi

# ── STEP 10 · Firewall ───────────────────────────────────────────────────────
if ! $UPDATE_ONLY; then
  step "Firewall"
  if command -v ufw &>/dev/null && systemctl is-active --quiet ufw 2>/dev/null; then
    info "Firewall: ufw detected"
    ufw allow 80/tcp  >/dev/null && ok "  ufw: port 80 allowed"
    ufw allow 443/tcp >/dev/null && ok "  ufw: port 443 allowed"
    ufw --force enable >/dev/null
    ok "ufw rules applied"
  elif systemctl is-active --quiet firewalld 2>/dev/null; then
    info "Firewall: firewalld detected"
    firewall-cmd --permanent --add-service=http  >/dev/null && ok "  firewalld: http allowed"
    firewall-cmd --permanent --add-service=https >/dev/null && ok "  firewalld: https allowed"
    firewall-cmd --reload >/dev/null
    ok "firewalld rules applied and reloaded"
  else
    warn "No active firewall detected (ufw / firewalld)"
    warn "Open ports 80 and 443 manually if needed."
    warn "Azure users: also check Network Security Group → Inbound rules in the Azure Portal."
  fi
fi

# ── STEP 11 · Postgres tuning + LO sweep (3-ops artefacts) ───────────────────
# Installs two files authored by the 3-ops slice:
#   • infra/postgres/cca-tuning.conf → PG conf.d, then reload (06 §6.1)
#   • infra/cron/vacuumlo.sh         → nightly systemd timer (cron fallback)
#                                      to sweep orphaned large objects (03 §7.2)
# Both are GUARDED by existence checks: 3-ops runs in parallel and the files may
# not be present in an older bundle. Missing source = skip with a warning, never
# fatal. Every action is idempotent — safe to re-run.
#
# EXTERNAL mode: both artefacts are LOCAL-server operations — editing the live
# postgresql.conf's conf.d and running vacuumlo as the local 'postgres' OS user.
# On a remote managed instance neither exists on this VM; server tuning + the LO
# sweep belong on the DB server and are owned by the DBA. So the whole step is
# skipped (and not counted) in external mode.
if [[ "$DB_MODE" == "external" ]]; then
  TOTAL_STEPS=$((TOTAL_STEPS - 1))
  if ! $UPDATE_ONLY; then
    info "Postgres tuning + LO sweep: SKIPPED in external mode (remote DB — DBA owns server tuning + vacuumlo)."
  fi
elif ! $UPDATE_ONLY; then
  step "Postgres tuning + LO sweep"

  PG_TUNING_SRC="$SRC_DIR/infra/postgres/cca-tuning.conf"
  VACUUMLO_SRC="$SRC_DIR/infra/cron/vacuumlo.sh"

  # ── (a) Postgres tuning conf → conf.d ──────────────────────────────────────
  if [[ -f "$PG_TUNING_SRC" ]]; then
    # Detect the active server's conf.d. Prefer the directory next to the live
    # postgresql.conf (PG_CONF was resolved in step 6); fall back to scanning
    # the standard Debian / RHEL locations.
    PG_CONFD=""
    if [[ -n "${PG_CONF:-}" && -f "${PG_CONF:-}" ]]; then
      PG_CONFD="$(dirname "$PG_CONF")/conf.d"
    fi
    if [[ -z "$PG_CONFD" || ! -d "$PG_CONFD" ]]; then
      for d in /etc/postgresql/*/main/conf.d \
               /var/lib/pgsql/*/data/conf.d \
               /var/lib/pgsql/data/conf.d; do
        [[ -d "$d" ]] && { PG_CONFD="$d"; break; }
      done
    fi
    # If no conf.d exists yet, create one next to postgresql.conf and make sure
    # the base config includes it.
    if [[ -z "$PG_CONFD" && -n "${PG_CONF:-}" && -f "${PG_CONF:-}" ]]; then
      PG_CONFD="$(dirname "$PG_CONF")/conf.d"
      mkdir -p "$PG_CONFD"
      if ! grep -qE "^\s*include_dir\s+'?conf\.d'?" "$PG_CONF"; then
        echo "include_dir 'conf.d'" >> "$PG_CONF"
        info "Added include_dir 'conf.d' to $PG_CONF"
      fi
    fi

    if [[ -n "$PG_CONFD" && -d "$PG_CONFD" ]]; then
      cp "$PG_TUNING_SRC" "$PG_CONFD/cca-tuning.conf"
      chmod 644 "$PG_CONFD/cca-tuning.conf"
      ok "PG tuning conf installed → $PG_CONFD/cca-tuning.conf"
      if [[ -n "${PG_SVC:-}" ]]; then
        systemctl reload "$PG_SVC" 2>/dev/null \
          || systemctl restart "$PG_SVC" 2>/dev/null \
          || warn "Could not reload $PG_SVC — apply tuning manually"
        ok "PostgreSQL reloaded to pick up tuning"
      else
        warn "PG service name unknown — reload PostgreSQL manually to apply tuning"
      fi
    else
      warn "No PostgreSQL conf.d found — copy cca-tuning.conf in by hand"
    fi
  else
    warn "infra/postgres/cca-tuning.conf absent (3-ops slice not in bundle) — skipping PG tuning"
  fi

  # ── (b) vacuumlo nightly sweep → systemd timer (cron fallback) ─────────────
  if [[ -f "$VACUUMLO_SRC" ]]; then
    install -m 0755 "$VACUUMLO_SRC" /usr/local/bin/dept-vacuumlo.sh
    ok "LO sweep installed → /usr/local/bin/dept-vacuumlo.sh"

    if command -v systemctl &>/dev/null; then
      # Preferred: systemd timer (journald integration, per 06 §6.4).
      cat > /etc/systemd/system/dept-vacuumlo.service <<EOF
[Unit]
Description=DEPT CCA — sweep orphaned Postgres large objects (vacuumlo)
After=${PG_SVC:-postgresql}.service

[Service]
Type=oneshot
User=postgres
ExecStart=/usr/local/bin/dept-vacuumlo.sh
EOF
      cat > /etc/systemd/system/dept-vacuumlo.timer <<EOF
[Unit]
Description=DEPT CCA — nightly vacuumlo sweep

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
      systemctl daemon-reload
      systemctl enable --now dept-vacuumlo.timer >/dev/null 2>&1 \
        && ok "dept-vacuumlo.timer enabled (nightly 03:30)" \
        || warn "Could not enable dept-vacuumlo.timer — enable it manually"
    elif [[ -d /etc/cron.d ]]; then
      # Fallback: cron.d entry running as postgres.
      printf '30 3 * * * postgres /usr/local/bin/dept-vacuumlo.sh\n' \
        > /etc/cron.d/dept-vacuumlo
      chmod 644 /etc/cron.d/dept-vacuumlo
      ok "LO sweep cron installed → /etc/cron.d/dept-vacuumlo (nightly 03:30)"
    else
      warn "Neither systemd nor /etc/cron.d available — schedule dept-vacuumlo.sh manually"
    fi
  else
    warn "infra/cron/vacuumlo.sh absent (3-ops slice not in bundle) — skipping LO sweep install"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────
ELAPSED=$(( SECONDS - DEPLOY_START ))
PROTO="https"; $TLS_AVAILABLE || PROTO="http"

printf '\n%b' "$C_GREEN"
printf '╔══════════════════════════════════════════════════════════╗\n'
printf '║   ✓  Deploy complete in %ds%-31s║\n' "$ELAPSED" ""
printf '╚══════════════════════════════════════════════════════════╝\n'
printf '%b\n' "$C_RESET"

printf '%b┌─ URLs ──────────────────────────────────────────────────────────────────┐%b\n' "$C_CYAN" "$C_RESET"
printf '%b│%b  Quiz / cert app  : %s://%s/\n'                  "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  SPA (Feed/Read)  : %s://%s/app/\n'              "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  Course           : %s://%s/anatomy/anatomy-of-code-course.html\n' "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  Checklist        : %s://%s/anatomy/code-coder-checklist.html\n'   "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  Runbook (static) : %s://%s/anatomy/architect-runbook.html\n'      "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  Runbook index    : %s://%s/runbook\n'                             "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  Runbook upload   : %s://%s/api/runbooks/upload  (POST .xlsx)\n'  "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  Runbook template : %s://%s/api/runbooks/template\n'              "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  FAQs             : %s://%s/anatomy/faqs/index.html\n'             "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
$TLS_AVAILABLE && \
printf '%b│%b  OAuth callback   : https://%s/auth/google/callback\n'             "$C_CYAN" "$C_RESET" "$DOMAIN" || true
[[ "$DEPLOY_DIRECTUS" == "true" ]] && \
printf '%b│%b  CMS (Directus)   : %s://%s/cms/\n'                "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN" || true
printf '%b└─────────────────────────────────────────────────────────────────────────┘%b\n\n' "$C_CYAN" "$C_RESET"

printf '%b┌─ Operations ────────────────────────────────────────────────────────────┐%b\n' "$C_CYAN" "$C_RESET"
printf '%b│%b  App status   : systemctl status %s\n'              "$C_CYAN" "$C_RESET" "$SERVICE_NAME"
printf '%b│%b  App logs     : journalctl -u %s -f\n'              "$C_CYAN" "$C_RESET" "$SERVICE_NAME"
printf '%b│%b  Web logs     : tail -f %s/%s_error.log\n'          "$C_CYAN" "$C_RESET" "$APACHE_LOG_DIR" "$SERVICE_NAME"
printf '%b│%b  Restart app  : systemctl restart %s\n'             "$C_CYAN" "$C_RESET" "$SERVICE_NAME"
printf '%b│%b  Reload web   : systemctl reload %s\n'              "$C_CYAN" "$C_RESET" "$APACHE_SERVICE"
printf '%b│%b  Update code  : sudo %s/deploy.sh --update\n'       "$C_CYAN" "$C_RESET" "$APP_HOME"
if [[ "$DB_MODE" == "external" ]]; then
printf '%b│%b  DB connect   : PGSSLMODE=%s psql -U %s -d %s -h %s -p %s\n' "$C_CYAN" "$C_RESET" "$DB_SSLMODE" "$DB_USER" "$DB_NAME" "$DB_HOST" "$DB_PORT"
else
printf '%b│%b  DB connect   : psql -U %s -d %s -h 127.0.0.1\n'   "$C_CYAN" "$C_RESET" "$DB_USER" "$DB_NAME"
fi
[[ "$DEPLOY_DIRECTUS" == "true" ]] && {
printf '%b│%b  CMS status   : systemctl status %s\n'              "$C_CYAN" "$C_RESET" "$CMS_SERVICE_NAME"
printf '%b│%b  CMS logs     : journalctl -u %s -f\n'              "$C_CYAN" "$C_RESET" "$CMS_SERVICE_NAME"
printf '%b│%b  Restart CMS  : systemctl restart %s\n'             "$C_CYAN" "$C_RESET" "$CMS_SERVICE_NAME"
} || true
printf '%b└─────────────────────────────────────────────────────────────────────────┘%b\n\n' "$C_CYAN" "$C_RESET"

# Surface the generated Directus admin password once (first install only). It is
# in cms/.env; we print it here so the operator can capture it before rotating.
if [[ "$DEPLOY_DIRECTUS" == "true" && -n "${CMS_ADMIN_PASSWORD:-}" ]]; then
  warn "Directus break-glass admin: ${CMS_ADMIN_EMAIL}"
  warn "  initial password: ${CMS_ADMIN_PASSWORD}   (stored in ${APP_HOME}/cms/.env — rotate after first login)"
fi

if grep -q '^QUIZ_DEV_MODE=true' "$QUIZ_DIR/.env" 2>/dev/null; then
  warn "DEV mode active — email login only, no real OAuth or SMTP."
  warn "Edit $QUIZ_DIR/.env and restart to enable production auth."
fi
if ! $TLS_AVAILABLE; then
  warn "TLS not configured — running on HTTP."
  warn "Get a cert:  sudo certbot --apache -d ${DOMAIN}"
  warn "Then set CERT_FILE/KEY_FILE and re-run ./deploy.sh"
fi
