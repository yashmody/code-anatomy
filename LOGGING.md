# Logging & diagnostics

How to find logs and, when something breaks, produce **one redacted file** you
can paste/attach for help.

## TL;DR — capture everything to share

**On the production VM** (run as root / with sudo so journald is readable):

```bash
cd /opt/dept-anatomy        # or wherever the bundle lives
sudo ./scripts/collect-logs.sh
# → writes /tmp/cca-diagnostics-<timestamp>.txt  (secrets redacted) — send that file
```

**Locally:**

```bash
./scripts/collect-logs.sh
```

The script gathers service status, journald, Apache logs, the app log, health
checks, the Alembic head, listening ports, and the last deploy log — then
**redacts** passwords, API keys, tokens, JWTs and Bearer headers before writing
the file. Review it, then share it.

## Where logs live

### Production (the VM)

| Component | Where | Read it |
|---|---|---|
| FastAPI app (`cca-quiz`) | systemd journald | `journalctl -u cca-quiz -n 500 --no-pager` · live: `-f` |
| Directus (`cms-directus`) | systemd journald | `journalctl -u cms-directus -n 300 --no-pager` |
| Apache | `/var/log/httpd/` | `tail -f /var/log/httpd/cca-quiz_error.log` (+ `_access.log`) |
| App file log (rotating) | `<APP_HOME>/backend/logs/backend-app.log` | `tail -f` — supplements journald |
| Deploy run | `/var/log/cca/deploy-<ts>.log` | written automatically by `deploy.sh` |
| Adobe content-refresh cron | `/var/log/cca/adobe-sync.log` | per `infra/cron/adobe-sync.sh` |

> In prod, **journald is the primary source** for the app and Directus (it
> captures their stdout/stderr, including tracebacks at startup). The app file
> log is a rotating copy of the app's own `app.*` log lines — handy, but check
> journald first for boot failures.

### Local dev (`./start_local.sh`)

| Component | Where |
|---|---|
| FastAPI backend | `logs/backend.log` |
| Static web server | `logs/frontend.log` |
| Directus (`--with-cms`) | `logs/directus.log` |
| App file log | `backend/logs/backend-app.log` |

`start_local.sh` now waits for `/healthz` before declaring success and prints the
last 30 backend log lines if startup fails (the backend takes ~10–20s because
its lifespan runs `create_all` + seeding against the remote dev DB).

## App logging internals

- Configured in `backend/app/core/observability.py` (`configure_logging`).
- Structured **logfmt** lines: `ts=… level=… logger=… request_id=… msg=…` — every
  in-request line carries the `X-Request-ID` so one request is traceable.
- Outputs to **stdout** (→ journald in prod) **and** a **rotating file**
  (`backend/logs/backend-app.log`, 5 MB × 5).
- Config knobs (`backend/.env`): `LOG_LEVEL` (default INFO), `LOG_TO_FILE`
  (default true), `LOG_DIR`, `LOG_FILE`.

## Common production checks

```bash
sudo systemctl status cca-quiz cms-directus      # are the services up?
journalctl -u cca-quiz -n 100 --no-pager         # app errors / tracebacks
curl -s http://127.0.0.1:8000/healthz            # app answering locally?
curl -s http://127.0.0.1:8000/readyz             # DB reachable?
sudo httpd -t                                    # Apache config valid?
cd /opt/dept-anatomy/backend && .venv/bin/alembic current   # schema at head?
```

If any of these is wrong, run `scripts/collect-logs.sh` and send the file.
