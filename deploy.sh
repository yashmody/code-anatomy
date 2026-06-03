#!/usr/bin/env bash
# ============================================================================
# DEPT® · Anatomy of Code — single-VM deployment script
#   Target: CentOS 8 / RHEL 8 with Apache httpd (mod_proxy)
#
# Installs and runs the deploy bundle on a CentOS 8 VM:
#   • content-system/        → served as static files by Apache at /anatomy/
#   • quiz-certification/     → FastAPI app under systemd (uvicorn), proxied at /
#   • prompt-library/         → NOT deployed (consumed as a code/teaching resource)
#
# Layout produced on the VM:
#   http://<vm>/             → quiz app (FastAPI, behind Apache reverse proxy)
#   http://<vm>/anatomy/     → static content-system (course, checklist, FAQ, runbook)
#
# Usage:
#   sudo ./deploy.sh                 # full install
#   sudo ./deploy.sh --update        # pull new code + restart (skip pkg/SELinux/web setup)
#
# Re-runnable (idempotent). Handles SELinux (enforcing) and firewalld.
#
# NOTE: CentOS 8 reached end-of-life (Dec 2021); its repos now live on
# vault.centos.org. If `dnf` fails to reach mirrors, see the troubleshooting
# note printed at the end, or switch the VM to CentOS Stream 8 / a RHEL clone.
# ============================================================================
set -euo pipefail

# --- Tunables (override via environment) ------------------------------------
APP_USER="${APP_USER:-cca}"                       # dedicated service user
APP_HOME="${APP_HOME:-/opt/dept-anatomy}"         # where the bundle lives on the VM
QUIZ_PORT="${QUIZ_PORT:-8000}"                    # internal uvicorn port
QUIZ_WORKERS="${QUIZ_WORKERS:-2}"                 # uvicorn worker count
DOMAIN="${DOMAIN:-internal.in.deptagency.com}"    # public hostname this VM answers on
SERVER_NAME="${SERVER_NAME:-$DOMAIN}"             # Apache ServerName

# TLS cert files (already provisioned on this VM). Override if they live elsewhere.
CERT_FILE="${CERT_FILE:-/etc/pki/tls/certs/${DOMAIN}.crt}"
KEY_FILE="${KEY_FILE:-/etc/pki/tls/private/${DOMAIN}.key}"
CHAIN_FILE="${CHAIN_FILE:-}"                       # optional CA chain (SSLCertificateChainFile)

# Optional: pass real OAuth creds to flip straight to production mode.
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"

PYTHON_PKG="${PYTHON_PKG:-python39}"              # AppStream module: python39 (3.9) or python38
SERVICE_NAME="cca-quiz"

# Source = directory this script lives in (the bundle root)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx \033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root (use: sudo ./deploy.sh)"

UPDATE_ONLY=false
[[ "${1:-}" == "--update" ]] && UPDATE_ONLY=true

# Detect SELinux state once (getenforce may be absent if SELinux not installed)
SELINUX_ON=false
if command -v getenforce &>/dev/null && [[ "$(getenforce)" != "Disabled" ]]; then
  SELINUX_ON=true
fi

# ----------------------------------------------------------------------------
# 1. System packages  (httpd + proxy modules already present on this VM;
#    install is idempotent and just fills any gaps)
# ----------------------------------------------------------------------------
if ! $UPDATE_ONLY; then
  log "Installing system packages (${PYTHON_PKG}, httpd, mod_ssl, rsync, SELinux tools)…"
  dnf install -y -q "${PYTHON_PKG}" "${PYTHON_PKG}-devel" httpd mod_ssl rsync \
    policycoreutils-python-utils

  # TLS is required (Google OAuth callback). Fail early with a clear message.
  [[ -f "$CERT_FILE" ]] || die "TLS cert not found at $CERT_FILE — set CERT_FILE=/path/to/cert.crt"
  [[ -f "$KEY_FILE"  ]] || die "TLS key not found at $KEY_FILE — set KEY_FILE=/path/to/key.key"
  [[ -z "$CHAIN_FILE" || -f "$CHAIN_FILE" ]] || die "CHAIN_FILE set but not found: $CHAIN_FILE"
  # mod_proxy / mod_proxy_http / mod_headers ship with httpd and are loaded by
  # default via /etc/httpd/conf.modules.d/00-proxy.conf — no extra package.
  PYBIN="/usr/bin/${PYTHON_PKG/python3/python3.}"     # python39 -> python3.9
  [[ -x "$PYBIN" ]] || PYBIN="$(command -v python3.9 || command -v python3.8 || command -v python3)"
else
  PYBIN="$APP_HOME/quiz-certification/.venv/bin/python"
fi

# ----------------------------------------------------------------------------
# 2. Service user
# ----------------------------------------------------------------------------
if ! id "$APP_USER" &>/dev/null; then
  log "Creating service user '$APP_USER'…"
  useradd --system --create-home --home-dir "/home/$APP_USER" --shell /sbin/nologin "$APP_USER"
fi

# ----------------------------------------------------------------------------
# 3. Copy bundle into place
# ----------------------------------------------------------------------------
log "Syncing bundle into $APP_HOME…"
mkdir -p "$APP_HOME"
# Preserve runtime data dirs (quiz_results/certificates/outbox) and .env across updates.
rsync -a --delete \
  --exclude '.venv/' \
  --exclude 'quiz-certification/quiz_results/' \
  --exclude 'quiz-certification/certificates/' \
  --exclude 'quiz-certification/outbox/' \
  --exclude 'quiz-certification/.env' \
  "$SRC_DIR/content-system" \
  "$SRC_DIR/quiz-certification" \
  "$APP_HOME/"

QUIZ_DIR="$APP_HOME/quiz-certification"
mkdir -p "$QUIZ_DIR"/{quiz_results,certificates,outbox}

# ----------------------------------------------------------------------------
# 4. Python venv + dependencies
# ----------------------------------------------------------------------------
log "Setting up Python virtualenv (using $(${PYBIN} --version 2>&1))…"
if [[ ! -d "$QUIZ_DIR/.venv" ]]; then
  "$PYBIN" -m venv "$QUIZ_DIR/.venv"
fi
"$QUIZ_DIR/.venv/bin/pip" install --upgrade -q pip
"$QUIZ_DIR/.venv/bin/pip" install -q -r "$QUIZ_DIR/requirements.txt"

# ----------------------------------------------------------------------------
# 5. Environment file (.env)
# ----------------------------------------------------------------------------
if [[ ! -f "$QUIZ_DIR/.env" ]]; then
  log "Creating .env from .env.example (with a fresh SECRET_KEY)…"
  cp "$QUIZ_DIR/.env.example" "$QUIZ_DIR/.env"
  SECRET="$("$QUIZ_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" "$QUIZ_DIR/.env"
  # OAuth callback over https on this VM's domain.
  sed -i "s|^GOOGLE_REDIRECT_URI=.*|GOOGLE_REDIRECT_URI=https://${DOMAIN}/auth/google/callback|" "$QUIZ_DIR/.env"

  if [[ -n "$GOOGLE_CLIENT_ID" && -n "$GOOGLE_CLIENT_SECRET" ]]; then
    log "OAuth creds supplied — switching to production mode (QUIZ_DEV_MODE=false)."
    sed -i "s|^QUIZ_DEV_MODE=.*|QUIZ_DEV_MODE=false|"                       "$QUIZ_DIR/.env"
    sed -i "s|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}|"   "$QUIZ_DIR/.env"
    sed -i "s|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}|" "$QUIZ_DIR/.env"
    warn "Still set SMTP_HOST/USER/PASS in $QUIZ_DIR/.env — prod mode sends real email."
  else
    warn "Booting in DEV mode. Set QUIZ_DEV_MODE=false + GOOGLE_CLIENT_ID/SECRET + SMTP in $QUIZ_DIR/.env,"
    warn "  or re-run with: sudo GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... ./deploy.sh"
  fi
else
  log ".env already exists — leaving it untouched."
fi

chown -R "$APP_USER:$APP_USER" "$APP_HOME"
chmod 600 "$QUIZ_DIR/.env"

# ----------------------------------------------------------------------------
# 6. systemd service for the FastAPI app
# ----------------------------------------------------------------------------
log "Writing systemd unit /etc/systemd/system/${SERVICE_NAME}.service…"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=DEPT CCA Quiz (FastAPI)
After=network.target

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${QUIZ_DIR}
EnvironmentFile=${QUIZ_DIR}/.env
ExecStart=${QUIZ_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${QUIZ_PORT} --workers ${QUIZ_WORKERS}
Restart=on-failure
RestartSec=3
# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${QUIZ_DIR}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true
systemctl restart "${SERVICE_NAME}"

# ----------------------------------------------------------------------------
# 7. SELinux (enforcing by default on CentOS 8)
# ----------------------------------------------------------------------------
if $SELINUX_ON && ! $UPDATE_ONLY; then
  log "Applying SELinux policy (httpd network connect + content labels)…"
  # Let Apache open a network connection to the uvicorn backend
  setsebool -P httpd_can_network_connect 1
  # Label the static content dir so Apache is allowed to read it from /opt
  semanage fcontext -a -t httpd_sys_content_t "${APP_HOME}/content-system(/.*)?" 2>/dev/null \
    || semanage fcontext -m -t httpd_sys_content_t "${APP_HOME}/content-system(/.*)?"
  restorecon -Rv "${APP_HOME}/content-system" >/dev/null
fi

# ----------------------------------------------------------------------------
# 8. Apache httpd: static content + reverse proxy
# ----------------------------------------------------------------------------
if ! $UPDATE_ONLY; then
  log "Configuring Apache TLS vhost (/etc/httpd/conf.d/${SERVICE_NAME}.conf)…"
  cat > "/etc/httpd/conf.d/${SERVICE_NAME}.conf" <<EOF
# Redirect plain HTTP → HTTPS
<VirtualHost *:80>
    ServerName ${SERVER_NAME}
    RewriteEngine On
    RewriteRule ^/?(.*) https://${SERVER_NAME}/\$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName ${SERVER_NAME}

    SSLEngine on
    SSLCertificateFile    ${CERT_FILE}
    SSLCertificateKeyFile ${KEY_FILE}
$( [[ -n "$CHAIN_FILE" ]] && echo "    SSLCertificateChainFile ${CHAIN_FILE}" )

    # --- Static content-system files (course, checklist, FAQ, runbook) ------
    Alias /anatomy "${APP_HOME}/content-system"
    <Directory "${APP_HOME}/content-system">
        Require all granted
        DirectoryIndex anatomy-of-code-course.html
        Options +Indexes
    </Directory>

    # --- Reverse proxy everything else → the FastAPI quiz app ----------------
    # Exclude the static alias from proxying (must come before "ProxyPass /").
    ProxyPass        /anatomy !
    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass        /  http://127.0.0.1:${QUIZ_PORT}/
    ProxyPassReverse /  http://127.0.0.1:${QUIZ_PORT}/

    ErrorLog  /var/log/httpd/${SERVICE_NAME}_error.log
    CustomLog /var/log/httpd/${SERVICE_NAME}_access.log combined
</VirtualHost>
EOF

  # Silence the stock CentOS welcome page so it can't shadow "/".
  if [[ -f /etc/httpd/conf.d/welcome.conf ]]; then
    mv /etc/httpd/conf.d/welcome.conf /etc/httpd/conf.d/welcome.conf.disabled
  fi

  log "Validating Apache config (httpd -t)…"
  httpd -t
  systemctl enable httpd >/dev/null 2>&1 || true
  systemctl restart httpd
fi

# ----------------------------------------------------------------------------
# 9. firewalld — open HTTP
# ----------------------------------------------------------------------------
if ! $UPDATE_ONLY && systemctl is-active --quiet firewalld; then
  log "Opening ports 80 + 443 in firewalld…"
  firewall-cmd --permanent --add-service=http  >/dev/null
  firewall-cmd --permanent --add-service=https >/dev/null
  firewall-cmd --reload >/dev/null
fi

# ----------------------------------------------------------------------------
# Done
# ----------------------------------------------------------------------------
log "Deploy complete."
echo
echo "  Quiz app : https://${DOMAIN}/        (status: $(systemctl is-active ${SERVICE_NAME}))"
echo "  Content  : https://${DOMAIN}/anatomy/anatomy-of-code-course.html"
echo "  OAuth cb : https://${DOMAIN}/auth/google/callback   (must match Google console)"
echo
echo "  App logs : journalctl -u ${SERVICE_NAME} -f"
echo "  Web logs : tail -f /var/log/httpd/${SERVICE_NAME}_error.log"
echo "  Restart  : systemctl restart ${SERVICE_NAME} && systemctl reload httpd"
echo "  Update   : sudo $APP_HOME/deploy.sh --update   (after syncing new code)"
echo
if grep -q '^QUIZ_DEV_MODE=true' "$QUIZ_DIR/.env" 2>/dev/null; then
  warn "Running in DEV mode (email login). Add OAuth creds + SMTP and flip QUIZ_DEV_MODE=false for production."
fi
echo "  If dnf could not reach mirrors (CentOS 8 EOL), repoint repos to vault.centos.org first."
