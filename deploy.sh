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
# Layout produced on the VM:
#   https://<vm>/             → quiz + certification app (FastAPI, via proxy)
#   https://<vm>/app/         → static SPA (Feed / Manual / Read)
#   https://<vm>/anatomy/     → static content-system (course, checklist, runbooks, FAQs)
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
QUIZ_WORKERS="${QUIZ_WORKERS:-2}"
DOMAIN="${DOMAIN:-internal.in.deptagency.com}"
SERVER_NAME="${SERVER_NAME:-$DOMAIN}"

DB_NAME="${DB_NAME:-codecoder}"
DB_USER="${DB_USER:-codecoder}"
DB_PASS="${DB_PASS:-}"

# TLS — override if your certs live elsewhere.
# Defaults are set after OS detection below.
CERT_FILE="${CERT_FILE:-}"
KEY_FILE="${KEY_FILE:-}"
CHAIN_FILE="${CHAIN_FILE:-}"

GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"

SERVICE_NAME="cca-quiz"
TOTAL_STEPS=10
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_START=$SECONDS
STEP_NUM=0

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
printf '║   Mode   : %-46s║\n' "$( $UPDATE_ONLY && echo '--update (code + restart only)' || echo 'full install')"
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
# Run a command as the postgres OS user. Tries runuser first (RHEL standard,
# bypasses PAM su restrictions), then su -. Always wrapped in `timeout` so a
# misconfigured socket / TCP fallback cannot hang the script.
# Inherits PGCONNECT_TIMEOUT and PGHOST from the parent environment.
pg_exec() {
  local cmd="PGCONNECT_TIMEOUT=${PGCONNECT_TIMEOUT:-3} ${PGHOST:+PGHOST=$PGHOST} $*"
  if command -v runuser &>/dev/null; then
    timeout 10 runuser -l postgres -c "$cmd"
  else
    timeout 10 su - postgres -c "$cmd"
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

# ── STEP 1 · Pre-flight checks ───────────────────────────────────────────────
step "Pre-flight checks"

if ! $UPDATE_ONLY; then
  # Python
  PYBIN=""
  for candidate in python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$candidate" &>/dev/null; then
      PYBIN="$(command -v "$candidate")"; break
    fi
  done
  [[ -n "$PYBIN" ]] \
    || die "Python 3 not found. Install: sudo apt install python3 python3-venv python3-pip"

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

  # Run a trivial query with explicit socket path + connect timeout.
  # PGHOST forces psql to use the socket (no silent TCP fallback).
  export PGHOST="$PG_SOCK"
  export PGCONNECT_TIMEOUT=3
  if pg_exec "psql -c 'SELECT 1'" >/dev/null 2>&1; then
    ok "PostgreSQL  : reachable via socket ($PG_SOCK)"
  else
    info "Trying to capture the actual psql error:"
    pg_exec "psql -c 'SELECT 1'" 2>&1 | head -5 | while read -r l; do warn "  $l"; done
    die "psql failed even with explicit socket path. Check $PG_SOCK permissions."
  fi

  ok "All pre-flight checks passed"
else
  PYBIN="$APP_HOME/quiz-certification/.venv/bin/python"
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

mkdir -p "$APP_HOME"
info "Running rsync from $SRC_DIR …"

RSYNC_OUT="$(rsync -a --delete --stats \
  --exclude '.venv/' \
  --exclude 'quiz-certification/quiz_results/' \
  --exclude 'quiz-certification/certificates/' \
  --exclude 'quiz-certification/outbox/' \
  --exclude 'quiz-certification/.env' \
  --exclude 'content-architecture/venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "$SRC_DIR/content-system" \
  "$SRC_DIR/quiz-certification" \
  "$SRC_DIR/app" \
  "$SRC_DIR/content-architecture" \
  "$APP_HOME/" 2>&1)"

# Print key rsync stats
echo "$RSYNC_OUT" | grep -E 'Number of files:|transferred|speedup' | while read -r line; do
  info "$line"
done

QUIZ_DIR="$APP_HOME/quiz-certification"
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
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" "$QUIZ_DIR/.env"
  ok "Generated SECRET_KEY"

  if [[ -z "$DB_PASS" ]]; then
    DB_PASS="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(24))')"
    ok "Generated DB password"
  fi
  DB_URL="postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"

  sed -i "s|^GOOGLE_REDIRECT_URI=.*|GOOGLE_REDIRECT_URI=https://${DOMAIN}/auth/google/callback|" \
    "$QUIZ_DIR/.env"
  ok "OAuth redirect URI   → https://${DOMAIN}/auth/google/callback"

  if grep -qE '^#?\s*DATABASE_URL=' "$QUIZ_DIR/.env"; then
    sed -i "s|^#\?\s*DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" "$QUIZ_DIR/.env"
  else
    echo "DATABASE_URL=${DB_URL}" >> "$QUIZ_DIR/.env"
  fi
  ok "DATABASE_URL         → postgresql://${DB_USER}:***@localhost:5432/${DB_NAME}"

  if [[ -n "$GOOGLE_CLIENT_ID" && -n "$GOOGLE_CLIENT_SECRET" ]]; then
    sed -i "s|^QUIZ_DEV_MODE=.*|QUIZ_DEV_MODE=false|"                       "$QUIZ_DIR/.env"
    sed -i "s|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}|"   "$QUIZ_DIR/.env"
    sed -i "s|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}|" "$QUIZ_DIR/.env"
    ok "Mode                 → PRODUCTION (OAuth enabled)"
    warn "Remember to set SMTP_HOST/USER/PASS in $QUIZ_DIR/.env"
  else
    ok "Mode                 → DEV (email login, no OAuth required)"
    warn "To enable production auth: set QUIZ_DEV_MODE=false + GOOGLE_CLIENT_ID/SECRET + SMTP"
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
if ! pg_exec "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" \
    2>/dev/null | grep -q 1; then
  [[ -z "$DB_PASS" ]] && \
    DB_PASS="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(24))')"
  pg_exec "psql -c \"CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}'\""
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}|" \
    "$QUIZ_DIR/.env"
  ok "Role '${DB_USER}' created"
else
  ok "Role '${DB_USER}' already exists"
fi

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
if [[ -z "$DB_PASS" ]]; then
  DB_PASS="$(grep '^DATABASE_URL=' "$QUIZ_DIR/.env" \
             | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')" || DB_PASS=""
fi

info "Applying deploy_schema.sql …"
if [[ -n "$DB_PASS" ]]; then
  PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -d "$DB_NAME" -h 127.0.0.1 \
    -f "$QUIZ_DIR/deploy_schema.sql" \
    2>&1 | grep -v '^$' | while read -r line; do info "  pg: $line"; done
else
  su - "$APP_USER" -c "psql -d ${DB_NAME} -f ${QUIZ_DIR}/deploy_schema.sql" 2>/dev/null \
    | while read -r line; do info "  pg: $line"; done \
  || pg_exec "psql -d ${DB_NAME} -f ${QUIZ_DIR}/deploy_schema.sql" \
    | while read -r line; do info "  pg: $line"; done
fi
ok "Schema applied (tables/indexes created or already exist)"

# ETL seed
info "Running ETL migration: question bank + feed + course chapters + framework …"
cd "$QUIZ_DIR"
set -a; source "$QUIZ_DIR/.env"; set +a
"$QUIZ_DIR/.venv/bin/python" -m scripts.migrate_to_postgres \
  2>&1 | while read -r line; do info "  etl: $line"; done
ok "ETL migration complete"

# ── STEP 7 · systemd service ─────────────────────────────────────────────────
step "systemd service  ($SERVICE_NAME)"

info "Writing /etc/systemd/system/${SERVICE_NAME}.service …"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=DEPT CCA Quiz (FastAPI / uvicorn)
After=network.target ${PG_SVC}.service

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${QUIZ_DIR}
EnvironmentFile=${QUIZ_DIR}/.env
ExecStart=${QUIZ_DIR}/.venv/bin/uvicorn app.main:app \\
    --host 127.0.0.1 \\
    --port ${QUIZ_PORT} \\
    --workers ${QUIZ_WORKERS} \\
    --proxy-headers \\
    --forwarded-allow-ips='*'
Restart=on-failure
RestartSec=5
# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${QUIZ_DIR}

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

# ── STEP 8 · SELinux (RHEL only) ─────────────────────────────────────────────
if $SELINUX_ON && ! $UPDATE_ONLY; then
  step "SELinux policy"
  info "Allowing httpd network connections …"
  setsebool -P httpd_can_network_connect 1
  ok "httpd_can_network_connect = on"

  info "Labelling content directories …"
  semanage fcontext -a -t httpd_sys_content_t "${APP_HOME}/content-system(/.*)?" 2>/dev/null \
    || semanage fcontext -m -t httpd_sys_content_t "${APP_HOME}/content-system(/.*)?"
  semanage fcontext -a -t httpd_sys_content_t "${APP_HOME}/app(/.*)?" 2>/dev/null \
    || semanage fcontext -m -t httpd_sys_content_t "${APP_HOME}/app(/.*)?"
  restorecon -Rv "${APP_HOME}/content-system" "${APP_HOME}/app" >/dev/null
  ok "SELinux file contexts applied"
else
  # Don't consume a step number when SELinux is skipped
  TOTAL_STEPS=$((TOTAL_STEPS - 1))
fi

# ── STEP 9 · Apache vhost config ─────────────────────────────────────────────
if ! $UPDATE_ONLY; then
  step "Apache vhost config"

  # Ubuntu: enable required modules
  if [[ "$OS_FAMILY" == "debian" ]]; then
    info "Enabling Apache modules …"
    for mod in proxy proxy_http ssl rewrite headers; do
      if a2enmod "$mod" >/dev/null 2>&1; then
        ok "  a2enmod $mod"
      else
        info "  $mod already enabled"
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

    Alias /anatomy \"${APP_HOME}/content-system\"
    <Directory \"${APP_HOME}/content-system\">
        Require all granted
        DirectoryIndex anatomy-of-code-course.html
        Options -Indexes +FollowSymLinks
    </Directory>

    Alias /app \"${APP_HOME}/app\"
    <Directory \"${APP_HOME}/app\">
        Require all granted
        DirectoryIndex index.html
        Options -Indexes +FollowSymLinks
        FallbackResource /app/index.html
    </Directory>

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto \"http\"
    ProxyPass        /anatomy !
    ProxyPass        /app     !
    ProxyPass        /  http://127.0.0.1:${QUIZ_PORT}/
    ProxyPassReverse /  http://127.0.0.1:${QUIZ_PORT}/

    ErrorLog  ${APACHE_LOG_DIR}/${SERVICE_NAME}_error.log
    CustomLog ${APACHE_LOG_DIR}/${SERVICE_NAME}_access.log combined
</VirtualHost>"
  fi

  if $TLS_AVAILABLE; then
    CHAIN_LINE=""
    [[ -n "$CHAIN_FILE" && -f "$CHAIN_FILE" ]] && \
      CHAIN_LINE="    SSLCertificateChainFile ${CHAIN_FILE}"
    HTTPS_BLOCK="<VirtualHost *:443>
    ServerName ${SERVER_NAME}

    SSLEngine on
    SSLCertificateFile    ${CERT_FILE}
    SSLCertificateKeyFile ${KEY_FILE}
${CHAIN_LINE}
    SSLProtocol           -all +TLSv1.2 +TLSv1.3
    SSLCipherSuite        HIGH:!aNULL:!MD5
    SSLHonorCipherOrder   on
    Header always set Strict-Transport-Security \"max-age=31536000; includeSubDomains\"

    Alias /anatomy \"${APP_HOME}/content-system\"
    <Directory \"${APP_HOME}/content-system\">
        Require all granted
        DirectoryIndex anatomy-of-code-course.html
        Options -Indexes +FollowSymLinks
    </Directory>

    Alias /app \"${APP_HOME}/app\"
    <Directory \"${APP_HOME}/app\">
        Require all granted
        DirectoryIndex index.html
        Options -Indexes +FollowSymLinks
        FallbackResource /app/index.html
    </Directory>

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto \"https\"
    ProxyPass        /anatomy !
    ProxyPass        /app     !
    ProxyPass        /  http://127.0.0.1:${QUIZ_PORT}/
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
printf '%b│%b  Runbooks         : %s://%s/anatomy/architect-runbook.html\n'      "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
printf '%b│%b  FAQs             : %s://%s/anatomy/faqs/index.html\n'             "$C_CYAN" "$C_RESET" "$PROTO" "$DOMAIN"
$TLS_AVAILABLE && \
printf '%b│%b  OAuth callback   : https://%s/auth/google/callback\n'             "$C_CYAN" "$C_RESET" "$DOMAIN" || true
printf '%b└─────────────────────────────────────────────────────────────────────────┘%b\n\n' "$C_CYAN" "$C_RESET"

printf '%b┌─ Operations ────────────────────────────────────────────────────────────┐%b\n' "$C_CYAN" "$C_RESET"
printf '%b│%b  App status   : systemctl status %s\n'              "$C_CYAN" "$C_RESET" "$SERVICE_NAME"
printf '%b│%b  App logs     : journalctl -u %s -f\n'              "$C_CYAN" "$C_RESET" "$SERVICE_NAME"
printf '%b│%b  Web logs     : tail -f %s/%s_error.log\n'          "$C_CYAN" "$C_RESET" "$APACHE_LOG_DIR" "$SERVICE_NAME"
printf '%b│%b  Restart app  : systemctl restart %s\n'             "$C_CYAN" "$C_RESET" "$SERVICE_NAME"
printf '%b│%b  Reload web   : systemctl reload %s\n'              "$C_CYAN" "$C_RESET" "$APACHE_SERVICE"
printf '%b│%b  Update code  : sudo %s/deploy.sh --update\n'       "$C_CYAN" "$C_RESET" "$APP_HOME"
printf '%b│%b  DB connect   : psql -U %s -d %s -h 127.0.0.1\n'   "$C_CYAN" "$C_RESET" "$DB_USER" "$DB_NAME"
printf '%b└─────────────────────────────────────────────────────────────────────────┘%b\n\n' "$C_CYAN" "$C_RESET"

if grep -q '^QUIZ_DEV_MODE=true' "$QUIZ_DIR/.env" 2>/dev/null; then
  warn "DEV mode active — email login only, no real OAuth or SMTP."
  warn "Edit $QUIZ_DIR/.env and restart to enable production auth."
fi
if ! $TLS_AVAILABLE; then
  warn "TLS not configured — running on HTTP."
  warn "Get a cert:  sudo certbot --apache -d ${DOMAIN}"
  warn "Then set CERT_FILE/KEY_FILE and re-run ./deploy.sh"
fi
