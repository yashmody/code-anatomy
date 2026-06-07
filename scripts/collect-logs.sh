#!/usr/bin/env bash
# collect-logs.sh — bundle all DEPT® Anatomy-of-Code logs + diagnostics into ONE
# redacted text file you can paste/attach when something isn't working.
#
# Works on the PROD VM (systemd + Apache) and locally. It gathers what it can
# and notes what's unavailable — it never fails just because a piece is missing.
#
# Secrets (DB passwords, API keys, tokens, JWTs, Bearer headers) are REDACTED
# before the file is written, so the bundle is safe to share.
#
# Usage (on the VM, as root or with sudo so journalctl is readable):
#   sudo ./scripts/collect-logs.sh
#   sudo APP_HOME=/opt/dept-anatomy LINES=800 ./scripts/collect-logs.sh
#
# Output: /tmp/cca-diagnostics-<timestamp>.txt   (path printed at the end)

set -uo pipefail

APP_HOME="${APP_HOME:-/opt/dept-anatomy}"
SERVICE="${SERVICE:-cca-quiz}"
CMS_SERVICE="${CMS_SERVICE:-cms-directus}"
LINES="${LINES:-600}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000}"

TS="$(date +%Y%m%d-%H%M%S 2>/dev/null || echo now)"
RAW="$(mktemp 2>/dev/null || echo /tmp/cca-raw.$$)"
OUT="${OUT:-/tmp/cca-diagnostics-$TS.txt}"

have() { command -v "$1" >/dev/null 2>&1; }
sec()  { printf '\n\n===== %s =====\n' "$1"; }
run()  { if have "${1%% *}" || [ -x "${1%% *}" ]; then eval "$@" 2>&1; else echo "(command not available: ${1%% *})"; fi; }

# Resolve Apache + app-log + deploy-log paths across distros, newest-first.
first_existing() { for p in "$@"; do [ -e "$p" ] && { echo "$p"; return; }; done; }
APACHE_ERR="$(first_existing /var/log/httpd/cca-quiz_error.log /var/log/apache2/cca-quiz_error.log /var/log/httpd/error_log)"
APACHE_ACC="$(first_existing /var/log/httpd/cca-quiz_access.log /var/log/apache2/cca-quiz_access.log /var/log/httpd/access_log)"
APP_LOG="$(first_existing "$APP_HOME/backend/logs/backend-app.log" "$APP_HOME/logs/backend-app.log" ./backend/logs/backend-app.log)"
DEPLOY_LOG="$(ls -t /var/log/cca/deploy-*.log "$APP_HOME"/logs/deploy-*.log ./logs/deploy-*.log 2>/dev/null | head -1)"

{
  sec "META"
  echo "generated : $(date 2>&1)"
  echo "host      : $(hostname 2>&1)"
  echo "os        : $(uname -a 2>&1)"
  echo "APP_HOME  : $APP_HOME"
  echo "APP_ENV   : ${APP_ENV:-(unset)}"
  echo "whoami    : $(whoami 2>&1)  (journalctl needs root/sudo)"

  sec "CODE REVISION"
  run "git -C '$APP_HOME' rev-parse HEAD"
  run "git -C '$APP_HOME' log --oneline -3"

  sec "SYSTEMD · $SERVICE status"
  run "systemctl status '$SERVICE' --no-pager -l | head -40"
  sec "SYSTEMD · $CMS_SERVICE status"
  run "systemctl status '$CMS_SERVICE' --no-pager -l | head -40"

  sec "JOURNAL · $SERVICE (last $LINES)"
  run "journalctl -u '$SERVICE' -n '$LINES' --no-pager"
  sec "JOURNAL · $CMS_SERVICE (last 300)"
  run "journalctl -u '$CMS_SERVICE' -n 300 --no-pager"

  sec "APACHE error log  ($APACHE_ERR)"
  [ -n "$APACHE_ERR" ] && tail -n 200 "$APACHE_ERR" 2>&1 || echo "(not found)"
  sec "APACHE access log (tail)  ($APACHE_ACC)"
  [ -n "$APACHE_ACC" ] && tail -n 60 "$APACHE_ACC" 2>&1 || echo "(not found)"
  sec "APACHE config test"
  run "httpd -t" ; run "apache2ctl -t"

  sec "APP FILE LOG  ($APP_LOG)"
  [ -n "$APP_LOG" ] && tail -n 200 "$APP_LOG" 2>&1 || echo "(not found — app may not have started, or LOG_TO_FILE is off)"

  sec "DEPLOY LOG (tail)  ($DEPLOY_LOG)"
  [ -n "$DEPLOY_LOG" ] && tail -n 150 "$DEPLOY_LOG" 2>&1 || echo "(no deploy log found)"

  sec "HEALTH / READINESS"
  run "curl -fsS -m 6 '$HEALTH_URL/healthz'" ; echo
  run "curl -fsS -m 6 '$HEALTH_URL/readyz'"  ; echo

  sec "ALEMBIC current"
  run "cd '$APP_HOME/backend' && .venv/bin/alembic current 2>&1 | tail -3"

  sec "LISTENING PORTS (80/443/8000/8055)"
  if have ss; then run "ss -ltnp | grep -E ':(80|443|8000|8055)\\b'"
  else run "netstat -ltnp 2>/dev/null | grep -E ':(80|443|8000|8055)\\b'"; fi

  sec "PROCESSES (uvicorn / directus / httpd)"
  run "ps aux | grep -E 'uvicorn|directus|httpd|apache2' | grep -v grep"

  sec "DISK / MEM"
  run "df -h '$APP_HOME' /var" ; run "free -h"
} > "$RAW" 2>&1

# ── Redact secrets before writing the shareable file ─────────────────────────
# perl is present on the prod VM and macOS; consistent case-insensitive regex.
if have perl; then
  perl -pe '
    s{(://[^:/@\s]+:)[^@\s]+(@)}{$1***REDACTED***$2}g;                       # url passwords
    s{(?i)\b(password|passwd|pwd|secret|secret_key|app_payload_secret|token|api[_-]?key|llm_api_key|client_secret|google_client_secret|db_password|admin_password|directus_admin_token|cert_hmac[a-z_]*)\b(["'"'"'\s]*[:=]["'"'"'\s]*)\S+}{$1$2***REDACTED***}g;
    s{sk-ant-[A-Za-z0-9_\-]+}{sk-ant-***REDACTED***}g;
    s{(?i)\bBearer\s+\S+}{Bearer ***REDACTED***}g;
    s{eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{6,}}{***JWT-REDACTED***}g;
  ' "$RAW" > "$OUT"
else
  echo "[collect-logs] WARNING: perl not found — secrets NOT redacted; review before sharing." >&2
  cp "$RAW" "$OUT"
fi
rm -f "$RAW" 2>/dev/null

echo "============================================================"
echo " Diagnostics written to: $OUT"
echo " Secrets redacted (passwords, API keys, tokens, JWTs)."
echo " Review it, then paste/attach the file contents here."
echo "============================================================"
