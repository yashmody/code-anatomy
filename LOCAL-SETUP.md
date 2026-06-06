# LOCAL-SETUP — testing the `v2` branch on your machine

The v2 re-architecture lives on `origin/v2` (branched off `main`; `main` is
untouched and still live). It is a modular-monolith FastAPI backend + a
buildless ES-module frontend + a Directus CMS, with the top-level folders
renamed (`quiz-certification/ → backend/`, `app/ → frontend/`, content
consolidated under `content/`). The full design is in
`docs/architecture/v2/`.

Pull it down and run the self-checks below. **Tier 1 needs no database and no
credentials — start there.**

---

## Prerequisites

- Python 3.12, Git
- **Node 22 LTS** for the docs site / Directus (Node 25 has a known local
  breakage — use 22)
- Postgres is *optional* — only needed to run the app against a real DB
  (Tier 2b)

---

## Get the code

```bash
git fetch origin
git checkout v2          # tracks origin/v2
```

---

## Tier 1 — deterministic gates (no DB, no credentials)

This is the core check. Every line below should come back green.

```bash
# 1. Backend env
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ..

# 2. Self-contained smoke (forces sqlite, no network) — expect: 15/15 checks passed
bash tests/baseline/smoke.sh

# 3. Backend unit tests — expect: 5 passed
cd backend && python -m pytest -q tests/ ; cd ..

# 4. Frontend import graph — expect: ALL RELATIVE IMPORTS RESOLVE (98/98)
python3 tests/baseline/check-frontend-imports.py
```

Expected results:

| Check | Command | Green looks like |
|---|---|---|
| Backend smoke | `bash tests/baseline/smoke.sh` | `15/15 checks passed`, exit 0 |
| Backend tests | `python -m pytest -q tests/` | `5 passed` |
| Frontend imports | `python3 tests/baseline/check-frontend-imports.py` | `ALL RELATIVE IMPORTS RESOLVE` (98/98) |

---

## Tier 2a — run it interactively on sqlite (quick look, no real DB)

```bash
cd backend
QUIZ_DEV_MODE=true DATABASE_URL="sqlite:///./dev.db" uvicorn app.main:app --reload --port 8000
# In another shell, serve the SPA + frozen course:
python3 -m http.server 8080
```

- Backend: <http://localhost:8000>
- SPA: <http://localhost:8080/frontend/index.html>

Sign in with any email — dev mode stubs Google OAuth, and "sent" mail lands in
`backend/outbox/`.

---

## Tier 2b — full run against Postgres (optional)

`./start_local.sh` connects to the **remote shared dev DB**. On the **first run**
(no `backend/.env` yet) it **prompts you for the database connection** — paste the
`DATABASE_URL` the maintainer emailed you, or type host / port / db / user /
password and it assembles + URL-encodes the connection string into `backend/.env`
(written `chmod 600`; the password is read hidden, never echoed). An existing
`backend/.env` is never touched; a non-interactive shell keeps the template
placeholder. So either:

- run `./start_local.sh` and paste the dev-DB credentials at the prompt, or
- spin up a throwaway local Postgres with `./start_local.sh --db` (then enter
  `localhost` and your local role at the prompt).

For build verification, Tier 1 + Tier 2a is sufficient.

---

## Docs site (optional)

Expect a clean build of 41 pages with zero broken links:

```bash
cd docs-site && npm ci && npm run build      # Node 22
```

---

## Known local caveats

- `/anatomy/*` resource links 404 in local dev — in production Apache aliases
  them to `content/frozen/`, but the stdlib static server cannot. Open
  `content/frozen/anatomy-of-code-course.html` directly if you need to eyeball
  the course.
- Do **not** commit `backend/.env` or `cms/.env` — they are gitignored; only
  the `.env.*.example` templates are tracked.

---

## Reporting back

Please report anything that is not green — with the command and its output — on
the v2 thread.
