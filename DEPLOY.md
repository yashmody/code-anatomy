# Deployment Guide — DEPT® Anatomy of Code

This guide walks you through deploying the bundle onto the CentOS 8 VM using `deploy.sh`.
No prior knowledge of the app is needed — just follow the steps in order.

**Time required:** ~20 minutes for a first deploy (including database setup).

---

## 1. What you're deploying

The bundle has five parts. The script deploys four of them:

| Part | What it is | How it's served |
|------|-----------|-----------------|
| `quiz-certification/` | A FastAPI web app (the certification quiz + API backend) | Runs as a background service; Apache proxies to it |
| `app/` | Static SPA (course reader, feed, manual) | Served by FastAPI at `/app` |
| `content-system/` | 4 static HTML files (course, checklist, FAQ, runbook) | Apache serves them directly |
| `content-architecture/` | Course chapters, framework hierarchy, feed JSON | Ingested into PostgreSQL by the migration script |
| `prompt-library/` | B0 prompt sequences + worked samples | **Not deployed** (consumed as a code resource) |

After deploy, the VM answers on one domain:

```
https://internal.in.deptagency.com/              → the quiz app (login, quiz, history)
https://internal.in.deptagency.com/app/           → the SPA (manual reader, feed, auth)
https://internal.in.deptagency.com/anatomy/...    → the static content
```

Under the hood:

```
  Browser ──HTTPS──▶ Apache (httpd) ──┬──▶ /anatomy/  → static files on disk
  (port 443)                          └──▶ /          → uvicorn on 127.0.0.1:8000
                                              │
                                              ├── /app/    → static SPA files
                                              ├── /api/*   → JSON API endpoints
                                              ├── /auth/*  → session & OAuth
                                              └── /quiz/*  → encrypted quiz runtime
                                              │
                                          PostgreSQL (codecoder)
                                              ├── users, attempts
                                              ├── questions (500+)
                                              ├── feed_items
                                              ├── course_chapters (31)
                                              ├── frameworks
                                              └── media_assets (pg_largeobject)
```

---

## 2. Before you start — checklist

Make sure all of these are true. If any is missing, get it sorted **before** running the script.

**Pre-installed software** (the script does **not** install these — they must already be on the VM):

- [ ] **Python 3.9+** (`python3 --version`)
- [ ] **Apache httpd + mod_ssl** (`httpd -v`)
- [ ] **PostgreSQL server** (`psql --version`)
- [ ] **rsync** (`rsync --version`)

**Environment:**

- [ ] You can SSH into the VM and run `sudo` (root access).
- [ ] The OS is **CentOS 8 / RHEL 8** (`cat /etc/redhat-release` to confirm).
- [ ] **DNS**: `internal.in.deptagency.com` resolves to this VM's IP. Test from the VM:
      `getent hosts internal.in.deptagency.com`
- [ ] **TLS cert + key files exist on the VM.** Defaults the script expects:
  - Certificate: `/etc/pki/tls/certs/internal.in.deptagency.com.crt`
  - Private key: `/etc/pki/tls/private/internal.in.deptagency.com.key`
  - If yours are elsewhere, note the paths — you'll pass them in (see step 4).
- [ ] **Google OAuth credentials** (Client ID + Secret) — get these from whoever owns the
      Google Cloud project. You can deploy without them (it runs in a test "dev mode"),
      but real logins need them.
- [ ] In the Google console, the **Authorized redirect URI** is set to exactly:
      `https://internal.in.deptagency.com/auth/google/callback`
- [ ] **SMTP credentials** for sending certificate emails (host, user, password).

> If you only have *some* of these, you can still do a dev-mode deploy now (step 4a) and
> come back to flip on production (step 6) once you have the OAuth + SMTP details.

---

## 3. Get the bundle onto the VM

Copy the whole bundle folder to the VM (from your laptop), then SSH in:

```bash
# from your machine — adjust the path/host
scp -r dept-deploy/ youruser@internal.in.deptagency.com:~/

# then log in
ssh youruser@internal.in.deptagency.com
cd ~/dept-deploy
```

---

## 4. Run the deploy script

The script must run as root. Pick **4a** (test first) or **4b** (straight to production).

### 4a. Dev-mode deploy (recommended for your first run)

Runs the app with a simple email login (no real Google OAuth), so you can confirm
the plumbing works before wiring in credentials.

```bash
sudo ./deploy.sh
```

If your cert/key are **not** in the default location, pass them in:

```bash
sudo CERT_FILE=/path/to/your.crt KEY_FILE=/path/to/your.key ./deploy.sh
```

### 4b. Production deploy (with OAuth)

If you already have the Google credentials, hand them to the script and it will turn on
production mode automatically:

```bash
sudo GOOGLE_CLIENT_ID='xxxx.apps.googleusercontent.com' \
     GOOGLE_CLIENT_SECRET='your-secret' \
     ./deploy.sh
```

You'll **still** need to add SMTP settings (step 6) — production mode sends real email.

### What the script does (so nothing surprises you)

1. **Pre-flight checks** — verifies Python 3, httpd, and psql are available; validates TLS cert/key paths.
2. Creates a locked-down service user `cca`.
3. Copies the bundle to `/opt/dept-anatomy` (including `app/` and `content-architecture/`).
4. Builds a Python virtualenv and installs the app's dependencies.
5. Creates the app's config file (`.env`) with a random session key and **DATABASE_URL**.
6. **PostgreSQL first-time setup:**
   - Initialises the cluster (`postgresql-setup --initdb`) if needed.
   - Starts and enables the `postgresql` service.
   - Creates the `codecoder` database role with a random password.
   - Creates the `codecoder` database.
   - Configures `pg_hba.conf` for password-based local auth.
   - Applies `deploy_schema.sql` (extensions, all tables, indexes).
   - Runs the ETL migration script to seed questions, course chapters, framework, and feed items.
7. Installs and starts a systemd service `cca-quiz` (this runs the app).
8. Configures **SELinux** (lets Apache talk to the app + read the static files).
9. Writes the Apache HTTPS config and reloads Apache.
10. Opens ports 80 and 443 in the firewall.

It is **safe to re-run** — it won't wipe your data, `.env`, or existing database rows.

---

## 5. Verify it worked

When the script finishes it prints a summary. Then check each layer:

```bash
# 1. Is the app service running?
systemctl status cca-quiz          # should say "active (running)"

# 2. Is PostgreSQL running?
systemctl status postgresql        # should say "active (running)"

# 3. Is the database populated?
sudo -u cca PGPASSWORD="$(grep DATABASE_URL /opt/dept-anatomy/quiz-certification/.env | sed 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/')" \
  psql -U codecoder -d codecoder -h 127.0.0.1 \
  -c "SELECT 'questions', count(*) FROM questions
      UNION ALL SELECT 'course_chapters', count(*) FROM course_chapters
      UNION ALL SELECT 'frameworks', count(*) FROM frameworks
      UNION ALL SELECT 'feed_items', count(*) FROM feed_items;"

# 4. Is the app answering locally (bypassing Apache)?
curl -I http://127.0.0.1:8000/      # should return HTTP/1.1 200 or 307

# 5. Does the /app/ SPA load?
curl -I http://127.0.0.1:8000/app/   # should return HTTP/1.1 200

# 6. Are the API endpoints alive?
curl http://127.0.0.1:8000/api/course/framework | head -c 200  # should return JSON

# 7. Is Apache config valid and running?
sudo httpd -t                       # should say "Syntax OK"
systemctl status httpd              # "active (running)"

# 8. End-to-end over HTTPS:
curl -I https://internal.in.deptagency.com/
curl -I https://internal.in.deptagency.com/app/
```

Then open in a browser:

- `https://internal.in.deptagency.com/` — the quiz login page
- `https://internal.in.deptagency.com/app/` — the SPA (course manual, feed)
- `https://internal.in.deptagency.com/anatomy/anatomy-of-code-course.html` — the course

✅ If all load over HTTPS with no certificate warning, you're done.

### Common first-deploy issue: "404 — /api/course/framework"

This means the database tables exist but are **empty** — the migration script didn't run
or didn't find the content files. Fix:

```bash
cd /opt/dept-anatomy/quiz-certification
sudo -u cca .venv/bin/python -m scripts.migrate_to_postgres
sudo systemctl restart cca-quiz
```

---

## 6. Switching to / configuring production

The app's settings live in **`/opt/dept-anatomy/quiz-certification/.env`**.
Edit it as root:

```bash
sudo nano /opt/dept-anatomy/quiz-certification/.env
```

Set these for production:

```ini
QUIZ_DEV_MODE=false
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-secret
SMTP_HOST=smtp.yourprovider.com
SMTP_USER=...
SMTP_PASS=...
```

Then restart the app:

```bash
sudo systemctl restart cca-quiz
```

> The `GOOGLE_REDIRECT_URI`, `SECRET_KEY`, and `DATABASE_URL` are already filled in
> correctly by the script — don't change them.

---

## 7. Updating the app later

When a new version of the bundle is handed to you:

```bash
# copy the new bundle to the VM (as in step 3), then:
cd ~/dept-deploy
sudo ./deploy.sh --update
```

`--update` re-syncs the code and restarts the service but **keeps** your `.env`,
generated certificates, and quiz results. It skips the package/firewall/SELinux setup
(faster).

### Re-running the data migration after a content update

If a new version includes updated course chapters, framework, or additional quiz questions:

```bash
cd /opt/dept-anatomy/quiz-certification
sudo -u cca .venv/bin/python -m scripts.migrate_to_postgres
sudo systemctl restart cca-quiz
```

The migration script is idempotent — it skips rows that already exist and only inserts new ones.

---

## 8. Day-to-day operations

```bash
# Live app logs (errors, requests)
journalctl -u cca-quiz -f

# Apache logs for this site
sudo tail -f /var/log/httpd/cca-quiz_error.log
sudo tail -f /var/log/httpd/cca-quiz_access.log

# Restart just the app
sudo systemctl restart cca-quiz

# Reload Apache after editing its config
sudo systemctl reload httpd

# Check database
sudo -u postgres psql -d codecoder -c "SELECT count(*) FROM questions;"
```

**Where things live:**

| Thing | Path |
|-------|------|
| App code & venv | `/opt/dept-anatomy/quiz-certification/` |
| App config | `/opt/dept-anatomy/quiz-certification/.env` |
| SPA frontend | `/opt/dept-anatomy/app/` |
| Static HTML | `/opt/dept-anatomy/content-system/` |
| Content architecture (source JSONs) | `/opt/dept-anatomy/content-architecture/` |
| Quiz attempt records | `/opt/dept-anatomy/quiz-certification/quiz_results/` |
| Generated certificates (PDFs) | `/opt/dept-anatomy/quiz-certification/certificates/` |
| PostgreSQL data | `/var/lib/pgsql/data/` |
| systemd service | `/etc/systemd/system/cca-quiz.service` |
| Apache site config | `/etc/httpd/conf.d/cca-quiz.conf` |

---

## 9. Database management

### Connecting to the database

```bash
# As the postgres superuser
sudo -u postgres psql -d codecoder

# As the app user (password is in .env)
PGPASSWORD=<password> psql -U codecoder -d codecoder -h 127.0.0.1
```

### Checking data counts

```sql
SELECT 'questions' AS table_name, count(*) FROM questions
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'attempts', count(*) FROM attempts
UNION ALL SELECT 'feed_items', count(*) FROM feed_items
UNION ALL SELECT 'course_chapters', count(*) FROM course_chapters
UNION ALL SELECT 'frameworks', count(*) FROM frameworks;
```

### Backup

```bash
sudo -u postgres pg_dump codecoder > /tmp/codecoder_backup_$(date +%Y%m%d).sql
```

### Restore

```bash
sudo -u postgres psql -d codecoder < /tmp/codecoder_backup_YYYYMMDD.sql
```

### Schema file

The canonical schema is at `quiz-certification/deploy_schema.sql`. It uses
`CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`, so it is safe to re-apply:

```bash
PGPASSWORD=<password> psql -U codecoder -d codecoder -h 127.0.0.1 \
  -f /opt/dept-anatomy/quiz-certification/deploy_schema.sql
```

---

## 10. Troubleshooting

**"404 — /api/course/framework" on first load**
The database tables are empty. The migration script either didn't run or
`content-architecture/` wasn't synced to the VM. Fix:
```bash
ls /opt/dept-anatomy/content-architecture/course/framework.json  # should exist
cd /opt/dept-anatomy/quiz-certification
sudo -u cca .venv/bin/python -m scripts.migrate_to_postgres
sudo systemctl restart cca-quiz
```

**The script stops with "TLS cert not found"**
The cert/key aren't where the script expected. Find them
(`sudo find /etc/pki -name '*.crt'`) and re-run passing `CERT_FILE=` and `KEY_FILE=`
(see step 4a).

**`dnf` can't download packages / "Failed to download metadata"**
CentOS 8 is end-of-life and its default mirrors are offline. The repos must point to
`vault.centos.org`. Ask your team lead — this is a VM-level fix, not something the script
does. Everything else works once packages can install.

**PostgreSQL won't start / "could not connect to server"**
Check if the cluster was initialised:
```bash
ls /var/lib/pgsql/data/PG_VERSION     # should exist
sudo postgresql-setup --initdb        # if not
sudo systemctl start postgresql
```

**Browser shows the app but logins fail / redirect error**
Almost always the OAuth redirect URI mismatch. The URI in the Google console must be
**exactly** `https://internal.in.deptagency.com/auth/google/callback` (no trailing slash,
`https` not `http`). Also confirm `QUIZ_DEV_MODE=false` and the client ID/secret are set
in `.env`, then `sudo systemctl restart cca-quiz`.

**502 / 503 from Apache, or the page won't load**
The app service is probably down. Check `systemctl status cca-quiz` and
`journalctl -u cca-quiz -n 50`. A common cause is a bad value in `.env`.

**`/anatomy/` pages give "403 Forbidden"**
SELinux hasn't labeled the files. Re-run the full deploy (`sudo ./deploy.sh`), or manually:
`sudo restorecon -Rv /opt/dept-anatomy/content-system`.

**Apache won't start after my edit**
Run `sudo httpd -t` — it tells you the file and line of the problem.

**Certificate warning in the browser**
The cert doesn't match the domain, or the CA chain is missing. If you have a chain/intermediate
file, re-run with `CHAIN_FILE=/path/to/chain.pem`.

---

## 11. Who to ask

- **OAuth client ID/secret & redirect URI** → owner of the Google Cloud project.
- **TLS certificate / DNS** → whoever manages the internal CA / network.
- **SMTP credentials** → email/IT team.
- **Database issues** → check `journalctl -u postgresql` and `/var/lib/pgsql/data/log/`.
- **App behaviour, question bank, admin tools** → see `quiz-certification/README.md`.
