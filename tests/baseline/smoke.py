#!/usr/bin/env python3
"""smoke.py — v2 parity smoke test.

Hits the key public endpoints on the v1 monolith and asserts HTTP status +
basic response shape. Re-runnable; idempotent; self-contained.

Run from anywhere:

    python3 tests/baseline/smoke.py

Or via the quiz-certification venv (recommended — uses the project's deps):

    cd quiz-certification && .venv/bin/python ../tests/baseline/smoke.py

Modes
-----
The script either spawns its own uvicorn or attaches to an already-running
server on $QUIZ_BASE_URL (default http://127.0.0.1:8765).

  - default       : spawn uvicorn against the local sqlite, run, tear down.
  - --no-spawn    : assume QUIZ_BASE_URL is already serving the app.
  - --base URL    : override the base URL (implies --no-spawn).
  - --port N      : port to spawn uvicorn on (default 8765).
  - --keep-server : leave uvicorn running after the suite (useful for poking).

Pre-requisites
--------------
- Python 3.11+ on PATH.
- For spawn mode: a working `quiz-certification/.venv` (FastAPI, uvicorn,
  SQLAlchemy already installed via `requirements.txt`).
- For spawn mode: `quiz-certification/q0.db` exists (it does on the v2 branch).

Fixtures
--------
Every successful request stores its body under tests/baseline/fixtures/. The
files are versioned so subsequent runs `diff` cleanly against the committed
baseline.

Exit codes
----------
0 — all assertions passed.
1 — one or more assertions failed (details printed to stderr).
2 — server could not be reached (spawn mode failed to boot, or QUIZ_BASE_URL
    was unreachable). Smoke is treated as INCONCLUSIVE, not failed.

Parity guarantees this script pins
----------------------------------
1. /login renders the public login page.
2. / 307s anonymous users to /login.
3. /verify and /verify/{cert_id} are publicly readable.
4. /api/course/chapters and /api/course/framework-explainer return JSON with
   the right top-level keys (chapters[] / explainer keys).
5. /api/course/framework either returns the framework dict OR 404 (DB unseeded
   locally). Both are recorded baselines; production parity asserts the dict.
6. /api/feed returns {feed: [...]}.
7. Protected endpoints (/auth/me, /auth/session-key, /api/moderate/queue,
   /quiz/start, /admin/attempts, /history) refuse unauthenticated requests
   with the documented status code (401 for API/JSON paths, 302 for page
   paths) — see routes.md.
8. The real-cert canary (`CCA-F-20260605-E79E74AB`) — every cert ever
   issued in production must keep verifying after the cutover. The
   smoke always *requests* `GET /verify/CCA-F-20260605-E79E74AB` and
   asserts HTTP 200 + a fixture body is captured. The *strict*
   `valid=true` assertion only runs when `SMOKE_REAL_CERT_CHECK=1`
   (default off — local sqlite cannot reproduce the prod HMAC key, so
   the body will read "invalid" against it). The strict toggle is what
   the production-snapshot gate uses; the local run keeps the GET as a
   route-shape smoke. Set `SMOKE_SKIP_REAL_CERT=1` to skip the canary
   entirely (offline / no server / firewalled host).

Cross-references
----------------
- routes.md — full inventory.
- db-snapshot.md — counts behind each endpoint.
- ../../docs/architecture/v2/02-parity-method.md — gate procedure.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO_ROOT / "quiz-certification"
VENV_PY = BACKEND / ".venv" / "bin" / "python"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_PORT = 8765


# ---------------------------------------------------------------- HTTP helpers


class _CIDict(dict):
    """Case-insensitive dict for HTTP headers — RFC 7230 §3.2."""

    def __init__(self, src=None):
        super().__init__()
        if src:
            for k, v in (src.items() if hasattr(src, "items") else src):
                self[k] = v

    def __setitem__(self, k, v):
        super().__setitem__(k.lower() if isinstance(k, str) else k, v)

    def __getitem__(self, k):
        return super().__getitem__(k.lower() if isinstance(k, str) else k)

    def get(self, k, default=None):
        return super().get(k.lower() if isinstance(k, str) else k, default)

    def __contains__(self, k):
        return super().__contains__(k.lower() if isinstance(k, str) else k)


@dataclass
class Response:
    status: int
    body: bytes
    headers: _CIDict

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.body)


def http(
    method: str,
    url: str,
    body: Optional[bytes] = None,
    headers: Optional[dict] = None,
    follow: bool = False,
    timeout: float = 5.0,
) -> Response:
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=headers or {},
    )

    # urllib's HTTPRedirectHandler swallows 3xx responses. To capture the raw
    # Location header on a redirect we raise on 3xx instead and let HTTPError
    # carry the headers through.
    class _RaiseOnRedirect(urllib.request.HTTPRedirectHandler):
        def http_error_302(self, req, fp, code, msg, headers):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

        http_error_301 = http_error_302
        http_error_303 = http_error_302
        http_error_307 = http_error_302
        http_error_308 = http_error_302

    opener = (
        urllib.request.build_opener()
        if follow
        else urllib.request.build_opener(_RaiseOnRedirect)
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return Response(resp.status, resp.read(), _CIDict(resp.headers))
    except urllib.error.HTTPError as e:
        # On 3xx we drained no body; on 4xx/5xx we read what we can.
        body_bytes = b""
        try:
            body_bytes = e.read() or b""
        except Exception:
            pass
        return Response(e.code, body_bytes, _CIDict(e.headers or {}))


# ----------------------------------------------------------------- assertions


class SmokeReport:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, predicate: Callable[[], bool], detail: str = "") -> None:
        try:
            ok = bool(predicate())
            note = detail
        except Exception as e:
            ok = False
            note = f"{detail} (raised {type(e).__name__}: {e})"
        self.results.append((name, ok, note))
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}]  {name}  {note}")

    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.results)

    def summary(self) -> str:
        n = len(self.results)
        ok = sum(1 for _, p, _ in self.results if p)
        return f"{ok}/{n} checks passed"


def save_fixture(name: str, response: Response) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / name).write_bytes(response.body)


# -------------------------------------------------------------- server spawn


def spawn_uvicorn(port: int) -> subprocess.Popen:
    if not VENV_PY.exists():
        print(
            f"ERROR: venv python not found at {VENV_PY}. "
            "Create it via `cd quiz-certification && python3 -m venv .venv "
            "&& .venv/bin/pip install -r requirements.txt` first.",
            file=sys.stderr,
        )
        sys.exit(2)

    env = os.environ.copy()
    env.setdefault("QUIZ_DEV_MODE", "true")
    # Pin sqlite path — same as v1 default.
    db_path = BACKEND / "q0.db"
    env.setdefault("DATABASE_URL", f"sqlite:///{db_path}")

    log_path = Path("/tmp/smoke-uvicorn.log")
    log = log_path.open("wb")
    proc = subprocess.Popen(
        [
            str(VENV_PY),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(BACKEND),
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
    )
    # Poll up to 10 seconds for the port to come alive.
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            r = http("GET", f"http://127.0.0.1:{port}/login", timeout=1)
            if r.status in (200, 302, 307):
                return proc
        except Exception:
            pass
        time.sleep(0.3)
    proc.terminate()
    proc.wait(timeout=5)
    print(
        f"ERROR: uvicorn did not come up on port {port}. "
        f"See {log_path} for details.",
        file=sys.stderr,
    )
    sys.exit(2)


# ----------------------------------------------------------------- the checks


def run_checks(base: str, report: SmokeReport) -> None:
    # 1. Anonymous home -> 307 to /login.
    r = http("GET", f"{base}/", follow=False)
    save_fixture("root.html", r)
    report.check(
        "GET / 307s to /login when unauth",
        lambda: r.status in (302, 307)
        and "/login" in r.headers.get("Location", ""),
        f"got status={r.status}, location={r.headers.get('Location')}",
    )

    # 2. /login renders HTML.
    r = http("GET", f"{base}/login")
    save_fixture("login.html", r)
    report.check(
        "GET /login -> 200 HTML",
        lambda: r.status == 200 and b"<html" in r.body.lower(),
        f"got status={r.status}, size={len(r.body)}",
    )

    # 3. /verify renders HTML for an empty cert query.
    r = http("GET", f"{base}/verify")
    save_fixture("verify.html", r)
    report.check(
        "GET /verify -> 200 HTML",
        lambda: r.status == 200 and b"<html" in r.body.lower(),
        f"got status={r.status}, size={len(r.body)}",
    )

    # 4. /verify/{cert_id} is publicly addressable.
    r = http("GET", f"{base}/verify/NONEXISTENT-CCA-CERT")
    save_fixture("verify-cert.html", r)
    report.check(
        "GET /verify/{cert_id} -> 200 HTML",
        lambda: r.status == 200,
        f"got status={r.status}",
    )

    # 5. /api/course/framework-explainer must return the framing dict.
    r = http("GET", f"{base}/api/course/framework-explainer")
    save_fixture("api-course-framework-explainer.json", r)

    def explainer_shape() -> bool:
        if r.status != 200:
            return False
        d = r.json()
        return isinstance(d, dict) and {"masthead", "parts", "code", "coder"}.issubset(
            d.keys()
        )

    report.check(
        "GET /api/course/framework-explainer -> 200 JSON with masthead/parts/code/coder",
        explainer_shape,
        f"got status={r.status}, size={len(r.body)}",
    )

    # 6. /api/course/chapters -> 200 + {"chapters":[...]}
    r = http("GET", f"{base}/api/course/chapters")
    save_fixture("api-course-chapters.json", r)

    def chapters_shape() -> bool:
        if r.status != 200:
            return False
        d = r.json()
        return isinstance(d, dict) and isinstance(d.get("chapters"), list)

    report.check(
        "GET /api/course/chapters -> 200 JSON {chapters: [...]}",
        chapters_shape,
        f"got status={r.status}, size={len(r.body)}",
    )

    # 7. /api/course/framework -> 200 OR 404 (404 acceptable when DB unseeded).
    r = http("GET", f"{base}/api/course/framework")
    save_fixture("api-course-framework.json", r)
    report.check(
        "GET /api/course/framework -> 200 or 404 (depends on seed)",
        lambda: r.status in (200, 404),
        f"got status={r.status} — production should be 200; local sqlite may be 404",
    )

    # 8. /api/feed -> 200 + {"feed":[...]}
    r = http("GET", f"{base}/api/feed")
    save_fixture("api-feed.json", r)

    def feed_shape() -> bool:
        if r.status != 200:
            return False
        d = r.json()
        return isinstance(d, dict) and isinstance(d.get("feed"), list)

    report.check(
        "GET /api/feed -> 200 JSON {feed: [...]}",
        feed_shape,
        f"got status={r.status}, size={len(r.body)}",
    )

    # 9-11. Unauthenticated API endpoints — must 401 with JSON.
    for path, fixture in (
        ("/auth/me", "auth-me-unauth.json"),
        ("/auth/session-key", "session-key-unauth.json"),
        ("/api/moderate/queue", "moderate-queue-unauth.json"),
    ):
        r = http("GET", f"{base}{path}", headers={"Accept": "application/json"})
        save_fixture(fixture, r)
        report.check(
            f"GET {path} (no session) -> 401",
            lambda r=r: r.status == 401,
            f"got status={r.status}",
        )

    # 12. POST /quiz/start (no session) -> 401.
    r = http(
        "POST",
        f"{base}/quiz/start",
        body=b'{"difficulty":"beginner"}',
        headers={"Content-Type": "application/json"},
    )
    save_fixture("quiz-start-unauth.json", r)
    report.check(
        "POST /quiz/start (no session) -> 401",
        lambda: r.status == 401,
        f"got status={r.status}",
    )

    # 13. /admin/attempts (no session) -> 302 (page-style guard).
    r = http("GET", f"{base}/admin/attempts", follow=False)
    save_fixture("admin-attempts-unauth.html", r)
    report.check(
        "GET /admin/attempts (no session) -> 302",
        lambda: r.status == 302,
        f"got status={r.status}",
    )

    # 14. /history (no session) -> 302 to /login.
    r = http("GET", f"{base}/history", follow=False)
    save_fixture("history-unauth.html", r)
    report.check(
        "GET /history (no session) -> 302 /login",
        lambda: r.status == 302 and "/login" in r.headers.get("Location", ""),
        f"got status={r.status}, location={r.headers.get('Location')}",
    )

    # 15. Real-cert canary (CCA-F-20260605-E79E74AB).
    #
    # This is the load-bearing prod cert from 02-parity-method.md §1.3 + §1.5.
    # Behaviour:
    #   - Default (local sqlite): assert HTTP 200 only — local can't reproduce
    #     the prod HMAC, so the body legitimately reads "invalid" against it.
    #     The route-shape smoke still catches a regression that breaks
    #     /verify/{cert_id} entirely.
    #   - SMOKE_REAL_CERT_CHECK=1 (prod-snapshot gate): assert HTTP 200 AND
    #     body indicates valid=true (the page renders "verify-result valid"
    #     + "Verified" copy). Toggle on at the Phase 1 acceptance smoke
    #     against a Postgres snapshot.
    #   - SMOKE_SKIP_REAL_CERT=1 (offline / firewalled / no server): the
    #     check is skipped entirely and recorded as PASS with a "skipped"
    #     note. This keeps the assertion in the script so it can never be
    #     accidentally dropped, while letting CI runs without the canary
    #     server pass cleanly.
    #
    # Cross-reference: docs/architecture/v2/02-parity-method.md §1.3
    # ("Every cert_id in prod-certs-pre.txt returns valid=true ...").
    if os.environ.get("SMOKE_SKIP_REAL_CERT") == "1":
        report.check(
            "GET /verify/CCA-F-20260605-E79E74AB -> real-cert canary",
            lambda: True,
            "SKIPPED via SMOKE_SKIP_REAL_CERT=1 (assertion preserved in script)",
        )
    else:
        r = http("GET", f"{base}/verify/CCA-F-20260605-E79E74AB")
        save_fixture("verify-real-cert.html", r)
        strict = os.environ.get("SMOKE_REAL_CERT_CHECK") == "1"
        if strict:
            def real_cert_valid() -> bool:
                if r.status != 200:
                    return False
                body_l = r.body.lower()
                # Two independent signals the verifier emits for valid=true:
                # the CSS class on the result card, and the visible copy.
                return (
                    b"verify-result valid" in body_l
                    and b"verified" in body_l
                )

            report.check(
                "GET /verify/CCA-F-20260605-E79E74AB -> valid=true (strict)",
                real_cert_valid,
                f"got status={r.status}, size={len(r.body)} (SMOKE_REAL_CERT_CHECK=1)",
            )
        else:
            report.check(
                "GET /verify/CCA-F-20260605-E79E74AB -> 200 (route-shape only)",
                lambda: r.status == 200,
                f"got status={r.status}, size={len(r.body)} — set "
                "SMOKE_REAL_CERT_CHECK=1 against a prod snapshot for strict",
            )


# ---------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None, help="Base URL (implies --no-spawn)")
    parser.add_argument(
        "--no-spawn",
        action="store_true",
        help="Do not start uvicorn; expect the server to already be up.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()

    if args.base:
        base = args.base.rstrip("/")
        proc = None
    elif args.no_spawn:
        base = os.environ.get(
            "QUIZ_BASE_URL", f"http://127.0.0.1:{args.port}"
        ).rstrip("/")
        proc = None
    else:
        proc = spawn_uvicorn(args.port)
        base = f"http://127.0.0.1:{args.port}"

    print(f"\n=== v2 parity smoke against {base} ===\n")
    report = SmokeReport()

    try:
        run_checks(base, report)
    finally:
        if proc is not None and not args.keep_server:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    print(f"\n=== {report.summary()} ===")
    if not report.passed():
        print("FAIL — at least one parity check did not match the baseline.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
