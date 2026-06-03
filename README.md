# DEPT® · Anatomy of Code — Deploy Bundle

Three things to ship, each independent. Pick the ones you need, deploy in any order.

```
dept-anatomy-of-code/
├── content-system/    · static HTML field manual (course, checklist, runbook, FAQ collection)
├── prompt-library/    · B0 agent outputs — prompt sequences + worked samples (starting with AEM → React Native)
└── quiz-certification/ · FastAPI quiz module (Claude Certified Architect Foundations)
```

---

## Deploy to a VM (the quick path)

If you just want the whole thing running on one CentOS 8 / RHEL 8 VM behind Apache + HTTPS,
there's a one-command installer:

```bash
sudo ./deploy.sh
```

It serves the static content at `/anatomy/` and runs the FastAPI quiz app (under systemd,
proxied by Apache) at `/` — on `https://internal.in.deptagency.com`. It handles SELinux,
firewalld, the Python venv, and the systemd service for you.

**Hand this to whoever runs the deploy:** the step-by-step guide — prerequisites, run
instructions, verification, and troubleshooting — is in **[`DEPLOY.md`](DEPLOY.md)**.

The per-component options below (Netlify, S3, Docker, etc.) are alternatives for when you
*don't* want the single-VM layout.

---

## 1 · content-system/

Self-contained HTML. No build step, no server-side code, no JS framework. Drop on any static host.

```
content-system/
├── anatomy-of-code-course.html   · main field manual · ~4,100 lines · CODE–CODER deep-dives + Part II
├── code-coder-checklist.html     · discovery checklist · 216 questions across 9 nodes
├── architect-runbook.html        · greenfield + brownfield engagement playbooks
└── faqs/                         · architect FAQ collection (vertical & platform-specific)
    ├── index.html                · landing page · published + coming-soon roster
    └── aem-banking-faq.html      · AEM × Banking · 13 questions · published
```

### Cross-links inside the files

The files reference each other by relative filename (`href="code-coder-checklist.html"` etc.). Keep them in the same directory or the same web root.

### Deploy options

**Easiest — any static host:**
```
# Netlify drop · drag the content-system/ folder onto app.netlify.com/drop

# Or Vercel
vercel deploy content-system/

# Or Cloudflare Pages
wrangler pages deploy content-system/

# Or S3 + CloudFront (the agency classic)
aws s3 sync content-system/ s3://your-bucket/ --acl public-read
```

**On AEM as static assets:**
```
# Upload to /content/dam/dept-anatomy/ as DAM assets, or expose via /etc/clientlibs.
# All four files self-contain their CSS — no clientlib refactor needed.
```

**Behind authentication (intranet):**
```
# Easiest: nginx with basic auth in front of the static directory.
# Or wrap behind your existing SSO via the agency portal.
```

### Customising

- **Logo** — every file references `https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg`. Swap in your own URL if rebranding for a client engagement.
- **Theme persistence** — each file uses a unique localStorage key (`course-theme`, `runbook-theme`, etc.) so users' dark/light preference persists per page.
- **Annotation system** — `anatomy-of-code-course.html` has a Review Mode (the floating FAB). Annotations save to localStorage under `anatomy-annotations-v1` per browser.

---

## 2 · prompt-library/

Home for everything B0 produces: prompt sequences and the worked samples that demonstrate them. As B0 ships more sequences, each goes in its own subfolder here.

```
prompt-library/
└── sample-aem-to-react-native/
    ├── README.md            · architecture diagram + setup steps
    ├── aem-side/            · CF model JSON + persisted GraphQL queries
    ├── rn-app/              · Expo + TypeScript app, layered per Stalwart discipline
    └── prompts/             · the 5-step agent-coding sequence that built the app
```

### What this is for

Two audiences:

1. **Engineers** — running the app to see AEM-headless mobile work in production-grade structure.
2. **Architects** — reading the `prompts/` folder to see how a 80-line architecture prompt yields short, focused per-file prompts. This is the teaching angle.

### Deploy as runnable sample

Full setup steps in `prompt-library/sample-aem-to-react-native/README.md`. Short version:

```bash
cd prompt-library/sample-aem-to-react-native/rn-app
npm install

# Point at your AEM publish endpoint
export AEM_BASE_URL=https://publish-p123-e456.adobeaemcloud.com
export AEM_NAMESPACE=dept-sample

npm start
# Press i (iOS), a (Android), or w (web)
```

The matching AEM side needs:
- A CF model at `/conf/dept-sample/settings/dam/cfm/models/article` matching `aem-side/article-model.json`
- Three persisted queries installed via `PUT /graphql/persist.json/dept-sample/...` — full curl examples in the sample README

### Deploy as teaching material

The `prompts/` markdown files can also stand alone — share them with a team about to start an AEM-headless mobile build. Sequence:

1. `00-architecture-prompt.md` — the architectural contract (read first)
2. `01-model-prompt.md` — generate `model.ts` from the CF JSON
3. `02-api-prompt.md` — generate the persisted GraphQL client
4. `03-cache-prompt.md` — generate the SWR cache layer
5. `04-screens-prompts.md` — generate components + 3 screens

The point isn't to run them as-is — it's to see the structure that lets each prompt stay short.

---

## 3 · quiz-certification/

A FastAPI app that delivers the Claude Certified Architect — Foundations (CCA-F) quiz. Google OAuth restricted to `@deptagency.com`, 50-question bank (25 beginner + 25 advanced), 7-day cooldown on fail, PDF certificate via reportlab, admin review tool.

```
quiz-certification/
├── README.md            · full setup, deployment, ops guide
├── requirements.txt
├── .env.example         · all required environment variables
├── app/                 · FastAPI source · 9 modules
├── templates/           · Jinja2 templates · 6 pages
├── static/              · CSS
├── data/                · question bank JSON
├── quiz_results/        · JSON dumps of every attempt (runtime · empty in bundle)
├── outbox/              · dev-mode email outbox (runtime · empty in bundle)
└── certificates/        · generated PDFs (runtime · empty in bundle)
```

### Local run

```bash
cd quiz-certification
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in OAuth credentials + SMTP

# Dev mode (email login, dev outbox)
APP_ENV=dev uvicorn app.main:app --reload --port 8000

# Visit http://localhost:8000
```

### Production deploy

```bash
# Containerised (recommended)
docker build -t cca-quiz .
docker run -d \
  --name cca-quiz \
  -p 8000:8000 \
  -v $(pwd)/quiz_results:/app/quiz_results \
  -v $(pwd)/certificates:/app/certificates \
  --env-file .env \
  cca-quiz

# Or directly on a managed PaaS (App Service / Cloud Run / Heroku)
# uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
```

### Required env vars (see `.env.example`)

- `APP_ENV` — `prod` or `dev`
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` — restricted to `@deptagency.com`
- `SECRET_KEY` — session cookie signing
- `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` — email delivery
- `BASE_URL` — public URL of the quiz (used in OAuth callback + cert links)

### Admin review

```bash
python -m app.review                  # list all attempts
python -m app.review --user user@deptagency.com  # filter by user
python -m app.review --regenerate-cert attempt_id  # regenerate a lost cert
```

Full ops detail in `quiz-certification/README.md`.

---

## Suggested deploy order

If shipping the whole bundle to a single host (e.g. the agency intranet):

1. **content-system/** first — static, cheap, visible. Goes live in minutes; gives the team something to read while the rest deploys.
2. **quiz-certification/** second — needs OAuth credentials and SMTP set up. Plan a quiet 2-hour window for the first deploy.
3. **prompt-library/** third — usually consumed as a code resource (Git, internal package registry), not "deployed" as a service.

A typical deploy layout:

```
docs.deptagency.com/anatomy/        ← content-system/
quiz.deptagency.com/                ← quiz-certification/
github.com/dept/aem-rn-sample       ← sample (as a repo, not a service)
```

---

## Versioning

This bundle is the C0 sub-agent's full output as of the date it was generated:

- Course HTML — every CODER letter has a deepblock (C/Stalwart, D/Deployment+SaaS, O/Quality, E/External, R/Release), plus Caching & Observability as cross-cutting layers in D
- Runbook — greenfield + brownfield 90-day playbooks
- Checklist — 216 questions across CODE-CODER (unchanged from initial Q0 build)
- FAQ — 13 architect-level Q&As for AEM Banking (unchanged)
- Sample — full AEM CFM → RN/Expo worked example with agent-coding prompts
- Quiz — full FastAPI module with 50-question bank, OAuth, cert generation, admin tools

When changes ship, expect a new bundle with the same folder layout.

---

## Pairs with

If you adopt this bundle:

- **Use the course** as the framework reference for design reviews and onboarding
- **Use the checklist** as the discovery instrument at engagement kickoff
- **Use the FAQ** when an AEM-banking question lands in the team that has a settled answer
- **Use the runbook** as the architect onboarding manual for new engagements
- **Use the sample** as the reference pattern for any AEM-headless mobile work
- **Use the quiz** as the certification gate before someone is allowed to architect alone

All five reinforce one another. Dropping any one of them creates a gap the others can't quite fill.
