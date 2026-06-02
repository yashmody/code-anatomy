# Q0 · The Anatomy of Code · Quiz Module

A self-contained, server-validated certification quiz app for **The Anatomy of
Code · CCA-F**. Generates dynamic quizzes from a content-driven question bank,
authenticates via Google SSO (domain-restricted), emails a branded PDF
certificate on pass, and enforces a one-week cool-down on fail.

Built with FastAPI + Jinja2 + reportlab. Pure Python, no external services
required for local development.

---

## What it does

- **Dynamic quiz generation** — questions sampled randomly per attempt, options
  shuffled per question. No two quizzes are alike. As the bank grows
  (`data/question_bank.json`), every new topic enters the pool automatically.
- **Two difficulty levels** — Beginner (framework basics) and Advanced
  (architect's call). Pool sizes shown on the home page.
- **Google SSO** — domain-restricted via the `hd=` hint plus a server-side
  check on the returned profile. Dev mode allows email-form login for local
  testing.
- **Server-side validation** — the client receives questions and options only;
  correct answers never leave the server. Submissions are graded against an
  in-memory store keyed by `quiz_id`.
- **Certificate on pass** — landscape A4 PDF, DEPT®-branded (orange #FF4900
  accents, serif name in Times-Bold, mono cert ID), emailed as an attachment.
- **JSON storage** — every attempt saved as
  `quiz_results/{date}_{safe_email}_{quiz_id_prefix}.json` with the full
  question set, answer key, user's answers, and grading.
- **Cool-down** — 7 days after a fail, enforced on `/quiz/start` with a 429.
- **CLI review** — `python -m app.review` to load and audit any saved JSON.

---

## Quick start (dev mode)

```bash
# 1. Set up a virtualenv
python -m venv .venv
source .venv/bin/activate              # on macOS/Linux
# .venv\Scripts\activate                # on Windows

# 2. Install
pip install -r requirements.txt

# 3. Configure (defaults are fine for dev mode)
cp .env.example .env

# 4. Run
uvicorn app.main:app --reload
```

Open <http://localhost:8000>. Sign in with any `@deptagency.com` email (the dev
form accepts anything matching the allowed domain). The "email" of the
certificate is written to `./outbox/` as a `.eml` file you can open in any mail
client to verify the PDF attachment looks right.

---

## Production setup

Set `QUIZ_DEV_MODE=false` and provide:

### Google OAuth

1. Go to <https://console.cloud.google.com/apis/credentials>
2. Create an OAuth 2.0 Client ID, type "Web application"
3. Add your domain to the authorized redirect URIs, e.g.
   `https://quiz.deptagency.com/auth/google/callback`
4. Copy the client ID and secret into `.env`
5. Set `GOOGLE_REDIRECT_URI` to match exactly

The `hd` parameter is sent to Google to bias the account chooser toward your
hosted domain, but the **enforcement** is on the server side after the profile
returns — the OAuth flow is rejected if the email doesn't end in
`ALLOWED_DOMAIN`.

### SMTP

Standard SMTP creds. TLS supported. Examples for common providers:

```
# Gmail / Workspace (app password required)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=youraccount@deptagency.com
SMTP_PASS=your-app-password

# SendGrid
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASS=SG.xxxxxxxxxxxxxxx

# SES
SMTP_HOST=email-smtp.eu-west-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=AKIA...
SMTP_PASS=...
```

### Session secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the output as `SECRET_KEY` in `.env`.

### Run behind a reverse proxy

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

In-memory active quizzes don't survive a restart and don't share across
workers. For multi-worker deployment, swap `_active_quizzes` in `app/main.py`
for Redis (one-line change in two places).

---

## Adding questions

Edit `data/question_bank.json`. Append entries to the `questions` array:

```json
{
  "id": "a26",
  "topic": "your-topic-slug",
  "section": "course-section-id",
  "difficulty": "advanced",
  "type": "mcq",
  "question": "Your question text?",
  "options": ["A", "B", "C", "D"],
  "correct": 2,
  "explanation": "Why C is right (shown in the review)."
}
```

Rules:
- `id` must be unique. Convention: `b##` for beginner, `a##` for advanced.
- `difficulty` is either `beginner` or `advanced`.
- `correct` is the **zero-based** index into `options` of the correct answer.
- `topic` is used for grouping on the home page and tagging in the review.
- `section` is a free-form pointer back to the course section (for traceability).
- `explanation` is shown in the post-quiz review — keep it tight, one or two
  sentences with the *why*.

The pool must have at least `QUESTIONS_PER_QUIZ` questions per difficulty
(default 10). The app boots with 25 beginner + 25 advanced.

---

## Review CLI

```bash
# List all attempts (newest first)
python -m app.review

# Filter by user
python -m app.review --user yash@deptagency.com

# Show stats across all attempts
python -m app.review --stats

# Show full question-by-question detail for one file
python -m app.review quiz_results/2026-06-01_yash_at_deptagency_com_a1b2c3d4.json

# Detailed view of all
python -m app.review --detailed
```

The CLI uses the same `storage` module the web app uses, so the source of
truth is always the JSON files in `quiz_results/`.

---

## File layout

```
quiz-q0/
├── README.md                       This file
├── requirements.txt                Python deps
├── .env.example                    Config template
├── app/
│   ├── __init__.py
│   ├── config.py                   Env-driven config
│   ├── main.py                     FastAPI routes
│   ├── auth.py                     Google OAuth + dev login
│   ├── quiz_generator.py           Random sampling, option shuffle, grading
│   ├── storage.py                  JSON dump + cool-down lookup
│   ├── certificate.py              reportlab PDF cert
│   ├── email_service.py            SMTP / dev outbox
│   └── review.py                   CLI review tool
├── data/
│   └── question_bank.json          50-question seed pool
├── templates/                      Jinja2 templates, DEPT®-branded
│   ├── base.html
│   ├── login.html
│   ├── home.html
│   ├── quiz.html
│   ├── history.html
│   └── admin.html
├── static/
│   └── style.css                   DEPT® brand system
├── quiz_results/                   Auto-created at runtime — JSON dumps
├── certificates/                   Auto-created at runtime — PDFs
└── outbox/                         Auto-created in dev — .eml files
```

---

## Anti-cheat model

The threat is a determined client trying to score-inflate. The defences:

1. **Correct answers never leave the server.** The `/quiz/start` response
   contains only question text and shuffled options. The mapping
   `question_id → correct_index` is held in server memory keyed by `quiz_id`.
2. **Per-quiz option shuffle.** Even if two clients receive the same set of
   questions, the correct index differs.
3. **Submission graded server-side.** The client posts `{question_id: chosen_index}`.
   The server compares to its stored mapping and returns a score. The client
   cannot submit a score directly.
4. **Quiz state expires on submit.** Once submitted, the active record is
   deleted; a `quiz_id` cannot be replayed.
5. **Ownership check on submit.** The session's email must match the quiz's
   stored owner.
6. **Time-bounded.** The 20-minute timer is enforced client-side (auto-submit)
   and corroborated by the `started_at` timestamp recorded in the storage
   record — easy to spot anomalies in audit.
7. **Cool-down on fail.** Brute-force impossible: one shot every 7 days.

What's *not* yet defended:
- Two browsers signed in as the same user could each start a quiz in parallel.
  Acceptable trade-off; can be tightened with a per-user "one active quiz"
  check on `/quiz/start`.
- An attacker who can read server memory has the answer key. Outside the
  threat model for this app.

---

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET    | /                       | Home (level selection) |
| GET    | /login                  | Sign-in page |
| POST   | /login/dev              | Dev-mode email login (disabled in prod) |
| GET    | /auth/google            | Start Google OAuth |
| GET    | /auth/google/callback   | OAuth callback |
| GET    | /logout                 | Clear session |
| POST   | /quiz/start             | Begin a quiz (returns questions) |
| POST   | /quiz/submit            | Submit (graded server-side) |
| GET    | /quiz/take              | Quiz UI |
| GET    | /certificate/{cert_id}  | Download a PDF (ownership-checked) |
| GET    | /history                | Past attempts for the current user |
| GET    | /admin/attempts         | All attempts (dev only) |

---

## Operational notes

- `quiz_results/` is the source of truth. Back it up; rotate it offsite. Each
  file is small (≈ 8 KB) so a year's worth at scale is a few hundred MB.
- Certificates can be regenerated from a result JSON at any time — the
  `/certificate/{cert_id}` endpoint will re-run the PDF generator if the file
  isn't on disk. This means certificates don't need to be backed up
  separately.
- The 7-day cool-down is computed from `submitted_at` of the most recent
  attempt. Time travel works against you: if you change the system clock, the
  cool-down behaves accordingly. In production behind NTP, this is fine.
- The session cookie is signed (not encrypted) by itsdangerous. Don't put
  secrets in the session.

---

## Roadmap (not in v1)

- LLM-assisted question generation directly from course HTML
- Per-section quizzes (vs. mixed bank sampling)
- Time-of-day adaptive difficulty
- Verification page (`/verify/{cert_id}`) for LinkedIn URL clicks
- Multi-tenant support (per-academy isolation)
- Redis-backed active-quiz store for multi-worker deployment
