#!/usr/bin/env bash
# Weekly Adobe content-refresh sync — cron wrapper.
#
# Schedule (Quartz, source of truth in config): 0 0 9 ? * MON *  (every Monday 09:00).
# Unix-cron equivalent for this wrapper's crontab line:
#   0 9 * * 1  cca  /opt/dept-anatomy/infra/cron/adobe-sync.sh >> /var/log/cca/adobe-sync.log 2>&1
#
# The script itself re-checks content_refresh_enabled and no-ops if disabled, so
# installing the crontab line is harmless before the feature is switched on.
# A lockfile prevents overlap if a run is slow.
set -euo pipefail

APP_HOME="${APP_HOME:-/opt/dept-anatomy}"
BACKEND="$APP_HOME/backend"
PY="${PY:-$BACKEND/.venv/bin/python}"
LOCK="${LOCK:-/tmp/cca-adobe-sync.lock}"

# Single-flight: skip if a previous run is still going.
if ! ( set -o noclobber; printf '%s' "$$" > "$LOCK" ) 2>/dev/null; then
  echo "[adobe-sync] another run holds $LOCK — skipping."
  exit 0
fi
trap 'rm -f "$LOCK"' EXIT

cd "$BACKEND"
echo "[adobe-sync] $(date -u +%FT%TZ) starting"
# No --force: respects content_refresh_enabled. Add --dry-run for a no-write run.
"$PY" -m scripts.sync_adobe_updates
echo "[adobe-sync] $(date -u +%FT%TZ) done"
