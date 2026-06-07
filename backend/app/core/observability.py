"""Observability seam — request correlation + structured logging.

Phase 3 (light, per `docs/architecture/v2/07-security-baseline.md` and general
operational hygiene). Two pieces:

1. **Request-ID middleware.** An ASGI middleware that reads an inbound
   `X-Request-ID` (so an upstream Apache or a load balancer can set it) or mints
   a fresh `uuid4`. The id is stashed in a `contextvar` for the duration of the
   request and echoed back on the response as `X-Request-ID`. Every log line
   emitted inside the request carries it (see `RequestIdFilter`), so a single
   request can be traced across handlers and modules.

2. **Structured logging.** `configure_logging(level)` installs a key=value
   line formatter on the root logger — `ts=… level=… logger=… request_id=… msg=…`
   — which greps cleanly and parses with `logfmt`-style tooling. It is
   idempotent: calling it twice does not stack handlers.

`install_observability(app)` wires the middleware onto a FastAPI app. The
middleware lives here (not in `security.py`) so the security seam stays focused
on headers/CORS/session; `security.install_middleware` calls into here so the
wiring order is a single decision (see `core/security.py`).
"""
from __future__ import annotations

import contextvars
import logging
import sys
import uuid
from typing import Optional

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# ─────────────────────────────────────────────────────────────────────────────
# Request-id context
# ─────────────────────────────────────────────────────────────────────────────

# Holds the current request's correlation id. Defaults to "-" outside a request
# (e.g. startup logs) so log lines always have a value.
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_REQUEST_ID_HEADER = b"x-request-id"


def get_request_id() -> str:
    """Return the current request's id, or '-' outside a request."""
    return _request_id.get()


def _coerce_request_id(raw: Optional[str]) -> str:
    """Validate an inbound id; mint a uuid4 if absent or implausible.

    We accept a client-supplied id but bound its length and charset so a
    hostile upstream can't inject newlines into our log lines (log-forging) or
    bloat memory. Anything outside a conservative allowlist is replaced.
    """
    if not raw:
        return uuid.uuid4().hex
    raw = raw.strip()
    if not raw or len(raw) > 128:
        return uuid.uuid4().hex
    # Allow the characters that appear in uuids, trace ids, and request ids.
    allowed = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    )
    if not set(raw) <= allowed:
        return uuid.uuid4().hex
    return raw


class RequestIdMiddleware:
    """ASGI middleware: bind a request id and echo it on the response.

    Order-independent — it only reads/writes the `X-Request-ID` header and the
    contextvar, so it composes with the security/session/CORS stack regardless
    of where it sits. Skips non-HTTP scopes (websocket/lifespan) cleanly.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Read inbound X-Request-ID (case-insensitive in ASGI: header names are
        # already lowercased bytes).
        inbound: Optional[str] = None
        for name, value in scope.get("headers", []):
            if name == _REQUEST_ID_HEADER:
                try:
                    inbound = value.decode("latin-1")
                except Exception:  # noqa: BLE001
                    inbound = None
                break

        request_id = _coerce_request_id(inbound)
        token = _request_id.set(request_id)
        rid_bytes = request_id.encode("latin-1")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Replace any upstream-set value so the response always reflects
                # the id we actually used (and logged).
                headers = [h for h in headers if h[0].lower() != _REQUEST_ID_HEADER]
                headers.append((_REQUEST_ID_HEADER, rid_bytes))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _request_id.reset(token)


# ─────────────────────────────────────────────────────────────────────────────
# Structured logging
# ─────────────────────────────────────────────────────────────────────────────


class RequestIdFilter(logging.Filter):
    """Inject the current request id onto every record as `record.request_id`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def _escape(value: str) -> str:
    """Make a value safe for a single logfmt line: no newlines, quote if spaced."""
    value = value.replace("\n", " ").replace("\r", " ")
    if " " in value or '"' in value:
        value = '"' + value.replace('"', "'") + '"'
    return value


class KeyValueFormatter(logging.Formatter):
    """Emit one logfmt-style line: ts=… level=… logger=… request_id=… msg=…

    Concise, greppable, and parseable by logfmt tooling. Exception info is
    appended after the line so tracebacks still surface.
    """

    default_time_format = "%Y-%m-%dT%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.default_time_format)
        request_id = getattr(record, "request_id", "-")
        msg = record.getMessage()
        line = (
            f"ts={ts} "
            f"level={record.levelname} "
            f"logger={_escape(record.name)} "
            f"request_id={_escape(str(request_id))} "
            f"msg={_escape(msg)}"
        )
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# Sentinel so configure_logging is idempotent — we tag our handler and skip if
# it's already attached.
_HANDLER_TAG = "_aoc_observability_handler"


def configure_logging(level: Optional[str] = None) -> None:
    """Install the structured formatter on the root logger. Idempotent.

    `level` is a logging level name ("INFO", "DEBUG", …). If omitted it reads
    `settings.log_level`. Calling this more than once replaces our handler's
    level/formatter rather than stacking handlers — safe to call from lifespan
    and from tests.
    """
    if level is None:
        try:
            from app.core.config import settings
            level = settings.log_level
        except Exception:  # noqa: BLE001 — never let logging setup break boot
            level = "INFO"

    level_value = logging.getLevelName(str(level).upper())
    if not isinstance(level_value, int):
        level_value = logging.INFO

    root = logging.getLogger()
    root.setLevel(level_value)

    rid_filter = RequestIdFilter()
    formatter = KeyValueFormatter()

    # Reuse our handler if it's already attached (idempotency).
    for handler in root.handlers:
        if getattr(handler, _HANDLER_TAG, False):
            handler.setLevel(level_value)
            handler.setFormatter(formatter)
            # Ensure the filter is present exactly once.
            if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
                handler.addFilter(rid_filter)
            return

    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _HANDLER_TAG, True)
    handler.setLevel(level_value)
    handler.setFormatter(formatter)
    handler.addFilter(rid_filter)
    root.addHandler(handler)

    # Rotating file handler — so there is ALWAYS a log file to read/share, even
    # when the launcher sends stdout to /dev/null. Best-effort: a filesystem
    # problem must never break boot.
    _attach_file_handler(root, level_value, formatter, rid_filter)


_FILE_HANDLER_TAG = "_cca_file_handler"


def _attach_file_handler(root, level_value, formatter, rid_filter) -> None:
    """Attach a RotatingFileHandler at settings.log_dir/log_file. Idempotent."""
    try:
        from app.core.config import settings
        if not settings.log_to_file:
            return
        for h in root.handlers:  # idempotency across lifespan/test re-calls
            if getattr(h, _FILE_HANDLER_TAG, False):
                h.setLevel(level_value)
                h.setFormatter(formatter)
                return
        import os
        from logging.handlers import RotatingFileHandler
        log_dir = str(settings.log_dir)
        os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(log_dir, settings.log_file),
            maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        setattr(fh, _FILE_HANDLER_TAG, True)
        fh.setLevel(level_value)
        fh.setFormatter(formatter)
        fh.addFilter(rid_filter)
        root.addHandler(fh)
    except Exception as exc:  # noqa: BLE001 — logging setup must never break boot
        logging.getLogger("app.observability").warning("file logging disabled: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Wiring
# ─────────────────────────────────────────────────────────────────────────────


def install_observability(app) -> None:
    """Attach the request-id middleware to a FastAPI/Starlette app.

    Call this once at composition time. `configure_logging()` is separate so it
    can run at the very start of lifespan, before any other log line.
    """
    app.add_middleware(RequestIdMiddleware)
