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
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root:  sudo ./deploy.sh"

UPDATE_ONLY=false
[[ "${1:-}" == "--update" ]] && UPDATE_ONLY=true

# ── OS detection ─────────────────────────────────────────────────────────────
# Sets all platform-specific variables in one place so the rest of the script
# can use them without branching.
if grep -qi 'ubuntu\|debian' /etc/os-release 2>/dev/null; then
  OS_FAMILY="debian"
  APACHE_SERVICE="apache2"
  APACHE_CONF_DIR="/etc/apache2"
  APACHE_SITE_FILE="/etc/apache2/sites-available/${SERVICE_NAME}.conf"
  APACHE_LOG_DIR="/var/log/apache2"
  APACHE_TEST="apache2ctl -t"
  # Cert defaults for Ubuntu/Azure (Let's Encrypt or manually placed)
  CERT_FILE="${CERT_FILE:-/etc/ssl/certs/${DOMAIN}.crt}"
  KEY_FILE="${KEY_FILE:-/etc/ssl/private/${DOMAIN}.key}"
  log "Detected OS family: Ubuntu / Debian"
else
  OS_FAMILY="rhel"
  APACHE_SERVICE="httpd"
  APACHE_CONF_DIR="/etc/httpd"
  APACHE_SITE_FILE="/etc/httpd/conf.d/${SERVICE_NAME}.conf"
  APACHE_LOG_DIR="/var/log/httpd"
  APACHE_TEST="httpd -t"
  CERT_FILE="${CERT_FILE:-/etc/pki/tls/certs/${DOMAIN}.crt}"
  KEY_FILE="${KEY_FILE:-/etc/pki/tls/private/${DOMAIN}.key}"
  log "Detected OS family: RHEL / CentOS"
fi

# ── pg_exec helper ───────────────────────────────────────────────────────────
# Run a command as the postgres OS user.
# Tries `runuser` first (RHEL standard, bypasses PAM su restrictions),
# then falls back to `su -`.
pg_exec() {
  if command -v runuser &>/dev/null; then
    runuser -l postgres -c "$*"
  else
    su - postgres -c "$*"
  fi
}

# ── pg_service_name ──────────────────────────────────────────────────────────
# Resolve the active PostgreSQL systemd unit name.
# Handles: postgresql (Ubuntu generic), postgresql-14/13/12 (RHEL PGDG),
#          postgresql@14-main (Ubuntu versioned).
# Returns the first active unit found, or empty string.
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
  # Not yet started — find any installed unit and return it so caller can start it
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

# SELinux is only relevant on RHEL-family VMs
SELINUX_ON=false
if [[ "$OS_FAMILY" == "rhel" ]] \
   && command -v getenforce &>/dev/null \
   && [[ "$(getenforce 2>/dev/null)" == "Enforcing" ]]; then
  SELINUX_ON=true
fi

# ── 1. Pre-flight checks ─────────────────────────────────────────────────────
# Python, Apache, and PostgreSQL are expected to be pre-installed.
# This section fails early with a clear message if any are missing.
if ! $UPDATE_ONLY; then
  log "Running pre-flight checks…"

  # Python — look for python3.x or python3 in order of preference
  PYBIN=""
  for candidate in python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$candidate" &>/dev/null; then
      PYBIN="$(command -v "$candidate")"
      break
    fi
  done
  [[ -n "$PYBIN" ]] \
    || die "Python 3 not found. Install python3 (Ubuntu: sudo apt install python3 python3-venv python3-pip)."

  PY_VER="$("$PYBIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  log "  Python: $PYBIN  ($PY_VER)"

  # python3-venv may need to be installed separately on Ubuntu
  if [[ "$OS_FAMILY" == "debian" ]]; then
    if ! "$PYBIN" -c "import venv" &>/dev/null; then
      log "  Installing python3-venv…"
      apt-get install -y -q "python3-venv" "python3-pip"
    fi
    # Build tools required for some pip packages (e.g. psycopg2)
    for pkg in build-essential libpq-dev python3-dev; do
      dpkg -s "$pkg" &>/dev/null || apt-get install -y -q "$pkg"
    done
  fi

  # Apache
  if [[ "$OS_FAMILY" == "debian" ]]; then
    command -v apache2 &>/dev/null \
      || die "apache2 not found. Install: sudo apt install apache2 libapache2-mod-proxy"
  else
    command -v httpd &>/dev/null \
      || die "httpd not found. Install: sudo dnf install httpd mod_ssl"
  fi

  # PostgreSQL client (psql) — the server is assumed to be running
  command -v psql &>/dev/null \
    || die "psql not found. Install the PostgreSQL client package."

  # Verify PostgreSQL is accepting connections.
  # -h 127.0.0.1 avoids Unix socket path differences between distros.
  # pg_isready needs no credentials and is immune to PAM restrictions.
  PG_SVC="$(pg_service_name || echo 'postgresql-14')"
  if command -v pg_isready &>/dev/null; then
    pg_isready -h 127.0.0.1 -q \
      || die "PostgreSQL is not accepting connections. Check: systemctl status ${PG_SVC}"
  else
    pg_exec "psql -h 127.0.0.1 -c 'SELECT 1'" >/dev/null 2>&1 \
      || die "Cannot connect to PostgreSQL. Check: systemctl status ${PG_SVC}"
  fi

  log "  All pre-flight checks passed."
else
  PYBIN="$APP_HOME/quiz-certification/.venv/bin/python"
fi

# ── 2. Service user ──────────────────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
  log "Creating service user '$APP_USER'…"
  useradd --system --create-home --home-dir "/home/$APP_USER" --shell /sbin/nologin "$APP_USER"
fi

# ── 3. Sync bundle into place ────────────────────────────────────────────────
log "Syncing bundle into $APP_HOME…"
mkdir -p "$APP_HOME"

# rsync the bundle. Runtime data dirs and .env are preserved across updates.
rsync -a --delete \
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
  "$APP_HOME/"

QUIZ_DIR="$APP_HOME/quiz-certification"
mkdir -p "$QUIZ_DIR"/{quiz_results,certificates,outbox}

# ── 4. Python venv + pip dependencies ───────────────────────────────────────
log "Setting up Python virtualenv in $QUIZ_DIR/.venv…"

if [[ ! -d "$QUIZ_DIR/.venv" ]]; then
  "$PYBIN" -m venv "$QUIZ_DIR/.venv"
  log "  Virtualenv created."
fi

"$QUIZ_DIR/.venv/bin/pip" install --upgrade -q pip
"$QUIZ_DIR/.venv/bin/pip" install -q -r "$QUIZ_DIR/requirements.txt"
log "  Dependencies installed."

# ── 5. Environment file (.env) ───────────────────────────────────────────────
if [[ ! -f "$QUIZ_DIR/.env" ]]; then
  log "Creating .env from .env.example…"
  cp "$QUIZ_DIR/.env.example" "$QUIZ_DIR/.env"

  # Fresh secret key
  SECRET="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" "$QUIZ_DIR/.env"

  # Generate DB password if not supplied — written now so it's available in
  # step 6 (PostgreSQL) and doesn't require a second sed pass.
  if [[ -z "$DB_PASS" ]]; then
    DB_PASS="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(24))')"
    log "  Generated DB password."
  fi
  DB_URL="postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"

  # OAuth redirect must match the configured Google Cloud project exactly
  sed -i "s|^GOOGLE_REDIRECT_URI=.*|GOOGLE_REDIRECT_URI=https://${DOMAIN}/auth/google/callback|" "$QUIZ_DIR/.env"

  # Write DATABASE_URL (comment line or existing value, or append)
  if grep -qE '^#?\s*DATABASE_URL=' "$QUIZ_DIR/.env"; then
    sed -i "s|^#\?\s*DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" "$QUIZ_DIR/.env"
  else
    echo "DATABASE_URL=${DB_URL}" >> "$QUIZ_DIR/.env"
  fi

  # Flip to production mode if OAuth creds were supplied
  if [[ -n "$GOOGLE_CLIENT_ID" && -n "$GOOGLE_CLIENT_SECRET" ]]; then
    log "  OAuth creds supplied — enabling production mode (QUIZ_DEV_MODE=false)."
    sed -i "s|^QUIZ_DEV_MODE=.*|QUIZ_DEV_MODE=false|"                       "$QUIZ_DIR/.env"
    sed -i "s|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}|"   "$QUIZ_DIR/.env"
    sed -i "s|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}|" "$QUIZ_DIR/.env"
    warn "  Production mode active. Set SMTP_HOST/USER/PASS in $QUIZ_DIR/.env."
  else
    warn "  Running in DEV mode. No Google OAuth or SMTP required."
    warn "  To switch: set QUIZ_DEV_MODE=false + GOOGLE_CLIENT_ID/SECRET + SMTP in $QUIZ_DIR/.env"
    warn "  Or re-run:  sudo GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... ./deploy.sh"
  fi
else
  log ".env already exists — leaving it untouched."
  # Read the existing DB_PASS from .env for use in the PostgreSQL step
  if [[ -z "$DB_PASS" ]]; then
    DB_PASS="$(grep '^DATABASE_URL=' "$QUIZ_DIR/.env" \
               | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')" || DB_PASS=""
  fi
fi

chown -R "$APP_USER:$APP_USER" "$APP_HOME"
chmod 600 "$QUIZ_DIR/.env"

# ── 6. PostgreSQL — role, database, schema, ETL seed ────────────────────────
log "Setting up PostgreSQL database '${DB_NAME}'…"

# Resolve the PostgreSQL service unit name (handles postgresql-14, postgresql, etc.)
PG_SVC="$(pg_service_name)" \
  || die "No PostgreSQL systemd unit found. Ensure postgresql (or postgresql-14) is installed."
log "  PostgreSQL service unit: ${PG_SVC}"

# Start if not already active
systemctl is-active --quiet "$PG_SVC" \
  || systemctl start "$PG_SVC" \
  || die "Could not start ${PG_SVC}. Check: systemctl status ${PG_SVC}"

# Wait until accepting TCP connections on 127.0.0.1 (up to 20 s)
for i in {1..20}; do
  if command -v pg_isready &>/dev/null; then
    pg_isready -h 127.0.0.1 -q && break
  else
    pg_exec "psql -h 127.0.0.1 -c 'SELECT 1'" >/dev/null 2>&1 && break
  fi
  sleep 1
  [[ $i -eq 20 ]] && die "PostgreSQL did not become ready after 20 s."
done
log "  PostgreSQL is up."

# Create role (idempotent)
if ! pg_exec "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" | grep -q 1; then
  [[ -z "$DB_PASS" ]] && \
    DB_PASS="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(24))')"
  pg_exec "psql -c \"CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}'\""
  # Persist generated password into .env
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}|" \
    "$QUIZ_DIR/.env"
  log "  Role '${DB_USER}' created."
else
  log "  Role '${DB_USER}' already exists."
fi

# Create database (idempotent)
if ! pg_exec "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" | grep -q 1; then
  pg_exec "psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}\""
  log "  Database '${DB_NAME}' created."
else
  log "  Database '${DB_NAME}' already exists."
fi

# Grant privileges (idempotent — GRANT is safe to re-run)
pg_exec "psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER}\""

# ── pg_hba.conf — add md5 entry for the app user if missing ─────────────────
# Resolve hba_file dynamically — works on Ubuntu (/etc/postgresql/…) and RHEL (/var/lib/pgsql/…)
PG_HBA="$(pg_exec "psql -tAc 'SHOW hba_file'")"
log "  pg_hba.conf: $PG_HBA"

if [[ -n "$PG_HBA" && -f "$PG_HBA" ]]; then
  HBA_CHANGED=false
  if ! grep -qE "^local\s+${DB_NAME}\s+${DB_USER}" "$PG_HBA"; then
    # Prepend before the first "local all" line
    sed -i "/^local\s\+all/i local   ${DB_NAME}   ${DB_USER}   md5" "$PG_HBA"
    HBA_CHANGED=true
  fi
  if ! grep -qE "^host\s+${DB_NAME}\s+${DB_USER}\s+127\.0\.0\.1" "$PG_HBA"; then
    sed -i "/^host\s\+all/i host   ${DB_NAME}   ${DB_USER}   127.0.0.1/32   md5" "$PG_HBA"
    HBA_CHANGED=true
  fi
  if $HBA_CHANGED; then
    systemctl reload "$PG_SVC" 2>/dev/null || systemctl restart "$PG_SVC" || true
    log "  pg_hba.conf updated and PostgreSQL reloaded."
  fi
fi

# ── Apply DDL schema (IF NOT EXISTS throughout — fully idempotent) ───────────
log "  Applying deploy_schema.sql…"
# Use the password from .env if DB_PASS is still empty (existing deployment)
if [[ -z "$DB_PASS" ]]; then
  DB_PASS="$(grep '^DATABASE_URL=' "$QUIZ_DIR/.env" \
             | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')" || DB_PASS=""
fi

if [[ -n "$DB_PASS" ]]; then
  PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -d "$DB_NAME" -h 127.0.0.1 \
    -f "$QUIZ_DIR/deploy_schema.sql"
else
  # Peer auth fallback (DB_USER matches an OS user with pg_ident)
  su - "$APP_USER" -c "psql -d ${DB_NAME} -f ${QUIZ_DIR}/deploy_schema.sql" 2>/dev/null \
    || pg_exec "psql -d ${DB_NAME} -f ${QUIZ_DIR}/deploy_schema.sql"
fi
log "  Schema applied."

# ── ETL seed (questions, feed, course chapters, framework) ───────────────────
log "  Running ETL migration (content-architecture → PostgreSQL)…"
cd "$QUIZ_DIR"
# Load DATABASE_URL from .env so the migration script picks it up
set -a; source "$QUIZ_DIR/.env"; set +a
"$QUIZ_DIR/.venv/bin/python" -m scripts.migrate_to_postgres
log "  ETL complete."

# ── 7. systemd service ───────────────────────────────────────────────────────
log "Writing systemd unit /etc/systemd/system/${SERVICE_NAME}.service…"
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

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1
systemctl restart "${SERVICE_NAME}"
log "  ${SERVICE_NAME} started. ($(systemctl is-active ${SERVICE_NAME}))"

# ── 8. SELinux (RHEL/CentOS only) ───────────────────────────────────────────
if $SELINUX_ON && ! $UPDATE_ONLY; then
  log "Applying SELinux policy (httpd network connect + content labels)…"
  setsebool -P httpd_can_network_connect 1
  semanage fcontext -a -t httpd_sys_content_t "${APP_HOME}/content-system(/.*)?" 2>/dev/null \
    || semanage fcontext -m -t httpd_sys_content_t "${APP_HOME}/content-system(/.*)?"
  semanage fcontext -a -t httpd_sys_content_t "${APP_HOME}/app(/.*)?" 2>/dev/null \
    || semanage fcontext -m -t httpd_sys_content_t "${APP_HOME}/app(/.*)?"
  restorecon -Rv "${APP_HOME}/content-system" "${APP_HOME}/app" >/dev/null
fi

# ── 9. Apache vhost config ───────────────────────────────────────────────────
if ! $UPDATE_ONLY; then
  log "Configuring Apache vhost ($APACHE_SITE_FILE)…"

  # Ubuntu: enable required modules before writing the config
  if [[ "$OS_FAMILY" == "debian" ]]; then
    for mod in proxy proxy_http ssl rewrite headers; do
      a2enmod "$mod" >/dev/null 2>&1 && log "  a2enmod $mod" || true
    done
  fi

  # Determine whether TLS certs exist; build the HTTPS block conditionally
  TLS_AVAILABLE=false
  [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]] && TLS_AVAILABLE=true

  # ── HTTP vhost (always present) ─────────────────────────────────────────
  # When TLS is available this just redirects; when not it serves the app.
  if $TLS_AVAILABLE; then
    HTTP_BLOCK="# Redirect plain HTTP → HTTPS
<VirtualHost *:80>
    ServerName ${SERVER_NAME}
    RewriteEngine On
    RewriteRule ^/?(.*) https://${SERVER_NAME}/\$1 [R=301,L]
</VirtualHost>"
  else
    warn "TLS cert not found at $CERT_FILE — serving over HTTP only."
    warn "To add TLS later: obtain a cert, set CERT_FILE/KEY_FILE, and re-run deploy.sh."
    HTTP_BLOCK="<VirtualHost *:80>
    ServerName ${SERVER_NAME}
    # --- Static content -------------------------------------------------------
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

    # --- Reverse proxy → FastAPI / uvicorn ------------------------------------
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

  # ── HTTPS vhost (only when certs are present) ────────────────────────────
  if $TLS_AVAILABLE; then
    CHAIN_LINE=""
    [[ -n "$CHAIN_FILE" && -f "$CHAIN_FILE" ]] && \
      CHAIN_LINE="    SSLCertificateChainFile ${CHAIN_FILE}"
    HTTPS_BLOCK="<VirtualHost *:443>
    ServerName ${SERVER_NAME}

    # TLS
    SSLEngine on
    SSLCertificateFile    ${CERT_FILE}
    SSLCertificateKeyFile ${KEY_FILE}
${CHAIN_LINE}
    # Modern TLS only
    SSLProtocol           -all +TLSv1.2 +TLSv1.3
    SSLCipherSuite        HIGH:!aNULL:!MD5
    SSLHonorCipherOrder   on
    Header always set Strict-Transport-Security \"max-age=31536000; includeSubDomains\"

    # --- Static content -------------------------------------------------------
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

    # --- Reverse proxy → FastAPI / uvicorn ------------------------------------
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

  # Write the config file
  printf '%s\n\n%s\n' "$HTTP_BLOCK" "$HTTPS_BLOCK" > "$APACHE_SITE_FILE"

  # Ubuntu: disable default site, enable ours
  if [[ "$OS_FAMILY" == "debian" ]]; then
    a2dissite 000-default.conf >/dev/null 2>&1 || true
    a2ensite "${SERVICE_NAME}.conf" >/dev/null 2>&1
  else
    # RHEL: silence the stock welcome page
    [[ -f /etc/httpd/conf.d/welcome.conf ]] && \
      mv /etc/httpd/conf.d/welcome.conf /etc/httpd/conf.d/welcome.conf.disabled 2>/dev/null || true
  fi

  log "Validating Apache configuration…"
  "$APACHE_TEST" 2>&1 | grep -v "Syntax OK" || true
  "$APACHE_TEST" 2>&1 | grep -q "Syntax OK" || die "Apache config has errors — check above output."

  systemctl enable  "$APACHE_SERVICE" >/dev/null 2>&1 || true
  systemctl restart "$APACHE_SERVICE"
  log "  Apache restarted. ($(systemctl is-active $APACHE_SERVICE))"
fi

# ── 10. Firewall ─────────────────────────────────────────────────────────────
if ! $UPDATE_ONLY; then
  if command -v ufw &>/dev/null && systemctl is-active --quiet ufw 2>/dev/null; then
    log "Opening ports 80 + 443 in ufw…"
    ufw allow 80/tcp  >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
    log "  ufw rules applied."
  elif systemctl is-active --quiet firewalld 2>/dev/null; then
    log "Opening ports 80 + 443 in firewalld…"
    firewall-cmd --permanent --add-service=http  >/dev/null
    firewall-cmd --permanent --add-service=https >/dev/null
    firewall-cmd --reload >/dev/null
    log "  firewalld rules applied."
  else
    warn "No active firewall detected (ufw / firewalld). Open ports 80 and 443 manually if needed."
    warn "  Azure: also check the Network Security Group inbound rules in the Azure Portal."
  fi
fi

# ── Done ─────────────────────────────────────────────────────────────────────
PROTO="https"
$TLS_AVAILABLE || PROTO="http"

log "Deploy complete."
echo
echo "  ┌─ URLs ──────────────────────────────────────────────────────────────────┐"
echo "  │  Quiz / cert app : ${PROTO}://${DOMAIN}/"
echo "  │  SPA (Feed/Read) : ${PROTO}://${DOMAIN}/app/"
echo "  │  Course          : ${PROTO}://${DOMAIN}/anatomy/anatomy-of-code-course.html"
echo "  │  Checklist       : ${PROTO}://${DOMAIN}/anatomy/code-coder-checklist.html"
echo "  │  Runbooks        : ${PROTO}://${DOMAIN}/anatomy/architect-runbook.html"
echo "  │  FAQs            : ${PROTO}://${DOMAIN}/anatomy/faqs/index.html"
$TLS_AVAILABLE && \
echo "  │  OAuth callback  : ${PROTO}://${DOMAIN}/auth/google/callback" || true
echo "  └─────────────────────────────────────────────────────────────────────────┘"
echo
echo "  ┌─ Operations ────────────────────────────────────────────────────────────┐"
echo "  │  App status  : systemctl status ${SERVICE_NAME}"
echo "  │  App logs    : journalctl -u ${SERVICE_NAME} -f"
echo "  │  Web logs    : tail -f ${APACHE_LOG_DIR}/${SERVICE_NAME}_error.log"
echo "  │  Restart app : systemctl restart ${SERVICE_NAME}"
echo "  │  Reload web  : systemctl reload ${APACHE_SERVICE}"
echo "  │  Update code : sudo $APP_HOME/deploy.sh --update"
echo "  │  DB connect  : psql -U ${DB_USER} -d ${DB_NAME} -h 127.0.0.1"
echo "  └─────────────────────────────────────────────────────────────────────────┘"
echo
if grep -q '^QUIZ_DEV_MODE=true' "$QUIZ_DIR/.env" 2>/dev/null; then
  warn "Running in DEV mode — email login only, no real OAuth or SMTP."
  warn "To enable production auth, edit $QUIZ_DIR/.env and restart the service."
fi
if ! $TLS_AVAILABLE; then
  warn "TLS is not configured. HTTPS is disabled."
  warn "Obtain a cert (Let's Encrypt: sudo certbot --apache -d ${DOMAIN})"
  warn "then set CERT_FILE/KEY_FILE and re-run ./deploy.sh to enable HTTPS."
fi
