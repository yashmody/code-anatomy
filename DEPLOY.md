# Deployment Guide — DEPT® Anatomy of Code

This guide walks you through deploying the bundle onto the CentOS 8 VM using `deploy.sh`.
No prior knowledge of the app is needed — just follow the steps in order.

**Time required:** ~15 minutes for a first deploy.

---

## 1. What you're deploying

The bundle has three parts. The script deploys two of them:

| Part | What it is | How it's served |
|------|-----------|-----------------|
| `quiz-certification/` | A FastAPI web app (the certification quiz) | Runs as a background service; Apache proxies to it |
| `content-system/` | 4 static HTML files (course, checklist, FAQ, runbook) | Apache serves them directly |
| `prompt-library/`             | B0 prompt sequences + worked samples | **Not deployed** (consumed as a code resource) |

> **Reader data is client-side only.** The course's reader-tools layer (reading progress,
> bookmarks, notes, and Review-Mode annotations) saves to each visitor's browser
> `localStorage`, not to the server. There is nothing to provision, persist, or back up for
> it — and clearing a browser, or switching browsers/devices, loses that user's notes. If
> durable or shared annotations are ever required, that's an application change, not a
> deploy-config one.

After deploy, the VM answers on one domain:

```
https://internal.in.deptagency.com/                  → the quiz app
https://internal.in.deptagency.com/anatomy/...       → the static content
```

Under the hood:

```
  Browser ──HTTPS──▶ Apache (httpd) ──┬──▶ /anatomy/  → static files on disk
  (port 443)                          └──▶ /          → uvicorn on 127.0.0.1:8000
                                                          (the FastAPI app, run by systemd)
```

---

## 2. Before you start — checklist

Make sure all of these are true. If any is missing, get it sorted **before** running the script.

- [ ] You can SSH into the VM and run `sudo` (root access).
- [ ] The OS is **CentOS 8 / RHEL 8** (`cat /etc/redhat-release` to confirm).
- [ ] **Apache httpd is installed** (it already is on this VM).
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

1. Installs packages: Python 3.9, `mod_ssl`, rsync, SELinux tools.
2. Creates a locked-down service user `cca`.
3. Copies the bundle to `/opt/dept-anatomy`.
4. Builds a Python virtualenv and installs the app's dependencies.
5. Creates the app's config file (`.env`) with a random session key.
6. Installs and starts a systemd service `cca-quiz` (this runs the app).
7. Configures **SELinux** (lets Apache talk to the app + read the static files).
8. Writes the Apache HTTPS config and reloads Apache.
9. Opens ports 80 and 443 in the firewall.

It is **safe to re-run** — it won't wipe your data or `.env`.

---

## 5. Verify it worked

When the script finishes it prints a summary. Then check each layer:

```bash
# 1. Is the app service running?
systemctl status cca-quiz          # should say "active (running)"

# 2. Is the app answering locally (bypassing Apache)?
curl -I http://127.0.0.1:8000/      # should return HTTP/1.1 200 or 307

# 3. Is Apache config valid and running?
sudo httpd -t                       # should say "Syntax OK"
systemctl status httpd              # "active (running)"

# 4. End-to-end over HTTPS:
curl -I https://internal.in.deptagency.com/
```

Then open in a browser:

- `https://internal.in.deptagency.com/` — the quiz login page
- `https://internal.in.deptagency.com/anatomy/anatomy-of-code-course.html` — the course

✅ If both load over HTTPS with no certificate warning, you're done.

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

> The `GOOGLE_REDIRECT_URI` and `SECRET_KEY` are already filled in correctly by the script —
> don't change them.

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
```

**Where things live:**

| Thing | Path |
|-------|------|
| App code & venv | `/opt/dept-anatomy/quiz-certification/` |
| App config | `/opt/dept-anatomy/quiz-certification/.env` |
| Static HTML | `/opt/dept-anatomy/content-system/` |
| Quiz attempt records | `/opt/dept-anatomy/quiz-certification/quiz_results/` |
| Generated certificates (PDFs) | `/opt/dept-anatomy/quiz-certification/certificates/` |
| systemd service | `/etc/systemd/system/cca-quiz.service` |
| Apache site config | `/etc/httpd/conf.d/cca-quiz.conf` |

---

## 9. Troubleshooting

**The script stops with "TLS cert not found"**
The cert/key aren't where the script expected. Find them
(`sudo find /etc/pki -name '*.crt'`) and re-run passing `CERT_FILE=` and `KEY_FILE=`
(see step 4a).

**`dnf` can't download packages / "Failed to download metadata"**
CentOS 8 is end-of-life and its default mirrors are offline. The repos must point to
`vault.centos.org`. Ask your team lead — this is a VM-level fix, not something the script
does. Everything else works once packages can install.

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

## 10. Who to ask

- **OAuth client ID/secret & redirect URI** → owner of the Google Cloud project.
- **TLS certificate / DNS** → whoever manages the internal CA / network.
- **SMTP credentials** → email/IT team.
- **App behaviour, question bank, admin tools** → see `quiz-certification/README.md`.
