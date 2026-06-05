#!/usr/bin/env bash
#
# ============================================================================
# DEPT(R) Anatomy of Code - TLS certificate provisioning (Let's Encrypt)
# ----------------------------------------------------------------------------
# Owner doc: 07-security-baseline.md section 9.5 (TLS automation), F-NET-02.
#
# WHAT: idempotently obtains (or confirms) a Let's Encrypt certificate for the
# site DOMAIN using certbot's Apache plug-in, and ensures the renewal timer is
# enabled. Mirrors the inline snippet deploy.sh would otherwise run, factored
# out so an operator can re-run cert provisioning by hand without re-running
# the whole deploy.
#
# IDEMPOTENT: does NOTHING (beyond confirming) if a valid, not-near-expiry
# certificate already exists for DOMAIN. certbot itself is idempotent on
# re-run, but we short-circuit before even calling it so the script is a
# no-op the operator can run any number of times.
#
# FALLBACK: if certbot is not installed, prints the manual instructions and
# exits 0 - it never breaks a deploy on a box without certbot (matches the
# existing manual flow in deploy.sh:862,1033).
#
# RENEWAL: certbot installs a systemd timer (certbot.timer) or a cron entry on
# install. We make sure the timer is enabled and started. The renewal runs
# `certbot renew` twice daily; it is a no-op until a cert is within 30 days of
# expiry. Verify with:  systemctl list-timers certbot.timer
# ============================================================================

set -euo pipefail

# -- Config (override via env) ----------------------------------------------
# Must match deploy.sh DOMAIN (deploy.sh:47). The cert is issued for this name.
DOMAIN="${DOMAIN:-internal.in.deptagency.com}"

# Registration / recovery contact for Let's Encrypt expiry notices.
ADMIN_EMAIL="${ADMIN_EMAIL:-${CERT_ADMIN_EMAIL:-platform@deptagency.com}}"

# Where Apache/the vhost expects the live cert. certbot --apache wires the
# vhost automatically; these are used only for the "is there already a valid
# cert?" short-circuit and align with certbot's standard live path.
CERT_LIVE_DIR="${CERT_LIVE_DIR:-/etc/letsencrypt/live/${DOMAIN}}"
CERT_FILE="${CERT_FILE:-${CERT_LIVE_DIR}/fullchain.pem}"

# Renewal margin: skip issuance if the existing cert is valid for more than
# this many seconds (30 days). Matches certbot's own renewal window.
RENEW_MARGIN_SECONDS="${RENEW_MARGIN_SECONDS:-2592000}"

log() { printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1"; }

# -- Fallback: no certbot ---------------------------------------------------
if ! command -v certbot >/dev/null 2>&1; then
    log "certbot not installed - skipping automated TLS provisioning."
    log "Manual path:  sudo certbot --apache -d ${DOMAIN} --email ${ADMIN_EMAIL} --agree-tos --redirect"
    exit 0
fi

# -- Idempotency: valid cert already present? -------------------------------
# If a cert exists and is valid well beyond the renewal margin, do nothing.
if [[ -f "$CERT_FILE" ]]; then
    # openssl -checkend N exits 0 if the cert will NOT expire within N seconds.
    if openssl x509 -checkend "$RENEW_MARGIN_SECONDS" -noout -in "$CERT_FILE" >/dev/null 2>&1; then
        log "Valid certificate already present for ${DOMAIN} (>30 days remaining). Nothing to do."
        # Still make sure the renewal timer is on (cheap, idempotent).
        if command -v systemctl >/dev/null 2>&1; then
            systemctl enable --now certbot.timer >/dev/null 2>&1 \
                && log "Renewal timer certbot.timer enabled." \
                || log "Note: could not enable certbot.timer (check renewal cron/timer manually)."
        fi
        exit 0
    fi
    log "Existing certificate for ${DOMAIN} is within the renewal window - reissuing."
fi

# -- Obtain / renew ---------------------------------------------------------
# --apache: certbot edits the Apache vhost and reloads it.
# --non-interactive + --agree-tos + --email: unattended issuance.
# --redirect: install the HTTP->HTTPS redirect (matches 07 section 9.5).
# --keep-until-expiring: do not needlessly reissue if certbot judges it fresh.
log "Requesting certificate for ${DOMAIN} via certbot --apache ..."
certbot --apache \
    -d "$DOMAIN" \
    --non-interactive \
    --agree-tos \
    --email "$ADMIN_EMAIL" \
    --redirect \
    --keep-until-expiring

log "Certificate provisioning complete for ${DOMAIN}."

# -- Renewal timer ----------------------------------------------------------
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now certbot.timer >/dev/null 2>&1 \
        && log "Renewal timer certbot.timer enabled (renews twice daily, no-op until <30 days to expiry)." \
        || log "Note: could not enable certbot.timer - verify renewal with 'systemctl list-timers certbot.timer' or the packaged cron job."
fi
